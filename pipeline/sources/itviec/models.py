"""Data contracts for ITviec scraped jobs.

Pydantic models act as the *data contract* between scraper layers:
if the site HTML changes and a field can no longer be parsed, validation
fails loudly at the boundary instead of silently writing empty strings.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class WorkingType(str, Enum):
    """Where the job is performed."""

    REMOTE = "Remote"
    HYBRID = "Hybrid"
    OFFICE = "At office"
    UNKNOWN = ""


class JobLabel(str, Enum):
    """Listing badge shown on the job card."""

    SUPER_HOT = "SUPER HOT"
    HOT = "HOT"
    NONE = ""


class Job(BaseModel):
    """A single job listing as scraped from the itviec.com listing page."""

    model_config = {"extra": "forbid"}

    # --- identity (from data-job-key / URL) ---
    job_key: str = Field(default="", description="Stable job UUID from data-job-key")
    url: str = Field(default="", description="Absolute job detail URL")

    # --- core fields ---
    title: str = ""
    company: str = ""
    salary: str = ""  # "Sign in to view salary" when login-gated
    job_function: str = ""  # e.g. "Site Reliability Engineer (SRE)"
    working_type: WorkingType = WorkingType.UNKNOWN
    location: str = ""
    tags: list[str] = Field(default_factory=list)
    posted_time: str = ""  # relative, e.g. "3 hours ago"
    label: JobLabel = JobLabel.NONE
    highlights: list[str] = Field(default_factory=list)

    # --- provenance ---
    page: int = Field(default=0, ge=0)
    scraped_at: str = ""  # ISO-8601 timestamp of the run that captured this row
    source: str = "itviec"

    @field_validator("job_key", "title", "url", "company", mode="before")
    @classmethod
    def _strip_strings(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("tags", "highlights", mode="before")
    @classmethod
    def _dedupe_lists(cls, v: Any) -> Any:
        if not isinstance(v, list):
            return v
        seen: set[str] = set()
        out: list[str] = []
        for item in v:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
        return out

    @property
    def dedup_key(self) -> str:
        """Stable identity used for upsert deduplication."""
        return self.job_key or self.url