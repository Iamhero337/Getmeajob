"""
Lever scraper — uses the public api.lever.co endpoint.

Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json

Like Greenhouse, this hits company career pages directly:
  - Direct apply links (no paywall)
  - Lower competition
  - Full descriptions in the API

Lever powers job pages for many tech companies (Netflix, Mixpanel, etc.).
The list of slugs is in config.yaml under boards.lever.companies.
"""
import requests
from .base import BaseScraper, JobListing


class LeverScraper(BaseScraper):
    @property
    def board_name(self) -> str:
        return "lever"

    def scrape(self, keywords: list[str]) -> list[JobListing]:
        companies = self.board_config.get("companies", [])
        if not companies:
            return []

        kw_lower = [k.lower() for k in keywords]
        candidate_locations = [
            l.lower() for l in self.board_config.get("locations", ["remote", "india"])
        ]

        results: list[JobListing] = []
        seen: set[str] = set()

        for slug in companies:
            try:
                jobs = self._fetch_company_jobs(slug)
            except Exception as e:
                print(f"[Lever] {slug}: {e}")
                continue

            for j in jobs:
                title = (j.get("text") or "").strip()
                if not title:
                    continue

                title_lower = title.lower()
                if not any(any(w in title_lower for w in kw.split()) for kw in kw_lower):
                    continue

                cats = j.get("categories") or {}
                location = (cats.get("location") or "").strip()
                commitment = (cats.get("commitment") or "").strip()
                team = (cats.get("team") or "").strip()
                location_lower = location.lower()

                is_remote = ("remote" in location_lower) or ("anywhere" in location_lower) or location == ""
                region_ok = is_remote or any(loc in location_lower for loc in candidate_locations)

                if not region_ok:
                    continue

                jid = f"lever_{slug}_{j.get('id')}"
                if jid in seen:
                    continue
                seen.add(jid)

                # Lever's description is broken into descriptionPlain + lists
                desc_parts = [
                    j.get("descriptionPlain") or "",
                    "\n".join(
                        f"{lst.get('text', '')}: " + " · ".join(lst.get("content", "").split("\n"))
                        for lst in (j.get("lists") or [])
                    ),
                    j.get("additionalPlain") or "",
                ]
                desc = "\n\n".join(p for p in desc_parts if p)[:4000]

                results.append(JobListing(
                    job_id=jid,
                    board="lever",
                    title=title,
                    company=slug.replace("-", " ").title(),
                    location=location or "Remote",
                    url=j.get("hostedUrl") or j.get("applyUrl") or "",
                    description=desc,
                    is_remote=is_remote,
                    company_type="startup",
                ))

        return results

    def _fetch_company_jobs(self, slug: str) -> list[dict]:
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        return r.json() if isinstance(r.json(), list) else []
