"""第九轮评审的回归测试：orphan 的双向语义、未知/错位 kind 的 fail-closed。

I-1  orphan = **既无入边也无出边**。只看入边会把「被下游用着的随机源」误报成孤点，
     而真正的死算子反而漏掉；常量源不再需要豁免名单（被用着就有出边）。
I-2  不认识的 InputKind 不许默认成 input；plan 里同一个名字不能既是权重又是输入，
     也不能有图里不存在的幽灵名。kind 的**正确性**由 placeholder_args 拿模块真实参数核对。
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import torch  # noqa: E402
from torch.export.graph_signature import InputKind  # noqa: E402

from papertrace.build_trace import build_trace  # noqa: E402
from papertrace.exceptions import BuildError, TraceUnsupported  # noqa: E402
from papertrace.parse_code.fx_edges import build_edges, finish_nodes  # noqa: E402
from papertrace.parse_code.fx_nodes import build_op_nodes  # noqa: E402
from papertrace.parse_code.fx_signature import (  # noqa: E402
    KIND_MAP,
    classify,
    input_plan,
    placeholder_args,
)
from papertrace.parse_code.fx_trace import _ensure_export_cache  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402
from tests.test_seventh_review import ENTRY, _write_repo  # noqa: E402


def _node(nid: str, op: str) -> dict:
    return {
        "id": nid, "level": "op", "kind": "op", "op": op,
        "outputs": [[2, 4]], "degraded": False,
    }


def _edge(src: str, dst: str) -> dict:
    return {"id": f"e:{src}->{dst}", "src": src, "dst": dst,
            "checked": True, "shape_consistent": True}


# ---------------------------------------------------------------- I-1 orphan

def test_source_with_a_consumer_is_not_an_orphan():
    """b 有出边、无入边：它是数据源，不是孤点。旧实现（只看入边）会把它数进去。"""
    nodes = [_node("a", "add"), _node("b", "rand")]
    counts = finish_nodes(nodes, [_edge("b", "a")])
    assert counts["orphan"] == 0, counts


def test_dead_end_with_incoming_is_not_an_orphan_either():
    """a 有入边、没人用：按 README 的定义（既无入边也无出边）它不算孤点。"""
    nodes = [_node("a", "add"), _node("b", "rand"), _node("c", "mul")]
    counts = finish_nodes(nodes, [_edge("b", "a")])
    assert counts["orphan"] == 1, counts  # 只有 c 是双向都断的


def test_used_constant_source_is_not_an_orphan():
    nodes = [_node("k", "ones"), _node("c", "cat")]
    assert finish_nodes(nodes, [_edge("k", "c")])["orphan"] == 0


def test_unused_constant_source_is_an_orphan():
    """常量豁免名单已删：一个谁都不用的 torch.ones 就是死代码，该被数出来。"""
    assert finish_nodes([_node("k", "ones")], [])["orphan"] == 1


def test_random_source_consumed_downstream_is_not_an_orphan_end_to_end():
    """I-1 的真实复现：torch.rand 被 add 用着，orphan 必须是 0（旧实现报 1）。"""
    repo = _write_repo("orphan-rand", """import torch
import torch.nn as nn


class M(nn.Module):
    def forward(self, x):
        return x + torch.rand(2, 4)

    def example_inputs(self):
        return torch.ones(2, 4)


def build_model():
    return M().eval()
""")
    doc = build_trace(repo, entry=ENTRY)
    counts = doc["meta"]["runtime"]["counts"]
    assert counts["orphan"] == 0, counts
    rand = [n for n in doc["nodes"] if n.get("op") == "rand"]
    assert rand, "图里该有 rand 源"
    assert any(e["src"] == rand[0]["id"] for e in doc["edges"]), "rand 该有出边"


def test_like_edges_are_checked_and_consistent():
    """M-1：只断言边存在不够——checked/shape_consistent 被打坏也要能红。"""
    repo = _write_repo("like-edges", """import torch
import torch.nn as nn


class M(nn.Module):
    def forward(self, x, y):
        return torch.cat([torch.ones_like(x), y], dim=1)

    def example_inputs(self):
        return torch.ones(2, 4), torch.ones(2, 6)


def build_model():
    return M().eval()
""")
    doc = build_trace(repo, entry=ENTRY)
    like = next(n for n in doc["nodes"] if n.get("op") == "ones_like")
    cat = next(n for n in doc["nodes"] if n.get("op") == "cat")
    x = next(n for n in doc["nodes"] if n.get("kind") == "input")
    into_like = [e for e in doc["edges"] if e["dst"] == like["id"]]
    assert into_like, "x -> ones_like 的边不能消失"
    assert all(e["checked"] and e["shape_consistent"] for e in into_like), into_like
    out_of_like = [e for e in doc["edges"] if e["src"] == like["id"] and e["dst"] == cat["id"]]
    assert out_of_like, "ones_like -> cat 的边不能消失"
    assert all(e["checked"] and e["shape_consistent"] for e in out_of_like), out_of_like
    assert cat["shape_in"] == [2, 6], cat["shape_in"]
    assert x["id"] != like["id"]


# ---------------------------------------------------------------- I-2 kind

def test_unknown_input_kind_is_refused_not_downgraded_to_input():
    spec = SimpleNamespace(arg=SimpleNamespace(name="p_w"),
                           kind=SimpleNamespace(name="WEIGHT"), target="w")
    exported = SimpleNamespace(graph_signature=SimpleNamespace(input_specs=[spec]))
    with pytest.raises(BuildError) as info:
        input_plan(exported)
    assert "不认识的 InputKind" in str(info.value), str(info.value)
    assert "WEIGHT" in str(info.value), str(info.value)


def test_known_input_kind_still_maps():
    """反向对照：认识的 kind 必须照常映射，否则上一条是恒真断言。"""
    spec = SimpleNamespace(arg=SimpleNamespace(name="p_w"),
                           kind=SimpleNamespace(name="PARAMETER"), target="w")
    exported = SimpleNamespace(graph_signature=SimpleNamespace(input_specs=[spec]))
    assert input_plan(exported)[0]["kind"] == "param"


def test_kind_map_covers_every_torch_input_kind():
    """torch 加了新 InputKind 时这条会红——那时该补映射，而不是让它静默变 input。"""
    assert set(KIND_MAP) == {k.name for k in InputKind}, sorted(
        {k.name for k in InputKind} - set(KIND_MAP)
    )


def test_classify_refuses_unknown_kind():
    with pytest.raises(BuildError) as info:
        classify([{"name": "x", "kind": "weight", "target": None}])
    assert "不认识" in str(info.value), str(info.value)


class _ParamAndInput(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.w = torch.nn.Parameter(torch.ones(4))

    def forward(self, x):
        return x + self.w


def _exported():
    _ensure_export_cache()
    module = _ParamAndInput().eval()
    return module, torch.export.export(module, (torch.ones(4),))


def test_plan_cannot_label_one_name_both_param_and_input():
    module, exported = _exported()
    plan = classify(input_plan(exported))
    plan["params"] = set(plan["params"]) | set(plan["inputs"])
    with pytest.raises(BuildError) as info:
        build_op_nodes(exported.graph, "root", {"root": "root"}, "root", plan=plan)
    assert "同时被标成权重和数据输入" in str(info.value), str(info.value)


def test_plan_with_a_ghost_placeholder_is_refused():
    module, exported = _exported()
    plan = classify(input_plan(exported))
    plan["params"] = set(plan["params"]) | {"ghost"}
    with pytest.raises(BuildError) as info:
        build_op_nodes(exported.graph, "root", {"root": "root"}, "root", plan=plan)
    assert "图里不存在的 placeholder" in str(info.value), str(info.value)


def test_flipped_kind_is_caught_against_the_modules_real_parameters():
    """名字覆盖齐全、kind 却标反：build_op_nodes 无从判断，但 placeholder_args
    拿模块真实参数核对，必须拒绝——这是 kind 正确性的权威关卡。"""
    module, exported = _exported()
    plan = input_plan(exported)
    flipped = [dict(item) for item in plan]
    for item in flipped:
        if item["kind"] == "input":
            item["kind"], item["target"] = "param", "x"  # 模块里没有叫 x 的参数
    with pytest.raises(TraceUnsupported) as info:
        placeholder_args(module, exported, flipped, ())
    assert "是权重" in str(info.value) and "找不到" in str(info.value), str(info.value)
