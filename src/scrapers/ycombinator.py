"""
Y Combinator "Work at a Startup" scraper.

Public job board: https://www.ycombinator.com/jobs
Public listing API (used by their site): https://www.ycombinator.com/api/companies/jobs

Hundreds of YC companies post here, many remote/India-friendly.
Direct apply via company website — no paywall, low competition.
"""
import requests
from .base import BaseScraper, JobListing


YC_API = "https://www.ycombinator.com/api/companies"


class YCombinatorScraper(BaseScraper):
    @property
    def board_name(self) -> str:
        return "ycombinator"

    def scrape(self, keywords: list[str]) -> list[JobListing]:
        kw_lower = [k.lower() for k in keywords]
        candidate_locations = [
            l.lower() for l in self.board_config.get("locations", ["remote", "india"])
        ]
        max_pages = self.board_config.get("max_pages", 4)

        results: list[JobListing] = []
        seen: set[str] = set()

        for page in range(1, max_pages + 1):
            try:
                params = {"page": page, "isHiring": "true"}
                r = requests.get(
                    YC_API,
                    params=params,
                    timeout=15,
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                )
                if r.status_code != 200:
                    break
                data = r.json()
            except Exception as e:
                print(f"[YC] page {page}: {e}")
                break

            companies = data.get("companies") if isinstance(data, dict) else data
            if not companies:
                break

            for c in companies:
                company_name = (c.get("name") or "").strip()
                company_slug = c.get("slug") or company_name.lower().replace(" ", "-")
                jobs = c.get("jobs") or []

                for j in jobs:
                    title = (j.get("title") or "").strip()
                    if not title:
                        continue

                    title_lower = title.lower()
                    if not any(any(w in title_lower for w in kw.split()) for kw in kw_lower):
                        continue

                    location = (j.get("location") or "").strip()
                    location_lower = location.lower()
                    is_remote = "remote" in location_lower or location == ""
                    region_ok = is_remote or any(loc in location_lower for loc in candidate_locations)
                    if not region_ok:
                        continue

                    jid = f"yc_{company_slug}_{j.get('id') or title_lower[:30]}"
                    if jid in seen:
                        continue
                    seen.add(jid)

                    results.append(JobListing(
                        job_id=jid,
                        board="ycombinator",
                        title=title,
                        company=company_name,
                        location=location or "Remote",
                        url=j.get("url") or f"https://www.ycombinator.com/companies/{company_slug}/jobs",
                        description=(j.get("description") or "")[:3000],
                        is_remote=is_remote,
                        company_type="startup",
                        salary=j.get("salary_range") or "",
                    ))

        return results
