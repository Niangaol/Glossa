"""fx 失败时的降级路径：语法级扫描。所有节点必须标 degraded=True。"""

from __future__ import annotations

from pathlib import Path


def fallback_ast(path: Path, fn_name: str) -> object:
    raise NotImplementedError("parse_code.treesitter_fallback.fallback_ast 尚未实现")
