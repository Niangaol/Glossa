"""仓库 ingest：定位本地路径或 clone，记录 commit，做 PyTorch 判定。"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple


class RepoMeta(NamedTuple):
    url: str
    commit: str
    language: str
    entry_module: str | None


def ingest_repo(src: str | Path, dest: Path) -> RepoMeta:
    raise NotImplementedError("ingest.repo.ingest_repo 尚未实现（M0 之后的切片）")


def find_pytorch_modules(root: Path) -> list[Path]:
    raise NotImplementedError("ingest.repo.find_pytorch_modules 尚未实现")
