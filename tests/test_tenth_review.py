"""第十轮：kind 标反的反向核对（地面真相是模块，不是 plan）。

第九轮只闭合了「spec 说权重 → 模块里真有」这一个方向。探针实测：把真实权重标成 input、
再给 example_inputs 多补一项，数量校验就骗过去了，权重顶着 kind=input 出图。
这里钉死反向判据，并证明它不会误杀合法模型（同名遮蔽、没用到的参数/缓冲、子模块、常量）。
"""

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import torch  # noqa: E402
from torch import nn  # noqa: E402

from papertrace.exceptions import BuildError  # noqa: E402
from papertrace.parse_code import fx_trace  # noqa: E402
from papertrace.parse_code.fx_contract import check_contract  # noqa: E402
from papertrace.parse_code.fx_signature import (  # noqa: E402
    classify,
    input_plan,
    placeholder_args,
)
from papertrace.parse_code.fx_trace import _ensure_export_cache  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402

ENTRY = "model:build_model"


def _exported(module, example):
    _ensure_export_cache()
    module = module.eval()
    return module, torch.export.export(module, example)


class Weight(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w


class Shadowed(nn.Module):
    """参数名与 forward 形参名同名：torch 给 p_x / x 两个 placeholder。"""

    def __init__(self):
        super().__init__()
        self.x = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.x


class Unused(nn.Module):
    def __init__(self):
        super().__init__()
        self.used = nn.Parameter(torch.ones(2, 4))
        self.unused = nn.Parameter(torch.zeros(3))
        self.register_buffer("never", torch.zeros(7))

    def forward(self, x):
        return x + self.used


class BufferOnly(nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("running", torch.zeros(2, 4))

    def forward(self, x):
        return x + self.running


class Sub(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w


class Nested(nn.Module):
    def __init__(self):
        super().__init__()
        self.sub = Sub()
        self.top = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return self.sub(x) + self.top


def _flip(plan, kind, target=None):
    out = [dict(item) for item in plan]
    for item in out:
        if item["kind"] == "param":
            item["kind"] = kind
            if target is not None:
                item["target"] = target
    return out


def test_weight_labelled_input_with_compensating_example_inputs_is_refused():
    """数量校验骗得过去，反向核对骗不过去——这才是 kind 正确性的关卡。"""
    module, exported = _exported(Weight(), (torch.zeros(2, 4),))
    flipped = _flip(input_plan(exported), "input", target="")
    for item in flipped:
        item["target"] = None
    # 先证明这个 plan 能骗过数量校验：两个 input、两项 example_inputs。
    assert sum(1 for i in flipped if i["kind"] == "input") == 2
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, flipped, (module.w.detach(), torch.zeros(2, 4)))
    text = str(info.value)
    assert "认领" in text and "w" in text, text


def test_const_label_on_a_trainable_parameter_is_refused():
    module, exported = _exported(Weight(), (torch.zeros(2, 4),))
    as_const = _flip(input_plan(exported), "const")
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, as_const, (torch.zeros(2, 4),))
    assert "可训练参数" in str(info.value), str(info.value)


def test_const_label_on_a_buffer_still_resolves():
    """反向对照：缓冲被标成常量是合法的，不能一刀切拒绝。"""
    module, exported = _exported(BufferOnly(), (torch.zeros(2, 4),))
    as_const = _flip(input_plan(exported), "const")
    args = placeholder_args(module, exported, as_const, (torch.zeros(2, 4),))
    assert [tuple(a.shape) for a in args] == [(2, 4), (2, 4)]


def test_unclaimed_buffer_alone_is_refused():
    """只有缓冲、没有参数的模型也要被反向核对覆盖。"""
    module, exported = _exported(BufferOnly(), (torch.zeros(2, 4),))
    plan = input_plan(exported)
    placeholders = [n.name for n in exported.graph.nodes if n.op == "placeholder"]
    params = dict(module.named_parameters())
    buffers = dict(module.named_buffers())
    check_contract(placeholders, plan, params, buffers)  # 正常 plan 通过
    flipped = _flip(plan, "input")
    for item in flipped:
        item["target"] = None
    with pytest.raises(BuildError) as info:
        check_contract(placeholders, flipped, params, buffers)
    assert "running" in str(info.value), str(info.value)


@pytest.mark.parametrize("model", [Shadowed, Unused, Nested], ids=["shadowed", "unused", "nested"])
def test_legitimate_models_are_not_refused(model):
    """同名遮蔽 / 没用到的参数与缓冲 / 子模块参数：反向核对都不能误杀。"""
    module, exported = _exported(model(), (torch.zeros(2, 4),))
    plan = input_plan(exported)
    args = placeholder_args(module, exported, plan, (torch.zeros(2, 4),))
    assert len(args) == len([n for n in exported.graph.nodes if n.op == "placeholder"])
    table = classify(plan)
    assert table["inputs"] == ["x"], table
    assert table["params"], "权重必须仍被认成权重"


def test_shadowed_names_keep_weight_and_input_apart():
    module, exported = _exported(Shadowed(), (torch.zeros(2, 4),))
    table = classify(input_plan(exported))
    assert table["params"] == {"p_x"}, table
    assert table["inputs"] == ["x"], table
    assert table["owner"]["p_x"] == "", table


def _write_repo(name, source):
    repo = scratch_dir(name)
    (repo / "model.py").write_text(source, encoding="utf-8")
    return repo


def test_cli_exits_2_when_a_weight_is_labelled_input(monkeypatch, capsys):
    from papertrace import cli

    repo = _write_repo("tenth-flip-cli", """import torch
import torch.nn as nn


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w

    def example_inputs(self):
        return torch.ones(1, 4)


def build_model():
    return M().eval()
""")
    out_dir = scratch_dir("tenth-flip-cli-out")
    real_plan = fx_trace.input_plan

    def flipped(exported):
        plan = [dict(item) for item in real_plan(exported)]
        for item in plan:
            if item["kind"] == "param":
                item["kind"], item["target"] = "input", None
        return plan

    monkeypatch.setattr(fx_trace, "input_plan", flipped)
    code = cli.main(["build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir)])
    assert code == 2, code
    assert "认领" in capsys.readouterr().err
    assert not (out_dir / "trace.json").exists(), "拒绝出图时不能留下 trace"
