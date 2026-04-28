"""
SQLite job application tracker.
Tracks every job found, scored, and applied to — prevents duplicate applications.
"""
import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text,
    DateTime, Boolean, Index, event
)
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(256), unique=True, nullable=False)  # board-specific ID
    board = Column(String(64), nullable=False)
    title = Column(String(256))
    company = Column(String(256))
    location = Column(String(256))
    is_remote = Column(Boolean, default=False)
    url = Column(String(1024))
    description = Column(Text)
    salary = Column(String(128))
    company_type = Column(String(64))   # startup | mnc | unknown
    score = Column(Float, default=0.0)
    found_at = Column(DateTime, default=datetime.utcnow)

    # Application tracking
    status = Column(String(32), default="found")  # found | queued | applied | skipped | failed
    applied_at = Column(DateTime, nullable=True)
    resume_path = Column(String(512), nullable=True)
    cover_letter_path = Column(String(512), nullable=True)
    notes = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_board", "board"),
        Index("ix_jobs_score", "score"),
    )


class Tracker:
    def __init__(self, db_path: str = "data/jobs.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)

        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(connection, _):
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return Session(self.engine)

    def already_seen(self, job_id: str) -> bool:
        """Skip any job already in the DB — prevents re-scraping the same job."""
        with self.session() as s:
            return s.query(Job).filter_by(job_id=job_id).count() > 0

    def delete_by_status(self, statuses: list[str]) -> int:
        """Delete all jobs with the given statuses. Returns count deleted."""
        with self.session() as s:
            n = s.query(Job).filter(Job.status.in_(statuses)).delete(synchronize_session=False)
            s.commit()
            return n

    def get_queued_full(self) -> list[dict]:
        """Return all queued jobs as dicts for re-processing."""
        with self.session() as s:
            jobs = s.query(Job).filter_by(status="queued").order_by(Job.score.desc()).all()
            return [
                {
                    "job_id": j.job_id,
                    "board": j.board,
                    "title": j.title or "",
                    "company": j.company or "",
                    "location": j.location or "",
                    "url": j.url or "",
                    "description": j.description or "",
                    "score": j.score or 0,
                    "is_remote": bool(j.is_remote),
                    "company_type": j.company_type or "unknown",
                    "resume_path": j.resume_path or "",
                    "cover_letter_path": j.cover_letter_path or "",
                }
                for j in jobs
            ]

    def save_job(self, job_data: dict) -> Job:
        with self.session() as s:
            existing = s.query(Job).filter_by(job_id=job_data["job_id"]).first()
            if existing:
                return existing
            job = Job(**{k: v for k, v in job_data.items() if hasattr(Job, k)})
            s.add(job)
            s.commit()
            s.refresh(job)
            return job

    def update_status(self, job_id: str, status: str, **kwargs):
        with self.session() as s:
            job = s.query(Job).filter_by(job_id=job_id).first()
            if job:
                job.status = status
                if status == "applied":
                    job.applied_at = datetime.utcnow()
                for k, v in kwargs.items():
                    if hasattr(job, k):
                        setattr(job, k, v)
                s.commit()

    def get_queued(self, limit: int = 50) -> list[Job]:
        with self.session() as s:
            jobs = (
                s.query(Job)
                .filter_by(status="queued")
                .order_by(Job.score.desc())
                .limit(limit)
                .all()
            )
            s.expunge_all()
            return jobs

    def stats(self) -> dict:
        with self.session() as s:
            total = s.query(Job).count()
            applied = s.query(Job).filter_by(status="applied").count()
            queued = s.query(Job).filter_by(status="queued").count()
            skipped = s.query(Job).filter_by(status="skipped").count()
            failed = s.query(Job).filter_by(status="failed").count()
        return {
            "total_found": total,
            "applied": applied,
            "queued": queued,
            "skipped": skipped,
            "failed": failed,
        }

    def recent_applications(self, n: int = 20) -> list[dict]:
        with self.session() as s:
            jobs = (
                s.query(Job)
                .filter_by(status="applied")
                .order_by(Job.applied_at.desc())
                .limit(n)
                .all()
            )
            return [
                {
                    "title": j.title,
                    "company": j.company,
                    "board": j.board,
                    "applied_at": str(j.applied_at),
                    "url": j.url,
                }
                for j in jobs
            ]
