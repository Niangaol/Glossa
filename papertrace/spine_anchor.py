"""单公式项落盘（S9）：把一个公式项落成 anchor 或 unresolved。

这是把单个公式项落成 anchor 的逻辑；逐层展开由调用方循环——spine._attach_unit
拿着 terms 与 claimed 集合逐项调用 attach_term，本模块不管循环。
**宁可报「对不上」也绝不编造对齐**：拿不到依据就写 unresolved，不凑 anchor。
裁决正文逐字照录在 task-S9-report.md，这里只记一句话结论。

R165：从 papertrace/spine.py 拆出（行为零变化）。本模块只放自己函数用到的
字面量与预算；NO_CANDIDATE_REASON / FALLBACK_PAIR_NOTE 经 papertrace.spine
再导出（拆文件计划的「保持」清单），定义在这里——它们只被本模块用到，
放 spine.py 会逼出循环 import。
"""

from __future__ import annotations

from papertrace.align.score import confidence
from papertrace.align.tier import tier, tier_reason
from papertrace.constants import CONF_YELLOW
from papertrace.spine_claims import (
    CLAIMED_REASON,
    judge_first_yes,
    unclaimed,
)
from papertrace.spine_fallback import (
    cap_tier, claimed_nodes, none_cause, resolve_code_range)

#: 本模块用到的字面量与预算（裁决编号见模块 docstring）
NO_CANDIDATE_REASON = "结构同构未命中，没有可判断的候选对"       # R37
FALLBACK_PAIR_NOTE = "候选来自算子类型+词法排序（结构同构未命中），最高黄线"  # R112
FALLBACK_EVIDENCE = "判断题没有给出 yes：只凭结构/检索信号出线，需人工复核"
ALTERNATIVE_LIMIT = 2   # schema alternatives maxItems
EVIDENCE_LIMIT = 80     # schema anchor.evidence maxLength


def attach_term(doc: dict, unit, term, signal, retrieval, node_ids: list, by_id: dict,
                fallback: bool, claimed: set[str],
                code_group: str | None = None) -> None:
    """一个公式项：三个信号 → confidence → tier → anchor 或 unresolved。

    R161/R163：code_group 非 None 时这条 anchor 属于某个同构组（结构路径）；
    None（回退路径）时不写这个键——回退路径没有层可言。
    """
    term_id = f"{unit.unit_id}-t{term.index}"
    # R85：逐项 s_retr 只取本项 forward 的最大分；缺键/空表 → 0.0（保守方向），
    # 绝不用单元级 retrieval["s_retr"]——兄弟项命中会把零检索的项抬上绿线
    s_retr = min(1.0, max(0.0, max(
        ((h.get("score") or 0.0)
         for h in (retrieval.get("forward") or {}).get(term_id) or []),
        default=0.0)))
    s_struct = float(signal.score)
    if not node_ids:
        # R37：judge 只对 StructSignal.pairs 里的配对调用。pairs 空就一个都不问——
        # 拿检索 top1 当候选会让「结构同构没命中」的项靠 embedding 相似度混上绿线
        record_unresolved(doc, term_id, NO_CANDIDATE_REASON, retrieval,
                          {"s_retr": s_retr, "s_judge": 0.0, "s_struct": s_struct})
        return
    available = unclaimed(node_ids, claimed)  # R135：跳过已被别的项认领的节点
    if not available:  # R137/R146：成因是「被占了」不是「没有候选」，文案分开
        doc["unresolved"].append({"kind": "paper_unit", "ref": term_id,
                                  "reason": CLAIMED_REASON})  # R146：不走 record_unresolved
        return
    s_judge, verdict, confirmed = judge_first_yes(term.latex, available, by_id, claimed)
    # R69：同一份 signals 既喂 confidence() 又写进 anchor.signals，不分别算、不取整
    signals = {"s_retr": s_retr, "s_judge": s_judge, "s_struct": s_struct}
    score = confidence(signals["s_retr"], signals["s_judge"], signals["s_struct"])
    level = cap_tier(tier(score, s_struct), fallback)  # R112
    if level == "none":
        record_unresolved(doc, term_id, none_cause(fallback), retrieval, signals)
        return
    # R68/R117：结构路径填首尾区间；回退路径只填 judge 确认的那一个节点
    code_range = resolve_code_range(available, confirmed, fallback)
    evidence = "；".join(p.strip() for p in (verdict, tier_reason(score, s_struct))
                        if p and p.strip())
    if fallback:  # R112：候选不是结构对上的，必须写在用户看得见的地方
        evidence = f"{FALLBACK_PAIR_NOTE}；{evidence}" if evidence else FALLBACK_PAIR_NOTE
    if s_judge <= 0:  # 判断题没说 yes：挂兜底证据，说明只凭结构/检索出线
        evidence = f"{evidence}；{FALLBACK_EVIDENCE}" if evidence else FALLBACK_EVIDENCE
    anchor = {"paper_unit_id": unit.unit_id, "formula_term_index": term.index,
              "code_expr_range": code_range,
              "aten_ops": [by_id[n]["op"] for n in available if n in by_id and by_id[n].get("op")],
              "confidence": score, "tier": level, "signals": signals,
              "source": "model" if s_judge > 0 else "static",  # R67
              "evidence": evidence[:EVIDENCE_LIMIT] or FALLBACK_EVIDENCE,
              "direction": "paper_to_code"}
    if code_group is not None:  # R163：结构路径必填，回退路径省略（None 就不写键）
        anchor["code_group"] = code_group
    if level == "yellow":  # brief：黄线必须带备选（schema maxItems 2）
        picks = [h for h in (retrieval.get("forward") or {}).get(term_id) or []
                 if h.get("code_id") not in available
                 and h.get("code_id") not in claimed][:ALTERNATIVE_LIMIT]  # R151
        anchor["alternatives"] = [
            {"code_id": h["code_id"], "op": (by_id.get(h["code_id"]) or {}).get("op", ""),
             "score": h.get("score")} for h in picks]
    doc["anchors"].append(anchor)
    claimed.update(claimed_nodes(available, confirmed, fallback))  # R147：占住已产出的节点
def record_unresolved(doc: dict, term_id: str, cause: str, retrieval: dict, signals: dict) -> None:
    """tier=='none' → 不产 anchor，把为什么说不清写进 unresolved。"""
    score = confidence(signals["s_retr"], signals["s_judge"], signals["s_struct"])
    parts = [f"置信度 {score:.4f} < {CONF_YELLOW:.2f}：{cause}"]
    detail = (retrieval.get("reason") or "").strip()
    if detail:
        parts.append(detail)
    parts.append("（s_retr=%.2f s_judge=%.2f s_struct=%.2f）" % (
        signals["s_retr"], signals["s_judge"], signals["s_struct"]))
    doc["unresolved"].append({"kind": "paper_unit", "ref": term_id,
                              "reason": "；".join(parts)})
