"""PaperTrace 命令行入口。

本切片只接通两条路径：`build --skeleton`（写合法的空 trace.json）与 `dump`
（打印规模计数）。其余命令明确报「尚未实现」并以 2 退出——**不允许**用一个
看起来成功的空结果代替真正的实现。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from papertrace.build_trace import (
    BuildError,
    build_trace,
    fused_ops_in,
    repo_commit,
    skeleton_trace,
)
from papertrace.exceptions import RuntimeUnavailable, TraceSchemaError, TraceUnsupported
from papertrace.schema_validate import dump_trace, load_trace, validate_trace

UNIMPLEMENTED = 2
#: 缺运行时要件（典型：没装 torch）。不许降级成空 trace。
MISSING_RUNTIME = 4
#: 模型能加载但追不动（自定义算子、数据依赖分支等）。
UNTRACEABLE = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="papertrace",
        description="PaperTrace：把 PyTorch 算子图与论文公式项逐项对上账。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="构建 trace.json（以及可选的单文件 HTML）")
    p_build.add_argument(
        "--repo", required=True, help="本地仓库路径（git URL 尚未实现，会报错退出）"
    )
    p_build.add_argument("--paper", default="none", help="arxiv:ID、本地 .tex/.pdf，或 none")
    p_build.add_argument("--out", default="output", help="输出目录")
    p_build.add_argument(
        "--entry",
        default="model:build_model",
        help="模型入口，写成 模块:符号（默认 model:build_model；工厂函数或零参类）",
    )
    p_build.add_argument("--batch", type=int, default=2, help="示例输入的 batch 大小")
    p_build.add_argument("--seq-len", type=int, default=None, help="示例输入的序列长度")
    p_build.add_argument(
        "--skeleton", action="store_true", help="只写合法的空 trace.json（不追踪）"
    )
    p_build.add_argument(
        "--force", action="store_true", help="允许覆盖已存在的 trace.json"
    )

    p_dump = sub.add_parser("dump", help="打印 trace.json 的规模计数")
    p_dump.add_argument("--trace", default="output/trace.json", help="trace.json 路径")
    p_dump.add_argument(
        "--ops", action="store_true", help="按拓扑序打印算子节点（形状 → 形状）"
    )
    p_dump.add_argument(
        "--edges", action="store_true", help="打印全部边（含形状与一致性），对账形状链用"
    )

    p_serve = sub.add_parser("serve", help="localhost 按需深钻")
    p_serve.add_argument("--trace", default="output/trace.json")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)

    p_eval = sub.add_parser("eval", help="跑 golden set")
    p_eval.add_argument("--golden", default="data/golden")

    return parser


def _cmd_build(args: argparse.Namespace) -> int:
    if args.paper not in ("none", "", None):
        print("papertrace build：论文 ingest 尚未实现。", file=sys.stderr)
        return UNIMPLEMENTED
    if args.skeleton:
        doc = skeleton_trace(repo_url=str(args.repo), commit=repo_commit(args.repo))
    else:
        try:
            doc = build_trace(
                args.repo,
                entry=args.entry,
                batch=args.batch,
                seq_len=args.seq_len,
            )
        except RuntimeUnavailable as exc:
            print(f"papertrace build：{exc}", file=sys.stderr)
            return MISSING_RUNTIME
        except TraceUnsupported as exc:
            print("papertrace build：下面是 torch.export 原始诊断——", file=sys.stderr)
            print(f"papertrace build：{exc}", file=sys.stderr)
            return UNTRACEABLE
        except BuildError as exc:
            print(f"papertrace build：{exc}", file=sys.stderr)
            return UNIMPLEMENTED
        fused = fused_ops_in(doc)
        if fused:
            print(
                "papertrace build：警告——图里有融合算子 "
                + "、".join(fused)
                + "，论文里对应的中间算子已被吞掉，算子级对账会漏检（节点已标 degraded）。",
                file=sys.stderr,
            )
    try:
        validate_trace(doc)
    except TraceSchemaError as exc:
        print(f"papertrace build：生成的 trace 不合法：\n{exc}", file=sys.stderr)
        return 1

    out_path = Path(args.out) / "trace.json"
    try:
        dump_trace(doc, out_path, overwrite=args.force)
    except FileExistsError as exc:
        print(f"papertrace build：{exc}", file=sys.stderr)
        return 3
    if args.skeleton:
        print(f"已写出 {out_path}（nodes=0 edges=0 anchors=0，骨架）")
    else:
        counts = (doc["meta"].get("runtime") or {}).get("counts") or {}
        kinds = {"op": 0, "param": 0, "input": 0}
        for node in doc["nodes"]:
            if node["level"] == "op":
                kinds[node.get("kind", "op")] = kinds.get(node.get("kind", "op"), 0) + 1
        total_ops = kinds["op"] + kinds["param"] + kinds["input"]
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
        real = (doc["meta"].get("runtime") or {}).get("real_execution") or {}
        if not real.get("ok", True):
            print(f"  注意：导出图没能再跑一遍，形状链来自 torch.export 推断：{real.get('reason')}")
    return 0


def _cmd_dump(args: argparse.Namespace) -> int:
    path = Path(args.trace)
    if not path.is_file():
        print(f"papertrace dump：找不到 {path}", file=sys.stderr)
        return 2
    doc = load_trace(path)
    try:
        validate_trace(doc)
    except TraceSchemaError as exc:
        print(f"papertrace dump：{path} 不是合法 trace：\n{exc}", file=sys.stderr)
        return 2
    if args.ops:
        _print_ops(doc)
        return 0
    if args.edges:
        _print_edges(doc)
        return 0
    broken = [e for e in doc["edges"] if e.get("checked") and not e["shape_consistent"]]
    unchecked = [e for e in doc["edges"] if not e.get("checked")]
    degraded = [n for n in doc["nodes"] if n["level"] == "op" and n["degraded"]]
    kinds = {"op": 0, "param": 0, "input": 0}
    for node in doc["nodes"]:
        if node["level"] == "op":
            kinds[node.get("kind", "op")] = kinds.get(node.get("kind", "op"), 0) + 1
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
            f"消费者 {_fmt_shape(edge['shape'])} ≠ 生产者 {_fmt_shape(edge.get('producer_shape'))}"
        )
    for node in degraded:
        print(f"  ~ {node['id']} {node['op']}：{node.get('degraded_reason') or '未说明原因'}")
    return 0


def _fmt_shape(shape) -> str:
    """() 是 0 维标量；(?) 是形状未知。两者不能混为一谈。"""
    if shape is None:
        return "(?)"
    if not shape:
        return "()"
    return "(" + ", ".join(str(d) for d in shape) + ")"


def _print_edges(doc: dict) -> None:
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
            f"{flag} {_fmt_shape(edge['shape']):<16} "
            f"生产者 {_fmt_shape(edge.get('producer_shape')):<16} "
            f"{edge['src']} ({src['op'] if src else '?'}) -> "
            f"{edge['dst']} ({dst['op'] if dst else '?'}) {edge['id']}"
        )
    print(f"edges={len(doc['edges'])} shape_broken={broken} shape_unchecked={unchecked}")


def _print_ops(doc: dict) -> None:
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
        shown_out = _fmt_shape(node["shape_out"]) if known_out else "(?)"
        # 形参/权重没有「输入形状」，画 - 别让人误读成 0 维标量；
        # 算子没观察到入参时画 (?)：空 [] 是 0 维标量，不能混用
        if node.get("kind") != "op":
            shown_in = "-"
        elif node.get("inputs"):
            shown_in = _fmt_shape(node["shape_in"])
        else:
            shown_in = "(?)"
        print(
            f"{node['id']:<16} {where:<34} "
            f"{shown_in} -> {shown_out} "
            f"{node['op']}{flag}"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        return _cmd_build(args)
    if args.command == "dump":
        return _cmd_dump(args)
    print(f"papertrace {args.command}：本切片未实现。", file=sys.stderr)
    return UNIMPLEMENTED


if __name__ == "__main__":
    raise SystemExit(main())
