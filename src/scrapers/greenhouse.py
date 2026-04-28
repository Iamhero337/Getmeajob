"""
Greenhouse scraper — uses the public boards-api.greenhouse.io endpoint.

Hundreds of high-quality companies post jobs on Greenhouse and expose them via:
  https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

This is one of the BEST job sources because:
  - Direct apply links to the company's own application form (no paywall)
  - Less competition than aggregators (most candidates use LinkedIn only)
  - Clean job descriptions returned in the API response

The list of company slugs is in config.yaml under boards.greenhouse.companies.
Adding a company is dead-simple: paste the slug from their boards URL.
e.g. boards.greenhouse.io/stripe → "stripe"
"""
import html
import re
import requests
from .base import BaseScraper, JobListing


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


class GreenhouseScraper(BaseScraper):
    @property
    def board_name(self) -> str:
        return "greenhouse"

    def scrape(self, keywords: list[str]) -> list[JobListing]:
        companies = self.board_config.get("companies", [])
        if not companies:
            return []

        kw_lower = [k.lower() for k in keywords]
        results: list[JobListing] = []
        seen: set[str] = set()
        candidate_locations = [
            l.lower() for l in self.board_config.get("locations", ["remote", "india"])
        ]

        for slug in companies:
            try:
                jobs = self._fetch_company_jobs(slug)
            except Exception as e:
                print(f"[Greenhouse] {slug}: {e}")
                continue

            for j in jobs:
                title = (j.get("title") or "").strip()
                if not title:
                    continue

                # Quick keyword filter on title (saves bandwidth/scoring time)
                title_lower = title.lower()
                if not any(any(w in title_lower for w in kw.split()) for kw in kw_lower):
                    continue

                location_obj = j.get("location") or {}
                location = (location_obj.get("name") or "").strip()
                location_lower = location.lower()

                is_remote = ("remote" in location_lower) or ("anywhere" in location_lower)
                # Region match: if our preferred locations are mentioned
                region_ok = is_remote or any(loc in location_lower for loc in candidate_locations)

                if not region_ok:
                    continue

                jid = f"greenhouse_{slug}_{j.get('id')}"
                if jid in seen:
                    continue
                seen.add(jid)

                desc = _strip_html(j.get("content", ""))[:4000]
                url = j.get("absolute_url") or f"https://boards.greenhouse.io/{slug}/jobs/{j.get('id')}"

                results.append(JobListing(
                    job_id=jid,
                    board="greenhouse",
                    title=title,
                    company=slug.replace("-", " ").title(),
                    location=location or "Remote",
                    url=url,
                    description=desc,
                    is_remote=is_remote,
                    company_type="startup",  # Most Greenhouse companies are startups/scale-ups
                ))

        return results

    def _fetch_company_jobs(self, slug: str) -> list[dict]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        return r.json().get("jobs", [])
