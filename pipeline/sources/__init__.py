"""Registry: ánh xạ tên source -> adapter. Thêm nguồn mới chỉ sửa file này."""

from __future__ import annotations

from pipeline.sources.arxiv import ArxivSource
from pipeline.sources.itviec import ItviecSource
from pipeline.sources.topcv import TopcvSource

REGISTRY: dict = {
    "arxiv": ArxivSource(),
    "itviec": ItviecSource(),
    "topcv": TopcvSource(),
}

ALL_SOURCES: list[str] = sorted(REGISTRY)


def get_source(name: str):
    try:
        return REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown source {name!r}. Choose from: {ALL_SOURCES}"
        ) from None
