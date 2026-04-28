# Get Me a Job — Architecture & Build Guide

A complete technical reference. If you read this top to bottom you can rebuild the entire project from scratch without looking at any other document.

---

## Table of Contents

1. [What This Project Does](#1-what-this-project-does)
2. [Why Each Decision Was Made](#2-why-each-decision-was-made)
3. [System Architecture](#3-system-architecture)
4. [Project Structure](#4-project-structure)
5. [Tech Stack & Dependencies](#5-tech-stack--dependencies)
6. [Pipeline: Step by Step](#6-pipeline-step-by-step)
7. [Component Deep Dives](#7-component-deep-dives)
   - [LLM Client](#71-llm-client)
   - [Resume Parser](#72-resume-parser)
   - [Resume Optimizer](#73-resume-optimizer)
   - [Resume Builder (PDF)](#74-resume-builder-pdf)
   - [Cover Letter Generator](#75-cover-letter-generator)
   - [Scrapers](#76-scrapers)
   - [Job Scorer](#77-job-scorer)
   - [Database Tracker](#78-database-tracker)
   - [LinkedIn Applier](#79-linkedin-applier)
   - [Orchestrator](#710-orchestrator)
   - [Flask Dashboard](#711-flask-dashboard)
   - [CLI (main.py)](#712-cli-mainpy)
8. [Configuration Reference](#8-configuration-reference)
9. [Data Flow Diagrams](#9-data-flow-diagrams)
10. [Building From Scratch](#10-building-from-scratch)
11. [Known Limitations & Edge Cases](#11-known-limitations--edge-cases)

---

## 1. What This Project Does

A fully autonomous job-hunting agent that:

1. **Scrapes** job listings from 9+ sources (LinkedIn, Greenhouse, Lever, YC, Naukri, Wellfound, WeWorkRemotely, Indeed, Remotive)
2. **Scores** every job 0-100 based on your preferences (remote-first, startup preference, title match, skill overlap, freshness, salary)
3. **Filters out** jobs you'd never take (senior roles, specific companies, roles requiring too many years)
4. **Generates** a unique tailored resume PDF + cover letter PDF for every job using a local LLM
5. **Auto-applies** via LinkedIn Easy Apply (headless Playwright browser automation)
6. **Queues** non-LinkedIn jobs for manual review via a web dashboard
7. **Tracks** everything in SQLite so the same job is never processed twice

The entire LLM component runs locally via LM Studio (OpenAI-compatible API) — no cloud AI costs, no data sent to external servers.

---

## 2. Why Each Decision Was Made

### Local LLM instead of OpenAI API
- **Cost**: Generating a tailored resume per job with GPT-4 would cost ~$0.10–$0.30 per job. 25 jobs/week = ~$300/year. Local is free.
- **Privacy**: Your resume, employment history, and salary expectations never leave your machine.
- **Speed**: Qwen2.5-7B on an RTX 3050 does ~5s per job. GPT-4 is similar speed but adds network latency.
- **Trade-off**: 7B parameter models are weaker than GPT-4. Quality is "good enough" for resume optimization but not perfect. The `_anchor_facts()` guard (see section 7.3) compensates for LLM hallucination on factual fields.

### LM Studio specifically
- Provides an OpenAI-compatible REST API at `localhost:1234` — drop-in replacement for `openai.OpenAI(base_url=...)`.
- GUI for model management (no CLI required).
- Handles CUDA/Metal GPU acceleration automatically.
- Alternative: Ollama (simpler, fewer models), llama.cpp directly (more control, harder to set up).

### SQLite instead of PostgreSQL
- Single developer, local machine, no concurrency requirements.
- Zero setup — file-based, auto-created on first run.
- SQLAlchemy ORM means migrating to PostgreSQL later is a one-line change (`create_engine` URL).
- WAL journal mode enabled so the Flask dashboard and the agent can read simultaneously without locking.

### WeasyPrint for PDF generation
- HTML→PDF using CSS — lets you design resume layout with standard CSS.
- Alternative: ReportLab (verbose Python API, harder to style), LaTeX (powerful but requires LaTeX installation), Puppeteer (overkill).
- Trade-off: WeasyPrint requires system libraries (`libpango`, `libcairo`) that aren't always pre-installed. The `setup.sh` handles this.

### Playwright instead of Selenium/Requests for LinkedIn
- LinkedIn aggressively detects bot traffic via browser fingerprinting.
- Playwright supports `--disable-blink-features=AutomationControlled` and `navigator.webdriver = undefined` injection — the two main fingerprint tells.
- Cookie-based auth (injecting `li_at` cookie) avoids the login flow entirely.
- Alternative: Requests with session cookies (LinkedIn breaks this frequently), Selenium (slower, heavier, similar detection risk).

### Greenhouse/Lever/YC APIs instead of more aggregators
- Greenhouse and Lever are **public JSON APIs** — no auth, no Cloudflare, no scraping required.
- 100+ top tech companies post jobs there. Direct apply links mean less friction.
- Indeed/LinkedIn have Cloudflare protection that randomly blocks scrapers. Greenhouse/Lever never do.
- RemoteOK was disabled by default: many listings redirect to a paid Slack to apply.

### One LLM call per job (resume + cover letter combined)
- Original design made two separate calls: one for resume optimization, one for cover letter.
- Combined into one `{"resume": {...}, "cover_letter": "..."}` JSON response.
- Reason: halves the LLM call count, and the cover letter quality improves when the LLM sees the full optimized resume context simultaneously.

### JD hash caching
- LLM calls are slow (~5s/job on GPU, ~45s on CPU). Re-running `regenerate` without a cache would redo every job.
- SHA1 hash of `title|company|description[:1500]` → `data/optimize_cache/{hash}.json`.
- Cache is intentionally cleared by `regenerate` command to force fresh output.

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    main.py (CLI)                         │
│  weekly / run / scrape / dashboard / regenerate / stats  │
└─────────────────┬───────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────┐
│              JobAgent (orchestrator.py)                  │
│  1. load_resume()  2. scrape_jobs()  3. filter_and_rank()│
│  4. show_jobs()    5. process_job()                      │
└──┬──────────────┬────────────────┬───────────────────────┘
   │              │                │
   ▼              ▼                ▼
┌──────┐   ┌──────────┐   ┌─────────────┐
│ LLM  │   │ Scrapers │   │   Scorer    │
│Client│   │(9 boards)│   │ (0-100 pts) │
└──┬───┘   └────┬─────┘   └──────┬──────┘
   │            │                │
   │            ▼                ▼
   │     ┌──────────────────────────┐
   │     │   SQLite DB (Tracker)    │
   │     │  jobs: found/queued/     │
   │     │  applied/skipped/failed  │
   │     └──────────────────────────┘
   │
   ▼
┌────────────────────────────────────┐
│         ResumeOptimizer            │
│  parse_full() → optimize_with_cover│
│  → _anchor_facts()                 │
└──────┬──────────────┬──────────────┘
       │              │
       ▼              ▼
┌────────────┐  ┌─────────────┐
│ PDF Builder│  │ Cover Letter│
│(WeasyPrint)│  │ Generator   │
└────────────┘  └─────────────┘
       │
       ▼
┌─────────────────────────────────┐
│     LinkedIn Applier            │
│  Playwright → headless Chrome   │
│  inject li_at cookie → Easy Apply
└──────────────┬──────────────────┘
               │
               ▼ (non-LinkedIn jobs)
┌─────────────────────────────────┐
│     Flask Dashboard             │
│  http://127.0.0.1:5050          │
│  - review resumes/cover letters │
│  - mark applied / skip / reset  │
└─────────────────────────────────┘
```

---

## 4. Project Structure

```
Getmeajob/
├── main.py                     # All CLI commands (Click framework)
├── config.yaml                 # Your personal config (gitignored)
├── config.example.yaml         # Template — copy to config.yaml
├── setup.sh                    # One-time install: apt deps + venv + pip
├── requirements.txt
│
├── templates/
│   └── resume_modern.html      # Jinja2 HTML template → WeasyPrint → PDF
│
├── src/
│   ├── llm/
│   │   └── client.py           # LM Studio OpenAI-compat wrapper + JSON repair
│   │
│   ├── scrapers/
│   │   ├── base.py             # JobListing dataclass + BaseScraper ABC
│   │   ├── greenhouse.py       # boards-api.greenhouse.io public JSON API
│   │   ├── lever.py            # api.lever.co public JSON API
│   │   ├── ycombinator.py      # workatastartup.com paginated API
│   │   ├── naukri.py           # naukri.com/jobapi/v3/search
│   │   ├── linkedin.py         # Playwright headless scraper (cookie auth)
│   │   ├── indeed.py           # Playwright headless scraper
│   │   ├── wellfound.py        # Playwright headless scraper
│   │   ├── weworkremotely.py   # RSS feed parser
│   │   ├── remotive.py         # Public JSON API
│   │   └── remoteok.py         # Public JSON API (disabled by default)
│   │
│   ├── resume/
│   │   ├── parser.py           # pdfplumber PDF→text + regex contact extraction
│   │   ├── optimizer.py        # LLM prompts + _anchor_facts() + JD hash cache
│   │   └── builder.py          # Jinja2 → WeasyPrint → PDF
│   │
│   ├── agent/
│   │   ├── orchestrator.py     # JobAgent: main pipeline class
│   │   ├── scorer.py           # score_job() + rank_jobs() + hard filters
│   │   └── cover_letter.py     # wrap_letter() + save_text() + save_pdf()
│   │
│   ├── apply/
│   │   ├── linkedin.py         # LinkedInApplier: Playwright Easy Apply automation
│   │   └── generic.py          # GenericApplier: placeholder for future boards
│   │
│   ├── database/
│   │   └── tracker.py          # SQLAlchemy ORM: Job model + Tracker CRUD
│   │
│   └── web/
│       ├── app.py              # Flask API + static file serving
│       └── templates/
│           └── dashboard.html  # Single-page app (vanilla JS + CSS)
│
├── resumes/
│   ├── my_resume.pdf           # ← YOUR RESUME GOES HERE (gitignored)
│   └── generated/              # Per-job tailored PDFs (gitignored)
│
└── data/
    ├── jobs.db                 # SQLite database (gitignored, auto-created)
    └── optimize_cache/         # JD hash → LLM output JSON (gitignored)
```

---

## 5. Tech Stack & Dependencies

| Library | Why |
|---|---|
| `openai` | OpenAI Python SDK — used to talk to LM Studio's OpenAI-compat API |
| `tenacity` | Retry decorator on LLM calls (3 attempts, exponential backoff) |
| `pdfplumber` | Extracts plain text from PDF resumes reliably |
| `weasyprint` | HTML+CSS → PDF for resume/cover letter rendering |
| `jinja2` | Templating engine for the HTML resume template |
| `playwright` | Headless Chromium for LinkedIn scraping and Easy Apply automation |
| `requests` | HTTP client for Greenhouse, Lever, Naukri, Remotive APIs |
| `beautifulsoup4` | HTML parsing (optimize command, some scrapers) |
| `lxml` | Fast HTML/XML parser backend for BeautifulSoup |
| `sqlalchemy` | ORM for SQLite job tracker |
| `flask` | Web server for the dashboard |
| `click` | CLI framework for main.py commands |
| `rich` | Terminal pretty-printing (tables, colors, progress) |
| `pyyaml` | YAML config file parsing |
| `python-docx` | DOCX resume support (optional) |

**Python version**: 3.10+ required (uses `X | Y` union type hints, `list[str]` generics).

---

## 6. Pipeline: Step by Step

When you run `python main.py weekly` (or `run`), this is the exact execution order:

### Step 1 — Load and Parse Resume
```
resumes/my_resume.pdf
    → pdfplumber extracts raw text
    → regex extracts: name, email, phone, linkedin URL, github URL
    → LLM (PARSE_PROMPT) deep-parses raw text into structured JSON:
      {name, email, phone, summary, skills[], experience[], education[], projects[], certifications[]}
    → config.yaml candidate section fills in any missing contact fields
```
The two-stage parse (regex first, LLM second) is intentional: regex is fast and reliable for contact info, LLM is needed for structured sections like work experience bullets.

### Step 2 — Scrape Jobs
All enabled scrapers run in sequence (not parallel, to avoid rate limits):
```
LinkedIn       → Playwright, cookie auth, searches by keyword+location
Greenhouse     → GET boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true per company
Lever          → GET api.lever.co/v0/postings/{slug}?mode=json per company
YCombinator    → GET workatastartup.com/api/companies?isHiring=true (paginated)
Naukri         → GET naukri.com/jobapi/v3/search with keyword + experience filters
Wellfound      → Playwright, public listing pages
WeWorkRemotely → RSS feed via requests
Indeed         → Playwright
Remotive       → GET remotive.com/api/remote-jobs
```
Each scraper returns a list of `JobListing` dataclass objects. All lists are merged, then deduplicated by `job_id` (a string that includes the board name to prevent cross-board collisions, e.g. `greenhouse_stripe_123456`).

### Step 3 — Score and Filter
```
For each JobListing:
    1. Hard filters (return score=0, job dropped):
       - Company name in blacklist_companies
       - Title contains a blacklist_keyword (Senior, Lead, 5+ years, etc.)
       - SENIOR_TITLE regex matches the title AND max_years_to_claim < 4
       - JD requires more years than max_years_to_claim + 2
       - Onsite in a sponsor-required country AND JD says "no sponsorship"
    2. Soft scoring (0-100 points):
       - Remote role: +25
       - Geo match: +5 (India) or +10 (sponsor country, no explicit denial)
       - Startup signals: +20 / MNC: +10 / Unknown: +5
       - Title keyword match: up to +25
       - Skill overlap: up to +20 (candidate skills vs JD text)
       - Top-skill bonus: up to +10 (extra if top 5-6 skills are in JD)
       - Salary above target: +5 or +10
       - Freshness: +10 (≤1d), +7 (≤3d), +4 (≤7d)
       - Title confirmed in description body: +3

Jobs with score 0 are dropped entirely.
Jobs with score < min_score_to_apply (default 45) are also dropped.

Remaining jobs are sorted descending by score.
```

### Step 4 — Deduplicate with Database
```
For each scored job:
    If job_id already in DB (any status) → skip (already seen/applied)
    Else → save to DB with status="found"
```
This is the key mechanism that prevents re-processing the same job across multiple weekly runs.

### Step 5 — Process Each Job (the expensive step)
```
For each job (up to max_applications_per_run):
    1. ONE LLM call: optimize_with_cover(base_resume, job)
       → Returns {resume: {...optimized...}, cover_letter: "..."}
       → _anchor_facts() overwrites company/title/dates/education with base values
       → Result cached by JD hash in data/optimize_cache/

    2. Build PDF resume:
       resume_data dict → Jinja2 HTML → WeasyPrint → resumes/generated/{name}_{company}_{title}.pdf

    3. Build cover letter files:
       cover_letter text → wrap in header/footer → save as .txt
       cover_letter text → WeasyPrint → save as _cover.pdf

    4. Update DB status to "queued", store resume_path + cover_letter_path

    5a. If board == "linkedin":
        LinkedInApplier.apply() → Playwright headless browser:
            - Inject li_at session cookie
            - Navigate to job URL
            - Click "Easy Apply" button
            - Fill form fields (file upload, text inputs, radio buttons, dropdowns)
            - Submit
        If submitted → DB status = "applied"
        If failed (no Easy Apply button) → DB status = "skipped"

    5b. If board != "linkedin":
        Add to external_queue list
        DB status stays "queued"
        User reviews in dashboard and applies manually

    6. Human-like delay: sleep(random(8, 25)) seconds
```

### Step 6 — Notify and Open Dashboard
```
paplay complete.oga × 3  →  desktop notification (notify-send or kdialog)
webbrowser.open("http://127.0.0.1:5050")  →  Flask dashboard starts
```

---

## 7. Component Deep Dives

### 7.1 LLM Client

**File**: `src/llm/client.py`

The `LMStudioClient` wraps the `openai.OpenAI` SDK pointed at `http://localhost:1234/v1`.

**Model resolution**: If `model: "auto"` in config, it calls `client.models.list()` and picks the first loaded model. This is convenient — you just load whatever model you want in LM Studio and the code uses it.

**`chat_json()`** — the core method used by the optimizer:
1. First attempt: calls with `response_format={"type": "json_object"}` (strict JSON mode). This forces LM Studio to produce valid JSON, but some models ignore it.
2. If that fails: calls in free-form text mode and runs `parse_llm_json()` on the output.
3. `parse_llm_json()` pipeline:
   - Try `json.loads()` directly.
   - If that fails, run `_extract_json_block()` which finds the largest balanced `{...}` or `[...]` in the text (handles models that wrap their JSON in explanation text).
   - If that fails, run `_repair_json()` which fixes: trailing commas, smart quotes (`"` → `"`).
4. Returns `None` if all attempts fail (never raises).

The `@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))` decorator on `chat()` handles transient connection errors to LM Studio.

---

### 7.2 Resume Parser

**File**: `src/resume/parser.py`

Two stages:

**Stage 1 — Text extraction**:
- PDF: `pdfplumber` page-by-page text extraction. More reliable than PyPDF2 for complex layouts.
- DOCX: `python-docx` paragraph joining.

**Stage 2 — Regex extraction** (fast, no LLM):
- `_extract_email()`: standard email regex.
- `_extract_phone()`: matches `+` or digit start, 9-15 chars of digits/spaces/dashes/parens.
- `_extract_linkedin()`: matches `linkedin.com/in/...`.
- `_extract_github()`: matches `github.com/...`.
- `_extract_name()`: looks at the first 5 lines, finds one that's 2-4 capitalized words with no special chars (heuristic).

The output is a partial dict: `{name, email, phone, linkedin, github, raw_text}`. The `summary`, `skills`, `experience`, etc. are empty — filled by the LLM in the next step.

---

### 7.3 Resume Optimizer

**File**: `src/resume/optimizer.py`

This is the most critical and complex component.

**`parse_full(raw_text)`** — called once per session:

Uses `PARSE_PROMPT` to ask the LLM to extract ALL resume sections into a structured JSON object. Temperature=0.1 (near-deterministic) since we want exact extraction, not creativity.

**`optimize_with_cover(base_resume, job)`** — called once per job:

Uses `COMBINED_OPTIMIZE_PROMPT` which tells the LLM to:
1. Rewrite the `summary` for this specific role.
2. Reorder/add/remove `skills` based on the JD.
3. Rewrite all experience `bullets` with strong action verbs + JD-relevant keywords.
4. Generate EXACTLY 2 new `projects`:
   - Project A: ~1 week scope (small, focused, complete)
   - Project B: ~1 month scope (full-stack, multi-component)
   Both use tech from the JD's actual stack.
5. Generate a 3-paragraph `cover_letter` (specific company detail, 2 mapped experiences, availability).

**Honesty constraints baked into the prompt**:
- `DO NOT claim more years than total_experience`
- If not certified, use "Trained on X", "Hands-on with X", "Built projects with X" — NEVER "Certified in X"
- Copy `certifications` verbatim from input, never invent new ones

**`_anchor_facts(optimized, base)`** — runs after every LLM call:

The LLM sometimes "helpfully" changes company names, corrects dates, or improves job titles. This is a problem — those facts must be exact and match the candidate's real history.

`_anchor_facts` does a positional merge: for each position in `experience[]` and `education[]`, it overwrites the factual fields (`company`, `title`, `start`, `end`, `institution`, `degree`, `year`) from the base resume while keeping the LLM-optimized `bullets`.

It also handles LLM malformation defensively:
- If LLM returns `experience` as a dict instead of a list, converts it.
- Filters out any non-dict items in the list.
- Pads the list to the same length as base if LLM returned fewer entries.

**Caching**:
```python
cache_key = sha1(f"{title}|{company}|{description[:1500]}".lower())[:16]
cache_path = f"data/optimize_cache/{cache_key}.json"
```
On cache hit, the full `{"resume": ..., "cover_letter": ...}` dict is returned immediately without an LLM call. The `regenerate` command clears this cache.

---

### 7.4 Resume Builder (PDF)

**File**: `src/resume/builder.py`
**Template**: `templates/resume_modern.html`

`build_pdf(resume_data, output_path)`:
1. Loads the Jinja2 template from `templates/resume_modern.html`.
2. Passes the resume dict as template context (flattened fields: name, email, skills list, experience list, etc.).
3. Renders to HTML string.
4. WeasyPrint converts HTML+CSS → PDF.

The template is a standard HTML file styled with CSS. You can edit it like any webpage. WeasyPrint supports most CSS2/3 properties. Key limitations: no JavaScript, no external fonts by default (embed via `@font-face` or use system fonts).

Filename generation:
```python
f"{slug(name)}_{slug(company)}_{slug(title)}.pdf"
# e.g. "md_irfan_stripe_backend_developer.pdf"
```

---

### 7.5 Cover Letter Generator

**File**: `src/agent/cover_letter.py`

Three functions:
- `wrap_letter(body, resume_data)`: adds a header with candidate name/contact info and a signature line.
- `save_text(letter, path)`: saves plain text `.txt`.
- `save_pdf(letter, resume_data, path)`: renders through a minimal WeasyPrint HTML template to PDF.

The cover letter body itself comes from the LLM (part of the combined `optimize_with_cover` call). If the LLM fails, `_fallback_cover()` in the optimizer generates a generic 3-sentence letter.

---

### 7.6 Scrapers

**File**: `src/scrapers/base.py` (interface)

All scrapers inherit `BaseScraper` and implement:
- `board_name` property: string identifier (used in config + DB)
- `scrape(keywords: list[str]) → list[JobListing]`

`JobListing` dataclass fields:
```python
job_id: str         # Unique: board_companyslug_apiid
board: str          # "greenhouse", "linkedin", etc.
title: str
company: str
location: str
url: str            # The apply URL
description: str    # Full JD text (stripped of HTML)
salary: str         # Raw string, may be empty
is_remote: bool
company_type: str   # "startup" | "mnc" | "unknown"
score: float        # Set by scorer, default 0
raw: dict           # Original API response (for freshness date parsing)
```

#### Greenhouse (`src/scrapers/greenhouse.py`)
```
API: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Returns: {"jobs": [{id, title, location: {name}, content (HTML), absolute_url}]}
```
- Iterates all slugs in `config.boards.greenhouse.companies`.
- Filters by title keyword (any word from any search keyword matches).
- Filters by location: `is_remote` if "remote"/"anywhere" in location, else checks if any preferred location string appears.
- Strips HTML from `content` using regex (`<[^>]+>` → space).
- Sets `company_type="startup"` for all Greenhouse jobs (the vast majority are startups/scale-ups).

#### Lever (`src/scrapers/lever.py`)
```
API: GET https://api.lever.co/v0/postings/{slug}?mode=json
Returns: [{id, text (title), categories: {location}, descriptionPlain, lists[], additionalPlain}]
```
- Assembles full description from `descriptionPlain` + each `list.content` + `additionalPlain`.
- Location from `categories.location`.

#### YCombinator (`src/scrapers/ycombinator.py`)
```
API: GET https://www.workatastartup.com/api/companies?isHiring=true&page=N
Returns: {companies: [{name, jobs: [{title, remote, location, description, url}]}]}
```
- Paginates up to `max_pages` (default 4, ~200 companies).
- Each company has a `jobs[]` array.
- Sets `company_type="startup"` for all YC jobs.

#### Naukri (`src/scrapers/naukri.py`)
```
API: GET https://www.naukri.com/jobapi/v3/search
Query params: keyword, location, experience, noOfResults, pageNo
Headers: appId=109, systemId=Naukri, Content-Type=application/json
Returns: {jobDetails: [{jobId, title, companyName, location, jdURL, jobDescription}]}
```
- Iterates each keyword × each location combination.
- Paginates up to 3 pages per keyword.

#### LinkedIn (`src/scrapers/linkedin.py`)
Playwright headless Chromium, cookie auth (`li_at`), navigates job search pages, extracts listings from the DOM.

#### WeWorkRemotely (`src/scrapers/weworkremotely.py`)
Parses the RSS feed at `https://weworkremotely.com/categories/remote-programming-jobs.rss`.

#### Remotive (`src/scrapers/remotive.py`)
```
API: GET https://remotive.com/api/remote-jobs?category={category}
Returns: {jobs: [{id, url, title, company_name, candidate_required_location, description}]}
```

---

### 7.7 Job Scorer

**File**: `src/agent/scorer.py`

**Hard filters** (return `score=0.0` — job is completely dropped):

| Filter | Logic |
|---|---|
| Company blacklist | `any(b in company.lower() for b in blacklist_companies)` |
| Title blacklist | `any(kw in title.lower() for kw in blacklist_keywords)` |
| Senior title regex | `SENIOR_TITLE.search(title)` AND `max_years_to_claim < 4` |
| Years required | `_parse_required_years(description) > max_years_to_claim + 2` |
| No sponsorship | Onsite in sponsor country AND `NO_SPONSOR.search(description)` |

Regex patterns used:
```python
SENIOR_TITLE = r"\b(senior|sr\.?|staff|principal|lead|architect|head\s+of|director|vp|chief|manager)\b"
YEARS_REQUIRED = r"(\d+)\+?\s*(?:to\s*\d+\s*)?(?:years|yrs)\s*(?:of\s*)?(?:experience|exp)"
NO_SPONSOR = r"(no sponsorship|do not\s+sponsor|us citizen(?:s|ship)?\s+(?:only|required)|...)"
```

**Soft scoring**:

```
Remote:          job.is_remote OR "remote" in title OR "remote" in description[:200]
                 → +25 if remote, +10 if hybrid

Geo:             location contains sponsor_country (with no NO_SPONSOR) → +10
                 location contains onsite_fallback_country → +5

Company type:    startup → +20, mnc → +10, unknown → +5
                 (if type="unknown", re-checks description for startup/MNC signals)

Title match:     for each desired keyword, count word matches in title
                 all words match → +25 (full match)
                 partial match → +int(25 × matches/total_words)
                 (takes max across all keywords)

Skill overlap:   for each candidate skill, regex search in description
                 ratio = hits / total_skills
                 → up to +20 (round(ratio × 20))

Top-skill bonus: same loop, but only for top_skills list
                 → up to +10 (round(top_ratio × 10))

Title in desc:   any word from title (>3 chars) in description[:500] → +3

Salary:          if job.salary contains numbers AND offered >= min_salary → +10
                 if offered >= min_salary × 0.8 → +5

Freshness:       days_ago ≤ 1 → +10
                 days_ago ≤ 3 → +7
                 days_ago ≤ 7 → +4
```

Final score is capped at 100.

`rank_jobs()` scores all jobs, drops `score=0`, sorts descending.

---

### 7.8 Database Tracker

**File**: `src/database/tracker.py`

SQLAlchemy ORM with a single `Job` table:

```sql
CREATE TABLE jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT UNIQUE NOT NULL,    -- board-specific ID (e.g. "greenhouse_stripe_12345")
    board         TEXT,
    title         TEXT,
    company       TEXT,
    location      TEXT,
    is_remote     BOOLEAN,
    url           TEXT,
    description   TEXT,
    salary        TEXT,
    company_type  TEXT,
    score         REAL,
    found_at      DATETIME,
    status        TEXT DEFAULT 'found',   -- found|queued|applied|skipped|failed
    applied_at    DATETIME,
    resume_path   TEXT,
    cover_letter_path TEXT,
    notes         TEXT
);
```

Indexes on `status`, `board`, `score` for the dashboard's filter queries.

WAL mode (`PRAGMA journal_mode=WAL`) allows concurrent reads from Flask while the agent writes.

**Key methods**:
- `already_seen(job_id)`: returns `True` for any status. Prevents re-scraping entirely.
- `save_job(job_data)`: INSERT OR IGNORE pattern (returns existing if already present).
- `update_status(job_id, status, **kwargs)`: sets any column via `setattr`.
- `delete_by_status(statuses)`: used by `clear` command to wipe `"found"` jobs.
- `get_queued_full()`: returns all `status="queued"` jobs as dicts for `regenerate`.

---

### 7.9 LinkedIn Applier

**File**: `src/apply/linkedin.py`

The most brittle component — LinkedIn frequently changes their DOM structure.

**Auth**: Injects the `li_at` session cookie into a new Playwright context. This bypasses the login page entirely and lands directly into the logged-in state.

**Anti-detection**:
```python
args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
# Plus:
await context.add_init_script(
    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
)
```

**Easy Apply flow** (`_handle_modal`):
- Loops up to 10 steps.
- Each step: upload resume if file input exists → fill textareas (cover letter) → fill text/number inputs → handle radio buttons → handle dropdowns → check for Submit button.
- If Submit found: click it → return `True`.
- If Next/Continue/Review found: click it → continue loop.
- If nothing found: break.

**Form filling heuristics** (`_fast_answer`):
1. Heuristic layer: regex triggers on question text → hardcoded Yes/No answers for common questions.
2. LLM fallback: for complex or unusual questions, asks the LLM to pick from the available options. Temperature=0, max_tokens=50.
3. Final fallback: pick first non-empty option.

---

### 7.10 Orchestrator

**File**: `src/agent/orchestrator.py`

`JobAgent` is the main class. `run()` method calls:
1. `llm.is_available()` — fail fast if LM Studio not running.
2. `load_resume()` — parse PDF + LLM deep-parse.
3. `scrape_jobs()` — run all scrapers, deduplicate.
4. `filter_and_rank()` — score → filter → DB dedup → save new jobs.
5. `show_jobs()` — print Rich table. In `require_approval=False` mode, proceeds automatically.
6. Loop over selected jobs: `process_job(job)`.
7. `_write_external_report()` — markdown file listing all non-LinkedIn jobs.

`_load_scrapers()` instantiates scrapers in quality order: LinkedIn/Greenhouse/Lever/YC/Naukri (BEST) → Wellfound/WeWorkRemotely/Indeed (GOOD) → RemoteOK/Remotive (OK).

---

### 7.11 Flask Dashboard

**File**: `src/web/app.py`
**Template**: `src/web/templates/dashboard.html`

Flask app running at `http://127.0.0.1:5050`.

**API endpoints**:

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Serves `dashboard.html` |
| GET | `/api/stats` | `{total_found, applied, queued, skipped, failed}` |
| GET | `/api/jobs` | Paginated job list. Params: `status`, `search`, `page`, `per_page` |
| POST | `/api/jobs/status` | Update a job's status. Body: `{job_id, status, notes}` |
| GET | `/files/<path>` | Serve a file by relative path from project root |
| GET | `/files/abs?path=...` | Serve a file by absolute path |

**Security on file serving**: both file routes call `os.path.abspath()` and verify the result starts with `PROJECT_ROOT` to prevent path traversal attacks.

**Dashboard frontend** (vanilla JS, no framework):
- Stats bar at top — click any stat to filter job list.
- Job list table — sorted by score descending, searchable, filterable by status.
- Clicking a row opens a detail panel:
  - Job metadata (title, company, score, board, location).
  - "Open Job Page" button → opens apply URL in new tab.
  - Resume: embedded `<iframe>` showing the PDF, download link.
  - Cover letter: TXT/PDF tab toggle, embedded PDF viewer, download links.
  - Action buttons: "Mark Applied" / "Skip" / "Reset to Queued".

---

### 7.12 CLI (main.py)

Built with `Click`. All commands use `@cli.command()`.

| Command | What it does |
|---|---|
| `run` | Full pipeline: scrape → score → optimize → apply |
| `weekly` | Same as `run` + sound notification + auto-opens dashboard |
| `scrape` | Scrape and score only, no LLM/apply, prints table |
| `resume` | Parse resume with LLM, print extracted JSON |
| `optimize <URL>` | Single-job test: fetch URL, optimize, save to `output/` |
| `stats` | Print DB stats table + recent applications |
| `check` | Verify LM Studio, Playwright, resume file, LinkedIn cookie, WeasyPrint |
| `dashboard` | Start Flask + open browser |
| `clear` | Delete all `status="found"` rows from DB |
| `regenerate` | Re-optimize all `status="queued"` jobs (clears cache first) |

`_notify_done()` tries sound files in order: `complete.oga` → `bell.oga` → `Oxygen-Sys-App-Positive.ogg`. Uses `paplay` (PulseAudio). Desktop notification tries `notify-send` first, then `kdialog` (KDE).

---

## 8. Configuration Reference

Full `config.yaml` key reference:

```yaml
lmstudio:
  base_url: "http://localhost:1234/v1"   # LM Studio server URL
  api_key: "lm-studio"                   # Ignored by LM Studio, required by SDK
  model: "auto"                          # "auto" = first loaded model
  temperature: 0.7                       # 0.6 used for optimization, 0.1 for parsing
  max_tokens: 3500                       # Max output tokens per LLM call

candidate:
  name, email, phone, linkedin_url, github_url, location, notice_period
  expected_salary_min, expected_salary_max, currency
  total_experience                       # Plain text, injected into optimizer prompt
  max_years_to_claim: 2                  # Hard cap: skips JDs requiring (this+3)+ years
  top_skills: [...]                      # 5-6 skills for scorer bonus weight + prompt leading
  geo:
    onsite_fallback_countries: ["india"] # Always OK for onsite
    sponsor_required_countries: [...]    # OK only if JD doesn't deny sponsorship

search:
  keywords: [...]                        # Role titles to search for
  prefer_remote: true                    # Adds +25 to remote roles
  prefer_startups: true                  # Adds +20 to startups (vs +10 MNC)
  blacklist_companies: [...]             # Any company whose name contains these strings
  blacklist_keywords: [...]              # Drop jobs whose TITLE contains these
  min_score_to_apply: 45                 # Jobs below this are skipped
  max_applications_per_run: 25           # Safety cap per run
  require_approval: false                # true = asks before proceeding

boards:
  linkedin:
    enabled: true
    session_cookie: "..."                # li_at cookie from browser DevTools
    locations: [...]                     # Location filters for LinkedIn search
    date_posted: "past_week"

  greenhouse:
    enabled: true
    locations: [...]                     # Filter applied to location.name field
    companies: [...]                     # List of board slugs (boards.greenhouse.io/{slug})

  lever:
    enabled: true
    locations: [...]
    companies: [...]                     # List of slugs (jobs.lever.co/{slug})

  ycombinator:
    enabled: true
    locations: ["remote", "india", "anywhere"]
    max_pages: 4

  naukri:
    enabled: true
    locations: [...]
    experience_years: 1                  # Min experience filter in Naukri's API
    max_per_keyword: 30

  wellfound, weworkremotely:
    enabled: true/false

  indeed:
    enabled: true
    session_cookie: ""                   # Optional, for applying through Indeed

  remoteok:
    enabled: false                       # Off by default (paywall frustration)
    tags: [...]

  remotive:
    enabled: true
    categories: [...]

resume:
  input_path: "resumes/my_resume.pdf"
  output_dir: "resumes/generated"
  template: "modern"                     # Filename of template in templates/ (without .html)
  generate_portfolio_projects: true
  max_portfolio_projects: 2
  optimization_level: "aggressive"       # conservative | balanced | aggressive

apply:
  min_delay: 8                           # Seconds between applications (lower bound)
  max_delay: 25                          # Seconds between applications (upper bound)
  default_answers:
    years_experience: "1"
    authorized_to_work: "Yes"
    require_sponsorship: "Yes"
    willing_to_relocate: "Yes"
    available_start: "1 month"
    salary_expectation: ""               # Empty = uses expected_salary_min

notifications:
  desktop: true
  log_file: "data/applications.log"
```

---

## 9. Data Flow Diagrams

### Resume Processing

```
PDF file
  │
  ▼ pdfplumber
raw text string
  │
  ├─► regex → {name, email, phone, linkedin, github}
  │
  ▼ LLM (PARSE_PROMPT, temperature=0.1)
base_resume dict:
  {name, email, phone, linkedin, github, summary,
   skills[], experience[], education[], projects[], certifications[]}
  │
  │  (per job)
  ▼ LLM (COMBINED_OPTIMIZE_PROMPT, temperature=0.6)
raw_output: {"resume": {...}, "cover_letter": "..."}
  │
  ▼ _anchor_facts(raw_output.resume, base_resume)
optimized_resume dict:
  {summary: LLM-written,
   skills: LLM-reordered,
   experience: [{company: BASE, title: BASE, start: BASE, end: BASE,
                 bullets: LLM-rewritten}],
   projects: LLM-generated (2 new ones),
   education: [{institution: BASE, degree: BASE, year: BASE}],
   ...}
  │
  ├─► Jinja2 → HTML → WeasyPrint → resume_{name}_{company}_{title}.pdf
  │
  └─► wrap_letter(cover_letter, optimized_resume)
        → cover_letter_text
        → save as .txt
        → WeasyPrint → cover_letter.pdf
```

### Job Lifecycle in DB

```
[SCRAPE]  →  status="found"
               │
               ▼ (passes score threshold, not already seen)
[OPTIMIZE] →  status="queued"  +  resume_path  +  cover_letter_path
               │
               ├─► board=="linkedin" → Playwright Easy Apply
               │        ├─► success → status="applied"  +  applied_at
               │        └─► failure → status="skipped"  +  notes
               │
               └─► board!="linkedin" → stays "queued"
                        │
                        ▼ (user action in dashboard)
                   status="applied" | "skipped"
```

---

## 10. Building From Scratch

A developer who wants to rebuild this from scratch would follow this order:

### Phase 1: Foundation (day 1)

1. **Create `src/scrapers/base.py`** — `JobListing` dataclass and `BaseScraper` ABC.
2. **Create `src/database/tracker.py`** — SQLAlchemy `Job` model and `Tracker` CRUD.
3. **Write one scraper** — Start with `greenhouse.py` (simple GET request, no auth, reliable API).
4. **Write `main.py` with just `scrape` command** — verify scrapers work.

### Phase 2: LLM Integration (day 2)

5. **Create `src/llm/client.py`** — `LMStudioClient` wrapper with `chat_json()`.
6. **Create `src/resume/parser.py`** — pdfplumber + regex extraction.
7. **Test `chat_json()`** — feed a resume text, see what the LLM returns.
8. **Create `src/resume/optimizer.py`** — write `PARSE_PROMPT`, then `COMBINED_OPTIMIZE_PROMPT`.
   - Start with `parse_full()` only. Verify the LLM returns valid JSON.
   - Add `optimize_with_cover()`. Test with one job.
   - Add `_anchor_facts()` after you see the LLM mutate company names.
9. **Add JD hash caching** — you'll notice how slow repeated LLM calls are.

### Phase 3: PDF Generation (day 3)

10. **Create `templates/resume_modern.html`** — start with a simple HTML table layout. Add CSS.
11. **Create `src/resume/builder.py`** — Jinja2 render → WeasyPrint PDF.
12. **Create `src/agent/cover_letter.py`** — `wrap_letter()`, `save_text()`, `save_pdf()`.
13. **Test end-to-end**: scrape one job → optimize → build PDF → verify it looks right.

### Phase 4: Scoring (day 4)

14. **Create `src/agent/scorer.py`** — implement hard filters first, then soft scoring.
15. **Tune weights** — run `python main.py scrape` and look at which jobs score highest. Adjust weights.

### Phase 5: Orchestration (day 5)

16. **Create `src/agent/orchestrator.py`** — `JobAgent.run()` wiring all the steps together.
17. **Add all remaining scrapers** — lever, ycombinator, naukri, linkedin, etc.
18. **Add `run` command to `main.py`**.

### Phase 6: Application (day 6)

19. **Create `src/apply/linkedin.py`** — start with just browser navigation and cookie injection.
20. **Test Easy Apply step by step**: first just click the button, then handle file upload, then form fields.
21. **Add `_fast_answer()` heuristics** before adding LLM fallback.

### Phase 7: Dashboard (day 7)

22. **Create `src/web/app.py`** — Flask with `/api/stats` and `/api/jobs` endpoints first.
23. **Create `dashboard.html`** — build the job list table first, then the detail panel, then PDF embeds.
24. **Add file-serving endpoints** — `/files/` and `/files/abs` for serving generated PDFs.

### Phase 8: Polish (day 8)

25. **Add `weekly` command** with sound notification.
26. **Add `regenerate` and `clear` commands**.
27. **Add `check` command** for diagnostics.
28. **Write `setup.sh`** — automate apt deps + venv + pip + playwright install.
29. **Write `config.example.yaml`** — replace all personal values with placeholders.
30. **Add `.gitignore`** for `config.yaml`, `resumes/*.pdf`, `data/`, `output/`, `venv/`.

---

## 11. Known Limitations & Edge Cases

### LinkedIn cookie expiry
`li_at` cookies expire every 2-4 weeks. When they do, LinkedIn scraping returns 0 results and Easy Apply silently fails. Fix: re-paste a fresh cookie from DevTools.

### LinkedIn DOM changes
LinkedIn changes their DOM structure periodically. The CSS selectors in `src/apply/linkedin.py` for the Easy Apply button, form fields, and Submit button may break. When Easy Apply stops working, inspect the current DOM and update the selectors.

### LLM JSON malformation
Even with `response_format=json_object`, small LLMs (7B) sometimes:
- Return experience as a dict instead of a list (handled by `_anchor_facts` normalization).
- Return only 1 project instead of 2 (no enforcement — accepted as-is).
- Return the cover letter as part of the JSON rather than as the `cover_letter` key (unhandled — falls back to `_fallback_cover`).
- Truncate output at `max_tokens` mid-JSON (returns `None` from `chat_json`, falls back to base resume).

### Greenhouse slug validity
Not all slugs in the config are valid. If a company migrated away from Greenhouse or uses a different slug, `_fetch_company_jobs` gets a non-200 response and silently skips it. Add logging if you want to audit.

### Naukri anti-scraping
Naukri's API sometimes returns empty results or rate-limits aggressive scraping. The `experience_years` and `max_per_keyword` settings help keep requests lightweight.

### WeasyPrint system dependencies
WeasyPrint requires `libpango`, `libcairo`, `libgdk-pixbuf2.0`, `libffi`, `libglib2.0` on Linux. The `setup.sh` installs these via `apt`. On non-Debian systems, install the equivalent packages manually.

### GPU VRAM requirements
Qwen2.5-7B Q4_K_M requires ~4.1GB VRAM. On a 6GB card (RTX 3050, 3060 laptop), load with all 28 layers on GPU. On 4GB cards, offload 20-24 layers to GPU and the rest to RAM (slower). 13B+ models will overflow 6GB VRAM — don't load them.

### Multi-page Easy Apply
LinkedIn's Easy Apply modal can have 1-10 steps depending on the company's settings. The `_handle_modal` loop handles up to 10 steps. Some companies add unusual custom screening questions that the heuristics don't recognize — these get answered by the LLM fallback, which may choose poorly.

### Score threshold tuning
The default `min_score_to_apply: 45` was tuned for a developer with ~2 years experience targeting remote roles in India and remote-with-sponsorship roles globally. If you're in a different market, adjust:
- Lower threshold (35-40) → more applications, lower average quality.
- Higher threshold (55-60) → fewer but better-matched applications.
- Add or remove `blacklist_keywords` to control which titles appear.
