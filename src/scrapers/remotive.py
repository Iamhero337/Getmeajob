"""
Remotive scraper — public API, no auth needed.
https://remotive.com/api/remote-jobs
"""
import time
import requests
from .base import BaseScraper, JobListing

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

MNC_KEYWORDS = {"google", "microsoft", "amazon", "meta", "apple", "netflix", "oracle",
                "ibm", "accenture", "infosys", "wipro", "tcs", "cognizant"}


class RemotiveScraper(BaseScraper):
    @property
    def board_name(self) -> str:
        return "remotive"

    def scrape(self, keywords: list[str]) -> list[JobListing]:
        categories = self.board_config.get(
            "categories", ["software-dev", "data", "all-others"]
        )
        results: list[JobListing] = []
        seen: set[str] = set()

        for kw in keywords[:6]:  # Limit to avoid rate limit
            try:
                resp = requests.get(
                    "https://remotive.com/api/remote-jobs",
                    params={"search": kw, "limit": 50},
                    headers=HEADERS,
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue

                jobs = resp.json().get("jobs", [])
                for job in jobs:
                    jid = f"remotive_{job['id']}"
                    if jid in seen:
                        continue
                    seen.add(jid)

                    company = job.get("company_name", "Unknown")
                    ctype = "mnc" if company.lower() in MNC_KEYWORDS else "unknown"

                    results.append(JobListing(
                        job_id=jid,
                        board="remotive",
                        title=job.get("title", ""),
                        company=company,
                        location="Remote",
                        url=job.get("url", ""),
                        description=job.get("description", ""),
                        salary=job.get("salary", ""),
                        is_remote=True,
                        company_type=ctype,
                        tags=job.get("tags", []),
                    ))

                time.sleep(1)

            except Exception as e:
                print(f"[Remotive] Error for keyword={kw}: {e}")
                continue

        return results
