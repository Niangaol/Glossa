"""论文脊柱（S9）：把论文侧产物接进 build_trace 产出的 trace dict。

链条：S2 ingest → S3 拆项 → S4 符号表 → S5 结构信号 → S6 双向检索 → S7 判断题 → 分档，
落进 meta/symbols/anchors/unresolved。**宁可报「对不上」也绝不编造对齐**：拿不到依据就写
unresolved，不凑 anchor。裁决正文逐字照录在 task-S9-report.md，这里只记一句话结论。

R79 model 从哪来：build_trace 只返回 dict，CLI 成功后用 load_entry **再取一次**模块
实例（0.003s vs 2.760s，绝不重新追踪）；R67 source 只 model/static，绝不用 runtime；
R68 code_expr_range 填 pairs 的 node_id 首尾区间，逐算子行号属 M1b。R85 逐项 s_retr
只取本项 forward 的最大分，缺键/空表 → 0.0，绝不用单元级 retrieval["s_retr"]——
兄弟项命中会把零检索的项抬上绿线。R78/R69/R70/R21/R56/R37/R2：拆项门是
split_formula(...)==[]，三个 signal 同一份 dict 既喂 confidence() 又写进 signals，
prompt_version 写 JUDGE_PROMPT_VERSION，符号差集记 unresolved，只捕预期不可用，
judge 只对 pairs 里的配对调用。
"""

from __future__ import annotations

from papertrace.align.judge import judge, judge_score
from papertrace.align.retrieve import retrieve_bidirectional
from papertrace.align.score import confidence
from papertrace.align.struct_signal import struct_signal
from papertrace.align.tier import tier, tier_reason
from papertrace.constants import CONF_YELLOW
from papertrace.exceptions import IngestError, LLMUnavailable
from papertrace.ingest.paper import ingest_paper
from papertrace.llm.client import get_llm
from papertrace.llm.prompts import JUDGE_PROMPT_VERSION
from papertrace.parse_paper.split_terms import split_formula
from papertrace.symbols.code_table import _FROZEN_SYMBOLS, build_code_symbols
from papertrace.symbols.mapping import map_symbols
from papertrace.symbols.paper_table import build_paper_symbols

#: 本模块用到的字面量与预算（裁决编号见模块 docstring）
UNSPLITTABLE_REASON = "公式拆不出项（超出白名单文法），不猜项"   # R78
NO_CANDIDATE_REASON = "结构同构未命中，没有可判断的候选对"       # R37
RANGE_SEP = ".."                                              # R68
UNKNOWN_BACKEND = "unknown"                                   # R70
FALLBACK_EVIDENCE = "判断题没有给出 yes：只凭结构/检索信号出线，需人工复核"
ALTERNATIVE_LIMIT = 2   # schema alternatives maxItems
EVIDENCE_LIMIT = 80     # schema anchor.evidence maxLength


def attach_paper(doc: dict, paper_src: str, model) -> dict:
    """把论文侧产物**原地**填进 doc，并返回同一个 doc。

    `model` 是**模块实例**（R79），None 表示 --skeleton 没有模型：符号抽不到、
    config 拿不到，一律 fail-closed 记 unresolved，不猜。
    """
    for key in ("anchors", "unresolved"):
        doc.setdefault(key, [])
    doc.setdefault("meta", {})
    symbols = doc.setdefault("symbols", {"code": [], "paper": [], "mapping": []})
    try:
        bundle = ingest_paper(paper_src)
    except IngestError as exc:
        doc["unresolved"].append({
            "kind": "paper_unit", "ref": str(paper_src),
            "reason": f"论文 ingest 失败：{exc}（不猜论文内容）"})
        doc["meta"].setdefault(
            "paper", {"source": "none", "unit_count": 0, "ingest_mode": "none"})
        # R86：早退也写 meta.model，别留 schema 默认的 prompt_version="0"（那会谎称 offline）
        doc["meta"]["model"] = _model_meta()
        return doc
    paper_meta = {"source": str(bundle.source), "unit_count": int(bundle.unit_count),
                  "ingest_mode": bundle.ingest_mode}
    if isinstance(bundle.title, str) and bundle.title.strip():
        paper_meta["title"] = bundle.title  # None 就省掉整个键（schema title 是 string）
    doc["meta"]["paper"] = paper_meta
    doc["meta"]["model"] = _model_meta()
    code_symbols = build_code_symbols(model, doc)  # R2：bundle 是 trace dict
    paper_symbols = build_paper_symbols(bundle)    # R2：bundle 是 PaperBundle
    symbols["code"] = code_symbols
    symbols["paper"] = paper_symbols
    symbols["mapping"] = map_symbols(code_symbols, paper_symbols)
    found = {row.get("symbol") for row in code_symbols or []}
    for name in _FROZEN_SYMBOLS:  # R21：差集记 unresolved，不猜值
        if name in found:
            continue
        reason = ("骨架模式（--skeleton）没有模型实例，抽不到代码侧符号" if model is None
                  else f"代码侧没抽到 {name}：config 缺字段、值为 None 或定义点定位失败（不猜值）")
        doc["unresolved"].append({"kind": "symbol", "ref": name, "reason": reason})
    by_id = {n["id"]: n for n in doc.get("nodes") or []
             if isinstance(n, dict) and n.get("id")}
    for unit in bundle.units:
        _attach_unit(doc, unit, model, by_id)
    return doc


def _attach_unit(doc: dict, unit, model, by_id: dict) -> None:
    """一个公式单元 → 逐公式项的 anchor / unresolved。"""
    terms = split_formula(unit.latex)
    if not terms:  # R78：门是拆不拆得出项，不是整式能不能过 sympy 文法
        doc["unresolved"].append({"kind": "paper_unit", "ref": unit.unit_id,
                                  "reason": UNSPLITTABLE_REASON})
        return
    signal = struct_signal(doc["nodes"], terms, getattr(model, "config", None))
    # S6 的 code_units 与 S5 同口径：level=='op' 且 kind=='op' 的算子节点
    code_units = [{"code_id": n["id"], "text": _node_text(n)} for n in doc["nodes"] or []
                  if isinstance(n, dict) and n.get("level") == "op"
                  and n.get("kind") == "op" and n.get("id")]
    retrieval = retrieve_bidirectional(code_units, [
        {"term_id": f"{unit.unit_id}-t{t.index}", "text": t.latex} for t in terms])
    grouped: dict[int, list[str]] = {}
    for index, node_id in signal.pairs or []:
        grouped.setdefault(index, []).append(node_id)
    for term in terms:
        _attach_term(doc, unit, term, signal, retrieval, grouped.get(term.index, []), by_id)


def _attach_term(doc: dict, unit, term, signal, retrieval, node_ids: list, by_id: dict) -> None:
    """一个公式项：三个信号 → confidence → tier → anchor 或 unresolved。"""
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
        _record_unresolved(doc, term_id, NO_CANDIDATE_REASON, retrieval,
                           {"s_retr": s_retr, "s_judge": 0.0, "s_struct": s_struct})
        return
    s_judge, verdict = _judge_pairs(term, node_ids, by_id)
    # R69：同一份 signals 既喂 confidence() 又写进 anchor.signals，不分别算、不取整
    signals = {"s_retr": s_retr, "s_judge": s_judge, "s_struct": s_struct}
    score = confidence(signals["s_retr"], signals["s_judge"], signals["s_struct"])
    level = tier(score, s_struct)
    if level == "none":
        _record_unresolved(doc, term_id, "判断题没有给出 yes 与依据", retrieval, signals)
        return
    # R68：填 pairs 的 node_id 区间；M1a 没有逐算子行号，绝不编 file:line
    code_range = node_ids[0] if len(node_ids) == 1 else f"{node_ids[0]}{RANGE_SEP}{node_ids[-1]}"
    evidence = "；".join(p.strip() for p in (verdict, tier_reason(score, s_struct))
                        if p and p.strip())
    if s_judge <= 0:  # 判断题没说 yes：挂兜底证据，说明只凭结构/检索出线
        evidence = f"{evidence}；{FALLBACK_EVIDENCE}" if evidence else FALLBACK_EVIDENCE
    anchor = {"paper_unit_id": unit.unit_id, "formula_term_index": term.index,
              "code_expr_range": code_range,
              "aten_ops": [by_id[n]["op"] for n in node_ids if n in by_id and by_id[n].get("op")],
              "confidence": score, "tier": level, "signals": signals,
              "source": "model" if s_judge > 0 else "static",  # R67
              "evidence": evidence[:EVIDENCE_LIMIT] or FALLBACK_EVIDENCE,
              "direction": "paper_to_code"}
    if level == "yellow":  # brief：黄线必须带备选（schema maxItems 2）
        picks = [h for h in (retrieval.get("forward") or {}).get(term_id) or []
                 if h.get("code_id") not in node_ids][:ALTERNATIVE_LIMIT]
        anchor["alternatives"] = [
            {"code_id": h["code_id"], "op": (by_id.get(h["code_id"]) or {}).get("op", ""),
             "score": h.get("score")} for h in picks]
    doc["anchors"].append(anchor)


def _record_unresolved(doc: dict, term_id: str, cause: str, retrieval: dict, signals: dict) -> None:
    """tier=='none' → 不产 anchor，把为什么说不清写进 unresolved。"""
    score = confidence(signals["s_retr"], signals["s_judge"], signals["s_struct"])
    parts = [f"置信度 {score:.2f} < {CONF_YELLOW:.2f}：{cause}"]
    detail = (retrieval.get("reason") or "").strip()
    if detail:
        parts.append(detail)
    parts.append("（s_retr=%.2f s_judge=%.2f s_struct=%.2f）" % (
        signals["s_retr"], signals["s_judge"], signals["s_struct"]))
    doc["unresolved"].append({"kind": "paper_unit", "ref": term_id,
                              "reason": "；".join(parts)})


def _judge_pairs(term, node_ids: list, by_id: dict) -> tuple[float, str]:
    """R37：只对 StructSignal.pairs 里的配对调 judge；任一是 → s_judge=1.0。"""
    for node_id in node_ids:
        node = by_id.get(node_id)
        if node is None:
            continue
        result = judge(term.latex, _node_text(node))
        if judge_score(result) > 0:
            return 1.0, (result.evidence or "").strip()
    return 0.0, ""


def _node_text(node: dict) -> str:
    """算子节点的一段自描述文本（喂给检索与判断题）。"""
    return (f"{node.get('op', '')} {node.get('label', '')} {node.get('loc', '')} "
            f"in={node.get('shape_in')} out={node.get('shape_out')}").strip()


def _model_meta() -> dict:
    """R70：meta.model 三要素——后端真实名、判断题 prompt 版本、embedding 模型名。"""
    try:
        backend = get_llm()
    except (LLMUnavailable, ValueError):
        # 后端名非法时 get_llm 也炸；记 "unknown" 而不是 "offline"——配置不是 offline
        return {"name": UNKNOWN_BACKEND, "prompt_version": JUDGE_PROMPT_VERSION,
                "embed_model": "none"}
    return {"name": str(getattr(backend, "name", UNKNOWN_BACKEND)),
            "prompt_version": JUDGE_PROMPT_VERSION,
            "embed_model": str(getattr(backend, "embed_model", None) or "none")}
