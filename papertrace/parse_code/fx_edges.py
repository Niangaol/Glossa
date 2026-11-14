"""边：逐参数位置连边，并只对能独立核实的地方判 shape_consistent。"""

from __future__ import annotations

from typing import Any

from papertrace.parse_code.fx_graph import FUSED_OPS, op_name

def iter_arg_nodes(node, by_name: dict[str, str]) -> list[tuple[str, Any]]:
    """递归展开 args/kwargs 里的节点引用，`cat([a, b])` 也不会丢边。"""
    found: list[tuple[str, Any]] = []

    def walk(label: str, value: Any) -> None:
        if getattr(value, "name", None) in by_name:
            found.append((label, value))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                walk(f"{label}[{i}]", item)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(f"{label}[{key!r}]", item)

    for position, arg in enumerate(node.args):
        walk(f"args[{position}]", arg)
    for key, arg in node.kwargs.items():
        walk(f"kwargs[{key}]", arg)
    return found


def is_getitem(node) -> bool:
    """torch.export 里 getitem 的 node.op 就是 "getitem"；兼容只有 target 的假节点。"""
    return getattr(node, "op", None) == "getitem" or op_name(node) == "getitem"


def resolve_arg_shape(consumer, producer_shapes: list[list[int]]) -> list[int] | None:
    """多输出生产者 + getitem 消费者：按索引取到**这一项**的形状。

    `split_with_sizes(x, [2, 3])` 的两项分别是 (2,2) 和 (2,3)；一律取第 1 项会让
    第二条边把 (2,3) 记成 (2,2)，形状链在自家输出里就断了。
    """
    if len(producer_shapes) <= 1 or not is_getitem(consumer) or len(consumer.args) < 2:
        return None
    index = consumer.args[1]
    if not isinstance(index, int):
        return None
    if index < 0:
        index += len(producer_shapes)
    return producer_shapes[index] if 0 <= index < len(producer_shapes) else None


def build_edges(graph, by_name: dict[str, str], op_nodes: list[dict], all_shapes: dict[str, list[list[int]]]) -> list[dict]:
    """逐参数位置建边，并**只对能独立核实的地方**判 shape_consistent。

    能独立核实的只有三处：多输出项索引解析后与 getitem 自己记的形状比、inplace 算子
    输出是否保持输入形状、以及形状根本拿不到。别处 SSA 保证同名值即同形状，判 true 不吹牛。
    """
    shapes_by_id = {n["id"]: n["shape_out"] for n in op_nodes}
    inplace_by_id = {n["id"]: n["inplace"] for n in op_nodes}
    dtype_by_id = {n["id"]: n["dtype"] for n in op_nodes}
    edges: list[dict] = []

    for node in graph.nodes:
        if node.op == "output" or node.name not in by_name:
            continue
        dst = by_name[node.name]
        for label, arg in iter_arg_nodes(node, by_name):
            src = by_name[arg.name]
            producer_shapes = all_shapes.get(src) or []
            resolved = resolve_arg_shape(node, producer_shapes)
            if resolved is not None:
                edge_shape = list(resolved)
            elif producer_shapes:
                edge_shape = list(producer_shapes[0])
            else:
                edge_shape = None

            consistent = edge_shape is not None
            if consistent and resolved is not None and is_getitem(node):
                consumed = shapes_by_id.get(dst)
                consistent = consumed is not None and consumed == resolved
            if consistent and inplace_by_id.get(src):
                dst_shape = shapes_by_id.get(dst)
                consistent = dst_shape is None or dst_shape == edge_shape

            edges.append(
                {
                    "id": f"e:{src}->{dst}:{label}",
                    "src": src,
                    "dst": dst,
                    "label": label,
                    "shape": edge_shape if edge_shape is not None else [],
                    "dtype": dtype_by_id.get(src),
                    "inplace": bool(inplace_by_id.get(src)),
                    "shape_consistent": bool(consistent),
                }
            )
    return edges


def finish_nodes(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """补 shape_in（取第一条来自算子的入边，权重边不算），并统计供 dump 用的计数。"""
    incoming: dict[str, list[dict]] = {}
    for edge in edges:
        incoming.setdefault(edge["dst"], []).append(edge)
    by_id = {n["id"]: n for n in nodes}

    for node in nodes:
        if node["level"] != "op":
            continue
        if node.get("kind") == "op":
            for edge in incoming.get(node["id"], []):
                src = by_id.get(edge["src"])
                # 权重边（param）不算主输入；形参（input）算
                if src is not None and src.get("kind") in ("op", "input") and edge["shape"]:
                    node["shape_in"] = list(edge["shape"])
                    break
        if node.get("kind") == "op" and not node["outputs"]:
            node["degraded"] = True
            node["degraded_reason"] = node["degraded_reason"] or "该节点没有张量输出形状"

    ops = [n for n in nodes if n.get("kind") == "op"]
    return {
        "operators": len(ops),
        "degraded": sum(1 for n in ops if n["degraded"]),
        "fused": sum(1 for n in ops if n["op"] in FUSED_OPS),
        "orphan": sum(
            1 for n in ops if n["id"] not in incoming and n["op"] != "arange"
        ),
        "shape_broken": sum(1 for e in edges if not e["shape_consistent"]),
    }
