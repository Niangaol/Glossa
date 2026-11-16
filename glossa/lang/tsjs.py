"""TS/JS 近似解析：掩码 + 正则（T4，parse='approx'）。

R281：所有正则都只在 masks.mask_source 的 masked 上跑，注释/字符串里的假 import 与
假 export 已被空格化；specifier 用 masks.string_at 回原文取——掩码换掉的是字符不是
位置，所以两边下标可以互认。
R278：import 的 line = 语句起始行（match.start() 之前的换行数 + 1），不是 from 所在行。
R298：只抓带 export 关键字的符号；let/var 归 kind='const'（页面只区分「导出常量」，
      不区分可变性，页面用不到的差异不编造）。嵌套符号不建父子关系（approx）。
R355：builtin 只认 `node:` 前缀，裸名一律 external——不自建 Node 内置名单。
      局限：import fs from "fs" 这类无前缀的 Node 内置会被归 external（不猜）。
R376：export 抓不全是「静默省略」：补抓列表式 `export { a, b as c }`（kind='export_list'
      ——**列表式导出不知原始 kind**）、多声明符（深度 0 的逗号处切，(){}[] 与尖括号都算
      深度）与生成器 `export function*`；其余以 export 开头却未被命中的形态一律记
      degraded（GC31），不静默零产出。
R377：`export const enum Direction` 抓 name='Direction'、kind='enum'（关键字备选最长
      优先，const enum 单独一支），不许产出名为 enum 的符号。
R379：`foo.import("./x")` 是普通方法调用，不是动态 import（前置 . / 标识符字符排除）。
R483：degraded 里给读者看的片段取自**原文**同一行同一偏移（masks.same_span，≤40 字符），
      掩码文本只用于解析与行号——否则字符串内容会显示成一片空格，看不出哪里没解析。
R285 非目标：不抓 export ... from 的 re-export（但记 degraded，不静默）、不追 re-export
      链、不解析 JSX 内部、不做类型推断、不解析模板字符串里的 ${}。
已知局限（如实声明）：
- 动态 import 只认字面量（import("./x")），变量/拼接的抓不到；
- import type 记 type_only=True；import { type X } 剥掉名字前缀，整条名字全带 type
  前缀时也记 True（混入值导入则 False）；两种写法都照常解析（R284）；
- 命名空间导入记 names=['*']；side-effect import（import "./x"）names=[]；
- doc_first_line 恒 None：JSDoc 未解析（approx 的诚实边界）；
- 花括号不配对、字符串/块注释未闭合（R375）、未解析的 export 形态都记 degraded。
"""

from __future__ import annotations

import re

from glossa.lang import masks

_STATIC = re.compile(r"\bimport\s+(type\s+)?([^;'\"]*?)\bfrom\s*(['\"])")
_SIDE = re.compile(r"\bimport\s*(['\"])")
_DYNAMIC = re.compile(r"(?<![\w$.])import\s*\(\s*(['\"])")
_EXPORT = re.compile(
    r"\bexport\s+(?:default\s+)?(async\s+)?"
    r"(const\s+enum|enum|class|interface|type|function|const|let|var)\b\s*"
    r"(\*)?\s*([A-Za-z_$][\w$]*)")
_EXPORT_LIST = re.compile(r"\bexport\s*\{")
_EXPORT_HEAD = re.compile(r"\bexport\b")
_NAME = re.compile(r"[A-Za-z_$][\w$]*")
_KIND = {"const enum": "enum", "let": "const", "var": "const"}
_DECL_KEYWORDS = ("const", "let", "var")
_DEEP, _SHALLOW = "([{<", ")]}>"
_CONT_BEFORE, _CONT_AFTER = ",=+-*/&|?:([{<>", ",=+-*&|?:)]"


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


def _decl_parts(masked: str, start: int) -> list[str]:
    """R376：多声明符在**深度 0** 的逗号处切；(){}[] 与尖括号都算深度（不裸 split）。

    深度 0 的换行按 ASI 结束声明，但逗号/运算符的某一侧算续行（多行声明不切坏）。
    """
    parts: list[str] = []
    depth, begin, i, n = 0, start, start, len(masked)
    while i < n:
        ch = masked[i]
        if ch in _DEEP:
            depth += 1
        elif ch in _SHALLOW:
            depth = max(0, depth - 1)
        elif depth == 0 and (ch == "," or ch == ";"):
            parts.append(masked[begin:i])
            begin = i + 1
            if ch == ";":
                return parts
        elif depth == 0 and ch == "\n" and (
                masked[:i].rstrip()[-1:] not in _CONT_BEFORE
                and masked[i:].lstrip()[:1] not in _CONT_AFTER):
            parts.append(masked[begin:i])
            return parts
        i += 1
    parts.append(masked[begin:i])
    return parts


def _row(name: str, kind: str, line: int) -> dict:
    return {"name": name, "kind": kind, "line": line,
            "end_line": None, "parent": None, "doc_first_line": None}


def _symbols(masked: str, text: str) -> tuple[list[dict], list[str]]:
    """R298/R376：export 符号 + 没解析的 export 形态（degraded），不许静默省略；R483 片段取原文。"""
    out: list[dict] = []
    covered: set[int] = set()
    for match in _EXPORT.finditer(masked):
        covered.add(match.start())
        keyword = re.sub(r"\s+", " ", match.group(2))
        kind = _KIND.get(keyword, keyword)
        if keyword == "function" and match.group(1):
            kind = "async_function"
        line = _line(masked, match.start())
        if keyword in _DECL_KEYWORDS:
            found = (_NAME.match(part.strip())
                     for part in _decl_parts(masked, match.end(2)))
            out.extend(_row(m.group(0), kind, line) for m in found if m)
        else:
            out.append(_row(match.group(4), kind, line))
    for match in _EXPORT_LIST.finditer(masked):
        close = masked.find("}", match.end())
        if close < 0:
            continue                     # 没闭合：交给「未解析」分支记 degraded
        covered.add(match.start())
        for part in masked[match.end():close].split(","):
            name = part.strip().split(" as ")[0].strip()
            if _NAME.fullmatch(name):
                out.append(_row(name, "export_list", _line(masked, match.start())))
    out.sort(key=lambda row: row["line"])
    notes = ["export 形态第一版未解析：%s（行号 %d）" % (
                 masks.same_span(text, h.start()), _line(masked, h.start()))
             for h in _EXPORT_HEAD.finditer(masked) if h.start() not in covered]
    return out, notes


def parse_source(text: str, relpath: str) -> dict:
    """近似解析一份 TS/JS 源码；relpath 只用于调用方对齐，本函数不读盘。"""
    masked, spans, notes = masks.mask_source_notes(text)
    symbols, export_notes = _symbols(masked, text)
    notes += export_notes
    if masked.count("{") != masked.count("}"):       # GC32：不猜缺失的那一半
        notes.append("花括号不配对：部分 export/import 可能漏抓（注释与字符串内的不算）")
    return {"symbols": symbols, "imports": _imports(text, masked, spans),
            "doc_first_line": None, "main_guard": False, "parse": "approx",
            "degraded": notes}
