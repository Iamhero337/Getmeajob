"""
Job scorer — assigns a 0-100 score with smart filters.

Hard filters (return 0 — job is dropped entirely):
  - Company in blacklist
  - Onsite outside India + visa not sponsored (per candidate's geo prefs)
  - Senior role (5+ years required) — candidate has under 2y
  - Title contains a blacklisted keyword

Score weights (totals 100):
  Remote:           +25 (if remote preferred)
  Geo match:        +0..+15 (preferred country with sponsorship)
  Company type:     +20 (startup=20, mnc=10, unknown=5)
  Title relevance:  +25 (keyword match)
  Skill overlap:    +20 (JD vs candidate skills, weighted by top_skills)
  Top-skill bonus:  +0..+10 (extra weight when JD mentions candidate's top skills)
  Salary:           +0..+10 (above target)
  Freshness:        +0..+10 (posted in last 24h-7d)
  Description:      +3 (title also confirmed in body)
"""
import re
from datetime import datetime, timedelta
from src.scrapers.base import JobListing


STARTUP_SIGNALS = [
    "seed", "series a", "series b", "funded", "startup", "backed",
    "yc", "y combinator", "techstars", "founded in 20", "founded in 19",
    "people company", "growing team", "small team",
]

MNC_SIGNALS = [
    "fortune 500", "global leader", "enterprise", "multinational",
    "10,000+ employees", "50,000+ employees", "billion",
]

# Senior-only signals — drop if candidate has under 2y experience
SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|architect|head\s+of|director|vp|chief|manager)\b",
    re.IGNORECASE,
)

# Years of experience demanded by the JD (catches "5+ years", "minimum 7 years", etc.)
YEARS_REQUIRED = re.compile(
    r"(\d+)\+?\s*(?:to\s*\d+\s*)?(?:years|yrs)\s*(?:of\s*)?(?:experience|exp)",
    re.IGNORECASE,
)

# Visa / authorization signals — used when role is onsite outside India
NO_SPONSOR = re.compile(
    r"(no sponsorship|do not\s+sponsor|not\s+sponsoring|"
    r"must be (?:authorized|eligible) to work in (?:the\s+)?(?:us|usa|uk|canada)|"
    r"us citizen(?:s|ship)?\s+(?:only|required)|"
    r"green\s*card holders only|must hold\s+(?:us|uk)\s+citizenship)",
    re.IGNORECASE,
)


def _parse_required_years(desc: str) -> int:
    """Largest 'X+ years' figure mentioned in the JD."""
    matches = YEARS_REQUIRED.findall(desc or "")
    return max((int(m) for m in matches), default=0)


def _parse_posted_days_ago(job: JobListing) -> int | None:
    """Best-effort freshness lookup. Returns days-since-posted or None."""
    raw = job.raw or {}
    for k in ("published_at", "created_at", "posted_at", "date_posted", "publication_date"):
        v = raw.get(k)
        if not v:
            continue
        try:
            if isinstance(v, (int, float)):  # epoch
                dt = datetime.fromtimestamp(v)
            else:
                dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            return max(0, (datetime.now(dt.tzinfo) - dt).days)
        except Exception:
            continue
    return None


def score_job(job: JobListing, candidate_skills: list[str], config: dict) -> float:
    """Return a 0-100 score. Returns 0 to indicate the job is filtered out."""
    search_cfg = config.get("search", {})
    candidate_cfg = config.get("candidate", {})
    geo_cfg = candidate_cfg.get("geo", {}) or {}

    prefer_remote = search_cfg.get("prefer_remote", True)
    prefer_startups = search_cfg.get("prefer_startups", True)
    blacklist_kw = [k.lower() for k in search_cfg.get("blacklist_keywords", [])]
    blacklist_co = [c.lower() for c in search_cfg.get("blacklist_companies", [])]
    desired_titles = [k.lower() for k in search_cfg.get("keywords", [])]
    top_skills = [s.lower() for s in candidate_cfg.get("top_skills", [])]
    max_years_claim = int(candidate_cfg.get("max_years_to_claim", 2))

    # Sponsorship-required countries (onsite OK only if sponsored)
    sponsor_countries = [c.lower() for c in geo_cfg.get("sponsor_required_countries", [])]
    onsite_fallback_countries = [c.lower() for c in geo_cfg.get("onsite_fallback_countries", ["india"])]

    title_lower = job.title.lower()
    desc_lower = (job.description or "").lower()
    company_lower = job.company.lower()

    # ─── HARD FILTERS (return 0) ─────────────────────────────────────────

    # Company blacklist
    if any(b and b in company_lower for b in blacklist_co):
        return 0.0

    # Title blacklist (Senior, Lead, etc.)
    if any(bl in title_lower for bl in blacklist_kw):
        return 0.0

    # Senior role detection from title
    if SENIOR_TITLE.search(job.title) and max_years_claim < 4:
        return 0.0

    # Years required check (e.g. JD asks for 5+ years)
    required_years = _parse_required_years(desc_lower)
    if required_years and required_years > max_years_claim + 2:
        return 0.0  # asking for 5+ years when candidate has 2 — skip

    # Onsite role outside India: only keep if sponsorship is mentioned (not denied)
    if not job.is_remote and "remote" not in title_lower:
        loc_lower = (job.location or "").lower()
        in_fallback = any(c in loc_lower for c in onsite_fallback_countries)
        in_sponsor_country = any(c in loc_lower for c in sponsor_countries)
        if not in_fallback and not in_sponsor_country:
            # Onsite somewhere we don't go
            pass  # Don't drop; just won't get bonus
        elif in_sponsor_country and NO_SPONSOR.search(desc_lower):
            return 0.0  # Onsite US/UK/etc. but explicitly says no sponsorship

    # ─── SOFT SCORING ────────────────────────────────────────────────────

    score = 0.0

    # Remote: +25
    if prefer_remote:
        if job.is_remote or "remote" in title_lower or "remote" in desc_lower[:200]:
            score += 25
        elif "hybrid" in desc_lower[:200]:
            score += 10

    # Geo match (sponsor country gets a small bonus): +0..+15
    loc_lower = (job.location or "").lower()
    if any(c in loc_lower for c in sponsor_countries):
        if not NO_SPONSOR.search(desc_lower):
            score += 10
    elif any(c in loc_lower for c in onsite_fallback_countries):
        score += 5

    # Company type: up to +20
    ctype = job.company_type
    if ctype == "unknown":
        if any(s in desc_lower for s in STARTUP_SIGNALS):
            ctype = "startup"
        elif any(s in desc_lower for s in MNC_SIGNALS):
            ctype = "mnc"
    if prefer_startups and ctype == "startup":
        score += 20
    elif ctype == "mnc":
        score += 10
    else:
        score += 5

    # Title relevance: up to +25
    title_score = 0
    for dt in desired_titles:
        dt_words = dt.split()
        matches = sum(1 for w in dt_words if w in title_lower)
        if matches == len(dt_words):
            title_score = 25
            break
        elif matches > 0:
            title_score = max(title_score, int(25 * matches / len(dt_words)))
    score += title_score

    # Skill overlap: up to +20 + top-skill bonus +0..+10
    if candidate_skills and desc_lower:
        skill_hits = 0
        top_hits = 0
        for s in candidate_skills:
            sl = s.lower().strip()
            if not sl:
                continue
            pattern = r"\b" + re.escape(sl) + r"\b"
            if re.search(pattern, desc_lower):
                skill_hits += 1
                if sl in top_skills:
                    top_hits += 1
        skill_ratio = min(skill_hits / max(len(candidate_skills), 1), 1.0)
        score += round(skill_ratio * 20)

        # Top-skill bonus: heavy reward when JD demands what candidate is best at
        if top_skills:
            top_ratio = min(top_hits / max(len(top_skills), 1), 1.0)
            score += round(top_ratio * 10)

    # Title-in-description: +3
    if any(w in desc_lower[:500] for w in title_lower.split() if len(w) > 3):
        score += 3

    # Salary bonus: up to +10
    min_salary = candidate_cfg.get("expected_salary_min", 0)
    if min_salary and job.salary:
        nums = re.findall(r"\d[\d,]*", job.salary.replace(",", ""))
        if nums:
            try:
                offered = int(nums[0])
                if offered >= min_salary:
                    score += 10
                elif offered >= min_salary * 0.8:
                    score += 5
            except ValueError:
                pass

    # Freshness bonus: up to +10
    days_ago = _parse_posted_days_ago(job)
    if days_ago is not None:
        if days_ago <= 1:
            score += 10
        elif days_ago <= 3:
            score += 7
        elif days_ago <= 7:
            score += 4

    return round(min(score, 100), 1)


def rank_jobs(jobs: list[JobListing], candidate_skills: list[str], config: dict) -> list[JobListing]:
    """Score and sort jobs. Drops anything that scored 0 (filtered out)."""
    for job in jobs:
        job.score = score_job(job, candidate_skills, config)
    return sorted([j for j in jobs if j.score > 0], key=lambda j: j.score, reverse=True)
