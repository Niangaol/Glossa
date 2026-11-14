"""M1a 的两个失效模式：融合算子吞掉中间算子、多输出算子的形状链断在自己输出里。

这两条都不是「看起来能跑」能发现的，必须专门盯。
"""

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch")

import torch  # noqa: E402
import torch.nn as nn  # noqa: E402
from torch.nn import functional as F  # noqa: E402

from papertrace.build_trace import fused_ops_in  # noqa: E402
from papertrace.parse_code.fx_trace import _resolve_arg_shape, trace_module  # noqa: E402


class _SdpaOnly(nn.Module):
    def forward(self, q, k, v):
        return F.scaled_dot_product_attention(q, k, v, is_causal=True)


class _SplitUneven(nn.Module):
    def forward(self, x):
        a, b = torch.split(x, [2, 3], dim=-1)
        return a.sum(-1) + b.sum(-1)


def _op(doc, name):
    return [n for n in doc["nodes"] if n["level"] == "op" and n["op"] == name]


def test_fused_attention_is_flagged_not_silently_accepted():
    """SDPA 一个算子吞了 matmul/scale/mask/softmax；不标出来就是静默漏检。"""
    q = torch.randn(2, 4, 6, 8)
    doc = trace_module(_SdpaOnly(), (q, q, q))

    sdpa = _op(doc, "scaled_dot_product_attention")
    assert len(sdpa) == 1, [n["op"] for n in doc["nodes"]]
    node = sdpa[0]
    assert node["degraded"] is True, "融合算子必须标 degraded"
    reason = node["degraded_reason"] or ""
    assert "融合" in reason
    for swallowed in ("matmul", "scale", "mask", "softmax"):
        assert swallowed in reason, f"reason 没写清吞了什么：{reason}"

    # 图里确实没有分开的算子——这正是要报警的原因
    assert not _op(doc, "matmul")
    assert not _op(doc, "softmax")
    assert fused_ops_in(doc) == ["scaled_dot_product_attention"]


def test_split_items_keep_their_own_shapes_in_edges():
    """split(x, [2,3]) 的两项是 (2,2) 和 (2,3)；边不能一律记成 (2,2)。"""
    doc = trace_module(_SplitUneven(), (torch.randn(2, 5),))

    getitems = _op(doc, "getitem")
    assert len(getitems) == 2
    outs = sorted(n["shape_out"] for n in getitems)
    assert outs == [[2, 2], [2, 3]]

    by_id = {n["id"]: n for n in doc["nodes"]}
    for gi in getitems:
        incoming = [e for e in doc["edges"] if e["dst"] == gi["id"]]
        assert incoming, "getitem 没有入边"
        edge = incoming[0]
        assert edge["shape"] == gi["shape_out"], (
            f"边形状 {edge['shape']} 与节点形状 {gi['shape_out']} 不一致"
        )
        assert gi["shape_in"] == gi["shape_out"]
        assert edge["shape_consistent"] is True

    # 消费 (2,3) 那一项 sum 的入参必须是 (2,3)
    sums = {tuple(n["shape_in"]): n for n in doc["nodes"] if n["op"] == "sum"}
    assert (2, 3) in sums, f"没有消费 (2,3) 的 sum：{list(sums)}"

    producer = [n for n in doc["nodes"] if n["op"] == "split_with_sizes"][0]
    assert producer["degraded"] is True
    assert "共 2 项" in (producer["degraded_reason"] or "")
    assert all(e["shape_consistent"] for e in doc["edges"])


def test_resolve_arg_shape_only_answers_when_it_can():
    class FakeArg:
        op = "getitem"

        def __init__(self, args):
            self.args = args

    shapes = [[2, 2], [2, 3]]
    assert _resolve_arg_shape(FakeArg([None, 0]), shapes) == [2, 2]
    assert _resolve_arg_shape(FakeArg([None, 1]), shapes) == [2, 3]
    assert _resolve_arg_shape(FakeArg([None, -1]), shapes) == [2, 3]
    # 索引越界 → 不知道，交给调用方按断链处理
    assert _resolve_arg_shape(FakeArg([None, 5]), shapes) is None
    # 单输出、非 getitem、索引不是常量 → 都不猜
    assert _resolve_arg_shape(FakeArg([None, 0]), [[2, 2]]) is None
    assert _resolve_arg_shape(FakeArg([None, 0]), shapes) == [2, 2]

    class NotGetitem(FakeArg):
        op = "add"

    assert _resolve_arg_shape(NotGetitem([None, 1]), shapes) is None
    assert _resolve_arg_shape(FakeArg([None, "i"]), shapes) is None
