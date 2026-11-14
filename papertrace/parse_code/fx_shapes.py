"""形状树的原语：真实执行里看到的值 ↔ 可序列化的形状。

叶子 `{"t": dims}`、容器 `{"l": [...]}` / `{"d": {...}}`、非张量 `None`。
把「张量」与「容器」分开记录，才分得清 `cat([a, b])` 的两个入参，
也才分得清「0 维标量」`{"t": []}` 与「没有张量」None。
"""

from __future__ import annotations

from typing import Any

from papertrace.exceptions import BuildError


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

def check_value_shape(node: Any, value: Any, target: Any) -> None:
    """spec 的 target 取到的张量，形状必须与导出图自己记的一致。

    这是**另一个**地面真相：`node.meta["val"]` 来自导出器在图上做的 fake 传播，与
    `input_specs` 的 target 映射是两个独立字段。互换两个**不同形状**参数的 target 时，
    名字/顺序/认领/四张表可以完全不变（第十三轮 I-1 实测放行，权重形状被记反、
    shape_broken 仍是 0），只有这道核对看得见。

    诚实的边界：同形状互换不可观测，本来也不会产生可见错误，所以不假装抓得住。
    非张量（int/bool/None/ScriptObject）与动态形状（SymInt）不比——不猜。
    """
    want = getattr(getattr(node, "meta", {}).get("val"), "shape", None)
    got = getattr(value, "shape", None)
    if want is None or got is None:
        return
    want, got = tuple(want), tuple(got)
    if any(not isinstance(d, int) for d in want + got):
        return
    if want != got:
        raise BuildError(
            f"input_specs 把 {node.name} 指到 target={target}，取到的张量是 {got}，"
            f"但导出图里这个节点是 {want}；spec 的 target 被改过"
            "（权重形状会被记反），按约定拒绝出图"
        )
