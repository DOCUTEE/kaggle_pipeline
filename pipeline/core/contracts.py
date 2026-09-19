"""Data contracts dùng chung — 1 pattern cho mọi source.

`pipeline/runner.py` chỉ biết các kiểu này, không biết gì về itviec/topcv.
Source adapter (pipeline/sources/<ten>.py) chịu trách nhiệm implement
`BaseSource` và trả về đúng các kiểu ở đây.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Tên file processed chuẩn cho MỌI source (mỗi source 1 thư mục riêng).
# JSON (không CSV) để giữ đúng kiểu dữ liệu: list, bool, số — không phải parse chuỗi.
PROCESSED_JSON = "processed_jobs.json"


@dataclass
class ScrapeResult:
    """Kết quả bước 1 (scrape) — raw snapshot đã ghi xuống đĩa."""

    source: str
    count: int = 0
    raw_dir: Path | None = None
    latest_json: Path | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ProcessResult:
    """Kết quả bước 2 (process) — JSON đã clean + enrich, schema chuẩn."""

    source: str
    rows: int = 0
    json_path: Path | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DbSpec:
    """Khai báo cách nạp processed CSV vào Postgres.

    Mỗi source tự khai báo; `pipeline/db.py` chỉ có 1 loader duy nhất đọc spec này.
    """

    table: str
    #: db_column -> tên cột trong processed JSON (giữ nguyên tên thì map 1-1)
    columns: dict[str, str]
    #: cột dùng cho ON CONFLICT ... DO UPDATE (phải có unique index)
    conflict_key: str
    #: cột update khi conflict
    update_columns: tuple[str, ...] = ()
    #: cột list → JSONB
    json_columns: tuple[str, ...] = ()
    #: cột bool
    bool_columns: tuple[str, ...] = ()
    #: cột text luôn ép str (vd job_id)
    text_columns: tuple[str, ...] = ()
