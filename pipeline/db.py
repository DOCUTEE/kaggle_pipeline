#!/usr/bin/env python3
"""Loader PostgreSQL — 1 implementation duy nhất cho mọi source.

Trước đây mỗi source có 1 hàm load copy-paste. Nay source khai báo `DbSpec`
(bảng, cột, khoá conflict, cột JSON/bool) và loader này làm phần còn lại.

Nguồn dữ liệu là processed JSON (`ProcessResult.json_path`); đây cũng là
đường tiêu thụ chính thức — phân tích/dashboard query thẳng Postgres.

Không có CLI riêng: gọi từ runner qua `adapter.load_db()`
(`python -m pipeline run <source> --load-db`).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.core.contracts import DbSpec
from pipeline.core.transform import load_processed_df
from pipeline.core.snapshot import split_list

# ─── CONFIG ───────────────────────────────────────────────────────────────────

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "kaggle_pipeline"),
    "user": os.getenv("DB_USER", "pipeline"),
    "password": os.getenv("DB_PASSWORD", "pipeline_dev_2024"),
}


def _get_conn():
    """Get psycopg2 connection."""
    try:
        import psycopg2
        return psycopg2.connect(**DB_CONFIG)
    except ImportError:
        print("[ERROR] psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Cannot connect to PostgreSQL: {e}")
        print("  Make sure Docker is running: docker compose -f infra/docker-compose.yml up -d")
        sys.exit(1)


# ─── VALUE COERCION ───────────────────────────────────────────────────────────

def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _scalar(value: Any) -> Any:
    """NaN/None → NULL cho Postgres."""
    return None if _is_missing(value) else value


def _json_value(value: Any) -> str:
    """Cột list → JSON array cho JSONB (nhận cả list thật lẫn chuỗi CSV cũ)."""
    return json.dumps(split_list(value), ensure_ascii=False)


def _bool_value(value: Any) -> bool:
    if _is_missing(value):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("true", "1", "yes", "y", "t")


def _text_value(value: Any) -> str:
    return "" if _is_missing(value) else str(value)


def coerce_row(row: pd.Series, spec: DbSpec) -> tuple:
    """Lấy giá trị theo `spec.columns` (db_column → cột processed JSON) và ép kiểu."""
    values = []
    for db_col, csv_col in spec.columns.items():
        raw = row.get(csv_col)
        if db_col in spec.json_columns:
            values.append(_json_value(raw))
        elif db_col in spec.bool_columns:
            values.append(_bool_value(raw))
        elif db_col in spec.text_columns:
            values.append(_text_value(raw))
        else:
            values.append(_scalar(raw))
    return tuple(values)


def build_insert_sql(spec: DbSpec) -> str:
    """Sinh câu INSERT ... ON CONFLICT ... DO UPDATE từ DbSpec."""
    cols = list(spec.columns)
    placeholders = ", ".join(["%s"] * len(cols))
    updates = ", ".join(f"{col} = EXCLUDED.{col}" for col in spec.update_columns)
    updates = f"{updates}, loaded_at = NOW()" if updates else "loaded_at = NOW()"
    return (
        f"INSERT INTO {spec.table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({spec.conflict_key}) DO UPDATE SET {updates}"
    )


# ─── LOADER ───────────────────────────────────────────────────────────────────

def load_processed(json_path: Path, spec: DbSpec) -> int:
    """Nạp processed JSON vào Postgres theo `spec`. Trả số row đã insert/update."""
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"Processed JSON not found: {json_path}")

    print(f"\n[db] Loading {json_path} → {spec.table}")
    df = load_processed_df(json_path)

    sql = build_insert_sql(spec)
    conn = _get_conn()
    cur = conn.cursor()

    inserted = 0
    for _, row in df.iterrows():
        try:
            cur.execute(sql, coerce_row(row, spec))
            inserted += 1
        except Exception as e:  # noqa: BLE001 — 1 row lỗi không chặn cả batch
            conn.rollback()
            print(f"  [WARN] Failed row: {e}")
            conn = _get_conn()
            cur = conn.cursor()

    conn.commit()
    cur.close()
    conn.close()

    print(f"  → Loaded {inserted}/{len(df)} rows into {spec.table}")
    return inserted


__all__ = ["DB_CONFIG", "build_insert_sql", "coerce_row", "load_processed"]
