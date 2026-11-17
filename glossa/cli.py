"""glossa 命令行（T10/T11）：analyze / explain / facts / serve。退出码 0–5 见 docs/glossa.md。

analyze 写 repo.json（过 schema，1 失败 0 成功）；explain 写 explain.html（渲染失败 2）；缺运行时或
--llm 后端不可用是 4（绝不降级）；--repo 不是目录是 5。
退出码 3 只属 analyze（输出已存在且没 --force）；explain 每次覆盖已存在的 explain.html（R74）。
R487：explain 默认复用 --out/repo.json（缺失才重扫并在页脚注明，--force 重扫并覆盖台账）；
台账读不进来是 1（stderr 原文，绝不静默回落重扫）。
参数错误由 argparse 以 2 退出，与构建失败同码、靠 stderr 区分。
A1：AI 配置集中在 glossa/explain/llm_config.py（显式入参 > GLOSSA_* > PAPERTRACE_*）；
没配后端时照旧出程序版事实页，只是页头多一条红条说清「本页没用人话讲解」，
配了 openai 但调不通仍然是 4——绝不静默退回事实版。
serve 是 T11 的 MCP 入口（R327：换行分隔 JSON-RPC 2.0 over stdio，stdout 只写协议流）。
facts 子命令与「--repo → doc」闸门在 glossa/cli_facts.py（R452：本文件守住 200 行上限）。
A6：--ai / --llm fake|openai / --style 与整条 AI 编排在 glossa/cli_explain.py（同一条 200 行尺），
这里只做一次分派；裸 --llm 的旧路径与输出逐字不变。
"""
from __future__ import annotations

import argparse
import pathlib
import sys

from glossa import cli_explain, cli_facts, schema_repo
from glossa.cli_facts import KINDS, doc_or_exit, fail
from glossa.explain import ai_pipeline, llm_config, narrate, render
from papertrace.exceptions import BuildError, LLMUnavailable, TraceSchemaError
from papertrace.exit_codes import MISSING_RUNTIME
from papertrace.schema_validate import dump_trace

OK = 0
SCHEMA_FAIL = 1
BUILD_FAIL = cli_facts.BUILD_FAIL          # 2：渲染失败（BuildError）
OCCUPIED = 3                               # 输出已存在且没有 --force
NO_RUNTIME = MISSING_RUNTIME               # 4：缺运行时 / --llm 后端不可用
NO_REPO = cli_facts.NO_REPO                # 5：--repo 不存在或不是目录


def print_summary(doc):
    """R325：一行摘要，数字全取 doc["totals"]（千位分隔），绝不另算一份。"""
    totals = doc.get("totals") or {}
    root_name = ((doc.get("meta") or {}).get("repo") or {}).get("root_name") or "未命名"
    order = (("files", "个文件"), ("symbols", "个符号"), ("imports", "条 import"),
             ("packages", "个包"), ("projects", "个项目"), ("entries", "个入口"))
    shown = " · ".join("{:,} {}".format(int(totals.get(key) or 0), label) for key, label in order)
    print("  仓库：%s · %s" % (root_name, shown))


def _cmd_analyze(args):
    doc, code = doc_or_exit(args)
    if doc is None:
        return code
    try:
        schema_repo.validate_repo(doc)
    except TraceSchemaError as exc:
        return fail(SCHEMA_FAIL, "glossa analyze：生成的 repo.json 不合法：\n%s" % exc)
    out = pathlib.Path(args.out) / "repo.json"
    try:
        dump_trace(doc, out, overwrite=args.force)
    except FileExistsError as exc:
        return fail(OCCUPIED, "glossa analyze：%s（加 --force 才覆盖）" % exc)
    print_summary(doc)
    print("repo.json：%s" % out)
    return OK


def _save_ledger(doc, out):
    """R487：--force 重扫之后把 repo.json 一起覆盖（explain 不再是只读不写）。"""
    schema_repo.validate_repo(doc)
    dump_trace(doc, pathlib.Path(out) / cli_facts.LEDGER, overwrite=True)
    return OK


def _cmd_explain(args):
    doc, code, rescanned = cli_facts.ledger_or_exit(args)      # R487：默认复用同目录台账
    if doc is None:
        return code
    if args.force:                                            # 重扫 + 覆盖台账（R487 §1）
        try:
            _save_ledger(doc, args.out)
        except TraceSchemaError as exc:
            return fail(SCHEMA_FAIL, "glossa explain：生成的 repo.json 不合法：\n%s" % exc)
    if cli_explain.wanted(args):                              # A6：--ai / --llm fake|openai
        return cli_explain.run(args, doc)
    try:
        cfg = llm_config.resolve()                            # A1：配置只读这一处
    except ValueError as exc:                                 # backend 写错：报原文，不吞成 traceback
        return fail(NO_RUNTIME, "glossa explain：AI 配置不合法：%s" % exc)
    mode, name, blocks = "program", None, None
    if args.llm:
        if cfg.backend == "offline":
            print("未配置模型后端，本页由程序生成")
        else:
            try:
                blocks, name = narrate.ask(doc, backend=ai_pipeline.backend())
            except LLMUnavailable as exc:
                return fail(NO_RUNTIME, "glossa explain：模型后端不可用：%s" % exc)
            except BuildError as exc:
                return fail(BUILD_FAIL, "glossa explain：模型给的 blocks 不合法：%s" % exc)
            mode = "model"
    fallback = mode == "program" and not llm_config.ready(cfg)   # A1：红条 = 这页没有 AI
    if blocks is None:
        blocks = narrate.program(doc)
    try:
        path = render.write_explain(doc, blocks, args.out, mode=mode, model_name=name,
                                    rescanned=rescanned, fallback=fallback)
    except BuildError as exc:
        return fail(BUILD_FAIL, "glossa explain：解释页渲染失败：%s" % exc)
    report = render.render_explain(doc, blocks, mode=mode, model_name=name,
                                   rescanned=rescanned, fallback=fallback)[1]
    print("讲解页：%s · %d 块 · 未溯源 %d 处%s" % (path, report["blocks"], report["untraced"],
                                            " · 模型 %s" % name if name else ""))
    return OK


def _cmd_serve(args):
    """R327/R329：stdio 上的 MCP server；UTF-8 写死，否则中文在 cp936 管道里会乱。"""
    from glossa.mcp.server import serve
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    serve(sys.stdin, sys.stdout)
    return OK


def build_parser():
    parser = argparse.ArgumentParser(prog="glossa", description="笺疏 Glossa：把任意代码仓库解析成事实台账与讲解页。")
    sub = parser.add_subparsers(dest="command", required=True)
    _common(sub.add_parser("analyze", help="扫一遍仓库，写 repo.json（11 个顶层键的事实台账）"))
    explain = _common(sub.add_parser("explain", help="生成单文件离线讲解页 explain.html"))
    cli_explain.add_options(explain)                          # A6：--ai / --llm / --style
    facts_cmd = sub.add_parser("facts", help="按 kind 打印事实台账（可分页）")
    facts_cmd.add_argument("--repo", required=True, help="仓库根目录")
    facts_cmd.add_argument("--kind", choices=KINDS, help="只显示这一类 fact")
    facts_cmd.add_argument("--offset", type=cli_facts.non_negative_int, default=0,
                           help="跳过前 N 条（<0 由 argparse 以 2 退出）")
    facts_cmd.add_argument("--limit", type=cli_facts.positive_int, help="最多显示 N 条（<1 同上）")
    sub.add_parser("serve", help="在 stdio 上起 MCP server（换行分隔 JSON-RPC 2.0）")
    return parser


def _common(parser):
    parser.add_argument("--repo", required=True, help="仓库根目录")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--force", action="store_true",
                        help="analyze：允许覆盖已存在的 repo.json；explain：重扫仓库并覆盖 repo.json"
                             "（不带它时 explain 复用 --out/repo.json，缺失才重扫）")
    parser.add_argument("--max-files", type=int, default=20_000, dest="max_files",
                        help="最多扫多少个文件（超出按连接数选点并记降级说明）")
    parser.add_argument("--no-default-excludes", action="store_true",
                        help="不启用默认排除规则（vendor/node_modules 等）")
    parser.add_argument("--bonus-trace", default=None, dest="bonus_trace",
                        help="旧 trace.json，用来和 repo.json 对账")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "analyze":
        return _cmd_analyze(args)
    if args.command == "explain":
        return _cmd_explain(args)
    if args.command == "facts":
        return cli_facts.run(args)
    return _cmd_serve(args)
