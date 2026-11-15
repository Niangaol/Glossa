"""认领唯一性（spine_claims）的冻结测试：7 条测试名一字不改。

假后端纪律（本项目血泪）：**单实例跨调用**——每次新建实例会重置计数器，会让
「跳过已认领候选」的断言假绿；并且**必须断言被测路径真被走到**（calls 计数），
否则测到的是 offline 兜底路径而不是真判断题。
"""

from __future__ import annotations

import pytest

from papertrace.llm.client import ChatResult
from papertrace import spine
from papertrace.spine_claims import (
    CLAIMED_REASON,
    duplicate_claims,
    judge_first_yes,
    node_text,
    unclaimed,
)

#: 真实 trace 里的算子节点（level=op, kind=op），字段与 fx_nodes 产出一致。
REAL_NODE = {
    "id": "root/@037",
    "level": "op",
    "kind": "op",
    "op": "matmul",
    "label": "matmul_1",
    "loc": "net.py:42",
    "shape_in": [[2, 4], [4, 2]],
    "shape_out": [[2, 2]],
}

#: 缺字段的畸形节点：五个文本字段全缺，node.get 兜底成空串/None。
MALFORMED_NODE = {"id": "root/@999", "level": "op", "kind": "op"}

#: 假后端的固定回答：judge 解析出 yes + 非空依据，judge_score 即 1.0。
FAKE_EVIDENCE = "同一算子的矩阵乘法"


class YesBackend:
    """永远答 yes 的假后端。**单实例跨调用**累计 calls，绝不每次新建。"""

    name = "fake-yes"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, prompt: str, *, system: str | None = None) -> ChatResult:
        self.calls += 1
        return ChatResult(text=f"verdict: yes\nevidence: {FAKE_EVIDENCE}",
                          model="fake-judge", backend="fake-yes")


@pytest.fixture
def yes_backend(monkeypatch) -> YesBackend:
    """把 judge 的 get_llm 换成单实例假后端，返回它以便断言 calls。"""
    backend = YesBackend()
    monkeypatch.setattr("papertrace.align.judge.get_llm", lambda: backend)
    return backend


def test_node_text_keeps_the_frozen_spine_format():
    """逐字钉住搬走前的格式（R152：helper 从 spine.py 搬到 spine_claims.py，输出不许变）。"""
    assert node_text(REAL_NODE) == "matmul matmul_1 net.py:42 in=[[2, 4], [4, 2]] out=[[2, 2]]"
    assert node_text(MALFORMED_NODE) == "in=None out=None"
    assert not hasattr(spine, "_node_text"), "helper 只留一份，别在 spine.py 里复活"


def test_unclaimed_keeps_order_and_does_not_mutate():
    """保序过滤 + 不改入参：['a','b','c'] 去掉 'b' 得 ['a','c']，集合原样。"""
    claimed = {"b"}
    assert unclaimed(["a", "b", "c"], claimed) == ["a", "c"]
    assert claimed == {"b"}


def test_claimed_candidate_is_skipped(yes_backend):
    """第一个候选已被认领 → 只问第二个（假后端 calls == 1）。"""
    by_id = {"n1": REAL_NODE, "n2": {**REAL_NODE, "id": "n2", "label": "matmul_2"}}
    claimed = {"n1"}
    result = judge_first_yes("QK^{T}", ["n1", "n2"], by_id, claimed)
    assert yes_backend.calls == 1
    assert result == (1.0, FAKE_EVIDENCE, "n2")


def test_confirmed_node_id_is_added_to_claimed(yes_backend):
    """命中即认领：三元组 (1.0, 依据, node_id)，claimed 收入该 id。"""
    by_id = {"n1": REAL_NODE}
    claimed: set[str] = set()
    result = judge_first_yes("QK^{T}", ["n1"], by_id, claimed)
    assert result == (1.0, FAKE_EVIDENCE, "n1")
    assert claimed == {"n1"}


def test_all_candidates_claimed_asks_no_judge(yes_backend):
    """全被占 → (0.0, "", None)，一个都不问，claimed 原样不动。"""
    by_id = {"n1": REAL_NODE, "n2": {**REAL_NODE, "id": "n2"}}
    claimed = {"n1", "n2"}
    result = judge_first_yes("QK^{T}", ["n1", "n2"], by_id, claimed)
    assert result == (0.0, "", None)
    assert yes_backend.calls == 0
    assert claimed == {"n1", "n2"}


def test_duplicate_claims_reports_repeated_ids():
    """同一单元内出现两次的 id 升序去重报告：['a', 'b']。"""
    assert duplicate_claims({0: ["a", "b"], 1: ["b", "a"]}) == ["a", "b"]


def test_claimed_reason_mentions_claim_and_same_unit():
    """CLAIMED_REASON 必须同时含「认领」与「同一」（用户看得见的理由）。"""
    assert "认领" in CLAIMED_REASON
    assert "同一" in CLAIMED_REASON
