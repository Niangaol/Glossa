"""M1a 核心守卫：nanoGPT 的 Attention 必须是 4 个独立算子，形状来自真实执行。

这些测试的意义不是「代码能跑」，而是钉住产品的立身之本：
如果 QKᵀ / scale / mask / softmax 被融合（或我们自己把它们编成一个节点），
PaperTrace 就没有东西可以对账了。
"""

import pytest

torch = pytest.importorskip("torch", reason="fx 追踪需要 torch（CPU 版即可）")

from papertrace.parse_code.fx_trace import trace_module  # noqa: E402
from tests.fixtures.nanogpt.model import CausalSelfAttention, GPTConfig  # noqa: E402

REQUIRED_NODE_FIELDS = {
    "id",
    "level",
    "op",
    "label",
    "loc",
    "shape_in",
    "shape_out",
    "dtype",
    "inplace",
    "source",
    "degraded",
    "repeat",
    "stale",
}


def _trace():
    cfg = GPTConfig(
        n_embd=32,
        n_head=4,
        n_layer=1,
        block_size=8,
        vocab_size=64,
        dropout=0.0,
        bias=False,
    )
    module = CausalSelfAttention(cfg).eval()
    x = torch.randn(2, 6, 32)
    return trace_module(module, (x,), module_id="attn")


def _ops(doc):
    return [n["op"] for n in doc["nodes"]]


def test_attention_ops_are_not_fused():
    """四个算子必须同时出现在图上。缺任何一个都说明 flash/SDPA 路径生效了。"""
    ops = _ops(_trace())
    for want in ("matmul", "mul", "masked_fill", "softmax"):
        assert any(want in op for op in ops), f"没有 {want} 节点；实际算子：{ops}"


def test_no_scaled_dot_product_attention_node():
    assert not any("scaled_dot_product_attention" in op for op in _ops(_trace()))


def test_shapes_follow_the_attention_math():
    doc = _trace()
    qk = [n for n in doc["nodes"] if n["op"].endswith("matmul")][0]
    # (B=2, n_head=4, T=6, T=6)
    assert qk["shape_out"] == [2, 4, 6, 6], qk["shape_out"]
    softmax = [n for n in doc["nodes"] if n["op"].endswith("softmax")][0]
    assert softmax["shape_out"] == qk["shape_out"]


def test_edges_are_shape_consistent():
    doc = _trace()
    assert doc["edges"], "一条边都没有，说明数据流没接对"
    broken = [e for e in doc["edges"] if not e["shape_consistent"]]
    assert not broken, f"形状对不上的边：{broken[:3]}"


def test_nodes_carry_every_schema_required_field():
    for node in _trace()["nodes"]:
        missing = REQUIRED_NODE_FIELDS - set(node)
        assert not missing, f"{node['id']} 缺字段 {missing}"
        if node["level"] == "op":
            assert node["source"] == "runtime", "算子节点的形状必须来自真实执行"
            # split 这类多输出算子表达不了，允许 degraded，但必须写明原因
            assert node["degraded"] is False or node["degraded_reason"]
        else:
            assert node["source"] == "static", "模块层级来自代码结构，不是执行"


def test_missing_torch_raises_runtime_unavailable(monkeypatch):
    """没 torch 时必须是显式错误，不能是裸 ImportError，更不能写空 trace。"""
    from papertrace import parse_code

    fx = parse_code.fx_trace

    def boom():
        raise fx.RuntimeUnavailable("没有 torch")

    monkeypatch.setattr(fx, "_require_torch", boom)
    with pytest.raises(fx.RuntimeUnavailable):
        fx.trace_module(object(), ())
