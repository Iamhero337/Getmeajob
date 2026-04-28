"""
Resume optimizer — tailors resume + cover letter per job using LM Studio.

What the LLM MUST customize per job:
  - summary: completely rewritten for this specific role
  - skills: reordered by relevance, JD keywords added, irrelevant ones dropped
  - experience bullets: rewritten to surface skills relevant to the JD
  - cover letter: 3 paragraphs targeting this exact role

What NEVER changes (anchored from base resume after LLM call):
  - experience: company names, start/end dates, job titles
  - education: institution, degree, year
  - contact info: name, email, phone, linkedin, github
"""
import copy
import hashlib
import json
import os
from src.llm.client import LMStudioClient


PARSE_PROMPT = """You are a professional resume parser.
Extract ALL information from the resume text below into a JSON object with this structure:

{{
  "name": "...",
  "email": "...",
  "phone": "...",
  "linkedin": "...",
  "github": "...",
  "location": "...",
  "summary": "...",
  "skills": ["..."],
  "experience": [
    {{"title": "...", "company": "...", "location": "...", "start": "...", "end": "...", "bullets": ["..."]}}
  ],
  "education": [
    {{"degree": "...", "institution": "...", "year": "...", "gpa": "..."}}
  ],
  "projects": [
    {{"name": "...", "tech": ["..."], "description": "...", "bullets": ["..."], "url": "..."}}
  ],
  "certifications": ["..."]
}}

Rules:
- Extract verbatim from the resume — DO NOT invent, infer, or paraphrase content not present
- If a field is missing, use empty string "" or empty array []
- Preserve all bullet points exactly as written

RESUME TEXT:
{resume_text}

Return ONLY the JSON object."""


COMBINED_OPTIMIZE_PROMPT = """You are an expert ATS resume optimizer for an early-career engineer (under 2 years experience). Customize the resume below for this SPECIFIC job.

━━━ CANDIDATE CONTEXT (always respect these) ━━━
• Total experience: {total_experience} — DO NOT claim more years than this
• Strongest skills (lead with these when relevant): {top_skills}
• Targeting: fresher → mid roles. If JD demands 5+ years, still apply but don't fabricate seniority.
• Honesty rule: if candidate isn't certified in something, NEVER write "Certified". Use:
   "Trained on X" / "Hands-on with X" / "Coursework in X" / "Self-taught X" / "Built projects with X"

━━━ CUSTOMIZE THESE FOR THIS JOB (make every job's resume unique) ━━━

1. summary (2-3 sentences)
   - Name the target role explicitly (e.g. "Backend Python developer with hands-on experience in...")
   - Lead with the candidate's strongest skill that overlaps the JD
   - End with a concrete differentiator or shipped result

2. skills (10-18 items)
   - REORDER: most relevant to THIS JD first
   - ADD: JD keywords the candidate can reasonably claim based on their experience or top_skills
   - REMOVE: skills irrelevant to this role (don't list React if it's a pure backend job)

3. experience[].bullets (rewrite ALL of them, every job)
   Each bullet: [Strong Action Verb] + [specific what] + [measurable result/impact]
   Examples:
     "Engineered REST APIs serving 50K+ daily requests using Django and PostgreSQL"
     "Reduced CI/CD pipeline runtime by 40% by parallelizing GitHub Actions test stages"
   DO NOT invent facts — REFRAME real work with JD-relevant keywords + stronger verbs.

4. projects — generate EXACTLY 2 NEW projects tailored to THIS JD:
   • Project A — "1-week scope": small but complete (CLI tool, single-feature webapp, focused script). Use 2-3 techs from the JD.
   • Project B — "1-month scope": full-stack or multi-component (full webapp with auth + DB + API + deploy, OR ML pipeline with training + inference + UI, OR distributed system). Use 4-6 techs from the JD.
   For each: realistic name, tech list, 1-2 sentence description, and 2-3 bullets describing the build (action verb + tech + outcome).
   These are aspirational — the candidate WILL build them if the role requires. Make them real-sounding, not generic.

5. certifications
   - Copy verbatim ONLY what's in the candidate's input.
   - DO NOT invent any. If the JD asks for AWS/GCP/etc. and the candidate doesn't have them, do NOT add — instead reflect that exposure in skills as "Hands-on with AWS" or in a project bullet.

6. cover_letter (3 paragraphs, no "Dear" or "Sincerely")
   • Para 1: ONE specific thing about THIS company or role from the JD (a product, a tech choice, a value, a recent launch). Show research, not boilerplate.
   • Para 2: 2 concrete experiences/projects that map directly to the JD's needs.
   • Para 3: Notice period + enthusiasm + call to action.

━━━ NEVER CHANGE (copy verbatim from input) ━━━
• experience[].company, title, start, end
• education[].institution, degree, year
• certifications (copy as-is, never invent)
• name, email, phone, linkedin, github

━━━ TARGET JOB ━━━
Title: {title}
Company: {company}
Description:
{job_description}

━━━ CANDIDATE RESUME ━━━
{resume_json}

Notice period: {notice_period}

Return ONLY this JSON object (no markdown, no explanation):
{{"resume": {{...full resume JSON...}}, "cover_letter": "..."}}"""


def _hash_jd(title: str, company: str, description: str) -> str:
    key = f"{title}|{company}|{(description or '')[:1500]}".lower()
    return hashlib.sha1(key.encode()).hexdigest()[:16]


class ResumeOptimizer:
    def __init__(self, llm: LMStudioClient, config: dict):
        self.llm = llm
        self.resume_cfg = config.get("resume", {})
        self.candidate_cfg = config.get("candidate", {})
        self.max_projects = self.resume_cfg.get("max_portfolio_projects", 3)
        self.generate_projects = self.resume_cfg.get("generate_portfolio_projects", True)
        self.level = self.resume_cfg.get("optimization_level", "aggressive")
        self.cache_dir = "data/optimize_cache"
        os.makedirs(self.cache_dir, exist_ok=True)

    # ----------------------------------------------------------------
    # Initial parse — runs once per session
    # ----------------------------------------------------------------
    def parse_full(self, raw_text: str) -> dict:
        messages = [
            {"role": "system", "content": "You are a resume parser. Output strictly valid JSON only."},
            {"role": "user", "content": PARSE_PROMPT.format(resume_text=raw_text[:3500])},
        ]
        result = self.llm.chat_json(messages, temperature=0.1, max_tokens=2500)
        if not result or not isinstance(result, dict):
            print("[Optimizer] LLM parse failed, returning empty structure")
            return {}
        return result

    # ----------------------------------------------------------------
    # Combined optimize — resume + cover letter in ONE LLM call
    # Returns: {"resume": {...}, "cover_letter": "..."}
    # ----------------------------------------------------------------
    def optimize_with_cover(self, base_resume: dict, job: dict) -> dict:
        jd = job.get("description", "") or f"Role: {job.get('title')} at {job.get('company')}"
        cache_key = _hash_jd(job.get("title", ""), job.get("company", ""), jd)
        cache_path = os.path.join(self.cache_dir, f"{cache_key}.json")

        if os.path.exists(cache_path):
            try:
                with open(cache_path) as f:
                    cached = json.load(f)
                print("  [dim](cache hit)[/dim]")
                return cached
            except Exception:
                pass

        notice = self.candidate_cfg.get("notice_period", "1 month")
        total_exp = self.candidate_cfg.get("total_experience", "under 2 years")
        top_skills = ", ".join(self.candidate_cfg.get("top_skills", [])) or "Python, SQL, Linux"

        messages = [
            {
                "role": "system",
                "content": "You are an expert resume optimizer for early-career engineers. Output strictly valid JSON only — no markdown, no commentary.",
            },
            {
                "role": "user",
                "content": COMBINED_OPTIMIZE_PROMPT.format(
                    title=job.get("title", "")[:80],
                    company=job.get("company", "")[:80],
                    job_description=jd[:2000],
                    resume_json=json.dumps(base_resume)[:2800],
                    notice_period=notice,
                    total_experience=total_exp,
                    top_skills=top_skills,
                ),
            },
        ]

        result = self.llm.chat_json(messages, temperature=0.6, max_tokens=3500)

        if not result or not isinstance(result, dict):
            return self._fallback_output(base_resume, job)

        optimized = result.get("resume")
        cover = result.get("cover_letter", "")

        if not optimized or not isinstance(optimized, dict):
            return self._fallback_output(base_resume, job)

        # Anchor all factual fields from base — LLM cannot change these
        optimized = self._anchor_facts(optimized, base_resume)

        out = {"resume": optimized, "cover_letter": cover or self._fallback_cover(base_resume, job)}

        try:
            with open(cache_path, "w") as f:
                json.dump(out, f)
        except Exception:
            pass

        return out

    # ----------------------------------------------------------------
    # Backwards-compat: optimize() returns just the resume dict
    # ----------------------------------------------------------------
    def optimize(self, base_resume: dict, job: dict) -> dict:
        return self.optimize_with_cover(base_resume, job)["resume"]

    # ----------------------------------------------------------------
    # Anchor factual fields — keeps LLM-optimized bullets/summary/skills
    # while guaranteeing company names, dates, education are never altered
    # ----------------------------------------------------------------
    def _anchor_facts(self, optimized: dict, base: dict) -> dict:
        result = copy.deepcopy(optimized)

        base_exps = [e for e in base.get("experience", []) if isinstance(e, dict)]
        raw_opt   = result.get("experience", [])
        # LLM sometimes returns experience as a dict or list of non-dicts — normalise
        if isinstance(raw_opt, dict):
            raw_opt = list(raw_opt.values())
        opt_exps = [e for e in (raw_opt if isinstance(raw_opt, list) else []) if isinstance(e, dict)]

        # Pad to same length as base using base entries as fallback
        while len(opt_exps) < len(base_exps):
            opt_exps.append(copy.deepcopy(base_exps[len(opt_exps)]))
        result["experience"] = opt_exps

        # Overwrite ONLY the facts that can never change
        for i, b in enumerate(base_exps):
            if i >= len(opt_exps):
                break
            opt_exps[i]["company"] = b.get("company", "")
            opt_exps[i]["title"]   = b.get("title", opt_exps[i].get("title", ""))
            opt_exps[i]["start"]   = b.get("start", opt_exps[i].get("start", ""))
            opt_exps[i]["end"]     = b.get("end", opt_exps[i].get("end", ""))
            # bullets intentionally NOT anchored — LLM rewrites them per job

        # Anchor education facts
        base_edu = [e for e in base.get("education", []) if isinstance(e, dict)]
        raw_edu  = result.get("education", [])
        if isinstance(raw_edu, dict):
            raw_edu = list(raw_edu.values())
        opt_edu = [e for e in (raw_edu if isinstance(raw_edu, list) else []) if isinstance(e, dict)]
        while len(opt_edu) < len(base_edu):
            opt_edu.append(copy.deepcopy(base_edu[len(opt_edu)]))
        result["education"] = opt_edu
        for i, b in enumerate(base_edu):
            if i >= len(opt_edu):
                break
            opt_edu[i]["institution"] = b.get("institution", "")
            opt_edu[i]["degree"]      = b.get("degree", opt_edu[i].get("degree", ""))
            opt_edu[i]["year"]        = b.get("year", opt_edu[i].get("year", ""))

        # Anchor contact info
        for k in ("name", "email", "phone", "linkedin", "github", "location"):
            if not result.get(k):
                result[k] = base.get(k, "")

        return result

    def _fallback_output(self, base_resume: dict, job: dict) -> dict:
        return {
            "resume": base_resume,
            "cover_letter": self._fallback_cover(base_resume, job),
        }

    def _fallback_cover(self, base_resume: dict, job: dict) -> str:
        skills = ", ".join((base_resume.get("skills") or [])[:5])
        return (
            f"I'm excited to apply for the {job.get('title')} role at {job.get('company')}. "
            f"My experience in {skills} aligns directly with what your team is building. "
            f"I'd love to discuss how I can contribute — I'm available within "
            f"{self.candidate_cfg.get('notice_period', '1 month')}."
        )
