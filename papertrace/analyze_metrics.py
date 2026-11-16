"""代码体检指标：参数量 / 峰值激活 / 粗估 FLOPs（Task C3，无论文模式）。

口径写死在这里，后来人要改口径，先改这段 docstring 再改测试（GC19：估算必须
自称估算，禁止「精确计算量」「实测 FLOPs」这类说法）：
- params：子树内 kind == "param" 节点 shape_out 乘积求和。**精确**，不估。
- max_activation：子树内 kind == "op" 节点 shape_out 乘积最大值，**数的是元素
  个数不是字节**，param 节点绝不参与（R203：权重不是激活）。
- est_flops：子树内 op in ("matmul", "linear") 的 2 * prod(shape_out) *
  shape_in[-1] 求和；其余算子计 0。**粗估**（trace 没记收缩维度，也没算逐元素
  算子与 norm，且随 batch / 序列长度线性变化）。
- degraded：子树内 degraded 为真的节点数；degraded_reasons 取它们的
  degraded_reason（去重、升序、跳过空串）。
- 子树 = 自身 + 所有后代（parent_id 层级树；root 的 parent_id 是 None）。
- R200：shape 为空或字段缺失一律计 0，绝不抛异常、绝不猜维度。
- R204：totals 的三个数字直接取 root 那一行（同一份子树口径），不另算一遍。
- 不许 import torch：这里只读 trace 字段。
"""

# 只对这两个算子粗估 FLOPs，其余算子一律计 0
FLOP_OPS = ("matmul", "linear")


def module_metrics(nodes: list[dict]) -> list[dict]:
    """按 module_id 升序，每条恰好 4 个键（缺数据时是 0，不是 None）。"""
    children = _children_by_parent(nodes)
    modules = [n for n in nodes if n.get("level") != "op"]
    out = []
    for mod in sorted(modules, key=lambda m: m.get("id", "")):
        sub = _subtree(mod, children)
        out.append(
            {
                "module_id": mod.get("id", ""),
                "params": _params(sub),
                "max_activation": _max_activation(sub),
                "est_flops": _est_flops(sub),
            }
        )
    return out


def analysis_totals(rows: list[dict], nodes: list[dict]) -> dict:
    """总量汇总：modules / params / max_activation / est_flops / degraded / degraded_reasons。

    R204：params / max_activation / est_flops 直接取 root 那一行，不许另算一遍——
    两条路算出来的数一旦漂移，报告里就会出现两个真相。
    """
    root = _root_node(nodes)
    sub = _subtree(root, _children_by_parent(nodes)) if root is not None else []
    row = _root_row(rows, root)
    return {
        "modules": len(rows),
        "params": row.get("params", 0) if row else 0,
        "max_activation": row.get("max_activation", 0) if row else 0,
        "est_flops": row.get("est_flops", 0) if row else 0,
        "degraded": _degraded_count(sub),
        "degraded_reasons": _degraded_reasons(sub),
    }


def _children_by_parent(nodes: list[dict]) -> dict:
    """parent_id → 直接子节点列表（一遍扫描，别对每个模块再扫全表）。"""
    table: dict = {}
    for node in nodes:
        table.setdefault(node.get("parent_id"), []).append(node)
    return table


def _root_node(nodes: list[dict]) -> dict | None:
    """root = parent_id 为 None 的节点；一个都没有就返回 None（R200：不抛）。"""
    for node in nodes:
        if node.get("parent_id") is None:
            return node
    return None


def _root_row(rows: list[dict], root: dict | None) -> dict | None:
    """root 对应的那一行；没有就算了，让调用方落到 0（R200：不抛）。"""
    if root is None:
        return None
    return next((r for r in rows if r.get("module_id") == root.get("id")), None)


def _subtree(root: dict, children: dict) -> list[dict]:
    """自身 + 所有后代（迭代展开，深树不爆递归栈）。"""
    out: list[dict] = []
    stack: list[dict] = [root]
    while stack:
        node = stack.pop()
        out.append(node)
        nid = node.get("id")
        if nid is not None:
            stack.extend(children.get(nid, []))
    return out


def _prod(shape) -> int:
    """形状求积；空列表或字段缺失 → 0（R200：不猜维度）。"""
    if not shape:
        return 0
    out = 1
    for dim in shape:
        out *= dim
    return out


def _params(sub: list[dict]) -> int:
    """子树内权重张量的元素数总和（精确）。"""
    return sum(_prod(n.get("shape_out")) for n in sub if n.get("kind") == "param")


def _max_activation(sub: list[dict]) -> int:
    """子树内算子输出的最大元素数（R203：param 节点绝不参与）。"""
    products = [_prod(n.get("shape_out")) for n in sub if n.get("kind") == "op"]
    return max(products) if products else 0


def _est_flops(sub: list[dict]) -> int:
    """粗估 FLOPs：只算 matmul / linear 的 2 * prod(shape_out) * shape_in[-1]。"""
    total = 0
    for node in sub:
        if node.get("op") not in FLOP_OPS:
            continue
        shape_in = node.get("shape_in") or []
        out = _prod(node.get("shape_out"))
        if not shape_in or not out:
            continue  # R200：没形状就不猜，计 0
        total += 2 * out * shape_in[-1]
    return total


def _degraded_count(sub: list[dict]) -> int:
    return sum(1 for n in sub if n.get("degraded"))


def _degraded_reasons(sub: list[dict]) -> list[str]:
    """降级原因：去重、升序、跳过空串（空串不是原因）。"""
    reasons = {
        n.get("degraded_reason")
        for n in sub
        if n.get("degraded") and (n.get("degraded_reason") or "").strip()
    }
    return sorted(reasons)
