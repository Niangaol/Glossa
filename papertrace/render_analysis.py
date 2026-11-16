"""C6：HTML 第 ⑥ 块「代码体检」的行构造（R220–R226）。

「纯行构造 + 模板只负责摆」的分工照 papertrace/render_terms.py（R166）：本文件
只产出已格式化的字符串与行 dict，模板不写业务判断。零 torch 依赖——只读
trace 字段；METHOD_TEXT 从 code_analysis import 同一份，不许手抄第二份
（GC19：粗估口径的自述只有一处真源）。

口径（要改先改这段 docstring，再改测试，GC19）：
- summary_line：总量行键名逐字复刻 C5 的 stdout 摘要（去掉「代码分析：」前缀，
  块标题已经是它），千位分隔 f"{n:,}"（R219）；analysis 为空 → ""。
- role_counts：R223 按 count 降序、count 相同按 role 升序；unknown 一律保留
  （R201/GC21：认不出来就说认不出来，不为好看折叠它）；roles 里没有的角色
  不补 0（R207：只数真出现的）。
- role_rows：R224 七个已格式化字符串字段，按 module_id 升序；三个数字列
  f"{n:,}"；cls / evidence 缺失如实记 "-"，数字缺失记 0（R200：不猜不抛）。
- method_text：原文返回 analysis["method"]；缺失回落 code_analysis.METHOD_TEXT。
- _degraded_text：计数与原因原文必须同时出现；0 个也照说「降级 0 个」，
  不因为不好看就把计数藏起来。
- symbols_note：R225 meta.paper 缺失或 source == "none" → 一句含「没有论文」
  的说明；有论文 → ""（不刷废话）。
- analysis_panel：R226 永远返回全部键（模板 StrictUndefined，缺键即炸）；
  has = analysis 是非空 dict；没有 analysis 的旧 trace 与骨架 trace 都是
  「显示块 + 如实说没有」，不是把块藏掉（空态句由模板 else 分支摆放）。
"""

from __future__ import annotations

from papertrace.code_analysis import METHOD_TEXT

#: R225：无论文时 ⑤ 符号表里的说明句（代码侧符号可列，论文侧无可列）。
NO_PAPER_NOTE = (
    "本次 build 没有论文，所以这张表只有代码侧符号，没有论文侧符号与映射可列"
)


def _num(value) -> str:
    """R219：千位分隔；缺字段 / None / 非 int 记 0（R200：不猜维度、不抛异常）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return "0"
    return f"{value:,}"


def summary_line(analysis) -> str:
    """总量行：34 个模块 · 参数量 29,856 · 峰值激活 2,048 元素 · 粗估 FLOPs 884,736。

    R219：键名逐字 + 千位分隔；analysis 为空（None / 空 dict）→ ""，模板走
    else 分支，不显示半句话。
    """
    if not analysis:
        return ""
    totals = analysis.get("totals") or {}
    return "%s 个模块 · 参数量 %s · 峰值激活 %s 元素 · 粗估 FLOPs %s" % (
        _num(totals.get("modules", 0)),
        _num(totals.get("params", 0)),
        _num(totals.get("max_activation", 0)),
        _num(totals.get("est_flops", 0)),
    )


def role_counts(analysis) -> list[dict]:
    """R223：[{"role": "attention", "count": 2}, …]；count 降序、count 相同 role 升序。

    unknown 一律保留（GC21）；roles 里没有的角色不补 0（R207）。
    """
    if not analysis:
        return []
    counts = [
        {"role": str(role), "count": count if isinstance(count, int) else 0}
        for role, count in (analysis.get("roles") or {}).items()
    ]
    counts.sort(key=lambda row: (-row["count"], row["role"]))
    return counts


def role_rows(analysis) -> list[dict]:
    """R224：模块表行，七个已格式化字符串字段，按 module_id 升序。

    三个数字列用 f"{n:,}"（R219）；cls / evidence 缺失如实记 "-"。
    """
    if not analysis:
        return []
    rows = []
    for mod in analysis.get("modules") or []:
        rows.append(
            {
                "module_id": str(mod.get("module_id") or "-"),
                "cls": str(mod.get("class") or "-"),
                "role": str(mod.get("role") or "-"),
                "params": _num(mod.get("params", 0)),
                "max_activation": _num(mod.get("max_activation", 0)),
                "est_flops": _num(mod.get("est_flops", 0)),
                "evidence": str(mod.get("evidence") or "-"),
            }
        )
    rows.sort(key=lambda row: row["module_id"])
    return rows


def method_text(analysis) -> str:
    """原文返回 analysis["method"]；缺失回落 code_analysis.METHOD_TEXT（同一份）。"""
    if analysis:
        method = analysis.get("method")
        if method:
            return str(method)
    return METHOD_TEXT


def _degraded_text(analysis) -> str:
    """降级计数 + 原因原文，两个都要出现；0 个也照说「降级 0 个」。"""
    if not analysis:
        return "降级 0 个"
    totals = analysis.get("totals") or {}
    head = "降级 %s 个" % _num(totals.get("degraded", 0))
    reasons = [str(r).strip() for r in (totals.get("degraded_reasons") or []) if str(r).strip()]
    if reasons:
        return head + "：" + "；".join(reasons)
    return head


def symbols_note(doc: dict) -> str:
    """R225：meta.paper 缺失或 source == "none" → 一句含「没有论文」的说明。"""
    paper = (doc.get("meta") or {}).get("paper") or {}
    if not paper or paper.get("source") == "none":
        return NO_PAPER_NOTE
    return ""


def analysis_panel(doc: dict) -> dict:
    """R220/R226：组装第 ⑥ 块；永远返回全部键（StrictUndefined 缺键即炸）。"""
    analysis = doc.get("analysis")
    return {
        "has": isinstance(analysis, dict) and bool(analysis),
        "summary": summary_line(analysis),
        "roles": role_counts(analysis),
        "rows": role_rows(analysis),
        "method": method_text(analysis),
        "degraded": _degraded_text(analysis),
        "symbols_note": symbols_note(doc),
    }
