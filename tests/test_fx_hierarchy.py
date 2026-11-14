"""M1a 二层守卫：算子节点必须挂在真实的模块层级下。

反例是「所有节点 parent_id 都是 root」——那样 UI 的 module 视图等于没做，
而且用户点开 Attention 会看到一堆无主的算子。
"""

import pytest

torch = pytest.importorskip("torch", reason="fx 追踪需要 torch（CPU 版即可）")

from papertrace.parse_code.fx_trace import trace_module  # noqa: E402
from tests.fixtures.nanogpt.model import GPT, GPTConfig  # noqa: E402


def _doc():
    cfg = GPTConfig(
        n_embd=32,
        n_head=4,
        n_layer=1,
        block_size=8,
        vocab_size=64,
        dropout=0.0,
        bias=False,
    )
    model = GPT(cfg).eval()
    idx = torch.randint(0, 64, (2, 6))
    return trace_module(model, (idx,), module_id="gpt")


def test_module_nodes_exist_and_are_unique():
    doc = _doc()
    modules = [n for n in doc["nodes"] if n["level"] == "module"]
    assert len(modules) > 5, "GPT 应该拆出 Embedding/Block/Attention/MLP..."
    ids = [n["id"] for n in modules]
    assert len(ids) == len(set(ids)), "模块 id 重复"


def test_every_op_has_a_module_parent():
    doc = _doc()
    by_id = {n["id"]: n for n in doc["nodes"]}
    ops = [n for n in doc["nodes"] if n["level"] == "op"]
    assert ops
    for node in ops:
        parent = node["parent_id"]
        assert parent in by_id, f"{node['id']} 的 parent_id {parent} 不存在"
        assert by_id[parent]["level"] == "module"


def test_parent_chain_terminates_at_root():
    doc = _doc()
    by_id = {n["id"]: n for n in doc["nodes"]}
    root = [n for n in doc["nodes"] if n["level"] == "module" and n["parent_id"] is None]
    assert len(root) == 1
    for node in doc["nodes"]:
        seen, cur = set(), node
        while cur["parent_id"] is not None:
            assert cur["id"] not in seen, f"{node['id']} 的父子链成环"
            seen.add(cur["id"])
            cur = by_id[cur["parent_id"]]
        assert cur["id"] == root[0]["id"]


def test_attention_ops_hang_under_the_attention_module():
    """Attention 下必须真有一整套算子，不是「随便哪个 matmul 在 attn 下」就过。"""
    doc = _doc()
    by_id = {n["id"]: n for n in doc["nodes"]}
    attn_ids = {
        n["id"]
        for n in doc["nodes"]
        if n["level"] == "module" and n["op"] == "CausalSelfAttention"
    }
    assert attn_ids
    under = [n for n in doc["nodes"] if n["level"] == "op" and n["parent_id"] in attn_ids]
    ops = {n["op"] for n in under}
    assert len(under) >= 4, f"attn 下只有 {len(under)} 个算子"
    # 注意力必须真算出来：qk^T、mask、softmax、乘 V 四步缺一不可
    assert "matmul" in ops, ops
    assert "masked_fill" in ops, ops
    assert "softmax" in ops, ops
    assert {"transpose", "view"} & ops, ops
    # 而且 attention 的算子不能一串全挂在 root 下冒充
    root_like = [
        n
        for n in doc["nodes"]
        if n["level"] == "op" and n["op"] in {"softmax", "masked_fill"} and "attn" not in by_id[n["parent_id"]]["label"]
    ]
    assert not root_like, f"这些节点没挂进 attention：{[n['id'] for n in root_like]}"


def test_attention_module_is_a_child_of_its_block():
    doc = _doc()
    by_id = {n["id"]: n for n in doc["nodes"]}
    attn = [n for n in by_id.values() if n["level"] == "module" and n["op"] == "CausalSelfAttention"]
    assert attn
    parent = by_id[attn[0]["parent_id"]]
    assert parent["op"] == "Block", parent["op"]
