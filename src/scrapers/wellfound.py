"""
Wellfound (AngelList) scraper — startup jobs.
Uses Playwright to handle JS-rendered content.
Priority source for startup jobs.
"""
import asyncio
import hashlib
import random
import time
from typing import Optional
from .base import BaseScraper, JobListing

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


SEARCH_KEYWORDS = [
    "full stack", "frontend", "backend", "python", "react",
    "software engineer", "ai engineer", "data engineer",
]


class WellfoundScraper(BaseScraper):
    @property
    def board_name(self) -> str:
        return "wellfound"

    def scrape(self, keywords: list[str]) -> list[JobListing]:
        if not PLAYWRIGHT_AVAILABLE:
            print("[Wellfound] playwright not installed — skipping")
            return []
        return asyncio.run(self._async_scrape(keywords))

    async def _async_scrape(self, keywords: list[str]) -> list[JobListing]:
        results: list[JobListing] = []
        seen: set[str] = set()

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            search_terms = keywords[:4]
            for term in search_terms:
                try:
                    url = (
                        f"https://wellfound.com/jobs?q={term.replace(' ', '+')}"
                        "&remote=true&jobType=fulltime"
                    )
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(random.uniform(2, 4))

                    # Scroll to load more jobs
                    for _ in range(3):
                        await page.evaluate("window.scrollBy(0, 800)")
                        await asyncio.sleep(random.uniform(0.8, 1.5))

                    job_cards = await page.query_selector_all('[data-test="StartupResult"]')

                    for card in job_cards[:20]:
                        try:
                            title_el = await card.query_selector("a[class*='jobTitle']")
                            company_el = await card.query_selector("a[class*='startupLink']")
                            location_el = await card.query_selector("[class*='location']")
                            link_el = await card.query_selector("a[href*='/jobs/']")

                            title = await title_el.inner_text() if title_el else ""
                            company = await company_el.inner_text() if company_el else ""
                            location = await location_el.inner_text() if location_el else "Remote"
                            href = await link_el.get_attribute("href") if link_el else ""
                            job_url = f"https://wellfound.com{href}" if href.startswith("/") else href

                            if not title:
                                continue

                            jid = "wf_" + hashlib.md5(job_url.encode()).hexdigest()[:12]
                            if jid in seen:
                                continue
                            seen.add(jid)

                            # Get description by visiting job page
                            desc = await self._get_description(context, job_url)

                            results.append(JobListing(
                                job_id=jid,
                                board="wellfound",
                                title=title.strip(),
                                company=company.strip(),
                                location=location.strip(),
                                url=job_url,
                                description=desc,
                                is_remote="remote" in location.lower(),
                                company_type="startup",  # Wellfound = startups
                            ))

                        except Exception:
                            continue

                    await asyncio.sleep(random.uniform(3, 6))

                except Exception as e:
                    print(f"[Wellfound] Error for '{term}': {e}")
                    continue

            await browser.close()

        return results

    async def _get_description(self, context, url: str) -> str:
        if not url:
            return ""
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1)
            desc_el = await page.query_selector("[class*='description']")
            text = await desc_el.inner_text() if desc_el else ""
            await page.close()
            return text[:3000]
        except Exception:
            return ""
