# Get Me a Job

AI-powered job hunting agent. Scrapes job boards, optimizes your resume for each role using a local LLM (LM Studio), generates cover letters, and auto-applies via LinkedIn Easy Apply.

**Platform:** Linux (tested on KDE Neon) | **AI:** LM Studio (100% offline, free)

---

## What it does

```
YOUR RESUME (PDF)
     ↓
  LLM parses it into structured data
     ↓
  Scrapes 9 sources, sorted BEST → OK:
  ── BEST (direct apply, no paywall):
     LinkedIn → Greenhouse (~80 cos) → Lever → YC → Naukri
  ── GOOD (free aggregators):
     Wellfound → WeWorkRemotely → Indeed
  ── OK (often paywalled, off by default):
     RemoteOK → Remotive
     ↓
  Scores every job (0-100):
  Remote first → Startups → MNCs → title match → skill overlap
     ↓
  For each top job:
    - LLM rewrites summary, skills, bullets for that exact JD
    - LLM generates a custom cover letter
    - Builds a clean PDF resume
    - Auto-applies via LinkedIn Easy Apply
    - Queues external jobs for manual apply via dashboard
     ↓
  Tracks everything in SQLite — never re-scrapes the same job twice
```

---

## Setup (one time)

```bash
cd ~/Documents/Gits/Getmeajob
bash setup.sh
source venv/bin/activate
```

---

## Before running

### 1. Start LM Studio
- Open LM Studio → load **Qwen2.5-7B-Instruct** (or any 7B+ model)
- In Load settings: set **GPU Offload to 28/28** (all layers on GPU)
- Go to **Developer** tab → confirm **Status: Running** at `http://127.0.0.1:1234`

### 2. Drop your resume
```
resumes/my_resume.pdf   ← put your PDF here
```

### 3. Edit config.yaml

Critical settings:
```yaml
candidate:
  name: "Your Name"
  email: "your@email.com"
  phone: "+91XXXXXXXXXX"
  location: "India"
  notice_period: "1 month"
  expected_salary_min: 600000

boards:
  linkedin:
    session_cookie: "PASTE_YOUR_li_at_COOKIE_HERE"
```

Getting your LinkedIn `li_at` cookie:
1. Log into LinkedIn in Chrome
2. Press F12 → Application tab → Cookies → https://www.linkedin.com
3. Find `li_at` → copy its Value
4. Paste into config.yaml

---

## Commands

### Every session

```bash
cd ~/Documents/Gits/Getmeajob
source venv/bin/activate
```

### All commands

| Command | What it does |
|---|---|
| `python main.py weekly` | **The one to run.** Scrape → generate resumes → 🔔 DING + desktop notification → auto-open dashboard |
| `python main.py run` | Same as `weekly` but without the sound + auto-dashboard |
| `python main.py dashboard` | Open web UI to apply to queued jobs, track applications |
| `python main.py regenerate` | Re-generate resumes for all queued jobs (use after changing LLM or resume) |
| `python main.py clear` | Delete scraped-but-unprocessed jobs from DB, keep applied history |
| `python main.py stats` | Terminal stats: found / queued / applied / skipped |
| `python main.py check` | Verify LM Studio, Playwright, resume file, LinkedIn cookie |
| `python main.py scrape` | Scrape jobs only — no resume generation, no apply |
| `python main.py resume` | Parse your resume and show what the LLM extracted |
| `python main.py optimize <URL>` | Test resume optimization on a single job URL |

### Typical weekly workflow

```bash
# 1. Open LM Studio → load model → start server (Status: Running)
# 2. Then ONE command:

source venv/bin/activate
python main.py weekly        # scrape → generate → DING → opens dashboard

# The agent runs in your terminal. When done, it'll play a sound 3x and
# pop up a desktop notification. Browser opens automatically to the dashboard.
# Mark each job as "Applied" in the dashboard as you go.
# Press Ctrl-C in the terminal when you're done to stop the dashboard.
```

### If resumes look wrong or you update your resume PDF

```bash
python main.py regenerate    # re-does all queued resumes from scratch
```

---

## Dashboard

```bash
python main.py dashboard
# Opens http://127.0.0.1:5050
```

Features:
- Stats bar — Total Found / To Apply / Applied / Skipped (click to filter)
- Job list — sorted by score, searchable, filterable by status
- Click any job row to open the detail panel:
  - **Open Job Page** — opens the apply URL in a new tab
  - **Resume** — embedded PDF preview + download
  - **Cover Letter** — read as text or view as PDF, download both
  - **Mark Applied / Skip / Reset** — updates status instantly

---

## How resume optimization works

For every job, the LLM does this:

1. **Summary** — rewritten completely to target the specific role and company
2. **Skills** — reordered by relevance, JD keywords added, irrelevant ones removed
3. **Experience bullets** — rewritten to surface the most relevant work with strong action verbs and metrics
4. **Two new projects per JD** — one ~1 week scope (small but complete) + one ~1 month scope (full-stack), both using the JD's actual tech stack
5. **Cover letter** — 3 paragraphs: a specific JD detail (not boilerplate) → top 2 mapped experiences → availability

**Honesty rules baked into the prompt:**
- Never invents certifications. If JD asks for AWS/GCP and you don't have it, the LLM uses "Hands-on with X", "Trained on X", or surfaces it in a project bullet — never "Certified in X".
- Never claims more years than `candidate.max_years_to_claim` in config.

What never changes: company names, employment dates, education, contact info.

Optimization levels (set in `config.yaml` under `resume.optimization_level`):
- `conservative` — keyword polish only, no new claims
- `balanced` — expand adjacent skills, add reasonable metrics
- `aggressive` — full ATS keyword injection, quantified results, portfolio projects (default)

---

## Job scoring & filtering

**Hard filters (job dropped to score 0):**
- Company in `blacklist_companies` (e.g. Wipro)
- Title contains a `blacklist_keywords` word (Senior, Lead, Manager, "5+ years", etc.)
- JD requires more years than `max_years_to_claim + 2`
- Onsite role in a sponsor-required country with explicit "no sponsorship" in JD

**Soft scoring (totals 100):**

| Factor | Points |
|--------|--------|
| Remote role | +25 |
| Geo match (sponsor country, sponsorship not denied) | +10 |
| Startup company | +20 |
| Title keyword match | up to +25 |
| Skill overlap with JD | up to +20 |
| Top-skills bonus (Python, Linux, AI/ML, etc. mentioned) | up to +10 |
| Salary above target | up to +10 |
| Posted within last 24h | +10 (or +7 within 3d, +4 within 7d) |

Jobs below `min_score_to_apply: 45` are skipped.

---

## Project structure

```
Getmeajob/
├── main.py                    # CLI entry point — all commands here
├── config.yaml                # All your settings
├── setup.sh                   # One-time install script
├── requirements.txt
├── templates/
│   └── resume_modern.html     # PDF resume template (HTML → WeasyPrint)
├── src/
│   ├── llm/client.py          # LM Studio API wrapper
│   ├── scrapers/              # 6 job board scrapers (Playwright + requests)
│   ├── resume/                # Parser + LLM optimizer + PDF builder
│   ├── apply/                 # LinkedIn Easy Apply + generic applier
│   ├── agent/                 # Orchestrator + job scorer + cover letter
│   ├── web/                   # Flask dashboard (app.py + templates)
│   └── database/tracker.py   # SQLite application tracker
├── resumes/
│   ├── my_resume.pdf          # ← YOUR RESUME GOES HERE
│   └── generated/             # Tailored resume + cover letter per job
├── data/
│   ├── jobs.db                # SQLite database (auto-created)
│   └── optimize_cache/        # LLM output cache by JD hash (speeds up re-runs)
└── output/                    # Test outputs (optimize command)
```

---

## Tips

1. **Run daily** — most boards post fresh jobs in the morning. Early applicants get seen first.
2. **LinkedIn cookie expires** every few weeks — re-paste `li_at` from DevTools when LinkedIn shows 0 jobs.
3. **GPU matters** — Qwen2.5-7B on GPU takes ~5s per job. On CPU it takes ~45s. Keep LM Studio loaded.
4. **Wellfound** has the best ROI for developers with under 2 years experience (startups, less competition).
5. **After applying to a job**, mark it as Applied in the dashboard so it stays in your history.
6. **Bigger model = better resumes** — if you upgrade your GPU, try 14B or 32B models.
7. **config.yaml keywords** — add more target roles to scrape more jobs per run.
