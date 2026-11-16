"""事实文本：同 id 多来源的合并句与源码摘录（T6 修复轮 3，R426/R435）。

R398 M4：同 id 多来源时列首条 + 最多两条另见，其余按总数披露「等 N 处」。
R426：numbers 必须 ⊆ text 的数字——只收 text 里真展示的那几条来源行号；「等 N 处」的 N 出现在
text 里但不必进 numbers（机器可读通道不许带没有文本支撑的数字，否则页面会画出假锚点）。
R398 M1：摘录超过 EXCERPT_CHARS 要截断并标「…（已截断，原文共 N 字符）」。
R398 M2：行区间先 min/max 再钳到文件行数内，绝不造反向 id；取不到原文就不产 fact:source。
"""

from __future__ import annotations

import pathlib

from glossa import facts_io

EXCERPT_CHARS = 120

def merge_text(head: str, extras: list[str], total: int) -> str:
    """首条 text + 最多两条另见（共列 3 处）；更多按总数披露（R398 M4）。

    total 是**来源总数**，不是已展示条数：>3 处时尾句写「等 N 处」的 N 就是它。
    """
    shown = extras[:2]
    tail = f" 等 {total} 处。" if total > 3 else "。"
    return f"{head.rstrip('。')}。另见：{'、'.join(shown)}{tail}"

def merge_into(row: dict, slot: dict, numbers, source: str) -> None:
    """同 id 多来源：text 与 numbers 一起重算，只保留真被展示的来源（R426）。"""
    if source not in [label for label, _nums in slot["items"]]:
        slot["items"].append((source, facts_io.numbers_of(numbers)))
    shown, total = slot["items"][:2], len(slot["items"]) + 1
    text = merge_text(slot["head"], [label for label, _nums in shown], total)
    visible = slot["head_numbers"] + [n for label, nums in shown for n in nums if str(n) in label]
    row["text"] = text
    row["numbers"] = facts_io.numbers_of([n for n in visible if str(n) in text])

def source_facts(files: list[dict], repo_root, degraded: list[dict]) -> list[tuple[str, list, str]]:
    """R294：按符号行区间摘原文，返回 (fact id, numbers, text)；坏区间钳位、取不到只记降级。"""
    root, cache, out = pathlib.Path(repo_root), {}, []
    for row in files:
        symbols = row.get("symbols") or []
        if not symbols:
            continue
        rel = row["path"]
        for sym in symbols:
            line, end = sym.get("line") or 1, sym.get("end_line")
            edge = line if end is None else end
            low, high, total, excerpt = facts_io.source_span(root / rel, line, end, cache)
            if not excerpt:                            # 取不到原文 → 不产 fact，只记降级
                facts_io.degrade(degraded, "facts:source",
                                 f"符号 {sym.get('name')} 的行区间 {line}–{edge} 与文件行数 {total} 不符，未摘原文")
                continue
            numbers, text = [low, high], f"{rel} 第 {low}–{high} 行原文：{excerpt}"
            if len(excerpt) > EXCERPT_CHARS:           # M1：截断必须标出来
                numbers.append(len(excerpt))
                text = (f"{rel} 第 {low}–{high} 行原文：{excerpt[:EXCERPT_CHARS]}"
                        f"…（已截断，原文共 {len(excerpt)} 字符）")
            if (low, high) != tuple(sorted((int(line), int(edge)))):
                text += f"（行区间 {line}–{edge} 已钳到文件 {total} 行内）"
            if end is None:
                text += "（只摘录了声明行）"
            out.append((f"fact:source:{rel}:{low}-{high}", numbers, text))
    return out
