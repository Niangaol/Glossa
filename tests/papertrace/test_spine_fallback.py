"""S15 回退层的单元测试（R112 / R117 / R118）。

这一层是「结构没对上时还要不要问 judge」的闸门：放行候选，但把绿线锁死。
"""

from __future__ import annotations

import pytest

from papertrace.parse_paper.split_terms import Term
from papertrace.spine.fallback import cap_tier, pairs_or_fallback, resolve_code_range


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
    import papertrace.spine.fallback as fb

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


def _matmul_nodes(count: int) -> list[dict]:
    """count 个同型算子节点：全都对一个 matmul 项有资格，用来把预算撑爆。"""
    return [{"id": f"root/@m{i}", "level": "op", "kind": "op", "op": "matmul",
             "label": f"root.matmul{i}"} for i in range(count)]


def test_fallback_budget_defaults_are_pinned_by_signature_and_behaviour():
    """S15 预算：per_term_limit=3 / total_limit=12 既是签名默认值，也真的在截断候选。

    原有断言只写 `set(grouped) <= {0,1,2}`——那测的是「键是 term.index」，压根没碰预算
    （D-M-4）。这里用 5 个 term × 9 个同型资格节点把两个上限同时撑爆。
    """
    import inspect

    import papertrace.spine.fallback as fb

    params = inspect.signature(fb.pairs_or_fallback).parameters
    assert params["per_term_limit"].default == 3, "每项候选的默认上限就是 3"
    assert params["total_limit"].default == 12, "合计候选的默认上限就是 12"

    # ① 单个 term 面对 9 个资格候选 → 只拿 3 个（per_term_limit 真的在截断）
    single_grouped, single_fallback = pairs_or_fallback(_Signal([]), _terms()[:1], _matmul_nodes(9))
    assert single_fallback is True
    assert list(single_grouped) == [0]
    assert len(single_grouped[0]) == 3, "单 term 超过 per_term_limit 必须被截到 3 个"

    # ② 5 个 term 抢 9 个同型资格节点 → 每项 ≤3 且合计 ≤12（total_limit 真的在截断）
    flood_terms = [Term(i, "QK^{T}", "matmul") for i in range(5)]
    grouped, fallback = pairs_or_fallback(_Signal([]), flood_terms, _matmul_nodes(9))
    assert fallback is True
    assert set(grouped) <= {0, 1, 2, 3, 4}
    for index, ids in grouped.items():
        assert len(ids) <= 3, f"term {index} 拿了 {len(ids)} 个候选，超过每项上限 3"
    total = sum(len(ids) for ids in grouped.values())
    assert total <= 12, f"回退候选合计 {total} 个，超过 total_limit=12"
    assert total == 12, "预算按 term.index 升序分配：前四项各 3 个正好用尽 12"
    assert 4 not in grouped, "预算耗尽后第五项如实为空，不凑对"


def test_resolve_range_uses_confirmed_node_on_fallback():
    """"R117：回退路径只指认 judge 确认的那一个节点，绝不按首尾区间扩张。"""
    assert resolve_code_range(["root/@1", "root/@2", "root/@3"], "root/@2", True) == "root/@2"
    assert resolve_code_range(["root/@1", "root/@2"], "root/@2", True) == "root/@2"


def test_resolve_range_keeps_first_last_on_structure_path():
    """结构路径的字面格式没变：单节点原样，多节点 first..last。"""
    assert resolve_code_range(["root/@1"], None, False) == "root/@1"
    assert resolve_code_range(["root/@1", "root/@2", "root/@3"], None, False) == "root/@1..root/@3"
    assert resolve_code_range([], None, False) == ""


def test_resolve_range_never_spans_on_fallback_even_without_confirmed():
    """R158：回退路径一律单节点——judge 没确认（confirmed=None）时也不许按首尾区间扩张。

    回退路径上 s_judge=0 也照样出黄线（s_retr=1 时 c≈0.46 ≥ 0.45，R147），
    此时 confirmed 是 None；老实现在这里会写 first..last，把整组没审过的
    候选画成一条线。所以 fallback=True 时必须落到第一个节点。
    """
    assert resolve_code_range(["root/@1", "root/@2", "root/@3"], None, True) == "root/@1"
    assert resolve_code_range(["a", "b", "c"], "b", True) == "b"
    # 结构路径一个字都不动：三节点仍是 first..last
    assert resolve_code_range(["a", "b", "c"], None, False) == "a..c"


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
