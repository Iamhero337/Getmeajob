"""
WeWorkRemotely scraper — parses their RSS/HTML feeds.
Remote-only job board.
"""
import hashlib
import time
import requests
from bs4 import BeautifulSoup
from .base import BaseScraper, JobListing

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

CATEGORY_URLS = [
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-data-science-jobs.rss",
]


class WeWorkRemotelyScraper(BaseScraper):
    @property
    def board_name(self) -> str:
        return "weworkremotely"

    def scrape(self, keywords: list[str]) -> list[JobListing]:
        results: list[JobListing] = []
        seen: set[str] = set()
        kw_lower = [k.lower() for k in keywords]

        for rss_url in CATEGORY_URLS:
            try:
                resp = requests.get(rss_url, headers=HEADERS, timeout=15)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.content, "xml")
                items = soup.find_all("item")

                for item in items:
                    title = item.find("title").get_text(strip=True) if item.find("title") else ""
                    link = item.find("link").get_text(strip=True) if item.find("link") else ""
                    description = item.find("description").get_text(strip=True) if item.find("description") else ""
                    region = item.find("region").get_text(strip=True) if item.find("region") else "Remote"
                    company_el = item.find("company_name")
                    company = company_el.get_text(strip=True) if company_el else "Unknown"

                    # Keyword relevance filter
                    text = (title + " " + description).lower()
                    if not any(kw in text for kw in kw_lower):
                        continue

                    jid = "wwr_" + hashlib.md5(link.encode()).hexdigest()[:12]
                    if jid in seen:
                        continue
                    seen.add(jid)

                    results.append(JobListing(
                        job_id=jid,
                        board="weworkremotely",
                        title=title,
                        company=company,
                        location=region or "Remote",
                        url=link,
                        description=description,
                        is_remote=True,
                        company_type="unknown",
                    ))

                time.sleep(1)

            except Exception as e:
                print(f"[WWR] Error: {e}")
                continue

        return results
