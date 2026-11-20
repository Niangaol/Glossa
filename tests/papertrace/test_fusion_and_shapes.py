"""M1a 的两个失效模式：融合算子吞掉中间算子、多输出算子的形状链断在自己输出里。

这两条都不是「看起来能跑」能发现的，必须专门盯。
"""

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch")

import torch  # noqa: E402
import torch.nn as nn  # noqa: E402
from torch.nn import functional as F  # noqa: E402

from papertrace.build.trace import fused_ops_in  # noqa: E402
from papertrace.parse_code.fx_edges import _producer_item  # noqa: E402
from papertrace.parse_code.fx_shapes import (  # noqa: E402
    navigate,
    shape_tree,
    tree_leaf,
    tree_shapes,
)
from papertrace.parse_code.fx_trace import trace_module  # noqa: E402


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


def test_shape_tree_helpers_answer_only_when_they_can():
    """形状树：没有信息就返回 None（未核实），绝不猜一个「看起来合理」的形状。"""

    class T:
        def __init__(self, shape):
            self.shape = shape

    assert shape_tree(T((2, 3))) == {"t": [2, 3]}
    assert shape_tree([T((2, 3)), T((4,))]) == {"l": [{"t": [2, 3]}, {"t": [4]}]}
    assert shape_tree({"x": T((1,))}) == {"d": {"x": {"t": [1]}}}
    assert shape_tree(3) is None

    assert tree_leaf({"t": [2, 3]}) == [2, 3]
    assert tree_leaf({"l": [{"t": [2, 3]}]}) is None
    assert tree_leaf(None) is None
    assert tree_shapes({"l": [{"t": [2, 3]}, {"l": [{"t": [1]}]}]}) == [[2, 3], [1]]

    tree = {"d": {"args": {"l": [{"t": [2, 3]}, {"d": {"y": {"t": [5]}}}]}}}
    assert navigate(tree, ["args", 0]) == {"t": [2, 3]}
    assert navigate(tree, ["args", 1, "y"]) == {"t": [5]}
    assert navigate(tree, ["args", 9]) is None
    assert navigate(tree, ["kwargs", "x"]) is None


def test_producer_item_reads_the_indexed_output_only():
    """getitem 的边形状 = 生产者容器里被取出的那一项；索引不是常量就不猜。"""

    class FakeNode:
        op = "getitem"

        def __init__(self, args):
            self.args = args
            self.kwargs = {}

    observed = {"out": {"l": [{"t": [2, 2]}, {"t": [2, 3]}]}}
    assert _producer_item(observed, FakeNode([None, 0]), [None, 0]) == [2, 2]
    assert _producer_item(observed, FakeNode([None, 1]), [None, 1]) == [2, 3]
    assert _producer_item(observed, FakeNode([None, -1]), [None, -1]) == [2, 3]
    assert _producer_item(observed, FakeNode([None, 5]), [None, 5]) is None
    assert _producer_item(observed, FakeNode([None, "i"]), [None, "i"]) is None
    # 单输出（不是容器）→ 不知道，交给调用方按未核实处理
    assert _producer_item({"out": {"t": [2, 2]}}, FakeNode([None, 0]), [None, 0]) is None

    class NotGetitem(FakeNode):
        op = "add"

    assert _producer_item(observed, NotGetitem([None, 1]), [None, 1]) is None
