"""Data model của TopCV — contract giữa parser và scraper.

Cùng vai trò với `pipeline/sources/itviec/models.py`. Khác itviec (dùng pydantic
để validate HTML đổi cấu trúc), TopCV dùng dataclass thuần vì dữ liệu lấy từ
HTML đã render sẵn qua Playwright, phần validate nằm ở `parse_job_card`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Job:
    """Một tin tuyển dụng trên topcv.vn."""

    job_id: str = ""
    title: str = ""
    url: str = ""
    company: str = ""
    company_url: str = ""
    salary: str = ""
    location: str = ""
    experience: str = ""
    level: str = ""
    job_type: str = ""
    category: str = ""
    skills: list = field(default_factory=list)
    posted_date: str = ""
    deadline: str = ""
    is_hot: bool = False
    is_urgent: bool = False
    scrape_date: str = ""

    def __post_init__(self) -> None:
        if not self.scrape_date:
            self.scrape_date = datetime.now().strftime("%Y-%m-%d")


__all__ = ["Job"]
