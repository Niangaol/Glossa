"""S15 回退候选的编排层：结构同构不命中时，让判断题仍然有活干 —— 但绝不发绿线。

裁决逐字见 docs/superpowers/plans/2026-11-15-papertrace-s15-m1b.md。这里只记结论：

- **R112 锁黄线**：回退产出的 anchor，tier 上限 yellow。绿线是「结构对上了」的用户可见承诺，
  回退候选只有算子类型 + 词法排序，没有形状与序列依据，凭什么发绿。只封 tier，不动
  signals / confidence / s_struct（R69：同一份 signals 既喂 confidence() 又写进 anchor）。
- **R117 只指认一个节点**：回退时 judge 在候选里挑，挑中的那**一个**节点才是 code_expr_range。
  不按首尾区间猜 —— 实测本仓夹具上那个区间含 35 个真实节点，会画 35 条没审过的假彩线。
  结构路径（pairs 非空）完全不动，仍是 first..last（既有测试钉着这个格式）。
- **R118**：judge 确认的节点 id 由 spine._judge_pairs 返回；本模块只负责消费它拼 range。
"""

from __future__ import annotations

from papertrace.align.candidates import candidate_pairs

#: code_expr_range 的区间分隔符（既有格式，R68）
RANGE_SEP = ".."
#: 没出线时写进 unresolved 的原因：结构对上的走原话，回退候选必须说清自己不是结构对上的
NO_YES_REASON = "判断题没有给出 yes 与依据"
NO_YES_FALLBACK_REASON = "回退候选没拿到判断题 yes（结构同构未命中，候选来自算子类型+词法排序）"


def pairs_or_fallback(signal, terms: list, nodes: list[dict], *,
                      per_term_limit: int = 3, total_limit: int = 12) -> tuple[dict, bool]:
    """结构配对 → 按 term.index 分组；一个都没有时退到算子类型候选。

    返回 (grouped, fallback)。fallback 为 True 表示这批候选**不是**结构同构来的，
    调用方必须按 R112 把 tier 封在 yellow。回退也拿不到候选时返回 ({}, False)：
    空就是空，让调用方如实记 unresolved，不假装「回退过」。
    """
    grouped: dict[int, list[str]] = {}
    for index, node_id in signal.pairs or []:
        grouped.setdefault(index, []).append(node_id)
    if grouped:
        return grouped, False
    proposal = candidate_pairs(terms, nodes, per_term_limit=per_term_limit,
                               total_limit=total_limit)
    fallback: dict[int, list[str]] = {}
    for index, node_id in proposal.pairs or []:
        fallback.setdefault(index, []).append(node_id)
    return fallback, bool(fallback)


def resolve_code_range(node_ids: list[str], confirmed_id: str | None, fallback: bool) -> str:
    """anchor.code_expr_range：回退路径只写 judge 确认的那一个节点，结构路径保持 first..last。"""
    if not node_ids:
        return ""
    if fallback and confirmed_id:
        return str(confirmed_id)
    if len(node_ids) == 1:
        return str(node_ids[0])
    return f"{node_ids[0]}{RANGE_SEP}{node_ids[-1]}"


def none_cause(fallback: bool) -> str:
    """tier==none 时写给用户看的原因。回退路径必须自报家门，别让人以为结构对上了。"""
    return NO_YES_FALLBACK_REASON if fallback else NO_YES_REASON


def cap_tier(level: str, fallback: bool) -> str:
    """R112：回退产的线最高到黄线。只降不升，none 仍是 none。"""
    if fallback and level == "green":
        return "yellow"
    return level
