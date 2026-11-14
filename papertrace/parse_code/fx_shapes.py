"""形状树的原语：真实执行里看到的值 ↔ 可序列化的形状。

叶子 `{"t": dims}`、容器 `{"l": [...]}` / `{"d": {...}}`、非张量 `None`。
把「张量」与「容器」分开记录，才分得清 `cat([a, b])` 的两个入参，
也才分得清「0 维标量」`{"t": []}` 与「没有张量」None。
"""

from __future__ import annotations

from typing import Any


def val_shape(value: Any) -> list[int] | None:
    """张量形状。0 维张量是 []（标量），不是「未知」；未知返回 None。"""
    shape = getattr(value, "shape", None)
    if shape is None:
        return None
    return [int(d) for d in shape]


def shape_tree(value: Any) -> Any:
    """把一次真实执行里看到的参数/输出压成形状树，不留张量本身（省内存）。"""
    shape = val_shape(value)
    if shape is not None:
        return {"t": shape}
    if isinstance(value, dict):
        return {"d": {str(k): shape_tree(v) for k, v in value.items()}}
    if isinstance(value, (list, tuple)):
        return {"l": [shape_tree(item) for item in value]}
    return None


def tree_leaf(tree: Any) -> list[int] | None:
    """树里**整个**值是张量时给形状；容器或非张量给 None。"""
    if isinstance(tree, dict) and "t" in tree:
        return list(tree["t"])
    return None


def tree_shapes(tree: Any) -> list[list[int]]:
    """树里所有张量叶子的形状，按出现顺序。"""
    if isinstance(tree, dict):
        if "t" in tree:
            return [list(tree["t"])]
        leaves: list[list[int]] = []
        if "l" in tree:
            for item in tree["l"]:
                leaves.extend(tree_shapes(item))
        elif "d" in tree:
            for item in tree["d"].values():
                leaves.extend(tree_shapes(item))
        return leaves
    return []


def navigate(tree: Any, path: list[Any]) -> Any:
    """按 iter_arg_nodes 给出的路径（如 ["args", 0]）在形状树里取值；走不通返回 None。"""
    cur = tree
    for step in path:
        if cur is None:
            return None
        if isinstance(step, int) and "l" in cur:
            items = cur["l"]
            if step >= len(items) or step < -len(items):
                return None
            cur = items[step]
        elif "d" in cur:
            cur = cur["d"].get(str(step))
        else:
            return None
    return cur
