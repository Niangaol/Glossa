"""C6：HTML 第 ⑥ 块「代码体检」的行构造（R220–R226；修复轮 R235–R239）。

「纯行构造 + 模板只负责摆」的分工照 papertrace/render_terms.py（R166）：本文件
只产出已格式化的字符串与行 dict，模板不写业务判断。零 torch 依赖——只读
trace 字段；METHOD_TEXT 从 code_analysis import 同一份，不许手抄第二份
（GC19：粗估口径的自述只有一处真源）。

口径（要改先改这段 docstring，再改测试，GC19）：
- summary_line：总量行键名逐字复刻 C5 的 stdout 摘要（去掉「代码分析：」前缀，
  块标题已经是它），千位分隔 f"{n:,}"（R219）；analysis 为空 → ""。
  R235：totals 不完整（不是 dict / 五键缺键 / 值是 bool 或非 int）→ 返回
  「总计缺失（analysis.totals 不完整），摘要不可用」——一边渲染 34 行模块表
  一边说「0 个模块」是静默产出错误事实，比崩溃更糟。
- role_counts：R223 按 count 降序、count 相同按 role 升序；unknown 一律保留
  （R201/GC21：认不出来就说认不出来，不为好看折叠它）；roles 里没有的角色
  不补 0（R207：只数真出现的）；R239：bool 是 int 子类，计数不是真 int 就
  记 0，不许把 True 原样打出来。
- role_rows：R224 七个已格式化字符串字段，按 module_id 升序；三个数字列
  f"{n:,}"；cls / evidence 缺失如实记 "-"，数字缺失或非法同样记 "-"（R237：
  0 会被读成「测出来就是 0」，看得见的占位符才诚实）。
- method_text / method_label：R238 一对同源判定。trace 的 method 是非空 str
  → 标签「方法说明（逐字原文，不许截断）：」；回落 METHOD_TEXT → 标签
  「方法说明（内置默认文本，不是 trace 里的原文）：」。回落还不改口，
  provenance 就过强了。
- _degraded_text：计数与原因原文必须同时出现；R235：totals 不完整 → 返回
  ""（不许出现「降级 0 个」这种伪造计数，模板连整行一起收起来）。
- symbols_note：R225 meta.paper 缺失或 source == "none" → 一句含「没有论文」
  的说明；有论文 → ""（不刷废话）。
- analysis_panel：R226 永远返回全部键（模板 StrictUndefined，缺键即炸）；
  R236 入口把非 dict 的 analysis 归一化成 {}（5.get 炸 AttributeError 是把
  类型错误演成渲染崩溃）；本轮起八个键（R220 的七键 + R238 method_label）。
  没有 analysis 的旧 trace 与骨架 trace 都是「显示块 + 如实说没有」，
  不是把块藏掉（空态句由模板 else 分支摆放）。
"""

from __future__ import annotations

from papertrace.code_analysis import METHOD_TEXT

#: R225：无论文时 ⑤ 符号表里的说明句（代码侧符号可列，论文侧无可列）。
NO_PAPER_NOTE = (
    "本次 build 没有论文，所以这张表只有代码侧符号，没有论文侧符号与映射可列"
)

#: R238：两种方法说明标签——有原文 / 回落内置默认文本，二选一，不许混。
METHOD_LABEL_TRACE = "方法说明（逐字原文，不许截断）："
METHOD_LABEL_FALLBACK = "方法说明（内置默认文本，不是 trace 里的原文）："

#: R235：totals 完整性判据要查的五个键（summary 与 degraded 共用同一把尺子）。
_TOTALS_KEYS = ("modules", "params", "max_activation", "est_flops", "degraded")


def _is_int(value) -> bool:
    """R235/R239 同一口径：真 int。bool 是 int 子类，必须显式排除。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _num(value: int) -> str:
    """R219：千位分隔。调用方必须先过 _totals_ok，值一定是真 int。"""
    return f"{value:,}"


def _cell(value) -> str:
    """R237：模块表数字格——缺字段 / None / 非 int 记 "-"（0 像真测出来的 0）。"""
    return f"{value:,}" if _is_int(value) else "-"


def _totals_ok(analysis: dict) -> bool:
    """R235：totals 是 dict、五个键都在、每个值都是真 int（bool 不算 int）。"""
    totals = analysis.get("totals")
    if not isinstance(totals, dict):
        return False
    return all(key in totals and _is_int(totals[key]) for key in _TOTALS_KEYS)


def summary_line(analysis) -> str:
    """总量行：34 个模块 · 参数量 29,856 · 峰值激活 2,048 元素 · 粗估 FLOPs 884,736。

    R219：键名逐字 + 千位分隔；analysis 为空（None / 空 dict）→ ""，模板走
    else 分支，不显示半句话。R235：totals 不完整 → 如实说摘要不可用。
    """
    if not analysis:
        return ""
    if not _totals_ok(analysis):
        return "总计缺失（analysis.totals 不完整），摘要不可用"
    totals = analysis["totals"]
    return "%s 个模块 · 参数量 %s · 峰值激活 %s 元素 · 粗估 FLOPs %s" % (
        _num(totals["modules"]),
        _num(totals["params"]),
        _num(totals["max_activation"]),
        _num(totals["est_flops"]),
    )


def role_counts(analysis) -> list[dict]:
    """R223：[{"role": "attention", "count": 2}, …]；count 降序、count 相同 role 升序。

    unknown 一律保留（GC21）；roles 里没有的角色不补 0（R207）；R239：计数
    不是真 int（含 bool）就记 0，不许输出成 `linear True`。
    """
    if not analysis:
        return []
    counts = [
        {"role": str(role), "count": count if _is_int(count) else 0}
        for role, count in (analysis.get("roles") or {}).items()
    ]
    counts.sort(key=lambda row: (-row["count"], row["role"]))
    return counts


def role_rows(analysis) -> list[dict]:
    """R224：模块表行，七个已格式化字符串字段，按 module_id 升序。

    三个数字列用 f"{n:,}"（R219）；cls / evidence 缺失如实记 "-"，数字缺失
    或非法同样记 "-"（R237）。
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
                "params": _cell(mod.get("params")),
                "max_activation": _cell(mod.get("max_activation")),
                "est_flops": _cell(mod.get("est_flops")),
                "evidence": str(mod.get("evidence") or "-"),
            }
        )
    rows.sort(key=lambda row: row["module_id"])
    return rows


def _trace_method(analysis) -> str:
    """R238：trace 里的 method 原文；空串 / 非 str 都算没有（回落走另一条标签）。"""
    if analysis:
        method = analysis.get("method")
        if isinstance(method, str) and method:
            return method
    return ""


def method_text(analysis) -> str:
    """原文返回 analysis["method"]；缺失回落 code_analysis.METHOD_TEXT（同一份）。"""
    return _trace_method(analysis) or METHOD_TEXT


def method_label(analysis) -> str:
    """R238：标签跟 provenance 对齐，回落时不许还自称逐字原文。"""
    return METHOD_LABEL_TRACE if _trace_method(analysis) else METHOD_LABEL_FALLBACK


def _degraded_text(analysis) -> str:
    """降级计数 + 原因原文，两个都要出现；R235：totals 不完整 → ""（不伪造计数）。"""
    if not analysis or not _totals_ok(analysis):
        return ""
    totals = analysis["totals"]
    head = "降级 %s 个" % _num(totals["degraded"])
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
    """R220/R226/R236：组装第 ⑥ 块；永远返回全部键（StrictUndefined 缺键即炸）。

    R236：非 dict 的 analysis（int / list / str）在入口归一化成 {}——`5.get`
    炸 AttributeError，等于把一处类型错误演成整页渲染崩溃。
    """
    analysis = doc.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
    return {
        "has": bool(analysis),
        "summary": summary_line(analysis),
        "roles": role_counts(analysis),
        "rows": role_rows(analysis),
        "method": method_text(analysis),
        "method_label": method_label(analysis),
        "degraded": _degraded_text(analysis),
        "symbols_note": symbols_note(doc),
    }
