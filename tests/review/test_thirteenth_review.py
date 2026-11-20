"""第十三轮评审的回归测试：target 互换——四张表全不变，只有图自己记的形状看得见。

I-1 评审探针（output/review12/probe13x.py）实测：在**真** ExportedProgram 上互换两个
    参数的 target，check_contract / check_plan_source / check_plan_table 全过，trace 把
    p_a 记成 b 的形状、p_b 记成 a 的形状，而 shape_broken 仍是 0。
    修法：placeholder_args 解析出真实张量后，与 node.meta["val"] 的形状核对——那是导出器
    在图上做 fake 传播的结果，与 input_specs 的 target 映射是**两个独立字段**。
    第十四轮补：同形状互换**也**被拒（fx_names 的名字↔target 核对），因为跨模块时
    parent_id 会写反；本文件原来那条「不可观测」用例已按事实改写。
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import torch  # noqa: E402
from torch import nn  # noqa: E402
from torch.export.graph_signature import InputKind  # noqa: E402

from papertrace.exceptions import BuildError  # noqa: E402
from papertrace.parse_code.fx_contract import (  # noqa: E402
    check_contract,
    check_plan_source,
    check_plan_table,
)
from papertrace.parse_code.fx_shapes import check_value_shape  # noqa: E402
from papertrace.parse_code.fx_signature import (  # noqa: E402
    classify,
    input_plan,
    placeholder_args,
)
from tests._tmp import scratch_dir  # noqa: E402
from tests.review.test_seventh_review import ENTRY, _write_repo  # noqa: E402
from tests.review.test_twelfth_review import _build, _exported  # noqa: E402

ONE = (torch.zeros(2, 4),)
WEIGHT_KINDS = (InputKind.PARAMETER, InputKind.BUFFER)


class TwoParams(nn.Module):
    """两个**不同形状**的参数：互换 target 会让权重形状被记反。"""

    def __init__(self):
        super().__init__()
        self.a = nn.Parameter(torch.ones(2, 4))
        self.b = nn.Parameter(torch.ones(1, 4))

    def forward(self, x):
        return x + self.a + self.b


class ParamBuf(nn.Module):
    def __init__(self):
        super().__init__()
        self.a = nn.Parameter(torch.ones(2, 4))
        self.register_buffer("b", torch.ones(1, 4))

    def forward(self, x):
        return x + self.a + self.b


class TwoConsts(nn.Module):
    def __init__(self):
        super().__init__()
        self.p = torch.ones(2, 4)
        self.q = torch.ones(1, 4)

    def forward(self, x):
        return x + self.p + self.q


class TwoSame(nn.Module):
    """同形状：互换 target 不可观测，本切片不假装抓得住。"""

    def __init__(self):
        super().__init__()
        self.a = nn.Parameter(torch.ones(2, 4))
        self.b = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.a + self.b


class IntArg(nn.Module):
    def forward(self, x, k):
        return x * k


def _swap_targets(exported, kinds=WEIGHT_KINDS):
    """就地改**真**产物的 input_specs：前两个权重/常量的 target 互换。"""
    specs = [s for s in exported.graph_signature.input_specs if s.kind in kinds]
    assert len(specs) >= 2, specs
    specs[0].target, specs[1].target = specs[1].target, specs[0].target
    return exported


def _older_gates_all_pass(module, exported, plan):
    """证明这道核对不是重复劳动：前面几关在 target 互换后**全都过**。"""
    placeholders = [n.name for n in exported.graph.nodes if n.op == "placeholder"]
    check_contract(
        placeholders, plan,
        dict(module.named_parameters(remove_duplicate=False)),
        dict(module.named_buffers(remove_duplicate=False)),
    )
    check_plan_source(plan, input_plan(exported))
    check_plan_table(classify(plan), classify(input_plan(exported)))


# ------------------------------------------------- I-1 target 互换：形状核对

@pytest.mark.parametrize("cls,kinds", [
    (TwoParams, WEIGHT_KINDS),
    (ParamBuf, WEIGHT_KINDS),
    (TwoConsts, (InputKind.CONSTANT_TENSOR,)),
], ids=["two-params", "param-buffer", "two-consts"])
def test_swapping_targets_is_refused_by_the_graphs_own_shapes(cls, kinds):
    module, exported = _exported(cls(), ONE)
    _swap_targets(exported, kinds)
    plan = input_plan(exported)
    _older_gates_all_pass(module, exported, plan)
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, plan, ONE)
    text = str(info.value)
    assert "target" in text and "被改过" in text, text
    assert "(1, 4)" in text and "(2, 4)" in text, text


@pytest.mark.parametrize("cls", [TwoParams, ParamBuf], ids=["two-params", "param-buffer"])
def test_unswapped_targets_still_resolve_to_the_right_tensors(cls):
    """反向对照：核对不是恒真拒绝，真 spec 照常取到模块里那一个张量。"""
    module, exported = _exported(cls(), ONE)
    args = placeholder_args(module, exported, input_plan(exported), ONE)
    named = {**dict(module.named_parameters()), **dict(module.named_buffers())}
    assert args[0] is named["a"], (cls.__name__, args)
    assert args[1] is named["b"], (cls.__name__, args)
    assert args[2] is ONE[0]


def test_unswapped_constants_still_resolve_from_exported_constants():
    """常量的值只能来自 exported.constants（不是 named_parameters/buffers）。"""
    module, exported = _exported(TwoConsts(), ONE)
    args = placeholder_args(module, exported, input_plan(exported), ONE)
    assert args[0] is exported.constants["p"], args
    assert args[1] is exported.constants["q"], args
    assert args[2] is ONE[0]


def test_same_shape_target_swap_is_refused_by_the_name_gate():
    """第十三轮这里写的是「同形状互换不可观测」——**第十四轮证明那是错的**：
    跨模块时 parent_id 会写反（可见的错误数据）。名字↔target 核对（fx_names）
    连同模块的同形状互换一起拒绝。真正剩下的边界只有「压平撞名」，
    见 tests/test_fourteenth_review.py::test_ambiguous_swap_really_does_change_parent_id。
    """
    module, exported = _exported(TwoSame(), ONE)
    _swap_targets(exported)
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, input_plan(exported), ONE)
    assert "名字" in str(info.value), str(info.value)


def test_non_tensor_arguments_are_not_shape_checked():
    """int/bool/None 这类形参没有形状，不能因为「比不了」就拒绝合法模型。"""
    module, exported = _exported(IntArg(), (torch.zeros(2, 4), 3))
    args = placeholder_args(module, exported, input_plan(exported), (torch.zeros(2, 4), 3))
    assert args[-1] == 3, args


# ------------------------------------------------- check_value_shape 的单元边界

def _node(shape):
    val = None if shape is None else SimpleNamespace(shape=shape)
    return SimpleNamespace(name="p_a", meta={"val": val})


def test_check_value_shape_refuses_a_mismatch():
    with pytest.raises(BuildError) as info:
        check_value_shape(_node((2, 4)), torch.ones(1, 4), "b")
    assert "p_a" in str(info.value) and "target=b" in str(info.value)


@pytest.mark.parametrize("node,value", [
    (_node((2, 4)), torch.ones(2, 4)),
    (_node(None), torch.ones(1, 4)),
    (_node((2, 4)), 3),
    (_node((2, 4)), None),
    (_node(("s0", 4)), torch.ones(2, 4)),
], ids=["match", "no-meta", "int-value", "none-value", "symbolic-dim"])
def test_check_value_shape_does_not_guess(node, value):
    check_value_shape(node, value, "a")


# ------------------------------------------------- CLI 级：就地篡改真产物

TWO_PARAMS = """import torch
import torch.nn as nn


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.a = nn.Parameter(torch.ones(2, 4))
        self.b = nn.Parameter(torch.ones(1, 4))

    def forward(self, x):
        return x + self.a + self.b

    def example_inputs(self):
        return (torch.zeros(2, 4),)


def build_model():
    return M().eval()
"""


def test_cli_exits_2_when_the_real_exports_targets_are_swapped(monkeypatch, capsys):
    """篡改发生在 torch.export.export 的返回值上：所有 input_plan 绑定看到的都是同一份
    被改过的 spec，所以「与导出器核对」那几关一起失效——只有形状核对看得见。"""
    repo = _write_repo("thirteenth-swap", TWO_PARAMS)
    out_dir = scratch_dir("thirteenth-swap-out")
    real_export = torch.export.export

    def tampered(module, args, **kwargs):
        return _swap_targets(real_export(module, args, **kwargs))

    monkeypatch.setattr(torch.export, "export", tampered)
    assert _build(repo, out_dir) == 2
    err = capsys.readouterr().err
    assert "target" in err and "被改过" in err, err
    assert "Traceback" not in err, err
    assert not (out_dir / "trace.json").exists()


def test_cli_still_builds_the_same_repo_without_tampering(capsys):
    repo = _write_repo("thirteenth-clean", TWO_PARAMS)
    out_dir = scratch_dir("thirteenth-clean-out")
    assert _build(repo, out_dir) == 0
    assert (out_dir / "trace.json").exists()
