"""
Indeed scraper using Playwright (stealth). Indeed blocks requests-based scrapers.
"""
import asyncio
import hashlib
import random
import re
from .base import BaseScraper, JobListing

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

MNC_KEYWORDS = {
    "google", "microsoft", "amazon", "meta", "apple", "netflix", "oracle",
    "ibm", "accenture", "infosys", "wipro", "tcs", "cognizant", "capgemini",
}


class IndeedScraper(BaseScraper):
    @property
    def board_name(self) -> str:
        return "indeed"

    def scrape(self, keywords: list[str]) -> list[JobListing]:
        if not PLAYWRIGHT_AVAILABLE:
            print("[Indeed] playwright not installed — skipping")
            return []
        return asyncio.run(self._async_scrape(keywords))

    async def _async_scrape(self, keywords: list[str]) -> list[JobListing]:
        results: list[JobListing] = []
        seen: set[str] = set()
        locations = self.board_config.get("locations", ["Remote", "India"])

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
            )
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                window.chrome = { runtime: {} };
            """)
            page = await context.new_page()

            for kw in keywords[:4]:
                for loc in locations[:2]:
                    try:
                        params = f"q={kw.replace(' ', '+')}&l={loc.replace(' ', '+')}&fromage=7&sort=date"
                        if "remote" in loc.lower():
                            params += "&remotejob=032b3046-06a3-4876-8dfd-474eb5e7ed11"
                        url = f"https://www.indeed.com/jobs?{params}"

                        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        await asyncio.sleep(random.uniform(2, 4))

                        # Indeed sometimes shows a cloudflare challenge; bail gracefully
                        if "captcha" in page.url.lower() or "challenge" in page.url.lower():
                            break

                        for _ in range(2):
                            await page.evaluate("window.scrollBy(0, 600)")
                            await asyncio.sleep(random.uniform(0.5, 1.0))

                        cards = await page.query_selector_all("div.job_seen_beacon, [data-jk]")
                        for card in cards[:25]:
                            try:
                                jk = await card.get_attribute("data-jk")
                                title_el = await card.query_selector("h2 a, h2 span")
                                company_el = await card.query_selector(
                                    "[data-testid='company-name'], span.companyName"
                                )
                                loc_el = await card.query_selector(
                                    "[data-testid='text-location'], div.companyLocation"
                                )
                                salary_el = await card.query_selector(
                                    "[data-testid='attribute_snippet_testid'], div.salary-snippet"
                                )
                                link_el = await card.query_selector("h2 a")

                                title = (await title_el.inner_text()).strip() if title_el else ""
                                company = (await company_el.inner_text()).strip() if company_el else ""
                                location = (await loc_el.inner_text()).strip() if loc_el else loc
                                salary = (await salary_el.inner_text()).strip() if salary_el else ""

                                href = await link_el.get_attribute("href") if link_el else ""
                                job_url = (
                                    f"https://www.indeed.com{href}"
                                    if href and href.startswith("/")
                                    else (href or "")
                                )

                                if not jk:
                                    m = re.search(r"jk=([a-zA-Z0-9]+)", job_url)
                                    jk = m.group(1) if m else hashlib.md5(job_url.encode()).hexdigest()[:12]

                                jid = f"indeed_{jk}"
                                if jid in seen or not title:
                                    continue
                                seen.add(jid)

                                cname = company.lower()
                                ctype = "mnc" if any(m in cname for m in MNC_KEYWORDS) else "unknown"
                                is_remote = "remote" in location.lower()

                                results.append(JobListing(
                                    job_id=jid,
                                    board="indeed",
                                    title=title,
                                    company=company,
                                    location=location,
                                    url=job_url or f"https://www.indeed.com/viewjob?jk={jk}",
                                    description="",
                                    salary=salary,
                                    is_remote=is_remote,
                                    company_type=ctype,
                                ))
                            except Exception:
                                continue

                        await asyncio.sleep(random.uniform(2, 4))
                    except Exception as e:
                        print(f"[Indeed] Error '{kw}' / '{loc}': {e}")
                        continue

            await browser.close()

        return results
