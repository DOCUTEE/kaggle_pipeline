#!/usr/bin/env python3
"""Unified CLI — 1 entrypoint duy nhất cho toàn bộ pipeline.

Usage:
    python -m pipeline check-kaggle          # preflight Kaggle trước khi push
    python -m pipeline run itviec                  # full 6 bước, push Kaggle
    python -m pipeline run topcv --max-pages 5     # test nhanh 5 pages
    python -m pipeline run all --no-kaggle         # chạy cả 2, skip Kaggle
    python -m pipeline run itviec --load-db        # kèm nạp Postgres
    python -m pipeline run itviec --data-dir /mnt/kaggle_data/itviec

Tương thích ngược (vẫn chạy được):
    python -m pipeline.build ...      # build/process/dashboard cũ
    python -m pipeline.db ...         # load-db cũ
    python -m itviec ...              # scraper itviec cũ
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pipeline.runner import RunOptions, print_summary, run_many
from pipeline.sources import ALL_SOURCES

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=_LOG_FORMAT,
        stream=sys.stderr,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pipeline",
        description="Unified Vietnam IT jobs pipeline (itviec + topcv)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="Run full 6-step pipeline for a source")
    r.add_argument(
        "source", choices=[*ALL_SOURCES, "all"],
        help="Data source (or 'all' = chạy tuần tự itviec → topcv)",
    )
    r.add_argument("--data-dir", type=Path, default=None,
                   help="Override raw data dir (vd /mnt/kaggle_data/itviec)")
    r.add_argument("--dashboard-dir", type=Path, default=None,
                   help="Override dashboard output dir")
    r.add_argument("--max-pages", type=int, default=None,
                   help="Giới hạn số pages (test nhanh). Default theo source.")
    r.add_argument("--workers", type=int, default=None,
                   help="Số workers scrape. Default theo source.")
    r.add_argument("--timeout", type=int, default=30, help="HTTP timeout (s)")
    r.add_argument("--load-db", action="store_true",
                   help="Nạp processed CSV vào PostgreSQL")
    r.add_argument("--no-kaggle", dest="push_kaggle", action="store_false",
                   help="Bỏ qua bước push Kaggle")
    r.add_argument("--kaggle-dataset", type=str, default=None,
                   help="Override id Kaggle 'user/dataset'")
    r.add_argument("--keep-days", type=int, default=30,
                   help="Giữ snapshot N ngày gần nhất (0 = không cleanup)")
    r.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    r.set_defaults(push_kaggle=True)

    sub.add_parser("sources", help="Liệt kê các source đã đăng ký").set_defaults(command="sources")

    c = sub.add_parser("check-kaggle", help="Preflight: kiểm tra CLI + creds + owner trước khi push")
    c.add_argument(
        "source", nargs="?", default="all", choices=[*ALL_SOURCES, "all"],
        help="Source cần check (default: all)",
    )
    c.add_argument("--kaggle-dataset", type=str, default=None,
                   help="Chỉ check 1 dataset id 'user/dataset' cụ thể")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "sources":
        print("Registered sources:", ", ".join(ALL_SOURCES))
        return 0

    if args.command == "check-kaggle":
        from pipeline import settings
        from pipeline.kaggle_check import check_kaggle, print_report

        if args.kaggle_dataset:
            ids = [args.kaggle_dataset]
        else:
            targets = ALL_SOURCES if args.source == "all" else [args.source]
            ids = [settings.get_source(t).kaggle_dataset for t in targets]
        rep = check_kaggle(ids)
        print_report(rep)
        return 0 if rep.ok else 1

    # command == "run"
    _setup_logging(args.verbose)

    targets = ALL_SOURCES if args.source == "all" else [args.source]
    opts = RunOptions(
        data_dir=args.data_dir,
        dashboard_dir=args.dashboard_dir,
        max_pages=args.max_pages,
        workers=args.workers,
        timeout=args.timeout,
        load_db=args.load_db,
        push_kaggle=args.push_kaggle,
        kaggle_dataset=args.kaggle_dataset,
        keep_days=args.keep_days,
        verbose=args.verbose,
    )

    results = run_many(targets, opts)
    print_summary(results)
    return 1 if any(r.error for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
