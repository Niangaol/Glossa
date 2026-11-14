"""模型动物园：契约校验不能误杀合法写法（第十一轮 Q1 的回归）。

评审实测 16 种写法都能过 check_contract；这里把它们钉成回归，每条断言**精确**的
权重/常量/输入个数与真实执行成功，而不是「非空就算过」。期望个数来自
output/probes/probe11b.py 对导出器 plan 的实测，不是从被测代码反推的。

覆盖的写法：同名遮蔽、没用到的参数/缓冲、子模块、tied weights（参数与缓冲）、
常量折叠、普通 list 装 Parameter、requires_grad=False、ParameterList/Dict、
None 缓冲、非持久缓冲、training 分支、普通张量属性、没用到的子模块。
no_grad 单独一条：契约过得去，但追踪阶段明确拒绝（见文件末尾），不算误杀。
"""

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import torch  # noqa: E402
from torch import nn  # noqa: E402

from papertrace.parse_code.fx_trace import _ensure_export_cache, trace_module  # noqa: E402


class Sub(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, a):
        return a + self.w


class Shadowed(nn.Module):
    def __init__(self):
        super().__init__()
        self.x = nn.Parameter(torch.zeros(2, 4))

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


class Nested(nn.Module):
    def __init__(self):
        super().__init__()
        self.sub = Sub()
        self.top = nn.Parameter(torch.ones(2, 4))

    def forward(self, y, z):
        return self.sub(y) + self.top + z


class Tied(nn.Module):
    def __init__(self):
        super().__init__()
        self.a = nn.Parameter(torch.ones(2, 4))
        self.b = self.a

    def forward(self, x):
        return x + self.a + self.b


class TiedBuffer(nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("a", torch.ones(2, 4))
        self.register_buffer("b", self.a)

    def forward(self, x):
        return x + self.a + self.b


class NoGrad(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        with torch.no_grad():
            return x + self.w


class Folded(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w * 0


class PlainList(nn.Module):
    """普通 list 装 Parameter：不会被 named_parameters 收，导出器抬成常量。"""

    def __init__(self):
        super().__init__()
        self.ws = [nn.Parameter(torch.ones(2, 4))]

    def forward(self, x):
        return x + self.ws[0]


class Frozen(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4), requires_grad=False)

    def forward(self, x):
        return x + self.w


class PList(nn.Module):
    def __init__(self):
        super().__init__()
        self.ws = nn.ParameterList(
            [nn.Parameter(torch.ones(2, 4)), nn.Parameter(torch.zeros(2, 4))]
        )

    def forward(self, x):
        return x + self.ws[0] + self.ws[1]


class PDict(nn.Module):
    def __init__(self):
        super().__init__()
        self.ws = nn.ParameterDict({"a": nn.Parameter(torch.ones(2, 4))})

    def forward(self, x):
        return x + self.ws["a"]


class NoneBuffer(nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("maybe", None)
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w


class NonPersistent(nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("tmp", torch.zeros(2, 4), persistent=False)

    def forward(self, x):
        return x + self.tmp


class BranchTraining(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        if self.training:
            return x + self.w
        return x - self.w


class ConstAttr(nn.Module):
    def __init__(self):
        super().__init__()
        self.const = torch.ones(2, 4)

    def forward(self, x):
        return x + self.const


class UnusedSub(nn.Module):
    def __init__(self):
        super().__init__()
        self.sub = Sub()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w


ONE = (torch.zeros(2, 4),)
TWO = (torch.zeros(2, 4), torch.zeros(2, 4))

#: (id, 模型, example_inputs, 精确的 kind 计数)
ZOO = [
    ("shadowed", Shadowed, ONE, {"param": 1, "input": 1}),
    ("unused", Unused, ONE, {"param": 3, "input": 1}),
    ("nested", Nested, TWO, {"param": 2, "input": 2}),
    ("tied", Tied, ONE, {"param": 2, "input": 1}),
    ("tied-buffer", TiedBuffer, ONE, {"param": 2, "input": 1}),
    ("folded", Folded, ONE, {"param": 1, "input": 1}),
    ("plain-list", PlainList, ONE, {"const": 1, "input": 1}),
    ("frozen", Frozen, ONE, {"param": 1, "input": 1}),
    ("parameter-list", PList, ONE, {"param": 2, "input": 1}),
    ("parameter-dict", PDict, ONE, {"param": 1, "input": 1}),
    ("none-buffer", NoneBuffer, ONE, {"param": 1, "input": 1}),
    ("non-persistent", NonPersistent, ONE, {"param": 1, "input": 1}),
    ("branch-training", BranchTraining, ONE, {"param": 1, "input": 1}),
    ("const-attr", ConstAttr, ONE, {"const": 1, "input": 1}),
    ("unused-sub", UnusedSub, ONE, {"param": 2, "input": 1}),
]


@pytest.mark.parametrize("name,cls,example,expected", ZOO, ids=[z[0] for z in ZOO])
def test_zoo_models_are_traced_with_exact_kinds(name, cls, example, expected):
    traced = trace_module(cls().eval(), example)
    kinds: dict[str, int] = {}
    for node in traced["nodes"]:
        if node.get("level") != "op":
            continue
        kinds[node["kind"]] = kinds.get(node["kind"], 0) + 1
    for kind, count in expected.items():
        assert kinds.get(kind, 0) == count, (name, kind, kinds)
    assert traced["runtime"]["real_execution"] == {"ok": True, "reason": None}
    assert traced["runtime"]["counts"]["shape_broken"] == 0, traced["runtime"]["counts"]


def test_no_grad_region_is_refused_with_a_precise_reason():
    """能力边界（不是误杀）：no_grad 被导出器包成子模块，本切片只追纯张量图。

    契约校验（check_contract / placeholder_args）对它是通过的；拒绝发生在追踪阶段，
    因为那个 get_attr 不是张量，挂回去跑通也会把它标成 param，让权重数从 1 变 2。
    """
    from papertrace.exceptions import TraceUnsupported
    from papertrace.parse_code.fx_signature import input_plan, placeholder_args

    module = NoGrad().eval()
    _ensure_export_cache()
    exported = torch.export.export(module, ONE)
    plan = input_plan(exported)
    assert [(i['name'], i['kind']) for i in plan] == [('p_w', 'param'), ('x', 'input')]
    placeholder_args(module, exported, plan, ONE)  # 契约这一关是过的
    with pytest.raises(TraceUnsupported) as info:
        trace_module(module, ONE)
    text = str(info.value)
    assert "子模块" in text and "no_grad" in text, text
    assert "权重" in text, text
