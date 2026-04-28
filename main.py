#!/usr/bin/env python3
"""
GET ME A JOB
============
AI-powered job hunting agent. Scrapes, scores, optimizes resumes, and applies.

Usage:
  python main.py run          # Full automated run
  python main.py scrape       # Scrape jobs only (no apply)
  python main.py optimize     # Test resume optimizer on a single job URL
  python main.py stats        # Show application statistics
  python main.py check        # Check all systems (LM Studio, Playwright, etc.)
  python main.py resume       # Parse + preview your resume
"""
import os
import sys
import json
import yaml
import click
from rich.console import Console
from rich.table import Table

console = Console()


def load_config(path: str = "config.yaml") -> dict:
    if not os.path.exists(path):
        console.print(f"[red]config.yaml not found. Run from the project root directory.[/red]")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


@click.group()
def cli():
    """Get Me a Job — AI job hunting agent powered by LM Studio."""
    pass


@cli.command()
@click.option("--config", default="config.yaml", help="Path to config file")
def run(config):
    """Full pipeline: scrape → score → optimize → apply."""
    cfg = load_config(config)
    from src.agent.orchestrator import JobAgent
    agent = JobAgent(cfg)
    agent.run()


@cli.command()
@click.option("--config", default="config.yaml", help="Path to config file")
def scrape(config):
    """Scrape jobs from all enabled boards and show results (no apply)."""
    cfg = load_config(config)
    from src.agent.orchestrator import JobAgent
    from src.agent.scorer import rank_jobs

    agent = JobAgent(cfg)
    if not agent.load_resume():
        return

    jobs = agent.scrape_jobs()
    ranked = rank_jobs(jobs, agent.candidate_skills, cfg)

    table = Table(title=f"Jobs Found ({len(ranked)} total)", show_lines=True)
    table.add_column("#", width=4)
    table.add_column("Score", justify="right", style="bold green", width=7)
    table.add_column("Title", style="cyan", min_width=25)
    table.add_column("Company", min_width=18)
    table.add_column("Remote", justify="center", width=8)
    table.add_column("Type", width=9)
    table.add_column("Board", width=12)

    for i, job in enumerate(ranked[:50], 1):
        table.add_row(
            str(i), str(job.score),
            job.title[:45], job.company[:25],
            "✓" if job.is_remote else "",
            job.company_type, job.board,
        )

    console.print(table)


@cli.command()
@click.option("--config", default="config.yaml", help="Path to config file")
def resume(config):
    """Parse your resume and preview what the agent extracted."""
    cfg = load_config(config)
    from src.llm.client import LMStudioClient
    from src.resume.parser import parse_resume
    from src.resume.optimizer import ResumeOptimizer

    path = cfg.get("resume", {}).get("input_path", "resumes/my_resume.pdf")
    if not os.path.exists(path):
        console.print(f"[red]Resume not found at: {path}[/red]")
        return

    console.print(f"[cyan]Parsing: {path}[/cyan]")
    raw = parse_resume(path)

    console.print("[cyan]Deep parsing with LLM...[/cyan]")
    llm = LMStudioClient(cfg)
    optimizer = ResumeOptimizer(llm, cfg)
    data = optimizer.parse_full(raw["raw_text"])

    console.print_json(json.dumps(data, indent=2))


@cli.command()
@click.option("--config", default="config.yaml", help="Path to config file")
def stats(config):
    """Show application statistics from the database."""
    cfg = load_config(config)
    from src.database.tracker import Tracker

    tracker = Tracker()
    s = tracker.stats()

    table = Table(title="Application Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="bold")

    table.add_row("Total Jobs Found", str(s["total_found"]))
    table.add_row("Applied", str(s["applied"]))
    table.add_row("Queued", str(s["queued"]))
    table.add_row("Skipped", str(s["skipped"]))
    table.add_row("Failed", str(s["failed"]))

    console.print(table)

    recent = tracker.recent_applications(10)
    if recent:
        rtable = Table(title="Recent Applications", show_lines=True)
        rtable.add_column("Title", style="cyan")
        rtable.add_column("Company")
        rtable.add_column("Board")
        rtable.add_column("Applied At")

        for r in recent:
            rtable.add_row(r["title"], r["company"], r["board"], r["applied_at"])

        console.print(rtable)


@cli.command()
@click.option("--config", default="config.yaml", help="Path to config file")
def check(config):
    """Check all system requirements (LM Studio, Playwright, resume file)."""
    cfg = load_config(config)
    all_ok = True

    # LM Studio
    console.print("[cyan]Checking LM Studio...[/cyan]")
    try:
        from src.llm.client import LMStudioClient
        llm = LMStudioClient(cfg)
        if llm.is_available():
            model = llm._get_model()
            console.print(f"[green]  ✓ LM Studio connected. Model: {model}[/green]")
        else:
            console.print("[red]  ✗ LM Studio not available. Start it and load a model.[/red]")
            all_ok = False
    except Exception as e:
        console.print(f"[red]  ✗ LM Studio error: {e}[/red]")
        all_ok = False

    # Playwright
    console.print("[cyan]Checking Playwright / Chromium...[/cyan]")
    try:
        import subprocess
        result = subprocess.run(
            ["python", "-m", "playwright", "install", "--dry-run"],
            capture_output=True, text=True
        )
        console.print("[green]  ✓ Playwright installed[/green]")
    except Exception as e:
        console.print(f"[yellow]  ⚠ Playwright check: {e}[/yellow]")

    # Resume
    console.print("[cyan]Checking resume...[/cyan]")
    path = cfg.get("resume", {}).get("input_path", "resumes/my_resume.pdf")
    if os.path.exists(path):
        console.print(f"[green]  ✓ Resume found: {path}[/green]")
    else:
        console.print(f"[red]  ✗ Resume not found: {path}[/red]")
        console.print(f"[yellow]    → Drop your PDF resume at: {path}[/yellow]")
        all_ok = False

    # LinkedIn cookie
    console.print("[cyan]Checking LinkedIn session cookie...[/cyan]")
    li_cookie = cfg.get("boards", {}).get("linkedin", {}).get("session_cookie", "")
    if li_cookie:
        console.print("[green]  ✓ LinkedIn session cookie set[/green]")
    else:
        console.print("[yellow]  ⚠ LinkedIn session cookie not set (needed for LinkedIn apply)[/yellow]")
        console.print("[dim]    Get it: DevTools → Application → Cookies → linkedin.com → li_at[/dim]")

    # WeasyPrint (PDF)
    console.print("[cyan]Checking WeasyPrint (PDF builder)...[/cyan]")
    try:
        import weasyprint
        console.print("[green]  ✓ WeasyPrint available[/green]")
    except ImportError:
        console.print("[red]  ✗ WeasyPrint not installed. Run: pip install weasyprint[/red]")
        all_ok = False

    if all_ok:
        console.print("\n[bold green]All systems ready! Run: python main.py run[/bold green]")
    else:
        console.print("\n[bold yellow]Fix the above issues, then run: python main.py check[/bold yellow]")


@cli.command()
@click.argument("job_url")
@click.option("--config", default="config.yaml", help="Path to config file")
def optimize(job_url, config):
    """Optimize your resume for a specific job URL (test mode)."""
    cfg = load_config(config)
    from src.llm.client import LMStudioClient
    from src.resume.parser import parse_resume
    from src.resume.optimizer import ResumeOptimizer
    from src.resume.builder import build_pdf
    from src.agent import cover_letter as cl
    import requests
    from bs4 import BeautifulSoup

    console.print(f"[cyan]Fetching job description from: {job_url}[/cyan]")
    try:
        resp = requests.get(job_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "lxml")
        desc = soup.get_text(separator=" ", strip=True)[:3000]
    except Exception as e:
        console.print(f"[red]Could not fetch URL: {e}[/red]")
        return

    path = cfg.get("resume", {}).get("input_path", "resumes/my_resume.pdf")
    raw = parse_resume(path)
    llm = LMStudioClient(cfg)
    optimizer = ResumeOptimizer(llm, cfg)

    console.print("[cyan]Parsing resume with LLM...[/cyan]")
    base = optimizer.parse_full(raw["raw_text"])

    job = {"title": "Job", "company": "Company", "description": desc, "board": "manual", "url": job_url}

    console.print("[cyan]Optimizing resume + cover letter (combined LLM call)...[/cyan]")
    bundle = optimizer.optimize_with_cover(base, job)
    optimized = bundle["resume"]
    letter = cl.wrap_letter(bundle["cover_letter"], optimized)

    os.makedirs("output", exist_ok=True)
    out = "output/optimized_test.pdf"
    build_pdf(optimized, out)
    console.print(f"[bold green]✓ Optimized resume: {out}[/bold green]")

    cl.save_text(letter, "output/cover_letter_test.txt")
    cl.save_pdf(letter, optimized, "output/cover_letter_test.pdf")
    console.print(f"[bold green]✓ Cover letter (txt + pdf): output/cover_letter_test.*[/bold green]")

    console.print("\n[yellow]Cover Letter Preview:[/yellow]")
    console.print(letter)


@cli.command()
@click.option("--config", default="config.yaml")
def clear(config):
    """Delete all 'found' jobs from DB (they were scraped but never processed)."""
    from src.database.tracker import Tracker
    tracker = Tracker()
    n = tracker.delete_by_status(["found"])
    console.print(f"[green]Deleted {n} 'found' jobs from DB.[/green]")
    s = tracker.stats()
    console.print(f"[dim]Remaining: {s['total_found']} total | {s['queued']} queued | {s['applied']} applied[/dim]")


@cli.command()
@click.option("--config", default="config.yaml")
def regenerate(config):
    """Re-optimize resumes for all queued jobs with the current LLM settings."""
    cfg = load_config(config)
    from src.llm.client import LMStudioClient
    from src.database.tracker import Tracker
    from src.resume.parser import parse_resume
    from src.resume.optimizer import ResumeOptimizer
    from src.resume.builder import build_pdf, resume_filename
    from src.agent import cover_letter as cl
    import shutil

    tracker = Tracker()
    queued = tracker.get_queued_full()
    if not queued:
        console.print("[yellow]No queued jobs to regenerate.[/yellow]")
        return

    console.print(f"[cyan]Re-optimizing {len(queued)} queued jobs...[/cyan]")

    if not LMStudioClient(cfg).is_available():
        console.print("[red]LM Studio not available. Start it first.[/red]")
        return

    # Parse resume
    path = cfg.get("resume", {}).get("input_path", "resumes/my_resume.pdf")
    if not os.path.exists(path):
        console.print(f"[red]Resume not found: {path}[/red]")
        return

    llm = LMStudioClient(cfg)
    optimizer = ResumeOptimizer(llm, cfg)
    raw = parse_resume(path)
    console.print("[cyan]Parsing resume with LLM...[/cyan]")
    base_resume = optimizer.parse_full(raw["raw_text"])
    cand_cfg = cfg.get("candidate", {})
    for field in ["name", "email", "phone", "linkedin_url", "github_url", "location"]:
        cfg_val = cand_cfg.get(field, "")
        resume_key = field.replace("_url", "")
        if cfg_val and not base_resume.get(resume_key):
            base_resume[resume_key] = cfg_val

    output_dir = cfg.get("resume", {}).get("output_dir", "resumes/generated")
    os.makedirs(output_dir, exist_ok=True)

    # Clear cache so every job gets a fresh LLM call
    cache_dir = "data/optimize_cache"
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)
    os.makedirs(cache_dir, exist_ok=True)
    console.print("[dim]Cleared optimize cache — all jobs will be freshly optimized.[/dim]")

    for i, job in enumerate(queued, 1):
        console.print(f"\n[bold cyan][{i}/{len(queued)}] {job['title']} @ {job['company']}[/bold cyan]")
        step = "llm"
        try:
            step = "llm"
            bundle = optimizer.optimize_with_cover(base_resume, job)
            optimized = bundle.get("resume") or base_resume

            # Normalise skills to list if LLM returned a dict or None
            if not isinstance(optimized.get("skills"), list):
                optimized["skills"] = list(optimized["skills"].values()) if isinstance(optimized.get("skills"), dict) else base_resume.get("skills", [])

            cover_body = bundle.get("cover_letter") or ""
            full_letter = cl.wrap_letter(cover_body, optimized)

            step = "pdf"
            filename = resume_filename(optimized, job)
            resume_path = os.path.join(output_dir, filename)
            build_pdf(optimized, resume_path)

            step = "cover"
            cl_txt_path = resume_path.replace(".pdf", "_cover.txt")
            cl_pdf_path = resume_path.replace(".pdf", "_cover.pdf")
            cl.save_text(full_letter, cl_txt_path)
            cl.save_pdf(full_letter, optimized, cl_pdf_path)

            step = "db"
            tracker.update_status(
                job["job_id"], "queued",
                resume_path=resume_path,
                cover_letter_path=cl_pdf_path,
            )
            console.print(f"  [green]✓ Done — {os.path.basename(resume_path)}[/green]")
        except Exception as e:
            import traceback as tb
            console.print(f"  [red]Error at [{step}]: {e}[/red]")
            console.print(f"  [dim]{tb.format_exc().strip()}[/dim]")
            continue

    console.print(f"\n[bold green]Regeneration complete. Open dashboard to apply.[/bold green]")
    console.print("[dim]Run: python main.py dashboard[/dim]")


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=5050, help="Port to listen on")
def dashboard(host, port):
    """Launch the job application dashboard in your browser."""
    import threading
    import webbrowser
    from src.web.app import run_dashboard
    url = f"http://{host}:{port}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    run_dashboard(host=host, port=port)


def _notify_done(jobs_queued: int):
    """Play a sound + desktop notification when the weekly run finishes."""
    import subprocess
    # Play sound — try a few well-known locations
    for snd in (
        "/usr/share/sounds/freedesktop/stereo/complete.oga",
        "/usr/share/sounds/freedesktop/stereo/bell.oga",
        "/usr/share/sounds/Oxygen-Sys-App-Positive.ogg",
    ):
        if os.path.exists(snd):
            try:
                # Play 3x so it's hard to miss
                subprocess.Popen(
                    f"for i in 1 2 3; do paplay {snd}; sleep 0.3; done",
                    shell=True,
                    stderr=subprocess.DEVNULL,
                )
                break
            except Exception:
                continue

    msg = f"{jobs_queued} jobs queued — dashboard opening..."
    # Try notify-send first, then kdialog (KDE), then ignore
    for cmd in (
        ["notify-send", "-u", "normal", "-i", "applications-development",
         "✓ Job Agent Done", msg],
        ["kdialog", "--title", "✓ Job Agent Done", "--passivepopup", msg, "8"],
    ):
        try:
            subprocess.run(cmd, stderr=subprocess.DEVNULL, timeout=3)
            return
        except Exception:
            continue


@cli.command()
@click.option("--config", default="config.yaml")
@click.option("--port", default=5050)
def weekly(config, port):
    """Weekly: scrape new jobs → generate resumes → DING → open dashboard."""
    cfg = load_config(config)
    from src.agent.orchestrator import JobAgent
    from src.database.tracker import Tracker

    console.print("\n[bold yellow]══════════════════════════════════[/bold yellow]")
    console.print("[bold yellow]      WEEKLY JOB HUNT — START      [/bold yellow]")
    console.print("[bold yellow]══════════════════════════════════[/bold yellow]\n")

    agent = JobAgent(cfg)
    agent.run()

    queued = Tracker().stats().get("queued", 0)
    console.print(f"\n[bold green]🔔 Done! {queued} jobs queued. Opening dashboard...[/bold green]\n")

    _notify_done(queued)

    # Now open dashboard (this blocks until Ctrl-C)
    import threading
    import webbrowser
    from src.web.app import run_dashboard
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    run_dashboard(host="127.0.0.1", port=port)


if __name__ == "__main__":
    cli()
