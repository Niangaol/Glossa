"""C# 成员/基类判定的辅助函数（T5 修复轮 1 从 csharp.py 拆出，守 GC1 的 ≤200 行）。

R381：where 泛型约束**先整段剥掉**再找基类冒号 —— bases 只许类型名，绝不许
      class / struct / new() / notnull 这类约束关键字。
R383/R384：方法判定允许 rest 以 '<'（泛型参数列表）开头再跟 '('；行尾判据加 '}'
      （一行方法体 public void A() { }）；属性还认 Allman 形态（声明行 + 下一非空行以 '{' 开头）。
R385：event→field、required→property、索引器→property/name 'this'、元组返回→method、
      implicit/explicit operator（及运算符重载）→method/name 'operator'。
认不出的声明返回 None —— 调用方必须记 degraded（GC31：不静默省略）。
"""

from __future__ import annotations

import re

MODS = (r"(?:(?:public|internal|private|protected|static|abstract|sealed|partial|file"
        r"|readonly|unsafe|extern|virtual|override|new|async|const|volatile|ref|event"
        r"|required)\s+)*")
_RET = r"(?:[A-Za-z_][\w.]*|\([^()]*\)|<[^<>]*(?:<[^<>]*>[^<>]*)*>|[\?\[\],])+"
TYPE_DECL = re.compile(r"^\s*(?P<mods>" + MODS + r")"
                       r"(?P<kw>class|interface|record|struct|enum)"
                       r"\s+(?:(?:struct|class)\s+)?(?P<name>[A-Za-z_]\w*)")
DECL = re.compile(r"^\s*(?P<mods>" + MODS + r")(?P<ret>" + _RET
                  + r")\s+(?P<name>[A-Za-z_]\w*)(?P<rest>.*)$")
_CONV = re.compile(r"^\s*(?P<mods>" + MODS + r")(?:implicit|explicit)\s+operator\b")
_OVERLOAD = re.compile(r"^\s*(?P<mods>" + MODS + r")[\w.<>,?\[\]]+\s+operator\s*[^\w\s]")
_PROP_OPEN = re.compile(r"\{\s*(?:get|set|init)\b")


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
    mods = hit.group("mods")
    name = hit.group("name")
    rest = hit.group("rest").lstrip()
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
