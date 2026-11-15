"""S15 回退层的单元测试（R112 / R117 / R118）。

这一层是「结构没对上时还要不要问 judge」的闸门：放行候选，但把绿线锁死。
"""

from __future__ import annotations

import pytest

from papertrace.parse_paper.split_terms import Term
from papertrace.spine_fallback import cap_tier, pairs_or_fallback, resolve_code_range


class _Signal:
    """结构信号的最小替身：本层只消费 .pairs。"""

    def __init__(self, pairs):
        self.pairs = pairs


def _nodes() -> list[dict]:
    return [
        {"id": "root/@1", "level": "op", "kind": "op", "op": "matmul", "label": "root.matmul"},
        {"id": "root/@2", "level": "op", "kind": "op", "op": "mul", "label": "root.mul"},
        {"id": "root/@3", "level": "op", "kind": "op", "op": "softmax", "label": "root.softmax"},
        {"id": "root/w", "level": "op", "kind": "param", "op": "placeholder", "label": "root.w"},
    ]


def _terms() -> list:
    return [Term(0, "QK^{T}", "matmul"), Term(1, r"\sqrt{d_k}", "scale"),
            Term(2, r"\mathrm{softmax}", "norm")]


def test_pairs_win_over_fallback(monkeypatch):
    """结构配对存在时，候选生成器一次都不许被调用（省 API、也守住 R37 的语义）。"""
    import papertrace.spine_fallback as fb

    def _boom(*args, **kwargs):
        raise AssertionError("结构已经有配对，不该退到词法候选")

    monkeypatch.setattr(fb, "candidate_pairs", _boom)
    grouped, fallback = fb.pairs_or_fallback(_Signal([(0, "root/@1"), (1, "root/@2")]),
                                             _terms(), _nodes())
    assert grouped == {0: ["root/@1"], 1: ["root/@2"]}
    assert fallback is False


def test_empty_pairs_fall_back_to_kind_candidates():
    """结构没命中 → 用算子类型候选；连候选都没有时 fallback 必须是 False（空就是空）。"""
    grouped, fallback = pairs_or_fallback(_Signal([]), _terms(), _nodes())
    assert fallback is True
    assert grouped, "回退必须真的拿到候选，否则本层毫无意义"
    assert set(grouped) <= {0, 1, 2}
    assert all(node_id.startswith("root/@") for ids in grouped.values() for node_id in ids)
    assert "root/w" not in [n for ids in grouped.values() for n in ids], "权重不是候选"
    empty, empty_flag = pairs_or_fallback(_Signal([]), [], _nodes())
    assert empty == {} and empty_flag is False


def test_resolve_range_uses_confirmed_node_on_fallback():
    """"R117：回退路径只指认 judge 确认的那一个节点，绝不按首尾区间扩张。"""
    assert resolve_code_range(["root/@1", "root/@2", "root/@3"], "root/@2", True) == "root/@2"
    assert resolve_code_range(["root/@1", "root/@2"], "root/@2", True) == "root/@2"


def test_resolve_range_keeps_first_last_on_structure_path():
    """结构路径的字面格式没变：单节点原样，多节点 first..last。"""
    assert resolve_code_range(["root/@1"], None, False) == "root/@1"
    assert resolve_code_range(["root/@1", "root/@2", "root/@3"], None, False) == "root/@1..root/@3"
    assert resolve_code_range([], None, False) == ""


@pytest.mark.parametrize("level,fallback,expected", [
    ("green", True, "yellow"),
    ("green", False, "green"),
    ("yellow", True, "yellow"),
    ("yellow", False, "yellow"),
    ("none", True, "none"),
    ("none", False, "none"),
])
def test_cap_tier_turns_green_into_yellow_only_on_fallback(level, fallback, expected):
    """R112：回退产的线最高到黄；结构产的线不受影响；none 永远不因为回退变成别的。"""
    assert cap_tier(level, fallback) == expected
