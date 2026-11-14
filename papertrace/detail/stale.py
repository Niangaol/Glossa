"""stale 传播：子结论推翻父结论时，父节点标 stale 并记 conflicts，禁止静默覆盖。"""

from __future__ import annotations


def mark_stale(trace, parent_id: str, child_id: str) -> dict:
    raise NotImplementedError("detail.stale.mark_stale 尚未实现")
