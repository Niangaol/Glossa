"""切出论文单元并分配稳定 ID，例如 §3.2-eq-attn。"""

from __future__ import annotations


def build_units(tex: str) -> list[object]:
    raise NotImplementedError("parse_paper.units.build_units 尚未实现")
