#!/usr/bin/env python3
"""Load processed job data into PostgreSQL for Grafana dashboards.

Usage:
    python -m pipeline.db load itviec --csv data/itviec_v4/dashboard/processed_jobs.csv
    python -m pipeline.db load topcv --csv data/raw/topcv/processed_topcv.csv
    python -m pipeline.db load itviec --data-dir data/itviec_v4  (auto-finds processed_jobs.csv)
    python -m pipeline.db status
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

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


# ─── ITVIEC LOADER ────────────────────────────────────────────────────────────

def _to_json(val) -> str | None:
    """Convert a value to proper JSON string for PostgreSQL JSONB."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, list):
        return json.dumps(val)
    if isinstance(val, str):
        val = val.strip()
        if not val or val == "[]":
            return "[]"
        # CSV stores Python repr: ['Python', 'Java'] → convert to JSON: ["Python", "Java"]
        try:
            import ast
            parsed = ast.literal_eval(val)
            if isinstance(parsed, (list, dict)):
                return json.dumps(parsed, ensure_ascii=False)
        except (ValueError, SyntaxError):
            pass
        return val
    return json.dumps(val)

def load_itviec_csv(csv_path: Path) -> int:
    """Load processed iTViec CSV into PostgreSQL. Returns rows inserted."""
    print(f"\n[db] Loading iTViec data from {csv_path}")
    df = pd.read_csv(csv_path)

    # Convert list columns from string repr to proper JSON
    for col in ("tags", "skill_categories", "highlights"):
        if col in df.columns:
            df[col] = df[col].apply(_to_json)

    conn = _get_conn()
    cur = conn.cursor()

    inserted = 0
    for _, row in df.iterrows():
        try:
            cur.execute("""
                INSERT INTO itviec_jobs (
                    title, company, location, location_clean, salary,
                    working_type, job_function, seniority, label, label_clean,
                    posted_time, posted_hours_ago, url, tags, highlights,
                    skill_categories, num_tags, has_highlights, scraped_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    title = EXCLUDED.title,
                    company = EXCLUDED.company,
                    salary = EXCLUDED.salary,
                    seniority = EXCLUDED.seniority,
                    label = EXCLUDED.label,
                    tags = EXCLUDED.tags,
                    scraped_at = EXCLUDED.scraped_at,
                    loaded_at = NOW()
            """, (
                row.get("title"),
                row.get("company"),
                row.get("location"),
                row.get("location_clean"),
                row.get("salary"),
                row.get("working_type"),
                row.get("job_function"),
                row.get("seniority"),
                row.get("label"),
                row.get("label_clean"),
                row.get("posted_time"),
                row.get("posted_hours_ago"),
                row.get("url"),
                row.get("tags"),
                row.get("highlights"),
                row.get("skill_categories"),
                row.get("num_tags"),
                row.get("has_highlights"),
                row.get("scraped_at"),
            ))
            inserted += 1
        except Exception as e:
            conn.rollback()
            print(f"  [WARN] Failed row: {e}")
            conn = _get_conn()
            cur = conn.cursor()

    conn.commit()
    cur.close()
    conn.close()

    print(f"  → Loaded {inserted}/{len(df)} rows into itviec_jobs")
    return inserted


# ─── TOPCV LOADER ─────────────────────────────────────────────────────────────

def load_topcv_csv(csv_path: Path) -> int:
    """Load TopCV CSV into PostgreSQL. Returns rows inserted."""
    print(f"\n[db] Loading TopCV data from {csv_path}")
    df = pd.read_csv(csv_path)

    conn = _get_conn()
    cur = conn.cursor()

    inserted = 0
    for _, row in df.iterrows():
        try:
            cur.execute("""
                INSERT INTO topcv_jobs (
                    job_id, title, company, salary, location,
                    experience, level, skills, url, is_hot,
                    posted_date, scrape_date
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    salary = EXCLUDED.salary,
                    skills = EXCLUDED.skills,
                    scrape_date = EXCLUDED.scrape_date
            """, (
                str(row.get("job_id", "")),
                row.get("title"),
                row.get("company"),
                row.get("salary"),
                row.get("location"),
                row.get("experience"),
                row.get("level"),
                row.get("skills"),
                row.get("url"),
                bool(row.get("is_hot", False)),
                row.get("posted_date"),
                row.get("scrape_date"),
            ))
            inserted += 1
        except Exception as e:
            conn.rollback()
            print(f"  [WARN] Failed row: {e}")
            conn = _get_conn()
            cur = conn.cursor()

    conn.commit()
    cur.close()
    conn.close()

    print(f"  → Loaded {inserted}/{len(df)} rows into topcv_jobs")
    return inserted


# ─── ARXIV LOADER ─────────────────────────────────────────────────────────────

def load_arxiv_csv(csv_path: Path) -> int:
    """Load arXiv processed CSV vào PostgreSQL. Returns rows inserted.

    Upsert theo arxiv_id (idempotent — chạy lại không trùng).
    """
    print(f"\n[db] Loading arXiv data from {csv_path}")
    df = pd.read_csv(csv_path)
    # CSV rỗng -> pandas đọc thành NaN: chuẩn hóa về "" để DB không dính chuỗi 'NaN'
    df = df.where(pd.notna(df), "")

    conn = _get_conn()
    cur = conn.cursor()

    inserted = 0
    for _, row in df.iterrows():
        arxiv_id = str(row.get("arxiv_id", "")).strip()
        if not arxiv_id:
            continue
        try:
            cur.execute("""
                INSERT INTO arxiv_papers (
                    arxiv_id, title, authors, abstract, categories, primary_category,
                    published, updated, pdf_url, pdf_local, minio_key, pdf_location,
                    comment, journal_ref, doi, scrape_date, query
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (arxiv_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    authors = EXCLUDED.authors,
                    abstract = EXCLUDED.abstract,
                    categories = EXCLUDED.categories,
                    primary_category = EXCLUDED.primary_category,
                    published = EXCLUDED.published,
                    updated = EXCLUDED.updated,
                    pdf_url = EXCLUDED.pdf_url,
                    pdf_local = EXCLUDED.pdf_local,
                    minio_key = EXCLUDED.minio_key,
                    pdf_location = EXCLUDED.pdf_location,
                    comment = EXCLUDED.comment,
                    journal_ref = EXCLUDED.journal_ref,
                    doi = EXCLUDED.doi,
                    scrape_date = EXCLUDED.scrape_date,
                    query = EXCLUDED.query,
                    loaded_at = NOW()
            """, (
                arxiv_id,
                row.get("title"),
                row.get("authors"),
                row.get("abstract"),
                row.get("categories"),
                row.get("primary_category"),
                row.get("published") or None,
                row.get("updated") or None,
                row.get("pdf_url"),
                row.get("pdf_local"),
                row.get("minio_key"),
                row.get("pdf_location"),
                row.get("comment"),
                row.get("journal_ref"),
                row.get("doi"),
                row.get("scrape_date"),
                row.get("query"),
            ))
            inserted += 1
        except Exception as e:
            conn.rollback()
            print(f"  [WARN] Failed row {arxiv_id}: {e}")
            conn = _get_conn()
            cur = conn.cursor()

    conn.commit()
    cur.close()
    conn.close()

    print(f"  → Loaded {inserted}/{len(df)} rows into arxiv_papers")
    return inserted


# ─── STATUS ───────────────────────────────────────────────────────────────────

def status():
    """Print database status."""
    conn = _get_conn()
    cur = conn.cursor()

    print("\n=== Database Status ===")

    try:
        cur.execute("SELECT COUNT(*) FROM itviec_jobs")
        itviec_count = cur.fetchone()[0]
        print(f"  iTViec jobs:  {itviec_count:>6}")

        cur.execute("SELECT COUNT(*) FROM topcv_jobs")
        topcv_count = cur.fetchone()[0]
        print(f"  TopCV jobs:   {topcv_count:>6}")
        try:
            cur.execute("SELECT COUNT(*) FROM arxiv_papers")
            print(f"  arXiv papers: {cur.fetchone()[0]:>6}")
        except Exception:
            conn.rollback()

        cur.execute("SELECT COUNT(DISTINCT company) FROM itviec_jobs")
        companies = cur.fetchone()[0]
        print(f"  Companies:    {companies:>6}")

        cur.execute("SELECT MAX(scraped_at) FROM itviec_jobs")
        last_scrape = cur.fetchone()[0]
        print(f"  Last scrape:  {last_scrape}")

        cur.execute("SELECT location_clean, COUNT(*) as cnt FROM itviec_jobs GROUP BY location_clean ORDER BY cnt DESC LIMIT 5")
        print("\n  Top locations:")
        for loc, cnt in cur.fetchall():
            print(f"    {loc or 'Unknown':20s} {cnt:>5}")

    except Exception as e:
        print(f"  [ERROR] {e}")

    cur.close()
    conn.close()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(prog="pipeline.db", description="Load job data into PostgreSQL")
    sub = parser.add_subparsers(dest="command", required=True)

    # load
    p_load = sub.add_parser("load", help="Load CSV into database")
    p_load.add_argument("source", choices=["itviec", "topcv", "arxiv"], help="Data source")
    p_load.add_argument("--csv", type=Path, help="Path to CSV file")
    p_load.add_argument("--data-dir", type=Path, help="Data directory (auto-finds CSV)")

    # status
    sub.add_parser("status", help="Show database status")

    args = parser.parse_args()

    if args.command == "status":
        status()
    elif args.command == "load":
        csv_path = args.csv
        if not csv_path and args.data_dir:
            if args.source == "itviec":
                csv_path = args.data_dir / "processed_jobs.csv"
            else:
                csv_path = args.data_dir / "processed_topcv.csv"
        if not csv_path or not csv_path.exists():
            print(f"[ERROR] CSV not found. Provide --csv or --data-dir")
            sys.exit(1)

        if args.source == "itviec":
            load_itviec_csv(csv_path)
        elif args.source == "arxiv":
            load_arxiv_csv(csv_path)
        else:
            load_topcv_csv(csv_path)


if __name__ == "__main__":
    main()
