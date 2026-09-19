"""Ghi raw snapshot — 1 implementation duy nhất cho mọi source (JSON-only).

- **Atomic writes**: temp file cùng thư mục + `os.replace()` → crash giữa chừng
  không bao giờ để lại JSON bị cắt cụt cho bước sau đọc nhầm.
- **Dedup trong 1 batch** theo `key_field` (fallback `url`) → snapshot idempotent.
- **`*_latest.json`**: bản copy luôn trỏ tới snapshot mới nhất cho consumer
  (process / Kaggle staging).
- **JSON thay CSV**: giữ đúng kiểu dữ liệu (list, bool, số) nên không cần
  join/split chuỗi; dữ liệu phân tích đọc từ Postgres/Grafana.

Quy ước file: `<prefix>_<run_id>.json` + `<prefix>_latest.json`
(vd `itviec_jobs_20260920_101500.json`).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

#: Dấu phân cách của các bản CSV cũ (`"a | b"`). Giữ lại để đọc dữ liệu legacy.
LIST_SEP = " | "


def split_list(value: Any) -> list[str]:
    """Chuẩn hoá giá trị list: nhận list thật (JSON) hoặc chuỗi CSV cũ `"a | b"`."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if value is None:
        return []
    if isinstance(value, float):  # NaN từ pandas
        return []
    text = str(value).strip()
    if not text or text == "[]":
        return []
    return [part.strip() for part in text.split(LIST_SEP) if part.strip()]


#: Mode cho file ghi ra volume dùng chung (host user + Airflow container khác uid).
#: mkstemp mặc định tạo 0600 → user khác không đọc được; 0664 cho phép đọc/rename.
SHARED_FILE_MODE = 0o664


def _atomic_write(path: Path, writer) -> None:
    """Ghi qua temp file cùng thư mục rồi `os.replace()` (atomic trên POSIX).

    Dùng `os.replace` nên ghi đè được cả file của user khác (rename chỉ cần quyền
    trên thư mục) — quan trọng vì volume này được ghi bởi cả host user lẫn
    Airflow container (uid 50000).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.fchmod(fd, SHARED_FILE_MODE)
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer(f)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _copy_latest(source: Path, latest_name: str) -> None:
    """Copy snapshot → `*_latest.*` cũng bằng atomic replace."""
    latest = source.parent / latest_name
    fd, tmp_name = tempfile.mkstemp(dir=str(source.parent), suffix=".tmp")
    os.close(fd)
    try:
        shutil.copy2(source, tmp_name)
        os.chmod(tmp_name, SHARED_FILE_MODE)  # copy2 giữ mode gốc (0600)
        os.replace(tmp_name, latest)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, payload: Any) -> Path:
    """Ghi JSON atomic (temp + os.replace) — dùng cho cả raw và processed."""
    def writer(f):
        json.dump(payload, f, ensure_ascii=False, indent=2)

    _atomic_write(Path(path), writer)
    return Path(path)


def atomic_write_text(path: Path, text: str) -> Path:
    """Ghi text atomic (dashboard HTML) — overwrite được file của user khác."""
    def writer(f):
        f.write(text)

    _atomic_write(Path(path), writer)
    return Path(path)


@dataclass
class SnapshotResult:
    """Snapshot đã ghi, dùng cho logging/metrics."""

    total: int = 0
    path_json: Path | None = None


class SnapshotStore:
    """Ghi raw rows (list[dict]) thành snapshot JSON."""

    def __init__(
        self,
        output_dir: Path,
        prefix: str,
        *,
        key_field: str = "job_id",
        source: str = "",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.prefix = prefix
        self.key_field = key_field
        self.source = source

    # ------------------------------------------------------------------
    def save(self, rows: Iterable[dict], *, run_id: str | None = None) -> SnapshotResult:
        """Ghi toàn bộ rows; trả về đường dẫn đã ghi."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique = self._dedupe(rows)

        if not unique:
            logger.warning("[%s] snapshot rỗng — không ghi file", self.prefix)
            return SnapshotResult(total=0)

        path = self._write_json(unique, run_id)
        return SnapshotResult(total=len(unique), path_json=path)

    # ------------------------------------------------------------------
    def _dedupe(self, rows: Iterable[dict]) -> list[dict]:
        """Gộp trùng theo key_field (fallback url); lần xuất hiện sau thắng."""
        unique: dict[str, dict] = {}
        for idx, row in enumerate(rows):
            key = str(row.get(self.key_field) or row.get("url") or f"__row{idx}")
            unique[key] = row
        return list(unique.values())

    def _write_json(self, rows: list[dict], run_id: str) -> Path:
        path = self.output_dir / f"{self.prefix}_{run_id}.json"
        payload = {
            "source": self.source or self.prefix.split("_")[0],
            "scraped_at": run_id,
            "total_jobs": len(rows),
            "jobs": rows,
        }
        atomic_write_json(path, payload)
        _copy_latest(path, f"{self.prefix}_latest.json")
        return path
