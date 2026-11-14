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

    def forward(self, tokens):
        return tokens + self.used


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

    def forward(self, y, z):
        return self.sub(y) + self.top + z


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


class ConstAttr(nn.Module):
    """普通张量属性：torch.export 把它当常量（CONSTANT_TENSOR，值在 constants 里）。"""

    def __init__(self):
        super().__init__()
        self.w = torch.ones(2, 4)

    def forward(self, x):
        return x + self.w


def _const_plan_without_values():
    """导出器说 w 是常量，但 constants 里拿不到值（版本差异/被裁掉）。

    第十一轮之后 plan 必须与导出器逐项一致，所以不能再靠手改 kind 来走到 const 分支；
    这里用**导出器自己的** plan，只把值拿掉，让 const 分支去模块里找。

    第十二轮之后 placeholder_args 只接受真 ExportedProgram（类型守卫），不能再拿
    SimpleNamespace 拼替身：直接清真产物的 `_constants`（torch 2.15 的 `constants`
    是只读 property，没有公开 setter）。
    """
    _, exported = _exported(ConstAttr(), (torch.zeros(2, 4),))
    plan = input_plan(exported)
    assert [i["kind"] for i in plan if i["target"] == "w"] == ["const"], plan
    exported._constants = {}
    return plan, exported


def test_const_label_on_a_trainable_parameter_is_refused():
    plan, stripped = _const_plan_without_values()
    with pytest.raises(BuildError) as info:
        placeholder_args(Weight(), stripped, plan, (torch.zeros(2, 4),))
    assert "可训练参数" in str(info.value), str(info.value)


def test_hand_flipped_const_label_is_refused_even_earlier():
    """手改 plan 把权重标成常量：现在先被「与导出器不一致」拦住（第十一轮 C1）。"""
    module, exported = _exported(Weight(), (torch.zeros(2, 4),))
    as_const = _flip(input_plan(exported), "const")
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, as_const, (torch.zeros(2, 4),))
    assert "与 torch.export 自己给的不一致" in str(info.value), str(info.value)


def test_const_label_on_a_buffer_is_refused():
    """缓冲是可变状态，不是导出常量：const 的值只能来自 exported.constants。

    以前这里兜底取 buffers[target]，等于给 const 开了第二套语义（KIND_MAP 里
    BUFFER→param，README 说 const 是 CONSTANT_TENSOR）。第十一轮 I-1 的 BufferOnly
    反例就是这么过的，现在明确拒绝。
    """
    plan, stripped = _const_plan_without_values()

    class BufferW(nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("w", torch.zeros(2, 4))

        def forward(self, x):
            return x + self.w

    holder = BufferW()
    with pytest.raises(BuildError) as info:
        placeholder_args(holder, stripped, plan, (torch.zeros(2, 4),))
    text = str(info.value)
    assert "缓冲" in text and "exported.constants" in text, text


def test_a_real_buffer_is_still_a_param_not_a_const():
    """反向对照：真缓冲走 BUFFER→param，取值来自模块，不需要 const 兜底。"""
    module, exported = _exported(BufferOnly(), (torch.zeros(2, 4),))
    plan = input_plan(exported)
    assert [(i["name"], i["kind"], i["target"]) for i in plan] == [
        ("b_running", "param", "running"), ("x", "input", None)
    ], plan
    args = placeholder_args(module, exported, plan, (torch.zeros(2, 4),))
    assert args[0] is module.running, args


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


#: (模型, example_inputs, 精确的 params 集合, 精确的 inputs 顺序, 精确的 owner)
#: 形参名刻意各不相同（x / tokens / y,z）：都叫 x 的话，把 inputs 写死成 ["x"]
#: 也只是在测自己造的模型（第十一轮 I-3）。期望值来自 probe11b 的实测 plan。
LEGIT = [
    (Shadowed, (torch.zeros(2, 4),), {"p_x"}, ["x"], {"p_x": ""}),
    (Unused, (torch.zeros(2, 4),), {"p_used", "p_unused", "b_never"}, ["tokens"],
     {"p_used": "", "p_unused": "", "b_never": ""}),
    (Nested, (torch.zeros(2, 4), torch.zeros(2, 4)), {"p_top", "p_sub_w"}, ["y", "z"],
     {"p_top": "", "p_sub_w": "sub"}),
]


@pytest.mark.parametrize("model,example,params,inputs,owner", LEGIT,
                         ids=["shadowed", "unused", "nested"])
def test_legitimate_models_are_not_refused(model, example, params, inputs, owner):
    """同名遮蔽 / 没用到的参数与缓冲 / 子模块参数：反向核对都不能误杀。"""
    module, exported = _exported(model(), example)
    plan = input_plan(exported)
    args = placeholder_args(module, exported, plan, example)
    assert len(args) == len([n for n in exported.graph.nodes if n.op == "placeholder"])
    table = classify(plan)
    assert table["params"] == params, table
    assert table["inputs"] == inputs, table
    assert table["owner"] == owner, table
    assert table["consts"] == set(), table
    # 权重位置拿到的必须是模块里那个张量本身，不是 example_inputs 顶替的。
    named = dict(module.named_parameters(remove_duplicate=False))
    named.update(dict(module.named_buffers(remove_duplicate=False)))
    for item, arg in zip(plan, args):
        if item["kind"] == "param":
            assert arg is named[item["target"]], (item, arg)


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
