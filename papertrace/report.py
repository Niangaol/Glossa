"""命令行输出的排版层：dump 的可读视图与 build 摘要。

单独成文件只为一个原因：cli.py 负责参数与退出码，排版细节不该把它的行数撑破
（Global Constraints：单源文件 ≤200 行）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from papertrace.build_trace import fused_ops_in
from papertrace.parse_code.fx_graph import FUSION_WARNING, fused_items


def fmt_shape(shape) -> str:
    """() 是 0 维标量；(?) 是形状未知。两者不能混为一谈。"""
    if shape is None:
        return "(?)"
    if not shape:
        return "()"
    return "(" + ", ".join(str(d) for d in shape) + ")"


def _kind_counts(doc: dict) -> dict[str, int]:
    kinds = {"op": 0, "param": 0, "input": 0}
    for node in doc["nodes"]:
        if node["level"] == "op":
            key = node.get("kind", "op")
            kinds[key] = kinds.get(key, 0) + 1
    return kinds


def print_build_summary(doc: dict, out_path: Path) -> None:
    """build 写完 trace 后的两行摘要：规模 + 必须当场看见的异常计数。"""
    counts = (doc["meta"].get("runtime") or {}).get("counts") or {}
    kinds = _kind_counts(doc)
    print(
        f"已写出 {out_path}（nodes={len(doc['nodes'])}：算子 {kinds['op']} / "
        f"权重 {kinds['param']} / 输入 {kinds['input']}，edges={len(doc['edges'])}，真实追踪）"
    )
    # 降级、融合、孤点、断链必须在摘要里就看得见，不能等用户去翻 JSON
    print(
        "  degraded={} fused={} orphan={} shape_broken={} shape_unchecked={}".format(
            counts.get("degraded", "?"),
            counts.get("fused", "?"),
            counts.get("orphan", "?"),
            counts.get("shape_broken", "?"),
            counts.get("shape_unchecked", "?"),
        )
    )


def print_fusion_warning(doc: dict) -> None:
    """融合算子会吞掉论文里的中间算子：不喊一声就等于静默漏检。"""
    fused = fused_ops_in(doc)
    if not fused:
        return
    items: list[str] = []
    for name in fused:
        for item in fused_items(name) or ():
            if item not in items:
                items.append(item)
    print(
        "papertrace build：警告——"
        + FUSION_WARNING.format(
            count=len(fused), names="、".join(fused), items="/".join(items)
        ),
        file=sys.stderr,
    )


def print_overview(doc: dict) -> None:
    """dump 默认视图：规模计数 + 断链 + 降级明细。"""
    broken = [e for e in doc["edges"] if e.get("checked") and not e["shape_consistent"]]
    unchecked = [e for e in doc["edges"] if not e.get("checked")]
    degraded = [n for n in doc["nodes"] if n["level"] == "op" and n["degraded"]]
    kinds = _kind_counts(doc)
    print(
        "nodes={} edges={} anchors={} mismatches={} unresolved={}".format(
            len(doc["nodes"]),
            len(doc["edges"]),
            len(doc["anchors"]),
            len(doc["mismatches"]),
            len(doc["unresolved"]),
        )
    )
    print(
        "operators={} (param={} input={}) degraded={} shape_broken={} shape_unchecked={}".format(
            kinds["op"], kinds["param"], kinds["input"], len(degraded), len(broken), len(unchecked)
        )
    )
    # 形状链断了必须看得见，不能只在 JSON 里躺着
    for edge in broken:
        print(
            f"  ! 形状对不上 {edge['src']} -> {edge['dst']} "
            f"消费者 {fmt_shape(edge['shape'])} ≠ 生产者 {fmt_shape(edge.get('producer_shape'))}"
        )
    for node in degraded:
        print(f"  ~ {node['id']} {node['op']}：{node.get('degraded_reason') or '未说明原因'}")


def print_edges(doc: dict) -> None:
    """形状链对账入口：每条边一行，不一致的用 ! 标出来。"""
    by_id = {n["id"]: n for n in doc["nodes"]}
    broken = 0
    unchecked = 0
    for edge in doc["edges"]:
        src, dst = by_id.get(edge["src"]), by_id.get(edge["dst"])
        if not edge.get("checked"):
            flag = "?"
            unchecked += 1
        elif edge["shape_consistent"]:
            flag = " "
        else:
            flag = "!"
            broken += 1
        print(
            f"{flag} {fmt_shape(edge['shape']):<16} "
            f"生产者 {fmt_shape(edge.get('producer_shape')):<16} "
            f"{edge['src']} ({src['op'] if src else '?'}) -> "
            f"{edge['dst']} ({dst['op'] if dst else '?'}) {edge['id']}"
        )
    print(f"edges={len(doc['edges'])} shape_broken={broken} shape_unchecked={unchecked}")


def print_ops(doc: dict) -> None:
    """按拓扑序打印算子：这是 M1a 的「肉眼验收」入口。"""
    by_id = {n["id"]: n for n in doc["nodes"]}
    for node in doc["nodes"]:
        if node["level"] != "op":
            continue
        module = by_id.get(node.get("parent_id") or "")
        where = module["label"] if module else "-"
        flag = ""
        if node["degraded"]:
            reason = (node.get("degraded_reason") or "").strip()
            flag = "  [degraded: " + (reason[:58] + "…" if len(reason) > 58 else reason) + "]"
        # outputs 为空 = 这个节点没有张量输出；[[]] = 0 维标量
        known_out = bool(node.get("outputs")) or bool(node["shape_out"])
        shown_out = fmt_shape(node["shape_out"]) if known_out else "(?)"
        # 形参/权重没有「输入形状」，画 - 别让人误读成 0 维标量；
        # 算子 inputs 为空表示「确实没有数据输入」（只用权重/缓冲，如 slice），也画 -；
        # (?) 只留给 trace 里**根本没有 inputs 字段**的老格式——那是真·未知。
        if node.get("kind") != "op":
            shown_in = "-"
        elif node.get("inputs"):
            shown_in = fmt_shape(node["shape_in"])
        elif "inputs" in node:
            shown_in = "-"
        else:
            shown_in = "(?)"
        print(
            f"{node['id']:<16} {where:<34} "
            f"{shown_in} -> {shown_out} "
            f"{node['op']}{flag}"
        )
