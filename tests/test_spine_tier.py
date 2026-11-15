"""S1：分档函数 + 绿线门（U1）+ anchor 契约（RF3）。

门的语义（派发裁决，唯一正确读法）：
- green 需要 c >= CONF_GREEN **且** s_struct >= GREEN_STRUCT_MIN
- yellow 需要 c >= CONF_YELLOW（不受门影响）
- none 是 c < CONF_YELLOW
s_struct 低只会把 green 降成 yellow，绝不会把 yellow 降成 none，也绝不会把任何档往上升。

为什么门必须长在生成侧的 tier() 里：HTML 渲染时手上只有一个 confidence 数字，
执行不了「还要看 s_struct」这条判据；只有分档函数同时见过 c 和 s_struct。
"""

import json
import re
from pathlib import Path

import pytest

from papertrace.align.score import confidence
from papertrace.align.tier import tier, tier_reason
from papertrace.constants import CONF_GREEN, CONF_YELLOW, GREEN_STRUCT_MIN
from papertrace.exceptions import TraceSchemaError
from papertrace.schema_anchor import anchor_errors
from papertrace.schema_validate import minimal_trace, validate_trace

# 档位序号：none < yellow < green，用来断言「门只降不升」。
_RANK = {"none": 0, "yellow": 1, "green": 2}


def _ungated_rank(c: float) -> int:
    """无门时的档位序号：只看 confidence，与 s_struct 无关。"""
    if c >= CONF_GREEN:
        return _RANK["green"]
    if c >= CONF_YELLOW:
        return _RANK["yellow"]
    return _RANK["none"]


@pytest.mark.parametrize(
    ("c", "s_struct", "expected"),
    [
        (0.8808, 1.0, "green"),  # confidence(1,1,1)：双门槛都过
        (0.7685, 0.0, "yellow"),  # U1 反例：confidence(1,1,0)，c 够绿但结构信号为零
        (0.7685, 0.49, "yellow"),  # 差 0.01 也不放行
        (0.7685, 0.5, "green"),  # 门槛取闭区间：等于 GREEN_STRUCT_MIN 即过门
        (0.6900, 1.0, "yellow"),  # c 不够绿，结构信号满分也只是黄
        (0.45, 1.0, "yellow"),  # 黄线下界取闭区间
        (0.4499, 1.0, "none"),
        (0.2315, 1.0, "none"),  # confidence(1,0,0) 一类的低证据
    ],
)
def test_green_requires_both_thresholds(c, s_struct, expected):
    assert tier(c, s_struct) == expected


def test_gate_only_downgrades():
    """100 个 (c, s) 网格：有门的档位序号必须 <= 无门的档位序号。"""
    grid = [i / 10 for i in range(10)]  # 0.0, 0.1, ..., 1.0
    assert len(grid) == 10
    for c in grid:
        for s in grid:
            gated = _RANK[tier(c, s)]
            assert gated <= _ungated_rank(c), f"c={c} s={s} 被门抬升了：{tier(c, s)}"


def test_tier_matches_confidence_formula():
    """真实公式算出的 c 必须被门拦住——证明门拦下的是一个本该绿的置信度。"""
    c = confidence(1, 1, 0)  # 检索与判断满分、结构信号为零
    assert c >= CONF_GREEN  # 无门时它本该是绿实线
    assert tier(c, 0.0) == "yellow"  # U1 门把它降成黄虚线
    assert tier(c, 1.0) == "green"  # 同一个 c，结构信号够就放行


def test_tier_reason_mentions_struct():
    reason = tier_reason(0.7685, 0.0)
    assert "结构" in reason
    assert "0.50" in reason
    assert len(reason) <= 40  # 要能塞进 anchor.evidence（schema 上限 80）


def test_tier_reason_empty_when_not_downgraded():
    # 过了门：没有降级原因
    assert tier_reason(0.8808, 1.0) == ""
    # 黄/不连线是置信度自己的事，不是门降的，同样没有原因
    assert tier_reason(0.45, 0.0) == ""
    assert tier_reason(0.2315, 0.0) == ""


def _anchor(**overrides) -> dict:
    """一个形状合法的 anchor；overrides 用来手改字段模拟涂色。"""
    anchor = {
        "paper_unit_id": "S3.2-eq-attn",
        "formula_term_index": 0,
        "code_expr_range": "model.py:30-30",
        "aten_ops": ["aten::matmul"],
        "confidence": 0.9,
        "source": "model",
        "evidence": "QK^T 与论文项同形",
    }
    anchor.update(overrides)
    return anchor


def _doc(*anchors: dict) -> dict:
    doc = minimal_trace()
    doc["anchors"] = list(anchors)
    return doc


def test_anchor_without_tier_still_valid():
    """旧 trace 没有 tier/signals：不校验，必须原样通过（纯增量的底线）。"""
    doc = _doc(_anchor())
    assert anchor_errors(doc) == []
    validate_trace(doc)


def test_valid_tier_and_signals_pass():
    """tier 与 signals 重算结果一致时放行——否则门会把正常数据全毙掉。"""
    doc = _doc(_anchor(tier="green", signals={"s_retr": 1.0, "s_judge": 1.0, "s_struct": 1.0}))
    assert anchor_errors(doc) == []
    validate_trace(doc)


def test_tier_must_match_recomputed_gate():
    """手改涂绿：signals 重算出来是 yellow，tier 却写 green，必须抓到。"""
    doc = _doc(_anchor(tier="green", signals={"s_retr": 1.0, "s_judge": 1.0, "s_struct": 0.0}))
    errors = anchor_errors(doc)
    assert errors
    assert any("tier" in e for e in errors)


def test_tier_without_signals_is_rejected():
    """带了 tier 却删掉 signals：无法复核分档，必须抓到。"""
    doc = _doc(_anchor(tier="green"))
    errors = anchor_errors(doc)
    assert errors
    assert any("signals" in e for e in errors)


@pytest.mark.parametrize(
    "signals",
    [
        {"s_retr": 1.0, "s_judge": 1.0},  # 缺 s_struct
        {"s_retr": 1.5, "s_judge": 0.5, "s_struct": 0.5},  # 越界：>1
        {"s_retr": -0.1, "s_judge": 0.5, "s_struct": 0.5},  # 越界：<0
        {"s_retr": "1.0", "s_judge": 0.5, "s_struct": 0.5},  # 不是数字
    ],
)
def test_signals_out_of_range_is_rejected(signals):
    doc = _doc(_anchor(tier="yellow", signals=signals))
    assert anchor_errors(doc)


def test_validate_trace_catches_hand_painted_tier():
    """端到端：钩子挂在 structural_errors 末尾，validate_trace 必须执行门。"""
    doc = _doc(_anchor(tier="green", signals={"s_retr": 1.0, "s_judge": 1.0, "s_struct": 0.0}))
    with pytest.raises(TraceSchemaError) as excinfo:
        validate_trace(doc)
    assert any("tier" in e for e in excinfo.value.errors)


def test_conservative_downgrade_to_yellow_is_allowed():
    """R171：tier 不得高于重算结果——**降格必须放行**。

    回退路径上 spine_fallback.cap_tier 按 R112 把 green 封顶成 yellow：
    signals 重算仍是 green（c=sigmoid(4·(0.30·1.0+0.50·1.0+0.20·0.6−0.5))≈0.8428、
    s_struct=0.60 ≥ GREEN_STRUCT_MIN=0.50），落盘 yellow 是产品自己的保守下调——
    用户看到的是更弱的结论，不是假事实。旧判据「必须相等」会把这份合法配置
    判成「手改涂色」，让构建在最后一步崩掉；本测试就是那条网。
    """
    doc = _doc(_anchor(tier="yellow", signals={"s_retr": 1.0, "s_judge": 1.0, "s_struct": 0.6}))
    assert anchor_errors(doc) == []
    validate_trace(doc)


def test_upgrade_from_none_to_yellow_is_rejected():
    """R171 的另一半：**升格必须抓**——signals 全 0 重算 none，落盘 yellow。

    把「不连线」涂成黄线是往「多断言」的方向造假，与 RF3 的原始目的
    （把黄涂成绿）同族，只是档位不同；既有两条涂色用例没有覆盖 none→yellow
    这一面，判据改成秩比较之后必须仍然拒。
    """
    doc = _doc(_anchor(tier="yellow", signals={"s_retr": 0.0, "s_judge": 0.0, "s_struct": 0.0}))
    errors = anchor_errors(doc)
    assert errors
    assert any("tier" in e for e in errors)


def test_green_struct_min_is_the_u1_gate():
    """常量值本身就是产品语义：0.5，不许被顺手改成别的数。"""
    assert GREEN_STRUCT_MIN == 0.5
    assert CONF_GREEN == 0.75
    assert CONF_YELLOW == 0.45


def test_unresolved_confidence_rendering_avoids_self_contradiction():
    """Important-3 (FIX-3): c ∈ [0.445, 0.45) 时，不许渲染出「置信度 0.45 < 0.45」自相矛盾。"""
    from papertrace.spine_anchor import record_unresolved

    doc = {"unresolved": []}
    s_retr, s_judge, s_struct = 0.95, 0.0, 0.8
    c = confidence(s_retr, s_judge, s_struct)
    assert 0.445 <= c < CONF_YELLOW, f"前置条件：c 必须落在 [0.445, {CONF_YELLOW})，实际 {c}"

    signals = {"s_retr": s_retr, "s_judge": s_judge, "s_struct": s_struct}
    record_unresolved(doc, "t0", "未连线", {}, signals)
    reason = doc["unresolved"][0]["reason"]
    # 提取渲染出的置信度与门槛字符串，断言不得相同
    match = re.search(r"置信度\s+([\d\.]+)\s+<\s+([\d\.]+)", reason)
    assert match is not None, f"未匹配到置信度比较结构：{reason}"
    rendered_score, rendered_threshold = match.group(1), match.group(2)
    assert rendered_score != rendered_threshold, (
        f"自相矛盾：左侧 {rendered_score} 与右侧 {rendered_threshold} 相同"
    )
    assert f"{c:.4f}" in reason


def test_anchor_schema_declares_code_group():
    """补 R169 顶掉的同名声明用例（L3 plan 漏项，波次 6 F6-②）。

    为什么值得单独立一条：schema/trace.schema.json 里删掉 code_group 声明，
    产品代码和现有测试照样全绿——schema 是最后一道守门，声明没了没人报警。
    这里钉住「properties 里有 code_group、类型 string、且不在 required」：
    回退路径不写 code_group，所以它必须保持可选。
    """
    p = Path(__file__).resolve().parents[1] / "schema" / "trace.schema.json"
    anchor = json.loads(p.read_text(encoding="utf-8"))["$defs"]["anchor"]
    assert anchor["properties"]["code_group"] == {"type": "string"}, (
        "code_group 必须留在 $defs.anchor.properties，且类型是 string")
    assert "code_group" not in anchor["required"], (
        "回退路径不写 code_group，它必须保持可选，不许进 required")

