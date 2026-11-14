"""把一条公式拆成项：matmul / 缩放 / 归一化 / 激活 / 转置 / concat 各算一项。"""

from __future__ import annotations


def split_formula(latex: str) -> list[object]:
    raise NotImplementedError("parse_paper.split_terms.split_formula 尚未实现")
