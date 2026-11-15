import importlib

import pytest

from papertrace.exceptions import LLMUnavailable

SUBPACKAGES = [
    "papertrace.ingest",
    "papertrace.parse_code",
    "papertrace.parse_paper",
    "papertrace.symbols",
    "papertrace.align",
    "papertrace.diff",
    "papertrace.trace_runtime",
    "papertrace.detail",
    "papertrace.llm",
]

MODULES = [
    "papertrace.constants",
    "papertrace.ingest.repo",
    "papertrace.ingest.paper",
    "papertrace.ingest.arxiv",
    "papertrace.parse_code.fx_trace",
    "papertrace.parse_code.loc",
    "papertrace.parse_code.einops_expand",
    "papertrace.parse_code.loop_fold",
    "papertrace.parse_code.treesitter_fallback",
    "papertrace.parse_code.export_try",
    "papertrace.parse_paper.units",
    "papertrace.parse_paper.split_terms",
    "papertrace.parse_paper.latex_safe",
    "papertrace.symbols.code_table",
    "papertrace.symbols.paper_table",
    "papertrace.symbols.mapping",
    "papertrace.symbols.shape_prop",
    "papertrace.align.embed",
    "papertrace.align.retrieve",
    "papertrace.align.judge",
    "papertrace.align.score",
    "papertrace.align.candidates",
    "papertrace.diff.dim",
    "papertrace.diff.struct",
    "papertrace.diff.missing",
    "papertrace.diff.reverse",
    "papertrace.trace_runtime.discover",
    "papertrace.trace_runtime.probe",
    "papertrace.trace_runtime.profile",
    "papertrace.detail.l0",
    "papertrace.detail.l1",
    "papertrace.detail.l2",
    "papertrace.detail.l3",
    "papertrace.detail.closure",
    "papertrace.detail.cache",
    "papertrace.detail.stale",
    "papertrace.detail.annotations",
    "papertrace.spine_fallback",
    "papertrace.spine_claims",
    "papertrace.paths",
]


@pytest.mark.parametrize("name", SUBPACKAGES + MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_untraceable_input_is_refused_explicitly():
    """追不动就报 TraceUnsupported，绝不给一张空图冒充追踪结果。"""
    pytest.importorskip("torch", reason="需要 torch 才能走到 export")
    from papertrace.exceptions import TraceUnsupported
    from papertrace.parse_code.fx_trace import trace_module

    with pytest.raises((TraceUnsupported, AttributeError, TypeError)):
        trace_module(object(), ())


def test_align_never_fakes_results():
    """对齐三件套都不许造结果：offline 下 judge 必须诚实归零；
    S6 之后 embed / retrieve 已实现，同样断言它们 offline 时诚实归零——
    judge 若写成 `return JudgeResult(True, "")`、embed 若返回假向量，
    都会制造假绿线，这是本切片最该防的失败模式。

    S7 起 judge 已实现（Task S7）：offline 下 `judge("x", "y")` 返回
    `JudgeResult(False, "")` 且 `judge_score == 0.0`（R49：`JudgeResult`
    没有 reason 字段，那句给用户看的 reason 由 S9 写进 unresolved / anchor）。"""
    from papertrace.align.embed import embed_texts
    from papertrace.align.judge import JudgeResult, judge, judge_score
    from papertrace.align.retrieve import retrieve_bidirectional

    result = judge("x", "y")
    assert result == JudgeResult(False, "")
    assert judge_score(result) == 0.0
    # R44：embed_texts 只转调，offline 就把 LLMUnavailable 原样抛出来
    with pytest.raises(LLMUnavailable):
        embed_texts(["x"])
    # R41/R42/R44：retrieve 是唯一捕获点 → 归零 + 空表 + reason，不兜底 0.5
    empty = retrieve_bidirectional([], [])
    assert empty["s_retr"] == 0.0
    assert empty["forward"] == {} and empty["backward"] == {}
    assert empty["conflicts"] == []
    assert isinstance(empty["reason"], str) and empty["reason"].strip()


def test_constants_freeze_weights():
    from papertrace.constants import W_JUDGE, W_RETR, W_STRUCT

    assert (W_RETR, W_JUDGE, W_STRUCT) == (0.30, 0.50, 0.20)
    assert abs(sum((W_RETR, W_JUDGE, W_STRUCT)) - 1.0) < 1e-9


def test_confidence_thresholds():
    from papertrace.align.score import confidence
    from papertrace.constants import CONF_GREEN, CONF_YELLOW

    assert confidence(1.0, 1.0, 1.0) > CONF_GREEN
    assert confidence(0.0, 0.0, 0.0) < CONF_YELLOW
    assert confidence(0.9, 1.0, 0.8) > confidence(0.4, 0.0, 0.5)


def test_naive_sigmoid_could_never_reach_green():
    """规格书原式 sigmoid(w·s) 的上限 0.731 达不到 0.75 绿线——这是改公式的理由。

    注意：这只是**考古**，它证明的是规格书自相矛盾，不约束我们的实现。
    真正约束实现的是下面 test_gain_and_center_are_pinned 与边界测试。
    """
    import math

    from papertrace.constants import CONF_GREEN

    assert 1.0 / (1.0 + math.exp(-1.0)) < CONF_GREEN


def test_gain_and_center_are_pinned():
    """增益/中心是产品语义所在，必须钉死：gain 调大就会让两个门槛同时饱和失效。"""
    from papertrace.constants import SIGMOID_CENTER, SIGMOID_GAIN

    assert SIGMOID_GAIN == 4.0
    assert SIGMOID_CENTER == 0.5


def test_confidence_boundaries_straddle_both_thresholds():
    """绿线/黄线两侧各给一个点：公式随便改都会在这里露馅。"""
    from papertrace.align.score import confidence
    from papertrace.constants import CONF_GREEN, CONF_YELLOW

    # 三项都 1.0 → 绿；三项都 0.75 → 黄（低于绿线，说明绿线不是随便就能到）
    assert confidence(1.0, 1.0, 1.0) > CONF_GREEN
    assert confidence(0.75, 0.75, 0.75) < CONF_GREEN
    # 刚好跨过绿线的位置：a=0.775 → 绿；a=0.77 → 不绿
    assert confidence(0.775, 0.775, 0.775) > CONF_GREEN
    assert confidence(0.77, 0.77, 0.77) < CONF_GREEN
    # 黄线两侧
    assert confidence(0.52, 0.52, 0.52) > CONF_YELLOW
    assert confidence(0.44, 0.44, 0.44) < CONF_YELLOW


def test_confidence_matches_documented_values():
    """docstring 里写的那三个数必须是真的（实测 0.881 / 0.500 / 0.231）。"""
    from papertrace.align.score import confidence

    assert abs(confidence(1.0, 1.0, 1.0) - 0.881) < 5e-4
    assert abs(confidence(0.5, 0.5, 0.5) - 0.500) < 5e-4
    assert abs(confidence(0.2, 0.2, 0.2) - 0.231) < 5e-4


def test_confidence_midpoint_is_half():
    from papertrace.align.score import confidence

    assert abs(confidence(0.5, 0.5, 0.5) - 0.5) < 1e-9


def test_confidence_is_monotone_in_each_signal():
    from papertrace.align.score import confidence

    for low, high in ((0.0, 1.0), (0.2, 0.9)):
        assert confidence(high, 0.5, 0.5) > confidence(low, 0.5, 0.5)
        assert confidence(0.5, high, 0.5) > confidence(0.5, low, 0.5)
        assert confidence(0.5, 0.5, high) > confidence(0.5, 0.5, low)
