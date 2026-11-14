import importlib

import pytest

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
]


@pytest.mark.parametrize("name", SUBPACKAGES + MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_unimplemented_stubs_raise_not_implemented():
    """占位函数必须明确报未实现，禁止返回 None/空列表冒充结果。"""
    from papertrace.parse_code.fx_trace import trace_module

    with pytest.raises(NotImplementedError):
        trace_module(object(), ())


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
    """守着这条：规格书原式 sigmoid(w·s) 的上限 0.731 达不到 0.75 绿线。

    这条测试存在的意义是防止有人"简化"回去——那会让绿线永远不出现。
    """
    import math

    from papertrace.constants import CONF_GREEN

    assert 1.0 / (1.0 + math.exp(-1.0)) < CONF_GREEN


def test_confidence_midpoint_is_half():
    from papertrace.align.score import confidence

    assert abs(confidence(0.5, 0.5, 0.5) - 0.5) < 1e-9


def test_confidence_is_monotone_in_each_signal():
    from papertrace.align.score import confidence

    for low, high in ((0.0, 1.0), (0.2, 0.9)):
        assert confidence(high, 0.5, 0.5) > confidence(low, 0.5, 0.5)
        assert confidence(0.5, high, 0.5) > confidence(0.5, low, 0.5)
        assert confidence(0.5, 0.5, high) > confidence(0.5, 0.5, low)
