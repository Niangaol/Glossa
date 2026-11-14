"""LaTeX → sympy 的容错转换。失败必须保留 raw，不许丢公式。"""

from __future__ import annotations


def latex_to_sympy_safe(latex: str) -> dict:
    raise NotImplementedError("parse_paper.latex_safe.latex_to_sympy_safe 尚未实现")
