"""Plugin contract cho mọi nguồn job (itviec, topcv, ...).

MỘT pattern duy nhất: mỗi source implement đủ 6 method dưới đây, và
`pipeline/runner.py` gọi chúng theo đúng thứ tự 6 bước — runner không có
`if source == ...` nào cả.

    scrape()          → ghi raw snapshot (JSON), trả ScrapeResult
    process()         → raw → processed JSON theo schema chuẩn, trả ProcessResult
    dashboard()        → processed CSV → HTML
    load_db()          → processed CSV → Postgres (theo db_spec())
    db_spec()          → khai báo bảng/cột cho loader generic
    staging_files()    → map file cần publish lên Kaggle

Thêm nguồn mới:
    1. Tạo class implement BaseSource trong `pipeline/sources/<ten>.py`
    2. Đăng ký 1 dòng trong `pipeline/sources/__init__.py`
    3. Thêm 1 entry trong `pipeline/settings.py::SOURCES`
Không sửa runner, CLI, DAG, shell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pipeline.core.contracts import DbSpec, ProcessResult, ScrapeResult


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
        """Bước 1 — scrape listings và ghi raw snapshot vào data_dir."""
        ...

    def process(self, data_dir: Path, out_dir: Path) -> ProcessResult:
        """Bước 2 — raw snapshot → processed JSON (schema chuẩn ở core/transform)."""
        ...

    def dashboard(self, processed: ProcessResult, out_dir: Path) -> Path:
        """Bước 3 — processed JSON → dashboard HTML."""
        ...

    def load_db(self, processed: ProcessResult) -> int:
        """Bước 4 (optional) — nạp processed JSON vào Postgres."""
        ...

    def db_spec(self) -> DbSpec:
        """Khai báo bảng/cột Postgres cho loader dùng chung."""
        ...

    def staging_files(self, data_dir: Path, dashboard_dir: Path) -> dict[Path, str]:
        """Bước 5 — file cần publish lên Kaggle (nguồn → tên file đích)."""
        ...


__all__ = ["BaseSource"]
