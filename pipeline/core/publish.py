"""Publish — staging + push Kaggle, dùng chung cho mọi source.

Source chỉ khai báo `staging_files()` (map `đường_dẫn_nguồn → tên_file_trên_Kaggle`),
phần copy và gọi Kaggle CLI nằm ở đây.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Mapping

import pandas as pd

logger = logging.getLogger(__name__)


def prepare_staging(staging_dir: Path, files: Mapping[Path, str]) -> Path:
    """Copy các file cần publish vào 1 staging dir chuẩn.

    Tránh push cả thư mục raw (kèm snapshot cũ) lên Kaggle.
    """
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    for src, dest_name in files.items():
        src = Path(src)
        if src.exists():
            shutil.copy2(src, staging_dir / dest_name)
        else:
            logger.warning("Kaggle staging: thiếu %s (bỏ qua)", src)
    return staging_dir


def push_to_kaggle(staging_dir: Path, dataset_id: str) -> bool:
    """Tạo metadata + `kaggle datasets version|create`. Trả True nếu thành công."""
    print(f"\n[kaggle] Pushing to {dataset_id}")
    meta = {
        "title": dataset_id.split("/")[-1],
        "id": dataset_id,
        "licenses": [{"name": "CC0-1.0"}],
    }
    (Path(staging_dir) / "dataset-metadata.json").write_text(json.dumps(meta, indent=2))

    def _run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["kaggle", *args], capture_output=True, text=True, timeout=300)

    try:
        result = _run(
            "datasets", "version",
            "-m", f"Auto update {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
            "-p", str(staging_dir), "--dir-mode", "zip",
        )
        if result.returncode == 0:
            print(f"  → Kaggle push SUCCESS\n{result.stdout}")
            return True

        print(f"  → Version failed, trying create: {result.stderr}")
        created = _run("datasets", "create", "-p", str(staging_dir), "--dir-mode", "zip")
        ok = created.returncode == 0
        print(f"  → {'SUCCESS' if ok else 'FAILED'}: {created.stdout or created.stderr}")
        return ok
    except FileNotFoundError:
        print("  → [WARN] kaggle CLI not found. Install: pip install kaggle")
    except subprocess.TimeoutExpired:
        print("  → [WARN] Kaggle push timed out")
    return False


def now_iso() -> str:
    """Timestamp ISO-8601 UTC dùng cho `scraped_at` khi scraper không cung cấp."""
    return datetime.now().astimezone().isoformat()
