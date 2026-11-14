"""arXiv 源码下载。拿到 .tar.gz 里的真 LaTeX，比解析 PDF 稳一个数量级。"""

from __future__ import annotations

from pathlib import Path


def fetch_arxiv_source(arxiv_id: str, dest: Path) -> Path:
    raise NotImplementedError("ingest.arxiv.fetch_arxiv_source 尚未实现")
