"""TS/JS 近似解析：掩码 + 正则（T4，parse='approx'）。

R281：所有正则都只在 masks.mask_source 的 masked 上跑，注释/字符串里的假 import 与
假 export 已被空格化；specifier 用 masks.string_at 回原文取——掩码换掉的是字符不是
位置，所以两边下标可以互认。
R278：import 的 line = 语句起始行（match.start() 之前的换行数 + 1），不是 from 所在行。
R298：只抓带 export 关键字的符号；let/var 归 kind='const'（页面只区分「导出常量」，
      不区分可变性，页面用不到的差异不编造）。嵌套符号不建父子关系（approx）。
R355：builtin 只认 `node:` 前缀，裸名一律 external——不自建 Node 内置名单。
      局限：import fs from "fs" 这类无前缀的 Node 内置会被归 external（不猜）。
R285 非目标：不抓 export ... from 的 re-export、不追 re-export 链、不解析 JSX 内部、
      不做类型推断、不解析模板字符串里的 ${}。
已知局限（如实声明）：
- 动态 import 只认字面量（import("./x")），变量/拼接的抓不到；
- import type 记 type_only=True；import { type X } 剥掉名字前缀，整条名字全带 type
  前缀时也记 True（混入值导入则 False）；两种写法都照常解析（R284）；
- 命名空间导入记 names=['*']；side-effect import（import "./x"）names=[]；
- doc_first_line 恒 None：JSDoc 未解析（approx 的诚实边界）；
- 花括号不配对只记 degraded，不猜缺失的那一半。
"""

from __future__ import annotations

import re

from glossa.lang import masks

_STATIC = re.compile(r"\bimport\s+(type\s+)?([^;'\"]*?)\bfrom\s*(['\"])")
_SIDE = re.compile(r"\bimport\s*(['\"])")
_DYNAMIC = re.compile(r"\bimport\s*\(\s*(['\"])")
_EXPORT = re.compile(
    r"\bexport\s+(?:default\s+)?(async\s+)?"
    r"(function|class|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)")
_NAME = re.compile(r"[A-Za-z_$][\w$]*")


def _line(masked: str, pos: int) -> int:
    """R278：语句起始行 = 前面的换行数 + 1。"""
    return masked.count("\n", 0, pos) + 1


def _one(part: str) -> tuple[str, bool]:
    """单个导入名：剥 type/typeof 前缀与 as 别名，返回 (名字, 是否带 type 前缀)。"""
    piece = part.strip()
    typed = piece.startswith("type ")
    if typed:
        piece = piece[5:].strip()
    if " as " in piece:
        piece = piece.split(" as ", 1)[0].strip()
    return (piece if _NAME.fullmatch(piece) else ""), typed


def _names(clause: str) -> tuple[list[str], bool]:
    """切出 names 与「是否全部是 type 前缀」；default 记 ['default']，命名空间记 ['*']。"""
    text = clause.strip()
    names: list[str] = []
    typed = total = 0
    brace = text.find("{")
    head = text[:brace] if brace >= 0 else text
    if brace >= 0:
        inner = text[brace + 1:]
        inner = inner[:inner.rfind("}")] if "}" in inner else inner
        for part in inner.split(","):
            name, is_type = _one(part)
            if name:
                names.append(name)
                total += 1
                typed += 1 if is_type else 0
    for piece in head.split(","):
        piece = piece.strip()
        if piece:
            names.append("*" if piece.startswith("*") else "default")
    return names, bool(total) and typed == total


def _imports(text: str, masked: str, spans: list[tuple[int, int]]) -> list[dict]:
    """三种形态：静态 import ... from、side-effect（无 from）、动态 import(...) 字面量。"""
    found: list[tuple[int, dict]] = []
    for match in _STATIC.finditer(masked):
        spec = masks.string_at(text, spans, match.end(3) - 1)
        if spec is None:
            continue
        names, all_typed = _names(match.group(2))
        found.append((match.start(), {
            "specifier": spec, "line": _line(masked, match.start()),
            "type_only": bool(match.group(1)) or all_typed,
            "dynamic": False, "names": names}))
    for match in _SIDE.finditer(masked):
        spec = masks.string_at(text, spans, match.end(1) - 1)
        if spec is not None:
            found.append((match.start(), {
                "specifier": spec, "line": _line(masked, match.start()),
                "type_only": False, "dynamic": False, "names": []}))
    for match in _DYNAMIC.finditer(masked):
        spec = masks.string_at(text, spans, match.end(1) - 1)
        if spec is not None:
            found.append((match.start(), {
                "specifier": spec, "line": _line(masked, match.start()),
                "type_only": False, "dynamic": True, "names": []}))
    found.sort(key=lambda pair: pair[0])
    return [row for _, row in found]


def _symbols(masked: str) -> list[dict]:
    """R298：只认带 export 关键字的符号；let/var 归 const。"""
    out: list[dict] = []
    for match in _EXPORT.finditer(masked):
        keyword = match.group(2)
        kind = "async_function" if keyword == "function" and match.group(1) else keyword
        out.append({"name": match.group(3),
                    "kind": "const" if kind in ("let", "var") else kind,
                    "line": _line(masked, match.start()),
                    "end_line": None, "parent": None, "doc_first_line": None})
    return out


def _degraded(masked: str) -> list[str]:
    """括号不配对只如实降级（GC32），不猜缺失的一半。"""
    if masked.count("{") != masked.count("}"):
        return ["花括号不配对：部分 export/import 可能漏抓（注释与字符串内的不算）"]
    return []


def parse_source(text: str, relpath: str) -> dict:
    """近似解析一份 TS/JS 源码；relpath 只用于调用方对齐，本函数不读盘。"""
    masked, spans = masks.mask_source(text)
    return {"symbols": _symbols(masked), "imports": _imports(text, masked, spans),
            "doc_first_line": None, "main_guard": False, "parse": "approx",
            "degraded": _degraded(masked)}
