"""A4 四道闸（gates.py）：安全、溯源、连线、体积。

四道闸都只做「判断 + 记账」，不替上层决定 exit，也不删证据：
- 安全闸直接调 guard.sanitize_html（R307/R419/R420 的口径只有一份真源）；R506 的
  strip_style 由 AI 版传 True 剥内联 style，程序版保持 R420 冻结的「style 属性放行」；
- 溯源闸只标记不删（R308），数字原样保留；R507：**空集只有 program=True 才放行**——
  程序版未溯源数恒为 0（R309/R314），AI 版空集意味着「一个数字都不可溯源」，全部标黄；
- 连线闸直接复用 patterns.validate_figure：出处对不上的边丢进 notes，绝不画；
- 标签闸（R508）：图节点 label 必须是这一节素材里查得到的人话，查不到整张图丢弃；
- 体积闸超限只回 True，截断与否由上层决定（R317：不截断、写盘前抛）。

gate_edges 把「允许的 (from, to) 对」包成一条合成事实再交给 validate_figure，节点上限、
重复 id、未知范式、方向核对全部沿用 A2 的同一份实现，不另造一套真源。
"""

from __future__ import annotations

from papertrace.constants import HTML_MAX_BYTES
from glossa.explain import guard, patterns

MAX_PAGE_BYTES = HTML_MAX_BYTES
_ALLOWED = "fact:gates:allowed"


def gate_html(html: str, *, strip_style: bool = False) -> tuple[str, list[str]]:
    """安全闸：返回 (干净 html, notes)；removed 数并进 notes。R506：AI 版连内联 style 一起剥。"""
    clean, removed, notes = guard.sanitize_html(html, strip_style=strip_style)
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


def gate_numbers(html: str, allowed: set[str], *, program: bool = False) -> tuple[str, int]:
    """溯源闸：不在 allowed 里的数字包 mark.untraced 并计数；R507：空集只有程序版放行。"""
    numbers = _numeric(allowed)
    if not numbers and program:          # R309/R314：程序版没有「模型编的数字」这一说
        return html, 0
    return guard.mark_untraced(html, numbers)


def _pack_text(pack: dict) -> str:
    """R508：这一节素材里模型看得见的文字，拼成一段用来查节点 label 出处的文本。"""
    pack = pack or {}
    rows = [pack.get("repo") or {}, pack.get("section") or {}]
    parts = [str(row.get(key) or "") for row in rows for key in ("root_name", "title", "goal")]
    for fact in pack.get("facts") or ():
        if not isinstance(fact, dict):
            continue
        parts.append(str(fact.get("text") or ""))
        for edge in fact.get("edges") or ():
            if isinstance(edge, dict):
                parts.extend((str(edge.get("from") or ""), str(edge.get("to") or "")))
    for src in pack.get("sources") or ():
        if isinstance(src, dict):
            parts.extend((str(src.get("path") or ""), str(src.get("text") or "")))
    return "\n".join(parts).casefold()


def gate_labels(fig: dict, pack: dict) -> tuple[dict | None, list[str]]:
    """R508：节点 label 必须是素材里查得到的人话；有一条查不到就整张图丢弃并披露。"""
    haystack = _pack_text(pack)
    bad = []
    for node in (fig or {}).get("nodes") or ():
        if not isinstance(node, dict):
            continue
        label = str(node.get("label") or node.get("id") or "").strip()
        if not label or label.startswith("fact:") or label.casefold() not in haystack:
            bad.append(label)
    if not bad:
        return fig, []
    # 披露里不回声模型原话：编出来的 label 一个字都不许借 notes 再上一次页。
    return None, ["图里有 %d 个节点 label 在这一节的素材里查不到（不是人话或没有出处），"
                  "整张图已丢弃（R508）" % len(bad)]


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
