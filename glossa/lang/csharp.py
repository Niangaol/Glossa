"""C# 近似解析：掩码 + 逐行扫（T5，parse='approx'）。

R286：掩码**复用** T4 的 masks.mask_source，绝不另写一套（两套掩码必然漂移，S2 的教训）。
      它的已知边界照抄：verbatim 字符串 @"…" 里的 "" 按普通字符串处理、可能提前结束，所以
      命中 @" 时记 degraded；$"…{expr}…" 的花括号内代码不解析（README 局限）。
R287：namespace 两形态（file-scoped 的 ';'、块级 '{'）都认；一个文件多个 namespace 只取
      第一个 + degraded。实测 Pokemon.cs 是 file-scoped（行 3）、MainViewModel.cs 是块级（行 5）。
R288：符号判据（防止把方法调用当声明）：成员只在「类型体层」认（depth == 当前类型体深度）。
R381–R385（修复轮 1）：泛型约束绝不许写成基类（先剥 where）；attribute 只贴**紧邻的下一行
      声明**（目标前缀 assembly:/module:/return:/param:、空行、语句、更深花括号一律整批丢弃）；
      泛型方法、一行方法体、Allman 属性、event/required/索引器/元组返回/operator 都要认；
      认不出的声明形态记 degraded「C# 声明形态第一版未解析」（GC31：宁可说没解析，不许静默省略）。
为什么逐行扫 + 深度栈、而不是全文正则：块级 namespace 的 '}' 与类的 '}' 必须分开数——
全文正则既会跨行误匹配，行号也会静默漂移（掩码等长那条硬不变量就是为行号而设的）。
已知局限（如实声明，不假装支持）：
- 构造器（public Foo()）不记符号，但会记 degraded（不静默省略，GC31）；
- 嵌套类型只记最近一层 parent；局部变量与局部函数不记（它们不在类型体层）；
- record 的位置参数列表不拆成符号（R288）。
"""

from __future__ import annotations

import re

from glossa.lang import masks
from glossa.lang.csharp_members import (DECL, TYPE_DECL, bases, member,
                                        next_body, row)

_USING = re.compile(r"^\s*(?:global\s+)?using\s+(?:(?P<static>static)\s+)?"
                    r"(?:(?P<alias>[A-Za-z_]\w*)\s*=\s*)?(?P<spec>[\w.]+)\s*;\s*$")
_NS_SEMI = re.compile(r"^\s*namespace\s+(?P<name>[\w.]+)\s*;\s*$")
_NS_BLOCK = re.compile(r"^\s*namespace\s+(?P<name>[\w.]+)\s*\{?\s*$")
_ATTR = re.compile(r"^\s*\[(?P<body>[^\[\]]*)\]")
_TARGETS = frozenset(("assembly", "module", "return", "param"))   # R382：整条丢
_UNSUPPORTED = frozenset(("field", "event", "method", "property", "type",
                          "typevar"))                       # R402：丢但记 degraded


def _prefix_note(head: str, relpath: str) -> str:
    return "attribute 目标前缀 %s 第一版未贴到符号（%s）" % (head, relpath)


def _attr_names(body: str, relpath: str, degraded: list[str]) -> list[str]:
    """'[A]'、'[A, B]' → 名字列表。

    R401：目标前缀**先按整条体判、再按逗号切**。旧版先切后判，只丢第一项，
          [assembly: V("1.0.0.0"), CLSCompliant(true)] 会漏出 CLSCompliant。
    R382：assembly:/module:/return:/param: 整条丢弃，不记 degraded（口径不变）。
    R402：field:/event:/method:/property:/type:/typevar: 第一版仍不实现，但**不许
          静默**——每个命中记一条 degraded（attribute 在声明之前解析，拿不到符号名，
          所以填文件）。
    """
    head = body.split(":", 1)[0].strip()
    if head in _TARGETS:                       # R401：命中就整条丢，不再切逗号
        return []
    if head in _UNSUPPORTED:                   # R402：整条丢，但如实降级
        degraded.append(_prefix_note(head, relpath))
        return []
    out: list[str] = []
    for part in body.split(","):
        piece = part.strip()
        if ":" in piece:
            part_head = piece.split(":", 1)[0].strip()
            if part_head in _TARGETS:          # 混写体里的目标前缀分项整项丢
                continue
            if part_head in _UNSUPPORTED:      # 混写体里的不支持分项同样不许静默
                degraded.append(_prefix_note(part_head, relpath))
                continue
            piece = piece.split(":", 1)[1].strip()
        hit = re.match(r"[A-Za-z_][\w.]*", piece)
        if hit is not None:
            out.append(hit.group(0).rsplit(".", 1)[-1])
    return out


def _namespace(namespaces: list[dict], name: str, idx: int, style: str,
               degraded: list[str]) -> None:
    """R287：多个 namespace 只取第一个，并如实降级（不装作只有一个）。"""
    if namespaces:
        note = "多个 namespace 只取第一个：" + namespaces[0]["name"]
        if note not in degraded:
            degraded.append(note)
        return
    namespaces.append({"name": name, "line": idx, "style": style})


def parse_source(text: str, relpath: str) -> dict:
    """近似解析一份 C# 源码；relpath 只用于调用方对齐，本函数不读盘。"""
    masked, _spans = masks.mask_source(text)
    lines = masked.split("\n")
    symbols: list[dict] = []
    imports: list[dict] = []
    namespaces: list[dict] = []
    degraded: list[str] = []
    depth = 0
    stack: list[tuple[str, int]] = []          # (类型名, 类型体所在的 depth)
    pending: str | None = None                 # 已声明、等 '{' 的类型
    held: list[str] = []                       # 上一行攒下的 attribute（只贴紧邻下一行）
    held_depth = 0
    for idx, raw in enumerate(lines, 1):
        line = raw
        fresh: list[str] = []
        while True:                            # 行首 attribute 剥掉再认声明
            hit = _ATTR.match(line)
            if hit is None:
                break
            fresh.extend(_attr_names(hit.group("body"), relpath, degraded))
            line = line[hit.end():]
        body = line.strip()
        attrs = held if held and depth == held_depth else []
        held = []
        if fresh and not body:                 # 纯 attribute 行：只等紧邻的下一行声明
            held, held_depth = attrs + fresh, depth
        else:
            attrs += fresh
        if body:
            parent = stack[-1][0] if stack else None
            ns = namespaces[0]["name"] if namespaces else None
            declared = TYPE_DECL.match(line)
            semi = _NS_SEMI.match(line)
            block = None if semi else _NS_BLOCK.match(line)
            if declared is not None:
                symbols.append(row(declared.group("name"), declared.group("kw"), idx, ns,
                                   attrs, parent, declared.group("mods"),
                                   bases(declared.group("kw"), line[declared.end():])))
                inline = "{" in line and line.count("{") == line.count("}")
                pending = None if inline else declared.group("name")
            elif semi is not None or block is not None:
                hit = semi or block
                _namespace(namespaces, hit.group("name"), idx,
                           "file_scoped" if semi is not None else "block", degraded)
            elif (used := _USING.match(line)) is not None:
                imports.append({"specifier": used.group("spec"), "line": idx,
                                "static": bool(used.group("static")),
                                "alias": used.group("alias")})
            elif stack and depth == stack[-1][1]:
                got = member(line, idx, ns, attrs, parent, next_body(lines, idx))
                if got is not None:
                    symbols.append(got)
                elif DECL.match(line) is not None:
                    degraded.append("C# 声明形态第一版未解析：%s（行号 %d）"
                                    % (body[:40], idx))
        for ch in line:
            if ch == "{":
                depth += 1
                if pending is not None:
                    stack.append((pending, depth))
                    pending = None
            elif ch == "}":
                if stack and stack[-1][1] == depth:
                    stack.pop()
                depth = max(depth - 1, 0)
    if '@"' in masked:
        degraded.append('verbatim 字符串按近似处理："" 转义可能提前结束掩码')
    if masked.count("{") != masked.count("}"):
        degraded.append("花括号不配对，存在未闭合的花括号：类型体与 namespace 作用域可能判断不准")
    return {"symbols": symbols, "imports": imports, "namespaces": namespaces,
            "doc_first_line": None, "main_guard": False, "parse": "approx",
            "degraded": degraded}
