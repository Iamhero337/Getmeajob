"""
Naukri.com scraper — India's largest job board.

Uses Naukri's public search JSON endpoint (no login needed):
  https://www.naukri.com/jobapi/v3/search

This is the highest-volume India source. For applying, you'll need to
log into Naukri manually in a browser (we just collect job links + JDs).
"""
import requests
from .base import BaseScraper, JobListing


NAUKRI_API = "https://www.naukri.com/jobapi/v3/search"


class NaukriScraper(BaseScraper):
    @property
    def board_name(self) -> str:
        return "naukri"

    def scrape(self, keywords: list[str]) -> list[JobListing]:
        results: list[JobListing] = []
        seen: set[str] = set()
        max_per_kw = self.board_config.get("max_per_keyword", 30)
        experience = str(self.board_config.get("experience_years", 1))
        locations = self.board_config.get("locations", ["india", "remote"])

        for kw in keywords[:8]:
            for loc in locations[:3]:
                try:
                    jobs = self._search(kw, loc, experience, max_per_kw)
                except Exception as e:
                    print(f"[Naukri] {kw}/{loc}: {e}")
                    continue

                for j in jobs:
                    jid_raw = j.get("jobId") or j.get("jobIdfromJD") or ""
                    if not jid_raw:
                        continue
                    jid = f"naukri_{jid_raw}"
                    if jid in seen:
                        continue
                    seen.add(jid)

                    title = (j.get("title") or "").strip()
                    company = (j.get("companyName") or "").strip()
                    placeholders = j.get("placeholders") or []
                    salary_str = ""
                    location_str = ""
                    exp_str = ""
                    for p in placeholders:
                        t = (p.get("type") or "").lower()
                        v = p.get("label", "")
                        if t == "salary":
                            salary_str = v
                        elif t == "location":
                            location_str = v
                        elif t == "experience":
                            exp_str = v

                    is_remote = "remote" in location_str.lower() or "wfh" in location_str.lower()
                    job_url = j.get("jdURL") or ""
                    if job_url and not job_url.startswith("http"):
                        job_url = f"https://www.naukri.com{job_url}"

                    desc = (j.get("jobDescription") or "").strip()[:3000]
                    tags = [t for t in (j.get("tagsAndSkills") or "").split(",") if t]

                    results.append(JobListing(
                        job_id=jid,
                        board="naukri",
                        title=title,
                        company=company,
                        location=location_str or "India",
                        url=job_url,
                        description=desc,
                        salary=salary_str,
                        is_remote=is_remote,
                        company_type="unknown",
                        tags=tags,
                    ))

        return results

    def _search(self, keyword: str, location: str, experience: str, count: int) -> list[dict]:
        params = {
            "noOfResults": str(min(count, 50)),
            "urlType": "search_by_key_loc",
            "searchType": "adv",
            "keyword": keyword,
            "location": location,
            "experience": experience,
            "k": keyword,
            "l": location,
            "seoKey": f"{keyword.replace(' ', '-')}-jobs-in-{location.replace(' ', '-')}",
            "pageNo": "1",
        }
        # Naukri requires these specific headers or returns 403
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "appId": "109",
            "systemId": "Naukri",
            "Referer": "https://www.naukri.com/",
        }
        r = requests.get(NAUKRI_API, params=params, headers=headers, timeout=20)
        if r.status_code != 200:
            return []
        return r.json().get("jobDetails", [])
