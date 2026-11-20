"""facts 子命令与「--repo → doc」闸门（T10；R452 从 cli.py 拆出——那边已到 200 行上限）。

这里放仓库到事实台账的唯一入口：analyze / explain / facts 共用同一份「路径不对 exit 5、
扫描失败 exit 2」的文案；facts 的 stdout 与拆分前逐字相同（既有 6 条 CLI 测试锁着）。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from glossa import facts as facts_mod, schema_repo
from papertrace.api import BuildError, TraceSchemaError
from papertrace.api import UNIMPLEMENTED, UNTRACEABLE

KINDS = ("file", "pkg", "project", "entry", "import", "symbol", "namespace",
         "graph", "excluded", "degraded", "source", "totals", "bonus")
BUILD_FAIL = UNIMPLEMENTED          # 2：扫描或组装失败（BuildError）
NO_REPO = UNTRACEABLE               # 5：--repo 不存在或不是目录
LEDGER = "repo.json"                # R487：explain 默认复用 --out/repo.json
SCHEMA_FAIL = 1                     # 1：台账读不进来 / 过不了 schema（绝不静默回落重扫）


def positive_int(text):
    """--limit：正整数；非法值交给 argparse 以 2 退出（R460：不静默夹取）。"""
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("--limit 必须是 ≥1 的整数，收到 %r" % text)
    return value


def non_negative_int(text):
    """--offset：非负整数；同上（R460）。"""
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("--offset 必须是 ≥0 的整数，收到 %r" % text)
    return value


def fail(code, message):
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


def doc_or_exit(args):
    """(doc, 退出码)：路径不对 → 5；扫描/组装失败 → 2。"""
    root = pathlib.Path(args.repo).resolve()     # R470：--repo . 与绝对路径必须得到同一本台账
    if not root.is_dir():
        return None, fail(NO_REPO, "glossa：仓库根目录不存在或不是目录：%s" % root)
    try:
        kw = {"max_files": getattr(args, "max_files", 20_000),
              "use_default_excludes": not getattr(args, "no_default_excludes", False),
              "bonus": _bonus(getattr(args, "bonus_trace", None))}
        return facts_mod.build_repo_doc(root, **kw), 0
    except BuildError as exc:
        return None, fail(BUILD_FAIL, "glossa %s：%s" % (args.command, exc))


def ledger_or_exit(args):
    """R487：(doc, 退出码, 是否本次重扫)。台账存在且没 --force 就复用它，缺失才重扫。

    读入失败（JSON 坏 / 过不了 schema）一律 exit 1 并把原文写 stderr：静默回落重扫会让
    页面与它旁边那本台账各说一个数（评审 I2 的 228299 vs 226158 就是这么来的）。
    """
    path = pathlib.Path(args.out) / LEDGER
    if path.is_file() and not getattr(args, "force", False):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            schema_repo.validate_repo(doc)
        except (OSError, ValueError, TraceSchemaError) as exc:
            print("glossa explain：读不了 %s（JSON 或 schema 不合法）：%s" % (path, exc),
                  file=sys.stderr)
            return None, SCHEMA_FAIL, False
        return doc, 0, False
    doc, code = doc_or_exit(args)
    return doc, code, True


def _pick(doc, kind):
    """按 kind 的 fact id 前缀筛（kind 为空 = 全部），返回升序 id 列表。"""
    rows = doc.get("facts") or {}
    if not kind:
        return sorted(rows)
    prefix = "fact:" + kind
    return sorted(fid for fid in rows if fid == prefix or fid.startswith(prefix + ":"))


def run(args):
    """facts：逐条打印「id  [numbers]  text」，末尾一行「共 N 条…第 A–B 条」。"""
    doc, code = doc_or_exit(args)
    if doc is None:
        return code
    rows = doc.get("facts") or {}
    picked = _pick(doc, args.kind)
    total, offset = len(picked), args.offset or 0
    stop = offset + (args.limit if args.limit is not None else total)
    shown = picked[offset:stop]
    for fid in shown:
        row = rows[fid]
        numbers = ",".join(str(n) for n in row.get("numbers") or [])
        print("%s  [%s]  %s" % (fid, numbers, row.get("text") or ""))
    if not shown:                       # R460：offset 超出总数时不许写「第 0–999 条」
        print("共 %d 条 fact 命中 kind=%s，本次显示 0 条（offset 超出共 %d 条）"
              % (total, args.kind or "全部", total))
    else:
        print("共 %d 条 fact 命中 kind=%s，本次显示第 %d–%d 条"
              % (total, args.kind or "全部", offset + 1, min(offset + len(shown), total)))
    return 0
