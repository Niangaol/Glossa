"""PaperTrace 命令行入口。

只负责两件事：把参数变成调用，把结果变成退出码。可读输出的排版都在
papertrace/report.py（单文件 ≤200 行的约束）。

S9 的取舍（R79，与 papertrace/spine.py 记同一段）：`--paper` 要接论文脊柱就得
有**模块实例**（符号表要 mod.config 与定义点定位，结构信号要 config 的四个超参名），
而 `build_trace()` 只返回 trace dict、且 build_trace.py 一行不许改。所以这里在
build_trace 成功后用 `load_entry(args.repo, args.entry)` **再取一次**模块实例
（实测 0.003s，相对 build_trace 的 2.760s 可忽略）——nodes/edges 仍来自第一次
追踪，绝不为了拿模块而重新追踪，GC8 逐项不变；load_entry 抛异常按 BuildError
收成一行错误，不冒 traceback。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import jinja2

from papertrace.build_trace import BuildError, build_trace, load_entry, repo_commit, skeleton_trace
from papertrace.exceptions import RuntimeUnavailable, TraceSchemaError, TraceUnsupported
from papertrace.exit_codes import MISSING_RUNTIME, UNIMPLEMENTED, UNTRACEABLE
from papertrace.paths import leaked_absolute, relativize_doc
from papertrace.render_html import write_html
from papertrace.report import (
    print_build_summary,
    print_edges,
    print_fusion_warning,
    print_ops,
    print_overview,
)
from papertrace.report_dump import run_dump
from papertrace.schema_validate import dump_trace, validate_trace
from papertrace.spine import attach_paper


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
        "--force", action="store_true", help="允许覆盖已存在的 trace.json（index.html 是派生产物每次覆盖不受此约束）"
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
            # 追不动就不写 trace：宁可 exit 5，也不给一份「看起来成功」的假结果
            print(f"papertrace build：{exc}", file=sys.stderr)
            return UNTRACEABLE
        except BuildError as exc:
            print(f"papertrace build：{exc}", file=sys.stderr)
            return UNIMPLEMENTED
        print_fusion_warning(doc)
    # S9：--paper 不是 none 就把论文脊柱接进来；接不上也照写 trace，
    # 失败原因落 doc["unresolved"]，绝不冒 traceback、绝不静默成功
    if args.paper not in ("none", "", None):
        model = None
        if not args.skeleton:
            try:
                model = load_entry(args.repo, args.entry)
            except BuildError as exc:
                print(f"papertrace build：{exc}", file=sys.stderr)
                return UNIMPLEMENTED
        try:
            attach_paper(doc, args.paper, model)
        except BuildError as exc:  # R148：契约错误（如结构配对重复）报一行，不冒 traceback
            print(f"papertrace build：{exc}", file=sys.stderr)
            return UNIMPLEMENTED
        print(f"  论文脊柱：anchors={len(doc['anchors'])} unresolved={len(doc['unresolved'])}（{args.paper}）")
    relativize_doc(doc)  # R139/R140：写盘前一次性把本机绝对路径改成相对构建目录
    leaked = leaked_absolute(doc)  # R154/R155：仍然绝对的路径必须当面提示，不许静默送出去
    if leaked:
        msg = f"papertrace build：{len(leaked)} 条路径不在构建目录 {Path.cwd()} 之下，按 GC14 原样保留（仍含盘符）；要便携化请在仓库根目录或其上级目录构建"
        print(msg, file=sys.stderr)
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
        print_build_summary(doc, out_path)
    # S10：单文件离线 HTML 是派生产物，skeleton 与真实 build 两条路都写（R83）。
    # index.html 每次 build 都覆盖，不受 --force 约束（R74）；HTML 写失败绝不
    # 影响 trace.json 已写出的事实，只报 exit 2。
    try:
        html_path = write_html(doc, Path(args.out))
    except (BuildError, jinja2.TemplateError) as exc:
        print(f"papertrace build：trace.json 已写出，HTML 渲染失败：{exc}", file=sys.stderr)
        return 2
    print(f"已写出 {html_path}（单文件离线 HTML，零外链）")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        return _cmd_build(args)
    if args.command == "dump":
        return run_dump(args.trace, ops=args.ops, edges=args.edges)
    print(f"papertrace {args.command}：本切片未实现。", file=sys.stderr)
    return UNIMPLEMENTED


if __name__ == "__main__":
    raise SystemExit(main())
