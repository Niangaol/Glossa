"""边：逐参数位置连边，形状取**消费者真实拿到的那一项**，再和生产者输出比。

两边都来自同一次真实执行（见 fx_observe），不是同一条 SSA 推断抄两遍：
消费者输入是运行时 `args[i][j]` 的形状，生产者输出是运行时节点的输出形状。
两边都拿不到时边标 `checked=false`——**未核实不等于一致**，不许默认 True。
"""

from __future__ import annotations

from typing import Any

from papertrace.parse_code.fx_graph import fused_items, is_getitem, op_name
from papertrace.parse_code.fx_shapes import navigate, tree_leaf


def iter_arg_nodes(node, by_name: dict[str, str]) -> list[tuple[str, Any, list[Any]]]:
    """递归展开 args/kwargs 里的节点引用，同时给出形状树里的取值路径。

    `cat([a, b])` 这类容器参数必须展开，否则整条边会静默消失；
    `b + 1` 里的 `b` 来自 `split` 的第 0 项，路径里带索引才能取对形状。
    """
    found: list[tuple[str, Any, list[Any]]] = []

    def walk(label: str, value: Any, path: list[Any]) -> None:
        if getattr(value, "name", None) in by_name:
            found.append((label, value, path))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                walk(f"{label}[{i}]", item, path + [i])
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(f"{label}[{key!r}]", item, path + [str(key)])

    for position, arg in enumerate(node.args):
        walk(f"args[{position}]", arg, ["args", position])
    for key, arg in node.kwargs.items():
        walk(f"kwargs[{key}]", arg, ["kwargs", str(key)])
    return found


def _consumer_args_tree(observed: dict[str, Any]) -> dict[str, Any] | None:
    if not observed:
        return None
    return {
        "d": {
            "args": {"l": observed.get("args") or []},
            "kwargs": {"d": observed.get("kwargs") or {}},
        }
    }


def _producer_item(observed: dict[str, Any], consumer, consumer_args) -> list[int] | None:
    """getitem 消费者：生产者的容器里被取出的那一项，就是这一条边的形状。"""
    if not observed or not is_getitem(consumer) or len(consumer_args) < 2:
        return None
    index = consumer_args[1]
    if not isinstance(index, int):
        return None
    tree = observed.get("out")
    items = tree.get("l") if isinstance(tree, dict) else None
    if not items:
        return None
    if index < 0:
        index += len(items)
    if not 0 <= index < len(items):
        return None
    return tree_leaf(items[index])


def build_edges(
    graph,
    by_name: dict[str, str],
    op_nodes: list[dict],
    all_shapes: dict[str, list[list[int]]],
    observed: dict[str, dict[str, Any]] | None = None,
) -> list[dict]:
    """逐参数位置建边；判定只用运行时观察到的两边形状。"""
    observed = observed or {}
    dtype_by_id = {n["id"]: n["dtype"] for n in op_nodes}
    inplace_by_id = {n["id"]: n["inplace"] for n in op_nodes}
    edges: list[dict] = []

    for node in graph.nodes:
        if node.op == "output" or node.name not in by_name:
            continue
        dst = by_name[node.name]
        seen = observed.get(node.name) or {}
        tree = _consumer_args_tree(seen)
        for label, arg, path in iter_arg_nodes(node, by_name):
            src = by_name[arg.name]
            producer = observed.get(arg.name) or {}
            if is_getitem(node) and path == ["args", 0]:
                # getitem 拿到的是容器，但它**实际取出**的那一项就是自己的输出；
                # 拿容器整体比会把每条 split 边都判成「未核实」。
                consumer_leaf = tree_leaf(seen.get("out"))
            else:
                consumer_leaf = tree_leaf(navigate(tree, path))
            item = None
            container = node.args[0] if node.args else None
            if getattr(container, "name", None) == arg.name:
                # 只有容器本身就是一个生产者节点时，「取第几项」才有确定含义；
                # 容器里混了多个生产者时索引落到谁身上无从判断，宁可不核实。
                item = _producer_item(producer, node, node.args)
            producer_leaf = item if item is not None else tree_leaf(producer.get("out"))
            if producer_leaf is None:
                # get_attr 节点不走 Interpreter.run_node，只能退回 export 的 val；
                # 单输出时 val 就是唯一一项，多输出不猜。
                fallback = all_shapes.get(src) or []
                if len(fallback) == 1:
                    producer_leaf = fallback[0]

            checked = consumer_leaf is not None and producer_leaf is not None
            consistent = bool(checked and consumer_leaf == producer_leaf)
            edge_shape = consumer_leaf if consumer_leaf is not None else producer_leaf

            edges.append(
                {
                    "id": f"e:{src}->{dst}:{label}",
                    "src": src,
                    "dst": dst,
                    "label": label,
                    "shape": edge_shape if edge_shape is not None else [],
                    "producer_shape": producer_leaf,
                    "checked": checked,
                    "dtype": dtype_by_id.get(src),
                    "inplace": bool(inplace_by_id.get(src)),
                    "shape_consistent": consistent,
                }
            )
    return edges


def finish_nodes(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """统计供 dump/摘要用的计数。shape_in 在节点构造时就来自真实入参，这里不再覆写。"""
    incoming: dict[str, list[dict]] = {}
    for edge in edges:
        incoming.setdefault(edge["dst"], []).append(edge)

    for node in nodes:
        if node["level"] != "op" or node.get("kind") != "op":
            continue
        if not node.get("outputs"):
            node["degraded"] = True
            node["degraded_reason"] = node.get("degraded_reason") or "该节点没有张量输出形状"

    ops = [n for n in nodes if n.get("kind") == "op"]
    return {
        "operators": len(ops),
        "degraded": sum(1 for n in ops if n["degraded"]),
        "fused": sum(1 for n in ops if fused_items(n["op"]) is not None),
        "orphan": sum(1 for n in ops if n["id"] not in incoming and n["op"] != "arange"),
        "shape_broken": sum(1 for e in edges if e["checked"] and not e["shape_consistent"]),
        "shape_unchecked": sum(1 for e in edges if not e["checked"]),
    }
