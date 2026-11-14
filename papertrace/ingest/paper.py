"""论文 ingest：本地 tex → arXiv 源码 → PDF 兜底。v1 不做 Nougat。"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple


class PaperBundle(NamedTuple):
    source: str
    ingest_mode: str
    unit_count: int
    title: str | None


def ingest_paper(src: str | Path) -> PaperBundle:
    raise NotImplementedError("ingest.paper.ingest_paper 尚未实现")
