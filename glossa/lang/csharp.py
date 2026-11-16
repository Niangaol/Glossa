"""C# 近似解析：掩码 + 逐行扫（T5，parse='approx'）。

R286：掩码**复用** T4 的 masks.mask_source，绝不另写一套（两套掩码必然漂移，S2 的教训）。
      它的已知边界照抄：verbatim 字符串 @"…" 里的 "" 按普通字符串处理、可能提前结束，所以
      命中 @" 时记 degraded；$"…{expr}…" 的花括号内代码不解析（README 局限）。
R287：namespace 两形态（file-scoped 的 ';'、块级 '{'）都认；一个文件多个 namespace 只取
      第一个 + degraded。实测 Pokemon.cs 是 file-scoped（行 3）、MainViewModel.cs 是块级（行 5）。
R288：符号判据（防止把方法调用当声明）：成员只在「类型体层」认（depth == 当前类型体深度），
      方法要求名字后紧跟 '(' 且行尾是 '{' 或 ';' 或下一非空行是 '{'；属性要求名字后是
      '{ get' / '{ set' / '{ init' / '=>'；字段要求名字后是 ';' 或 '='（因而没有 '(' 也没有 '{'）；
      attribute 记到**紧随其后的那个符号**（实测 ObservableProperty 行 7 → MainViewModel 行 8）。
为什么逐行扫 + 深度栈、而不是全文正则：块级 namespace 的 '}' 与类的 '}' 必须分开数——
全文正则既会跨行误匹配，行号也会静默漂移（掩码等长那条硬不变量就是为行号而设的）。
已知局限（如实声明，不假装支持）：
- 构造器（public Foo()）没有返回类型段，本版不记符号；
- 嵌套类型只记最近一层 parent；局部变量与局部函数不记（它们不在类型体层）；
- where 泛型约束整段丢弃；record 的位置参数列表不拆成符号（R288）。
"""

from __future__ import annotations

import re

from glossa.lang import masks

_MODS = (r"(?:(?:public|internal|private|protected|static|abstract|sealed|partial|file"
         r"|readonly|unsafe|extern|virtual|override|new|async|const|volatile|ref)\s+)*")
_TYPE = re.compile(r"^\s*(?P<mods>" + _MODS + r")(?P<kw>class|interface|record|struct|enum)"
                   r"\s+(?:(?:struct|class)\s+)?(?P<name>[A-Za-z_]\w*)")
_DECL = re.compile(r"^\s*(?P<mods>" + _MODS + r")(?P<ret>[\w.<>,?\[\]]+)\s+(?P<name>[A-Za-z_]\w*)"
                   r"(?P<rest>.*)$")
_USING = re.compile(r"^\s*(?:global\s+)?using\s+(?:(?P<static>static)\s+)?"
                    r"(?:(?P<alias>[A-Za-z_]\w*)\s*=\s*)?(?P<spec>[\w.]+)\s*;\s*$")
_NS_SEMI = re.compile(r"^\s*namespace\s+(?P<name>[\w.]+)\s*;\s*$")
_NS_BLOCK = re.compile(r"^\s*namespace\s+(?P<name>[\w.]+)\s*\{?\s*$")
_ATTR = re.compile(r"^\s*\[(?P<body>[^\[\]]*)\]")
_PROP_OPEN = r"\{\s*(?:get|set|init)\b"


def _attr_names(body: str) -> list[str]:
    """'[A]'、'[A, B]'、'[assembly: A(...)]' → 名字列表（剥命名空间前缀与参数）。"""
    out: list[str] = []
    for part in body.split(","):
        piece = part.strip()
        if ":" in piece:                       # [assembly: X] / [return: X]
            piece = piece.split(":", 1)[1].strip()
        hit = re.match(r"[A-Za-z_][\w.]*", piece)
        if hit is not None:
            out.append(hit.group(0).rsplit(".", 1)[-1])
    return out


def _bases(kw: str, rest: str) -> list[str]:
    """class/record 名后 ':' 到 '{' / ';' / where 之间的基类与接口；剥泛型参数（近似）。"""
    if kw not in ("class", "record") or ":" not in rest:
        return []
    seg = re.split(r"\{|;|\bwhere\b", rest.split(":", 1)[1])[0]
    out: list[str] = []
    for part in seg.split(","):
        piece = part.split("<", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_][\w.]*", piece):
            out.append(piece)
    return out


def _next_open(lines: list[str], idx: int) -> bool:
    """R288：方法声明允许把 '{' 放到下一非空行（实测 FindAsync 行 13 → '{' 行 14）。"""
    for raw in lines[idx:]:
        piece = raw.strip()
        if piece:
            return piece.startswith("{")
    return False


def _member(line: str, idx: int, ns: str | None, attrs: list[str],
            parent: str | None, next_open: bool) -> dict | None:
    """类型体层的一行声明 → method / property / field；认不出就 None（不猜）。"""
    hit = _DECL.match(line)
    if hit is None:
        return None
    mods, name, rest = hit.group("mods"), hit.group("name"), hit.group("rest").lstrip()
    row = {"name": name, "kind": "", "line": idx, "namespace": ns, "partial": False,
           "bases": [], "async": bool(re.search(r"\basync\b", mods)),
           "attributes": list(attrs), "parent": parent}
    if rest.startswith("("):
        if not (line.rstrip().endswith(("{", ";")) or next_open):
            return None                        # R288：调用的样子，不是声明
        row["kind"] = "method"
    elif rest.startswith("=>") or re.match(_PROP_OPEN, rest):
        row["kind"] = "property"
    elif rest.startswith((";", "=")):
        row["kind"] = "field"
    else:
        return None
    return row


def _namespace(namespaces: list[dict], name: str, idx: int, style: str,
               degraded: list[str]) -> None:
    """R287：多个 namespace 只取第一个，并如实降级（不装作只有一个）。"""
    if namespaces:
        note = "多命名空间只取第一个：" + namespaces[0]["name"]
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
    attrs: list[str] = []
    for idx, raw in enumerate(lines, 1):
        line = raw
        while True:                            # 行首 attribute 一律剥掉再认声明
            hit = _ATTR.match(line)
            if hit is None:
                break
            attrs.extend(_attr_names(hit.group("body")))
            line = line[hit.end():]
        if line.strip():
            parent = stack[-1][0] if stack else None
            ns = namespaces[0]["name"] if namespaces else None
            declared = _TYPE.match(line)
            semi = _NS_SEMI.match(line)
            block = None if semi else _NS_BLOCK.match(line)
            if declared is not None:
                symbols.append({"name": declared.group("name"), "kind": declared.group("kw"),
                                "line": idx, "namespace": ns, "async": False,
                                "partial": "partial" in declared.group("mods").split(),
                                "bases": _bases(declared.group("kw"), line[declared.end():]),
                                "attributes": list(attrs), "parent": parent})
                attrs = []
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
                row = _member(line, idx, ns, attrs, parent, _next_open(lines, idx))
                if row is not None:
                    symbols.append(row)
                    attrs = []
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
        degraded.append("花括号不配对：类型体与 namespace 作用域可能判断不准")
    return {"symbols": symbols, "imports": imports, "namespaces": namespaces,
            "doc_first_line": None, "main_guard": False, "parse": "approx",
            "degraded": degraded}
