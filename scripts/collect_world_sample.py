#!/usr/bin/env python3
"""Thu mẫu metadata đa ngành để vẽ dashboard "tình hình khoa học thế giới".

Mỗi category lấy N papers mới nhất (metadata-only, không tải PDF nên rất nhanh),
gộp thành 1 dataset chung đúng format của ArxivSource
(data/raw/arxiv/arxiv_latest.json/.csv) để process_arxiv/dashboard dùng được ngay.

Usage:
    python scripts/collect_world_sample.py                      # 8 ngành x 60 = ~480 papers
    python scripts/collect_world_sample.py --per-cat 30         # mẫu nhỏ test nhanh
    python scripts/collect_world_sample.py --data-dir data/raw/arxiv

Env (optional, ghi đè default):
    ARXIV_SORT_BY / ARXIV_SORT_ORDER (default submittedDate/descending)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# 8 ngành phủ rộng khoa học thế giới: AI/ML/NLP/Vision + Quantum + Astro + Stats + Neuro
CATEGORIES = [
    "cs.AI",      # Artificial Intelligence
    "cs.LG",      # Machine Learning
    "cs.CL",      # Computation & Language (NLP)
    "cs.CV",      # Computer Vision
    "quant-ph",   # Quantum Physics
    "astro-ph",   # Astrophysics
    "stat.ML",    # Statistics / ML
    "q-bio.NC",   # Neurons & Cognition
]

CSV_COLUMNS = [
    "arxiv_id", "title", "authors", "abstract", "categories",
    "primary_category", "published", "updated", "pdf_url", "pdf_local",
    "minio_key", "pdf_location", "comment", "journal_ref", "doi",
    "scrape_date", "query",
]


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.sources.arxiv import _fetch_batch

    ap = argparse.ArgumentParser(description="Collect multi-category arXiv sample")
    ap.add_argument("--per-cat", type=int, default=60, help="Papers mỗi category (default 60)")
    ap.add_argument("--data-dir", type=Path, default=Path("data/raw/arxiv"))
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    sort_by = os.getenv("ARXIV_SORT_BY", "submittedDate")
    sort_order = os.getenv("ARXIV_SORT_ORDER", "descending")
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    scrape_date = datetime.now().strftime("%Y-%m-%d")

    all_entries: list[dict] = []
    for i, cat in enumerate(CATEGORIES):
        if i > 0:
            time.sleep(3.0)  # politeness delay theo policy arXiv
        query = f"cat:{cat}"
        try:
            batch = _fetch_batch(query, 0, args.per_cat, sort_by, sort_order, args.timeout)
        except Exception as exc:
            print(f"[WARN] {cat}: fetch failed: {exc}", flush=True)
            continue
        print(f"[{cat}] fetched {len(batch)}", flush=True)
        for p in batch:
            all_entries.append({
                "arxiv_id": p.get("arxiv_id", ""),
                "title": p.get("title", ""),
                "authors": "; ".join(p.get("authors", [])),
                "abstract": p.get("abstract", ""),
                "categories": ";".join(p.get("categories", [])),
                "primary_category": p.get("primary_category", ""),
                "published": p.get("published", ""),
                "updated": p.get("updated", ""),
                "pdf_url": p.get("pdf_url", ""),
                "pdf_local": "",
                "minio_key": "",
                "pdf_location": "",
                "comment": p.get("comment", ""),
                "journal_ref": p.get("journal_ref", ""),
                "doi": p.get("doi", ""),
                "scrape_date": scrape_date,
                "query": query,
            })

    # Dedup theo arxiv_id (paper cross-list nhiều category chỉ giữ 1)
    seen, rows = set(), []
    for r in all_entries:
        if r["arxiv_id"] and r["arxiv_id"] not in seen:
            seen.add(r["arxiv_id"])
            rows.append(r)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {"scrape_date": scrape_date, "count": len(rows),
               "categories": CATEGORIES, "papers": [
                   {**{k: r[k] for k in ("arxiv_id", "title")}, **r} for r in rows]}

    for name in (f"arxiv_world_{ts}.json", "arxiv_latest.json"):
        p = data_dir / name
        fd, tmp = tempfile.mkstemp(dir=str(data_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    try:
        import pandas as pd
        df = pd.DataFrame(rows, columns=CSV_COLUMNS)
        df.to_csv(data_dir / f"arxiv_world_{ts}.csv", index=False)
        df.to_csv(data_dir / "arxiv_latest.csv", index=False)
    except Exception as exc:
        print(f"[WARN] CSV write failed: {exc}")
        return 1

    print(f"DONE: {len(rows)} papers (raw {len(all_entries)}, dedup {len(all_entries) - len(rows)}) "
          f"-> {data_dir}/arxiv_latest.json/.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
