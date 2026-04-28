"""
RemoteOK scraper — uses their public JSON API. No auth needed.
https://remoteok.com/api
"""
import time
import requests
from .base import BaseScraper, JobListing

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "application/json",
}

MNC_KEYWORDS = {"google", "microsoft", "amazon", "meta", "apple", "netflix", "oracle",
                "ibm", "accenture", "infosys", "wipro", "tcs", "cognizant", "capgemini",
                "deloitte", "pwc", "kpmg", "ey", "salesforce", "sap", "adobe"}


class RemoteOKScraper(BaseScraper):
    @property
    def board_name(self) -> str:
        return "remoteok"

    def scrape(self, keywords: list[str]) -> list[JobListing]:
        tags = self.board_config.get("tags", ["react", "python", "node", "fullstack"])
        results: list[JobListing] = []
        seen: set[str] = set()

        for tag in tags:
            try:
                resp = requests.get(
                    f"https://remoteok.com/api?tag={tag}",
                    headers=HEADERS,
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                # First element is metadata dict, skip it
                jobs = [j for j in data if isinstance(j, dict) and j.get("id")]

                for job in jobs:
                    jid = f"remoteok_{job['id']}"
                    if jid in seen:
                        continue
                    seen.add(jid)

                    company = job.get("company", "Unknown")
                    ctype = "mnc" if company.lower() in MNC_KEYWORDS else "unknown"

                    results.append(JobListing(
                        job_id=jid,
                        board="remoteok",
                        title=job.get("position", ""),
                        company=company,
                        location="Remote",
                        url=job.get("url", f"https://remoteok.com/l/{job['id']}"),
                        description=job.get("description", ""),
                        salary=f"{job.get('salary_min', '')} - {job.get('salary_max', '')}".strip(" -"),
                        is_remote=True,
                        company_type=ctype,
                        tags=job.get("tags", []),
                    ))

                time.sleep(1.5)  # Rate limit respect

            except Exception as e:
                print(f"[RemoteOK] Error for tag={tag}: {e}")
                continue

        return results
