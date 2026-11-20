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
judge 只对 pairs 里的配对调用。S15：结构未命中时退到算子类型候选（R112 回退产的线最高
到黄、R117 只指认 judge 确认的一个节点、R118 confirmed id），见 spine/fallback.py。
单公式项落盘（anchor 与 unresolved 写盘）在 spine/anchor.py（R165 拆出，行为零变化）。
"""

from __future__ import annotations

from papertrace.align.retrieve import retrieve_bidirectional
from papertrace.align.score import confidence
from papertrace.align.struct_signal import struct_signal
from papertrace.align.tier import tier, tier_reason
from papertrace.constants import CONF_YELLOW
from papertrace.exceptions import BuildError, IngestError, LLMUnavailable
from papertrace.ingest.paper import ingest_paper
from papertrace.llm.client import get_llm
from papertrace.llm.prompts import JUDGE_PROMPT_VERSION
from papertrace.parse_paper.split_terms import split_formula
from papertrace.symbols.code_table import _FROZEN_SYMBOLS, build_code_symbols
from papertrace.symbols.mapping import map_symbols
from papertrace.symbols.paper_table import build_paper_symbols
from papertrace.spine.anchor import (
    ALTERNATIVE_LIMIT, EVIDENCE_LIMIT, FALLBACK_EVIDENCE, FALLBACK_PAIR_NOTE,
    NO_CANDIDATE_REASON, attach_term, record_unresolved)
from papertrace.spine.claims import duplicate_claims, node_text
from papertrace.spine.fallback import pairs_or_fallback

#: 本模块用到的字面量与预算（裁决编号见模块 docstring）
UNSPLITTABLE_REASON = "公式拆不出项（超出白名单文法），不猜项"   # R78
UNKNOWN_BACKEND = "unknown"                                   # R70


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
    for name in (n for n in _FROZEN_SYMBOLS if n not in found):  # R21：差集记 unresolved，不猜值
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
    code_units = [{"code_id": n["id"], "text": node_text(n)} for n in doc["nodes"] or []
                  if isinstance(n, dict) and n.get("level") == "op"
                  and n.get("kind") == "op" and n.get("id")]
    retrieval = retrieve_bidirectional(code_units, [
        {"term_id": f"{unit.unit_id}-t{t.index}", "text": t.latex} for t in terms])
    if signal.pairs and not signal.groups:  # R169：产品永远 pairs 与 groups 一致
        # 只给 pairs 说明同构信号被截断；静默走回退会把结构路径伪装成「没命中」——
        # 宁可炸，也不猜
        raise BuildError(
            "结构信号给了 pairs 却没有 groups：拒绝把结构路径静默降级成回退路径")
    if signal.groups:  # R161：逐层展开只发生在结构同构路径，回退路径没有层可言
        passes = [(m.group, {i: [nid for i2, nid in m.pairs if i2 == i]
                             for i in range(len(terms))})
                  for m in signal.groups]
        for _, grouped in passes:  # R144/R162：重复守门也按组，不能跨组合表
            dups = duplicate_claims(grouped)
            if dups:
                raise BuildError(
                    f"结构配对出现重复节点，一个算子只归一个公式项：{dups}")
        fallback = False
    else:  # R112：回退路径一字不改——每个 term 一条 anchor，无层可言
        grouped, _ = pairs_or_fallback(signal, terms, doc["nodes"])
        passes = [(None, grouped)]
        fallback = True
    for code_group, grouped in passes:
        claimed: set[str] = set()  # R135/R147/R162：同单元同组独占，跨组跨单元共享
        for term in terms:
            attach_term(doc, unit, term, signal, retrieval, grouped.get(term.index, []),
                         by_id, fallback, claimed, code_group)


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
