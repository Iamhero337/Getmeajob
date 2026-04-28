"""
Main agent orchestrator — the brain that runs everything end to end.

Pipeline:
  1. Parse resume → structured data
  2. Scrape job boards in priority order
  3. Score & rank all jobs
  4. Deduplicate with DB
  5. For top N jobs:
     a. Fetch full job description
     b. Optimize resume with LLM
     c. Generate cover letter with LLM
     d. Build PDF resume
     e. Apply (LinkedIn Easy Apply / generic)
     f. Mark applied in DB
"""
import os
import time
import random
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from src.llm.client import LMStudioClient
from src.database.tracker import Tracker
from src.resume.parser import parse_resume
from src.resume.optimizer import ResumeOptimizer
from src.resume.builder import build_pdf, resume_filename
from src.agent import cover_letter as cl
from src.agent.scorer import rank_jobs
from src.scrapers.base import JobListing
from src.apply.linkedin import LinkedInApplier
from src.apply.generic import GenericApplier

console = Console()


def _load_scrapers(config: dict) -> list:
    """Load enabled scrapers in order of QUALITY (best sources run first).

    BEST  — Direct-apply, low-paywall: LinkedIn, Greenhouse, Lever, YC, Naukri
    GOOD  — Free aggregators: Wellfound, WeWorkRemotely, Indeed
    OK    — Often paywalled or low-signal: RemoteOK, Remotive
    """
    scrapers = []
    boards = config.get("boards", {})

    # ── BEST: direct-apply, low competition ──────────────────────────────
    if boards.get("linkedin", {}).get("enabled"):
        from src.scrapers.linkedin import LinkedInScraper
        scrapers.append(LinkedInScraper(config))

    if boards.get("greenhouse", {}).get("enabled"):
        from src.scrapers.greenhouse import GreenhouseScraper
        scrapers.append(GreenhouseScraper(config))

    if boards.get("lever", {}).get("enabled"):
        from src.scrapers.lever import LeverScraper
        scrapers.append(LeverScraper(config))

    if boards.get("ycombinator", {}).get("enabled"):
        from src.scrapers.ycombinator import YCombinatorScraper
        scrapers.append(YCombinatorScraper(config))

    if boards.get("naukri", {}).get("enabled"):
        from src.scrapers.naukri import NaukriScraper
        scrapers.append(NaukriScraper(config))

    # ── GOOD: free aggregators ───────────────────────────────────────────
    if boards.get("wellfound", {}).get("enabled"):
        from src.scrapers.wellfound import WellfoundScraper
        scrapers.append(WellfoundScraper(config))

    if boards.get("weworkremotely", {}).get("enabled"):
        from src.scrapers.weworkremotely import WeWorkRemotelyScraper
        scrapers.append(WeWorkRemotelyScraper(config))

    if boards.get("indeed", {}).get("enabled"):
        from src.scrapers.indeed import IndeedScraper
        scrapers.append(IndeedScraper(config))

    # ── OK: often paywalled, low-signal — disable if frustrating ─────────
    if boards.get("remoteok", {}).get("enabled"):
        from src.scrapers.remoteok import RemoteOKScraper
        scrapers.append(RemoteOKScraper(config))

    if boards.get("remotive", {}).get("enabled"):
        from src.scrapers.remotive import RemotiveScraper
        scrapers.append(RemotiveScraper(config))

    return scrapers


class JobAgent:
    def __init__(self, config: dict):
        self.config = config
        self.tracker = Tracker()
        self.llm = LMStudioClient(config)
        self.optimizer = ResumeOptimizer(self.llm, config)
        self.li_applier = LinkedInApplier(self.llm, config)
        self.generic_applier = GenericApplier(config)
        self.require_approval = config.get("search", {}).get("require_approval", True)
        self.max_per_run = config.get("search", {}).get("max_applications_per_run", 20)
        self.min_score = config.get("search", {}).get("min_score_to_apply", 55)
        self.output_dir = config.get("resume", {}).get("output_dir", "resumes/generated")
        self.base_resume: dict = {}
        self.candidate_skills: list[str] = []

    # ------------------------------------------------------------------
    # Step 1: Load and parse resume
    # ------------------------------------------------------------------
    def load_resume(self) -> bool:
        path = self.config.get("resume", {}).get("input_path", "resumes/my_resume.pdf")
        if not os.path.exists(path):
            console.print(f"[red]Resume not found at: {path}[/red]")
            console.print("[yellow]Drop your resume PDF at resumes/my_resume.pdf and re-run.[/yellow]")
            return False

        console.print(f"[cyan]Parsing resume: {path}[/cyan]")
        from src.resume.parser import parse_resume as _parse
        raw_data = _parse(path)

        console.print("[cyan]Deep-parsing resume with LLM (this is the most important step)...[/cyan]")
        self.base_resume = self.optimizer.parse_full(raw_data["raw_text"])

        # Merge contact info from regex parser as fallback
        for field in ["name", "email", "phone", "linkedin", "github"]:
            if not self.base_resume.get(field):
                self.base_resume[field] = raw_data.get(field, "")

        # Merge with config overrides
        cand_cfg = self.config.get("candidate", {})
        for field in ["name", "email", "phone", "linkedin_url", "github_url", "location"]:
            cfg_val = cand_cfg.get(field, "")
            resume_key = field.replace("_url", "")
            if cfg_val and not self.base_resume.get(resume_key):
                self.base_resume[resume_key] = cfg_val

        self.candidate_skills = self.base_resume.get("skills", [])
        console.print(f"[green]✓ Resume parsed. Found {len(self.candidate_skills)} skills.[/green]")
        return True

    # ------------------------------------------------------------------
    # Step 2: Scrape jobs
    # ------------------------------------------------------------------
    def scrape_jobs(self) -> list[JobListing]:
        keywords = self.config.get("search", {}).get("keywords", ["software engineer"])
        scrapers = _load_scrapers(self.config)

        all_jobs: list[JobListing] = []
        for scraper in scrapers:
            console.print(f"[cyan]Scraping {scraper.board_name}...[/cyan]")
            try:
                jobs = scraper.scrape(keywords)
                console.print(f"[green]  → {len(jobs)} jobs from {scraper.board_name}[/green]")
                all_jobs.extend(jobs)
            except Exception as e:
                console.print(f"[red]  Error scraping {scraper.board_name}: {e}[/red]")

        # Deduplicate by job_id
        seen = set()
        unique = []
        for job in all_jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                unique.append(job)

        console.print(f"[bold green]Total unique jobs found: {len(unique)}[/bold green]")
        return unique

    # ------------------------------------------------------------------
    # Step 3: Score, filter, deduplicate with DB
    # ------------------------------------------------------------------
    def filter_and_rank(self, jobs: list[JobListing]) -> list[JobListing]:
        # Score all jobs
        ranked = rank_jobs(jobs, self.candidate_skills, self.config)

        # Filter by score threshold
        ranked = [j for j in ranked if j.score >= self.min_score]

        # Filter out already seen
        new_jobs = []
        for job in ranked:
            if not self.tracker.already_seen(job.job_id):
                new_jobs.append(job)
                # Save to DB as "found"
                d = job.to_dict()
                d["status"] = "found"
                self.tracker.save_job(d)

        console.print(f"[green]{len(new_jobs)} new jobs above score threshold {self.min_score}[/green]")
        return new_jobs

    # ------------------------------------------------------------------
    # Step 4: Show jobs and get approval
    # ------------------------------------------------------------------
    def show_jobs(self, jobs: list[JobListing]) -> list[JobListing]:
        if not jobs:
            return []

        table = Table(title="Top Job Matches", show_lines=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Score", justify="right", style="bold green", width=7)
        table.add_column("Title", style="cyan", min_width=25)
        table.add_column("Company", min_width=18)
        table.add_column("Remote", justify="center", width=8)
        table.add_column("Type", width=9)
        table.add_column("Board", width=12)

        for i, job in enumerate(jobs[:30], 1):
            table.add_row(
                str(i),
                str(job.score),
                job.title[:45],
                job.company[:25],
                "✓" if job.is_remote else "",
                job.company_type,
                job.board,
            )

        console.print(table)

        if self.require_approval:
            console.print("\n[yellow]Apply to all listed jobs? (y=yes all / n=no / comma-separated numbers)[/yellow]")
            choice = input("→ ").strip().lower()

            if choice == "n":
                return []
            if choice == "y":
                return jobs[:min(len(jobs), self.max_per_run)]
            # Parse number list
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",")]
                return [jobs[i] for i in indices if 0 <= i < len(jobs)]
            except ValueError:
                return jobs[:min(len(jobs), self.max_per_run)]
        else:
            return jobs[:min(len(jobs), self.max_per_run)]

    # ------------------------------------------------------------------
    # Step 5: Process each job — optimize, generate, apply
    # Returns (applied: bool, external_entry: dict|None)
    # external_entry is set for non-LinkedIn jobs queued for batch review
    # ------------------------------------------------------------------
    def process_job(self, job: JobListing) -> tuple[bool, dict | None]:
        console.print(f"\n[bold cyan]→ {job.title} @ {job.company}[/bold cyan] [dim](score {job.score}, {job.board})[/dim]")

        job_dict = job.to_dict()

        # ONE LLM call: produces optimized resume + cover letter together
        console.print("  [dim]LLM: optimizing resume + cover letter...[/dim]")
        try:
            bundle = self.optimizer.optimize_with_cover(self.base_resume, job_dict)
        except Exception as e:
            console.print(f"  [red]LLM bundle failed: {e}[/red] — using base resume")
            bundle = {"resume": self.base_resume, "cover_letter": ""}

        optimized = bundle.get("resume") or self.base_resume
        cover_body = bundle.get("cover_letter") or ""
        full_letter = cl.wrap_letter(cover_body, optimized)

        # Build PDFs
        filename = resume_filename(optimized, job_dict)
        resume_path = os.path.join(self.output_dir, filename)
        try:
            build_pdf(optimized, resume_path)
        except Exception as e:
            console.print(f"  [red]Resume PDF failed: {e}[/red]")
            resume_path = self.config.get("resume", {}).get("input_path", "")

        cl_txt_path = resume_path.replace(".pdf", "_cover.txt")
        cl_pdf_path = resume_path.replace(".pdf", "_cover.pdf")
        cl.save_text(full_letter, cl_txt_path)
        cl.save_pdf(full_letter, optimized, cl_pdf_path)

        self.tracker.update_status(
            job.job_id, "queued",
            resume_path=resume_path,
            cover_letter_path=cl_pdf_path,
        )

        # --- Apply ---
        applied = False
        external_entry = None

        if job.board == "linkedin":
            console.print("  [dim]LinkedIn Easy Apply (headless)...[/dim]")
            try:
                applied = self.li_applier.apply(job_dict, resume_path, full_letter)
            except Exception as e:
                console.print(f"  [red]Apply error: {e}[/red]")
                applied = False

            if applied:
                self.tracker.update_status(job.job_id, "applied")
                console.print("  [bold green]✓ Submitted[/bold green]")
            else:
                self.tracker.update_status(job.job_id, "skipped",
                                           notes="No Easy Apply or apply failed")
                console.print("  [yellow]Skipped (no Easy Apply)[/yellow]")
        else:
            external_entry = {
                "title": job.title,
                "company": job.company,
                "board": job.board,
                "url": job.url,
                "resume": resume_path,
                "cover_letter_pdf": cl_pdf_path,
                "cover_letter_txt": cl_txt_path,
                "score": job.score,
            }
            self.tracker.update_status(job.job_id, "queued",
                                       notes="External — see external_applications.md")
            console.print("  [cyan]Queued for batch (external)[/cyan]")

        # Human-like delay
        min_d = self.config.get("apply", {}).get("min_delay", 8)
        max_d = self.config.get("apply", {}).get("max_delay", 25)
        delay = random.uniform(min_d, max_d)
        time.sleep(delay)

        return applied, external_entry

    def _write_external_report(self, entries: list[dict]):
        """Write all external applications to a markdown report for batch review."""
        if not entries:
            return
        os.makedirs("output", exist_ok=True)
        path = "output/external_applications.md"
        with open(path, "w") as f:
            f.write("# External Applications — Open & Apply in One Session\n\n")
            f.write(f"Total: {len(entries)} jobs\n\n")
            for i, e in enumerate(entries, 1):
                f.write(f"## {i}. {e['title']} @ {e['company']}\n")
                f.write(f"- **Board:** {e['board']} | **Score:** {e['score']}\n")
                f.write(f"- **URL:** {e['url']}\n")
                f.write(f"- **Resume PDF:** {e['resume']}\n")
                f.write(f"- **Cover Letter PDF:** {e.get('cover_letter_pdf', '')}\n")
                f.write(f"- **Cover Letter TXT:** {e.get('cover_letter_txt', '')}\n\n")
        console.print(f"\n[bold yellow]External jobs report saved: {path}[/bold yellow]")
        console.print("[dim]Open that file, visit each URL, attach the resume & cover letter.[/dim]")

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------
    def run(self):
        console.print("\n[bold yellow]══════════════════════════════════[/bold yellow]")
        console.print("[bold yellow]         GET ME A JOB AGENT        [/bold yellow]")
        console.print("[bold yellow]══════════════════════════════════[/bold yellow]\n")

        # Check LM Studio
        if not self.llm.is_available():
            console.print("[red]LM Studio not available. Start LM Studio and load a model first.[/red]")
            return

        # Load resume
        if not self.load_resume():
            return

        # Scrape
        all_jobs = self.scrape_jobs()
        if not all_jobs:
            console.print("[yellow]No jobs found. Try enabling more boards or changing keywords.[/yellow]")
            return

        # Filter and rank
        new_jobs = self.filter_and_rank(all_jobs)
        if not new_jobs:
            console.print("[yellow]No new jobs above score threshold. Already applied to everything or adjust min_score.[/yellow]")
            return

        # Show table — in autonomous mode just print and proceed, no prompt
        selected = self.show_jobs(new_jobs)
        if not selected:
            console.print("[yellow]No jobs selected.[/yellow]")
            return

        applied_count = 0
        external_queue: list[dict] = []

        for job in selected:
            try:
                applied, ext = self.process_job(job)
                if applied:
                    applied_count += 1
                if ext:
                    external_queue.append(ext)
            except Exception as e:
                console.print(f"[red]Error processing {job.title}: {e}[/red]")
                self.tracker.update_status(job.job_id, "failed", notes=str(e))

        # Write external jobs report (open all at once after the run)
        self._write_external_report(external_queue)

        # Final stats
        stats = self.tracker.stats()
        console.print(f"\n[bold green]Run complete![/bold green]")
        console.print(f"  LinkedIn auto-applied: {applied_count}")
        console.print(f"  External jobs queued:  {len(external_queue)} (see output/external_applications.md)")
        console.print(f"[dim]Total ever applied: {stats['applied']} | Total found: {stats['total_found']}[/dim]")
