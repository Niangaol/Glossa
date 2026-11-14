"""沙箱友好的临时目录。

本机的 DSH 文件沙箱拒绝对工作区子目录做递归删除（WinError 5），
pytest 的 tmp_path / --basetemp 都会在清理阶段炸。所以测试自己建目录、
自己收尾，不依赖 pytest 的清理。
"""

from __future__ import annotations

import itertools
import pathlib
import shutil

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "output" / "test-tmp"
_counter = itertools.count(1)


def scratch_dir(name: str) -> pathlib.Path:
    path = _ROOT / f"{name}-{next(_counter)}"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path
