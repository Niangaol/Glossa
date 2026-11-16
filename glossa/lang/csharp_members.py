r"""C# 成员/基类判定（T5 从 csharp.py 拆出，守 GC1 的 ≤200 行）。

R381：where 泛型约束先整段剥掉再找基类冒号 —— bases 只许类型名，绝不许 class /
      struct / new() / notnull 这类约束关键字。
R383/R384/R385：泛型方法、单行方法体、Allman 属性、event→field、required→property、
      索引器 name=this、元组返回类型、operator 重载都按既有口径认。
认不出的声明返回 None —— 调用方必须记 degraded（GC31：不静默省略）。

R467/R468：DECL 从正则改成过程式扫描（_DeclPattern）。旧 _RET 正则在「构造器参数带
可空/默认值」的行上指数回溯：PokemonData 单行 17.98s、三行 126.92s。扫描器把返回
类型切成互不歧义的 token 再按「最长优先」回退一次，语言与旧正则一致、复杂度 O(行长)。
唯一收窄：类型名尾随点（Foo.）不再算返回类型（C# 里也不是合法类型）。
"""

from __future__ import annotations

import re
from typing import NamedTuple

MODS_LIST = ("public", "internal", "private", "protected", "static", "abstract", "sealed",
             "partial", "file", "readonly", "unsafe", "extern", "virtual", "override",
             "new", "async", "const", "volatile", "ref", "event", "required")
MODS = r"(?:(?:" + "|".join(MODS_LIST) + r")\s+)*"
TYPE_DECL = re.compile(r"^\s*(?P<mods>" + MODS + r")"
                       r"(?P<kw>class|interface|record|struct|enum)"
                       r"\s+(?:(?:struct|class)\s+)?(?P<name>[A-Za-z_]\w*)")

_IDENT = re.compile(r"[A-Za-z_]\w*")
_MODS_RE = re.compile(MODS)
_RET_PUNCT = "?[],"
_CONV = re.compile(r"^\s*(?P<mods>" + MODS + r")(?:implicit|explicit)\s+operator\b")
_OVERLOAD = re.compile(r"^\s*(?P<mods>" + MODS + r")[\w.<>,?\[\]]+\s+operator\s*[^\w\s]")
_PROP_OPEN = re.compile(r"\{\s*(?:get|set|init)\b")


def _ident_end(text: str, start: int) -> int | None:
    """标识符（含点分限定 A.B.C）；尾随点不收（R467）。"""
    hit = _IDENT.match(text, start)
    if hit is None:
        return None
    end = hit.end()
    while end < len(text) and text[end] == ".":
        nxt = _IDENT.match(text, end + 1)
        if nxt is None:
            break
        end = nxt.end()
    return end


def _group_end(text: str, start: int) -> int | None:
    """返回类型里的括号组：单层 ( ... ) 或最多两层的 < ... >（与旧 _RET 同形）。"""
    if text[start] == "(":
        close = text.find(")", start + 1)
        return None if close < 0 or "(" in text[start + 1:close] else close + 1
    depth, pos = 0, start
    while pos < len(text):
        ch = text[pos]
        if ch == "<":
            depth += 1
            if depth > 2:
                return None
        elif ch == ">":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return None

def _ret_ends(text: str, start: int) -> list[int]:
    """返回类型在每个 token 边界上的候选终点（升序；空串不算）。"""
    ends, pos = [], start
    while pos < len(text) and not text[pos].isspace():
        ch = text[pos]
        if ch in _RET_PUNCT:
            nxt: int | None = pos + 1
        elif ch in "(<":
            nxt = _group_end(text, pos)
        else:
            nxt = _ident_end(text, pos)
        if nxt is None:
            break
        pos = nxt
        ends.append(pos)
    return ends

class _Decl(NamedTuple):
    """DECL.match 的返回值：mods/ret/name/rest，对应旧 match 的同名分组。"""

    mods: str
    ret: str
    name: str
    rest: str


class _DeclPattern:
    """R467：DECL 的确定性替身，.match(line) 与 re.Pattern 同名同用法。"""

    def match(self, line: str) -> _Decl | None:
        mods_start = len(line) - len(line.lstrip())
        i = _MODS_RE.match(line, mods_start).end()
        for end in reversed(_ret_ends(line, i)):
            if not line[end:end + 1].isspace():
                continue
            k = end
            while k < len(line) and line[k].isspace():
                k += 1
            name = _IDENT.match(line, k)
            if name is not None:
                return _Decl(line[mods_start:i], line[i:end], name.group(0),
                             line[name.end():])
        return None


DECL = _DeclPattern()


def row(name: str, kind: str, idx: int, ns: str | None, attrs: list[str],
        parent: str | None, mods: str = "",
        got_bases: list[str] | None = None) -> dict:
    """统一符号行形状（字段与旧版逐字一致，schema 不新增 kind）。"""
    return {"name": name, "kind": kind, "line": idx, "namespace": ns,
            "partial": "partial" in mods.split(),
            "bases": list(got_bases or []),
            "async": bool(re.search(r"\basync\b", mods)),
            "attributes": list(attrs), "parent": parent}


def bases(kw: str, rest: str) -> list[str]:
    """class/record 的基类与接口；R381：先剥 where 约束，再找 ':'。"""
    if kw not in ("class", "record"):
        return []
    plain = re.split(r"\bwhere\b", rest, maxsplit=1)[0]
    if ":" not in plain:
        return []
    seg = re.split(r"[{;]", plain.split(":", 1)[1])[0]
    out: list[str] = []
    for part in seg.split(","):
        piece = part.split("<", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_][\w.]*", piece):
            out.append(piece)
    return out


def next_body(lines: list[str], idx: int) -> str | None:
    """R288/R384：下一非空行（Allman 风格判定用）。"""
    for raw in lines[idx:]:
        piece = raw.strip()
        if piece:
            return piece
    return None


def _generic_call(rest: str) -> bool:
    """R383：rest 以泛型参数 '<...>' 开头、紧跟 '(' —— 泛型方法。"""
    if not rest.startswith("<"):
        return False
    depth = 0
    for i, ch in enumerate(rest):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth == 0:
                return rest[i + 1:].lstrip().startswith("(")
    return False


def _closed(line: str, nxt: str | None) -> bool:
    """R384：行尾 '{' / ';' / '}'，或下一非空行是 '{'（Allman）。"""
    return line.rstrip().endswith(("{", ";", "}")) or (nxt or "").startswith("{")


def member(line: str, idx: int, ns: str | None, attrs: list[str],
           parent: str | None, nxt: str | None) -> dict | None:
    """类型体层的一行声明 → 符号行；认不出就 None（调用方记 degraded）。"""
    hit = _CONV.match(line) or _OVERLOAD.match(line)
    if hit is not None:
        if not _closed(line, nxt):
            return None
        return row("operator", "method", idx, ns, attrs, parent, hit.group("mods"))
    hit = DECL.match(line)
    if hit is None:
        return None
    mods, name, rest = hit.mods, hit.name, hit.rest.lstrip()
    if parent is not None and name == parent and (rest.startswith("(")
                                                  or _generic_call(rest)):
        return None                        # 构造器：不记符号（调用方记 degraded）
    if rest.startswith("(") or _generic_call(rest):
        if not _closed(line, nxt):
            return None                    # R288：调用的样子，不是声明
        return row(name, "method", idx, ns, attrs, parent, mods)
    if ((name == "this" and rest.startswith("[")) or rest.startswith("=>")
            or _PROP_OPEN.match(rest)):
        return row(name, "property", idx, ns, attrs, parent, mods)
    if not rest and (nxt or "").startswith("{"):
        return row(name, "property", idx, ns, attrs, parent, mods)
    if rest.startswith((";", "=")):
        return row(name, "field", idx, ns, attrs, parent, mods)
    return None
