"""A4 四道闸（gates.py）：安全、溯源、连线、体积。

四道闸都只做「判断 + 记账」，不替上层决定 exit，也不删证据：
- 安全闸直接调 guard.sanitize_html（R307/R419/R420 的口径只有一份真源）；
- 溯源闸只标记不删（R308），数字原样保留；**空集是程序版的约定**——R309/R314 要求
  程序版未溯源数恒为 0，组件自产的数字不送进这道闸，所以空集直接放行并计 0；
- 连线闸直接复用 patterns.validate_figure：出处对不上的边丢进 notes，绝不画；
- 体积闸超限只回 True，截断与否由上层决定（R317：不截断、写盘前抛）。

gate_edges 把「允许的 (from, to) 对」包成一条合成事实再交给 validate_figure，节点上限、
重复 id、未知范式、方向核对全部沿用 A2 的同一份实现，不另造一套真源。
"""

from __future__ import annotations

from glossa.explain import guard, patterns

MAX_PAGE_BYTES = 2_000_000
_ALLOWED = "fact:gates:allowed"


def gate_html(html: str) -> tuple[str, list[str]]:
    """安全闸：返回 (干净 html, notes)；removed 数并进 notes，页面能照实披露。"""
    clean, removed, notes = guard.sanitize_html(html)
    if removed:
        notes = ["本块已移除 %d 处不允许的构造（R307）" % removed] + notes
    return clean, notes


def _numeric(allowed) -> set:
    """台账里的数字可能是 int，也可能是 "29,856"/"50%" 这种字符串写法；两种都认。"""
    out = set()
    for item in allowed or ():
        if item is None or isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            out.add(item)
            continue
        token = str(item).strip().replace(",", "").rstrip("%")
        try:
            out.add(int(token))
            continue
        except ValueError:
            pass
        try:
            out.add(float(token))
        except ValueError:
            continue
    return out


def gate_numbers(html: str, allowed: set[str]) -> tuple[str, int]:
    """溯源闸：不在 allowed 里的数字包 mark.untraced 并计数；空集=程序版，计 0。"""
    numbers = _numeric(allowed)
    if not numbers:                      # R309/R314：程序版没有「模型编的数字」这一说
        return html, 0
    return guard.mark_untraced(html, numbers)


def gate_edges(fig: dict, allowed: set[tuple[str, str]]) -> tuple[dict, list[str]]:
    """连线闸：只有 (from, to) 在 allowed 里、节点也合法的边才画；丢的边逐条进 notes。"""
    pairs = [{"from": src, "to": dst, "kind": "allowed"}
             for src, dst in sorted((str(a), str(b)) for a, b in allowed or ())]
    doc = {"facts": {_ALLOWED: {"text": "连线闸允许的边", "numbers": [], "edges": pairs}}}
    probe = dict(fig or {})
    rows = []
    for pos, edge in enumerate((fig or {}).get("edges") or ()):
        if not isinstance(edge, dict):
            rows.append(edge)            # 让 validate_figure 自己响亮报错
            continue
        row = dict(edge, fact=_ALLOWED, _gate_pos=pos)
        rows.append(row)
    probe["edges"] = rows
    clean, _dropped, notes = patterns.validate_figure(doc, probe)
    source = list((fig or {}).get("edges") or ())
    for edge in clean["edges"]:
        pos = int(edge.pop("_gate_pos", 0))
        edge["fact"] = source[pos].get("fact") if pos < len(source) else None
    return clean, notes


def gate_size(html: str) -> tuple[str, bool]:
    """体积闸：按 UTF-8 真实字节算；超限只报 True，不截断（R317）。"""
    return html, len(html.encode("utf-8")) > MAX_PAGE_BYTES
