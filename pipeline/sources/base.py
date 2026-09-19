"""Plugin interface cho mọi nguồn job (itviec, topcv, ...).

PATTERN THỐNG NHẤT:
    scrape()  -> lưu raw (csv/json latest) -> trả ScrapeResult
    process/dashboard/load-db/kaggle/cleanup  -> dùng chung trong pipeline/runner.py

Thêm nguồn mới chỉ cần:
    1. Tạo class implement BaseSource trong pipeline/sources/<ten>.py
    2. Đăng ký vào pipeline/sources/__init__.py REGISTRY
Không sửa runner, CLI, DAG, shell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ScrapeResult:
    """Kết quả chuẩn của bước scrape, mọi source đều trả về kiểu này."""

    source: str
    count: int = 0
    raw_dir: Path | None = None
    latest_csv: Path | None = None
    latest_json: Path | None = None
    extra: dict = field(default_factory=dict)


class BaseSource(Protocol):
    """Contract mọi source phải tuân theo."""

    name: str

    def scrape(
        self,
        data_dir: Path,
        *,
        max_pages: int | None = None,
        workers: int = 1,
        timeout: int = 30,
        verbose: bool = False,
    ) -> ScrapeResult:
        """Scrape toàn bộ listings của source vào data_dir. Idempotent ở mức file."""
        ...
