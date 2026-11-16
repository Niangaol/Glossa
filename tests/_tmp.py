"""沙箱友好的临时目录。

本机的 DSH 文件沙箱拒绝对工作区子目录做递归删除（WinError 5），
pytest 的 tmp_path / --basetemp 都会在清理阶段炸。所以测试自己建目录、
自己收尾，不依赖 pytest 的清理。

R405（T7 报告 C6）：目录名曾经用进程内计数器，xdist 的多个 worker 各自从 1 开始
编号，-1 直接撞车 —— 同一目录被两个测试 copytree 就出假红。改成 uuid4 前缀，
跨进程唯一，不再依赖进程内状态。
"""

from __future__ import annotations

import pathlib
import shutil
import uuid


_ROOT = pathlib.Path(__file__).resolve().parents[1] / "output" / "test-tmp"


def scratch_dir(name: str) -> pathlib.Path:
    path = _ROOT / f"{name}-{uuid.uuid4().hex[:8]}"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path
