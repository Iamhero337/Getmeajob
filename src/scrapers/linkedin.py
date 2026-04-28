"""
LinkedIn scraper using Playwright with stealth techniques.

WARNING: LinkedIn TOS §8.2 prohibits scraping. Use your own account session.
The li_at cookie from your browser session is required. This mimics human browsing.

How to get your li_at cookie:
1. Log into LinkedIn in Chrome/Firefox
2. Open DevTools (F12) → Application → Cookies → linkedin.com
3. Copy the value of 'li_at'
4. Paste it in config.yaml under boards.linkedin.session_cookie
"""
import asyncio
import hashlib
import random
import time
from .base import BaseScraper, JobListing

try:
    from playwright.async_api import async_playwright, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


DATE_MAP = {
    "past_day": "r86400",
    "past_week": "r604800",
    "past_month": "r2592000",
}

MNC_KEYWORDS = {
    "google", "microsoft", "amazon", "meta", "apple", "netflix", "oracle",
    "ibm", "accenture", "infosys", "wipro", "tcs", "cognizant", "capgemini",
    "deloitte", "pwc", "kpmg", "ey", "salesforce", "sap", "adobe", "cisco",
    "intel", "qualcomm", "samsung", "sony", "hp", "dell", "lenovo",
}


class LinkedInScraper(BaseScraper):
    @property
    def board_name(self) -> str:
        return "linkedin"

    def scrape(self, keywords: list[str]) -> list[JobListing]:
        session_cookie = self.board_config.get("session_cookie", "")
        if not session_cookie:
            print("[LinkedIn] No session cookie set. Skipping. Add li_at to config.yaml")
            return []
        if not PLAYWRIGHT_AVAILABLE:
            print("[LinkedIn] playwright not installed — skipping")
            return []
        return asyncio.run(self._async_scrape(keywords, session_cookie))

    async def _async_scrape(self, keywords: list[str], session_cookie: str) -> list[JobListing]:
        results: list[JobListing] = []
        seen: set[str] = set()

        locations = self.board_config.get("locations", ["Remote", "India"])
        date_filter = DATE_MAP.get(self.board_config.get("date_posted", "past_week"), "r604800")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="Asia/Kolkata",
            )

            # Hide automation markers before any navigation
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                window.chrome = { runtime: {} };
            """)

            page = await context.new_page()

            # Warm-up: navigate to linkedin.com first, THEN inject cookie
            # Injecting cookie before any navigation causes ERR_TOO_MANY_REDIRECTS
            try:
                await page.goto("https://www.linkedin.com", wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass

            await context.add_cookies([{
                "name": "li_at",
                "value": session_cookie,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            }])

            # Verify session is active — navigate to feed
            try:
                await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
                if "login" in page.url or "authwall" in page.url:
                    print("[LinkedIn] Cookie invalid or expired. Re-paste li_at from browser DevTools.")
                    await browser.close()
                    return []
                print("[LinkedIn] Session verified ✓")
            except Exception:
                pass

            # Warm up jobs section before searching — prevents redirect loop
            try:
                await page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(random.uniform(2, 3))
            except Exception:
                pass

            for keyword in keywords[:5]:
                for location in locations[:2]:
                    try:
                        kw_q = keyword.replace(' ', '%20')
                        loc_q = location.replace(' ', '%20')
                        url = (
                            f"https://www.linkedin.com/jobs/search/?"
                            f"keywords={kw_q}&location={loc_q}"
                        )

                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(random.uniform(2, 4))

                        # Human-like scroll
                        for _ in range(4):
                            await page.evaluate(
                                f"window.scrollBy(0, {random.randint(300, 600)})"
                            )
                            await asyncio.sleep(random.uniform(0.5, 1.2))

                        job_cards = await page.query_selector_all(
                            ".jobs-search__results-list li"
                        )
                        # Also try the logged-in selector
                        if not job_cards:
                            job_cards = await page.query_selector_all(
                                "[data-occludable-job-id]"
                            )

                        for card in job_cards[:25]:
                            try:
                                job_id_attr = await card.get_attribute("data-occludable-job-id")
                                if not job_id_attr:
                                    link_el = await card.query_selector("a[href*='/jobs/view/']")
                                    if link_el:
                                        href = await link_el.get_attribute("href")
                                        import re
                                        m = re.search(r"/jobs/view/(\d+)", href or "")
                                        job_id_attr = m.group(1) if m else None

                                if not job_id_attr:
                                    continue

                                jid = f"linkedin_{job_id_attr}"
                                if jid in seen:
                                    continue
                                seen.add(jid)

                                title_el = await card.query_selector(
                                    ".base-search-card__title, h3.job-card-list__title"
                                )
                                company_el = await card.query_selector(
                                    ".base-search-card__subtitle, h4.job-card-container__company-name"
                                )
                                location_el = await card.query_selector(
                                    ".job-search-card__location, .job-card-container__metadata-item"
                                )
                                link_el = await card.query_selector("a")

                                title = await title_el.inner_text() if title_el else ""
                                company = await company_el.inner_text() if company_el else ""
                                loc = await location_el.inner_text() if location_el else location
                                href = await link_el.get_attribute("href") if link_el else ""
                                job_url = href.split("?")[0] if href else (
                                    f"https://www.linkedin.com/jobs/view/{job_id_attr}"
                                )

                                cname = company.strip().lower()
                                ctype = "mnc" if any(m in cname for m in MNC_KEYWORDS) else "unknown"
                                is_remote = "remote" in loc.lower() or "remote" in location.lower()

                                results.append(JobListing(
                                    job_id=jid,
                                    board="linkedin",
                                    title=title.strip(),
                                    company=company.strip(),
                                    location=loc.strip(),
                                    url=job_url,
                                    description="",  # Fetched on demand before apply
                                    is_remote=is_remote,
                                    company_type=ctype,
                                ))

                            except Exception:
                                continue

                        await asyncio.sleep(random.uniform(4, 8))

                    except Exception as e:
                        print(f"[LinkedIn] Error for '{keyword}' in '{location}': {e}")
                        continue

            await browser.close()

        return results

    async def fetch_description(self, job_id_num: str, session_cookie: str) -> str:
        """Fetch full job description for a single job before applying."""
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.add_cookies([{
                "name": "li_at", "value": session_cookie,
                "domain": ".linkedin.com", "path": "/",
                "httpOnly": True, "secure": True,
            }])
            page = await context.new_page()
            try:
                await page.goto(
                    f"https://www.linkedin.com/jobs/view/{job_id_num}",
                    wait_until="domcontentloaded", timeout=20000,
                )
                await asyncio.sleep(1.5)
                desc_el = await page.query_selector(".jobs-description__content")
                text = await desc_el.inner_text() if desc_el else ""
                return text[:4000]
            except Exception:
                return ""
            finally:
                await browser.close()
