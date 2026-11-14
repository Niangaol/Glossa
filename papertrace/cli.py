"""PaperTrace 命令行入口。

本切片只保证 --help 与子命令存在；build / dump 在 Task 3 接上，
serve / eval 明确报「尚未实现」。
"""

from __future__ import annotations

import argparse
import sys

UNIMPLEMENTED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="papertrace",
        description="PaperTrace：把 PyTorch 算子图与论文公式项逐项对上账。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="构建 trace.json（以及可选的单文件 HTML）")
    p_build.add_argument("--repo", required=True, help="本地仓库路径或 git URL")
    p_build.add_argument("--paper", default="none", help="arxiv:ID、本地 .tex/.pdf，或 none")
    p_build.add_argument("--out", default="output", help="输出目录")
    p_build.add_argument("--skeleton", action="store_true", help="只写合法的空 trace.json")

    p_dump = sub.add_parser("dump", help="打印 trace.json 的规模计数")
    p_dump.add_argument("--trace", default="output/trace.json", help="trace.json 路径")

    p_serve = sub.add_parser("serve", help="localhost 按需深钻")
    p_serve.add_argument("--trace", default="output/trace.json")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)

    p_eval = sub.add_parser("eval", help="跑 golden set")
    p_eval.add_argument("--golden", default="data/golden")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in ("serve", "eval"):
        print(f"papertrace {args.command}：本切片未实现。", file=sys.stderr)
        return UNIMPLEMENTED
    print(f"papertrace {args.command}：本切片未实现。", file=sys.stderr)
    return UNIMPLEMENTED


if __name__ == "__main__":
    raise SystemExit(main())
