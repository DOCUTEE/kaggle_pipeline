#!/usr/bin/env python3
"""Cào tổng lực arXiv cho phân tích: metadata đa ngành + PDF -> MinIO + dashboard + DB.

Idempotent / resume được: paper đã có PDF local thì skip tải; metadata lưu
checkpoint sau mỗi phase nên rớt giữa chừng chạy lại vẫn tiếp tục được.

Usage (trên server, trong tmux):
    .venv/bin/python scripts/collect_max.py
    PER_CAT=400 CATS="cs.AI,cs.CL,quant-ph" .venv/bin/python scripts/collect_max.py --no-pdf
    .venv/bin/python scripts/collect_max.py --data-dir data/raw/arxiv --no-db

Env:
    CATS          — danh sách category, phân cách phẩy (default 16 ngành bên dưới)
    PER_CAT       — papers mỗi category (default 250)
    DOWNLOAD_PDF  — "1"/"0" (default "1", --no-pdf để tắt)
    ARXIV_SORT_BY / ARXIV_SORT_ORDER, MINIO_*, DB_* (như pipeline arxiv thường)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

DEFAULT_CATS = [
    "cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.RO", "cs.CR", "cs.SE", "cs.DB",
    "quant-ph", "hep-ph", "astro-ph", "stat.ML", "q-bio.NC", "math.CO",
    "eess.SP", "econ.EM",
]

CSV_COLUMNS = [
    "arxiv_id", "title", "authors", "abstract", "categories",
    "primary_category", "published", "updated", "pdf_url", "pdf_local",
    "minio_key", "pdf_location", "comment", "journal_ref", "doi",
    "scrape_date", "query",
]

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("collect_max")


def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.sources.arxiv import _fetch_batch, _safe_id, _download_pdf

    ap = argparse.ArgumentParser(description="Max arXiv collection for analysis")
    ap.add_argument("--data-dir", type=Path, default=Path("data/raw/arxiv"))
    ap.add_argument("--per-cat", type=int, default=int(os.getenv("PER_CAT", "250")))
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--no-pdf", action="store_true",
                    help="Chỉ lấy metadata, bỏ tải PDF")
    ap.add_argument("--no-db", action="store_true", help="Bỏ nạp Postgres")
    ap.add_argument("--no-dashboard", action="store_true", help="Bỏ build dashboard")
    args = ap.parse_args()

    cats = [c.strip() for c in os.getenv("CATS", ",".join(DEFAULT_CATS)).split(",") if c.strip()]
    download_pdf = os.getenv("DOWNLOAD_PDF", "1") == "1" and not args.no_pdf
    sort_by = os.getenv("ARXIV_SORT_BY", "submittedDate")
    sort_order = os.getenv("ARXIV_SORT_ORDER", "descending")
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    scrape_date = datetime.now().strftime("%Y-%m-%d")
    t0 = time.time()
    log.info("START cats=%d per_cat=%d pdf=%s dir=%s", len(cats), args.per_cat, download_pdf, data_dir)

    # ── Phase 1: metadata ──
    rows: list[dict] = []
    for i, cat in enumerate(cats):
        if i > 0:
            time.sleep(3.0)  # politeness delay
        query = f"cat:{cat}"
        for attempt in range(3):
            try:
                if attempt:
                    time.sleep(5)
                batch = _fetch_batch(query, 0, args.per_cat, sort_by, sort_order, args.timeout)
                break
            except Exception as exc:
                log.warning("[%s] attempt %d failed: %s", cat, attempt + 1, exc)
                batch = []
        log.info("[%s] fetched %d", cat, len(batch))
        for p in batch:
            rows.append({
                "arxiv_id": p.get("arxiv_id", ""), "title": p.get("title", ""),
                "authors": "; ".join(p.get("authors", [])), "abstract": p.get("abstract", ""),
                "categories": ";".join(p.get("categories", [])),
                "primary_category": p.get("primary_category", ""),
                "published": p.get("published", ""), "updated": p.get("updated", ""),
                "pdf_url": p.get("pdf_url", ""), "pdf_local": "", "minio_key": "",
                "pdf_location": "", "comment": p.get("comment", ""),
                "journal_ref": p.get("journal_ref", ""), "doi": p.get("doi", ""),
                "scrape_date": scrape_date, "query": query,
            })

    seen, uniq = set(), []
    for r in rows:
        if r["arxiv_id"] and r["arxiv_id"] not in seen:
            seen.add(r["arxiv_id"])
            uniq.append(r)
    rows = uniq
    log.info("Phase 1 done: %d unique papers in %.1f min", len(rows), (time.time() - t0) / 60)
    _save(data_dir, rows, scrape_date, cats, tag="meta")

    # ── Phase 2: PDFs -> MinIO (skip file đã có = resume) ──
    n_pdf = n_minio = 0
    if download_pdf:
        from pipeline import minio_store
        pdf_dir = data_dir / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        for j, r in enumerate(rows):
            aid = r["arxiv_id"]
            safe = _safe_id(aid)
            local = pdf_dir / f"{safe}.pdf"
            if local.exists() and local.stat().st_size > 0:
                r["pdf_local"] = str(local.resolve())
                if not r.get("pdf_location"):
                    ok, loc = minio_store.upload_file(local, f"arxiv/{safe}.pdf")
                    r["minio_key"] = f"arxiv/{safe}.pdf" if ok else ""
                    r["pdf_location"] = loc
                    n_minio += ok
                else:
                    n_minio += r["pdf_location"].startswith("s3://")
                n_pdf += 1
            elif r.get("pdf_url"):
                time.sleep(1.0)
                if _download_pdf(r["pdf_url"], local, args.timeout):
                    n_pdf += 1
                    ok, loc = minio_store.upload_file(local, f"arxiv/{safe}.pdf")
                    r["pdf_local"] = str(local.resolve())
                    r["minio_key"] = f"arxiv/{safe}.pdf" if ok else ""
                    r["pdf_location"] = loc
                    n_minio += ok
            if (j + 1) % 100 == 0:
                log.info("PDF progress %d/%d (pdf=%d minio=%d, %.1f min)",
                         j + 1, len(rows), n_pdf, n_minio, (time.time() - t0) / 60)
                _save(data_dir, rows, scrape_date, cats, tag="ckpt")
        log.info("Phase 2 done: pdf=%d minio=%d in %.1f min",
                 n_pdf, n_minio, (time.time() - t0) / 60)
        _save(data_dir, rows, scrape_date, cats, tag="full")

    # ── Phase 3: process + dashboard + DB ──
    if not args.no_dashboard:
        from pipeline import build as build_mod
        dash_dir = data_dir / "dashboard"
        dash_dir.mkdir(parents=True, exist_ok=True)
        try:
            build_mod.process_arxiv(data_dir, dash_dir)
            build_mod.build_arxiv_dashboard(data_dir, dash_dir)
        except Exception as exc:
            log.warning("dashboard failed: %s", exc)
    if not args.no_db:
        try:
            from pipeline import db as db_mod
            csv_path = data_dir / "dashboard" / "processed_arxiv.csv"
            if csv_path.exists():
                db_mod.load_arxiv_csv(csv_path)
        except Exception as exc:
            log.warning("load_db failed (DB chưa chạy?): %s", exc)

    log.info("DONE: %d papers, pdf=%d, minio=%d, total %.1f min",
             len(rows), n_pdf, n_minio, (time.time() - t0) / 60)
    return 0


def _save(data_dir: Path, rows: list[dict], scrape_date: str, cats: list[str], tag: str) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {"scrape_date": scrape_date, "count": len(rows),
               "categories": cats, "papers": rows}
    _atomic_write_json(data_dir / f"arxiv_{tag}_{ts}.json", payload)
    _atomic_write_json(data_dir / "arxiv_latest.json", payload)
    try:
        import pandas as pd
        df = pd.DataFrame(rows, columns=CSV_COLUMNS)
        df.to_csv(data_dir / f"arxiv_{tag}_{ts}.csv", index=False)
        df.to_csv(data_dir / "arxiv_latest.csv", index=False)
    except Exception as exc:
        log.warning("CSV write failed: %s", exc)


if __name__ == "__main__":
    raise SystemExit(main())
