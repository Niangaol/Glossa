"""glossa 命令行（T10）：analyze / explain / facts。退出码 0–5 见 docs/glossa.md。

analyze 写 repo.json（过 schema，1 失败 0 成功）；explain 写 explain.html（渲染失败 2）；输出
已存在且没 --force 是 3；缺运行时或 --llm 后端不可用是 4（绝不降级）；--repo 不是目录是 5。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib

from glossa import facts, schema_repo
from glossa.explain import narrate, render
from papertrace.exceptions import BuildError, LLMUnavailable, TraceSchemaError
from papertrace.exit_codes import MISSING_RUNTIME, UNIMPLEMENTED, UNTRACEABLE
from papertrace.schema_validate import dump_trace

OK = 0
SCHEMA_FAIL = 1
BUILD_FAIL = UNIMPLEMENTED          # 2：渲染失败（BuildError）
OCCUPIED = 3                        # 输出已存在且没有 --force
NO_RUNTIME = MISSING_RUNTIME        # 4：缺运行时 / --llm 后端不可用
NO_REPO = UNTRACEABLE               # 5：--repo 不存在或不是目录
_KINDS = ("file", "pkg", "project", "entry", "import", "symbol", "namespace",
          "graph", "excluded", "degraded", "source", "totals", "bonus")


def _fail(code, message):
    """一行大白话错误 + 退出码；本工具的输出就是给人读的，所以一律写 stdout。"""
    print(message)
    return code


def _bonus(path):
    """--bonus-trace 指向旧 trace.json：读不了就是构建失败，不装没事。"""
    if not path:
        return None
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError("读不了 --bonus-trace 的 JSON（%s）：%s" % (path, exc)) from exc


def _doc(args):
    """(doc, 退出码)：路径不对 → 5；扫描/组装失败 → 2。"""
    root = pathlib.Path(args.repo)
    if not root.is_dir():
        return None, _fail(UNTRACEABLE, "glossa：仓库根目录不存在或不是目录：%s" % root)
    try:
        kw = {"max_files": getattr(args, "max_files", 20_000),
              "use_default_excludes": not getattr(args, "no_default_excludes", False),
              "bonus": _bonus(getattr(args, "bonus_trace", None))}
        return facts.build_repo_doc(root, **kw), OK
    except BuildError as exc:
        return None, _fail(BUILD_FAIL, "glossa %s：%s" % (args.command, exc))


def _configured():
    """R323 ①：两个环境变量都没配（或都是 offline）→ 程序版，不算错误。"""
    for name in (narrate.ENV_GLOSSA_BACKEND, narrate.ENV_PAPER_BACKEND):
        value = (os.environ.get(name) or "").strip()
        if value and value.lower().split(":", 1)[0] != "offline":
            return True
    return False


def _backend():
    """GLOSSA_LLM_BACKEND 优先：临时映射成 papertrace 的变量，问完立刻恢复。"""
    chosen = (os.environ.get(narrate.ENV_GLOSSA_BACKEND) or "").strip()
    if not chosen:
        return narrate.get_llm()
    previous = os.environ.get(narrate.ENV_PAPER_BACKEND)
    os.environ[narrate.ENV_PAPER_BACKEND] = chosen
    try:
        return narrate.get_llm()
    finally:
        if previous is None:
            os.environ.pop(narrate.ENV_PAPER_BACKEND, None)
        else:
            os.environ[narrate.ENV_PAPER_BACKEND] = previous


def print_summary(doc):
    """R325：一行摘要，数字全取 doc["totals"]（千位分隔），绝不另算一份。"""
    totals = doc.get("totals") or {}
    root_name = ((doc.get("meta") or {}).get("repo") or {}).get("root_name") or "未命名"
    order = (("files", "个文件"), ("symbols", "个符号"), ("imports", "条 import"),
             ("packages", "个包"), ("projects", "个项目"), ("entries", "个入口"))
    shown = " · ".join("{:,} {}".format(int(totals.get(key) or 0), label) for key, label in order)
    print("  仓库：%s · %s" % (root_name, shown))


def _cmd_analyze(args):
    doc, code = _doc(args)
    if doc is None:
        return code
    try:
        schema_repo.validate_repo(doc)
    except TraceSchemaError as exc:
        return _fail(SCHEMA_FAIL, "glossa analyze：生成的 repo.json 不合法：\n%s" % exc)
    out = pathlib.Path(args.out) / "repo.json"
    try:
        dump_trace(doc, out, overwrite=args.force)
    except FileExistsError as exc:
        return _fail(OCCUPIED, "glossa analyze：%s（加 --force 才覆盖）" % exc)
    print_summary(doc)
    print("repo.json：%s" % out)
    return OK


def _cmd_explain(args):
    doc, code = _doc(args)
    if doc is None:
        return code
    mode, name, blocks = "program", None, None
    if args.llm:
        if not _configured():
            print("未配置模型后端，本页由程序生成")
        else:
            try:
                blocks, name = narrate.ask(doc, backend=_backend())
            except LLMUnavailable as exc:
                return _fail(NO_RUNTIME, "glossa explain：模型后端不可用：%s" % exc)
            except BuildError as exc:
                return _fail(BUILD_FAIL, "glossa explain：模型给的 blocks 不合法：%s" % exc)
            mode = "model"
    if blocks is None:
        blocks = narrate.program(doc)
    try:
        path = render.write_explain(doc, blocks, args.out, mode=mode, model_name=name)
    except BuildError as exc:
        return _fail(BUILD_FAIL, "glossa explain：解释页渲染失败：%s" % exc)
    report = render.render_explain(doc, blocks, mode=mode, model_name=name)[1]
    print("讲解页：%s · %d 块 · 未溯源 %d 处" % (path, report["blocks"], report["untraced"]))
    return OK


def _cmd_facts(args):
    doc, code = _doc(args)
    if doc is None:
        return code
    rows = doc.get("facts") or {}
    if args.kind:
        prefix = "fact:" + args.kind
        picked = sorted(fid for fid in rows if fid == prefix or fid.startswith(prefix + ":"))
    else:
        picked = sorted(rows)
    total, offset = len(picked), max(0, args.offset or 0)
    stop = offset + (args.limit if args.limit is not None else total)
    for fid in picked[offset:stop]:
        row = rows[fid]
        numbers = ",".join(str(n) for n in row.get("numbers") or [])
        print("%s  [%s]  %s" % (fid, numbers, row.get("text") or ""))
    shown = picked[offset:stop]
    print("共 %d 条 fact 命中 kind=%s，本次显示第 %d–%d 条"
          % (total, args.kind or "全部", offset + 1 if shown else 0, offset + len(shown)))
    return OK


def build_parser():
    parser = argparse.ArgumentParser(prog="glossa", description="笺疏 Glossa：把任意代码仓库解析成事实台账与讲解页。")
    sub = parser.add_subparsers(dest="command", required=True)
    _common(sub.add_parser("analyze", help="扫一遍仓库，写 repo.json（11 个顶层键的事实台账）"))
    explain = _common(sub.add_parser("explain", help="生成单文件离线讲解页 explain.html"))
    explain.add_argument("--llm", action="store_true",
                         help="用模型写讲解；后端不可用时 exit 4，绝不静默降级")
    facts_cmd = sub.add_parser("facts", help="按 kind 打印事实台账（可分页）")
    facts_cmd.add_argument("--repo", required=True, help="仓库根目录")
    facts_cmd.add_argument("--kind", choices=_KINDS, help="只显示这一类 fact")
    facts_cmd.add_argument("--offset", type=int, default=0, help="跳过前 N 条")
    facts_cmd.add_argument("--limit", type=int, help="最多显示 N 条")
    return parser


def _common(parser):
    parser.add_argument("--repo", required=True, help="仓库根目录")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--force", action="store_true", help="允许覆盖已存在的 repo.json / explain.html")
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
    return _cmd_facts(args)
