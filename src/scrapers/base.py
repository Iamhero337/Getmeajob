"""Base scraper interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JobListing:
    job_id: str
    board: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    salary: str = ""
    is_remote: bool = False
    company_type: str = "unknown"   # startup | mnc | unknown
    tags: list[str] = field(default_factory=list)
    score: float = 0.0
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "board": self.board,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "description": self.description,
            "salary": self.salary,
            "is_remote": self.is_remote,
            "company_type": self.company_type,
            "score": self.score,
        }


class BaseScraper(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.board_config = config.get("boards", {}).get(self.board_name, {})

    @property
    @abstractmethod
    def board_name(self) -> str: ...

    @abstractmethod
    def scrape(self, keywords: list[str]) -> list[JobListing]: ...

    def is_enabled(self) -> bool:
        return self.board_config.get("enabled", False)
