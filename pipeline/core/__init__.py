"""Core dùng chung cho mọi source — source-agnostic.

Mọi pipeline con (itviec, topcv, ...) đều dùng đúng các building block này:
    contracts  — kiểu dữ liệu trao đổi với runner
    snapshot   — ghi raw snapshot (atomic, dedup, latest)
    transform  — schema chuẩn + derived features
    dashboard  — 1 HTML shell + chart primitives
    publish    — staging + Kaggle push
"""

from pipeline.core.contracts import (
    PROCESSED_JSON,
    DbSpec,
    ProcessResult,
    ScrapeResult,
)

__all__ = ["PROCESSED_JSON", "DbSpec", "ProcessResult", "ScrapeResult"]
