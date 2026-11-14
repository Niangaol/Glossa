"""第十四轮评审的回归测试：同形状**跨模块** target 互换——parent_id 会写反。

I-1 评审探针（output/review13/probe14e_cli_parent.py）实测：Sub.w 与根上的 a 都是
    (2,4)，在真 ExportedProgram 上互换两者的 target，七道关全过、CLI exit 0，trace 里
    root.p_a 的 parent 变成 root/sub、root.p_sub_w 变成 root，而 shape_broken 仍是 0。
    第十三轮那句「同形状互换在 trace 里无可见差异」**是错的**：跨模块时 parent_id 可见。
    修法：placeholder 的名字在图上（torch 的 placeholder_naming_pass 生成），
    target 在 input_specs 里——再核一次这两个独立字段的对应关系（fx_names）。
    第十五轮把实现从「反推索引」改成「正向核对」：反推有损，会误杀 self_/连字符/
    大写的合法模型，也会漏检 self_a/self_b。压平撞名时两个 target 映射到同一个 base，
    核对自然通过——那是唯一剩下的洞，本文件把它钉成可观测的证据。

M-1：原来那条「不可观测」用例只断言 args 取到了对方张量，证明不了 trace 无差异。
    这里改成 trace 级证据：同模块互换其实**也被新关拒绝**（名字反推与模块无关），
    而真正剩下的残余洞是「压平撞名」——那条用例构建整份 trace，证明 parent_id 确实写反。
"""

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import torch  # noqa: E402
from torch import nn  # noqa: E402
from torch.export.graph_signature import InputKind  # noqa: E402

from papertrace.exceptions import BuildError  # noqa: E402
from papertrace.parse_code import fx_trace  # noqa: E402
from papertrace.parse_code.fx_contract import (  # noqa: E402
    check_contract,
    check_plan_source,
    check_plan_table,
)
from papertrace.parse_code.fx_names import check_name_target, strip_name  # noqa: E402
from papertrace.parse_code.fx_shapes import check_value_shape  # noqa: E402
from papertrace.parse_code.fx_signature import (  # noqa: E402
    classify,
    input_plan,
    placeholder_args,
)
from papertrace.parse_code.fx_trace import trace_module  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402
from tests.test_seventh_review import ENTRY, _write_repo  # noqa: E402
from tests.test_twelfth_review import _build, _exported  # noqa: E402

ONE = (torch.zeros(2, 4),)
WEIGHT_KINDS = (InputKind.PARAMETER, InputKind.BUFFER)


class Sub(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w


class ParentSwap(nn.Module):
    """根上的 a 与子模块里的 sub.w：**同形状、不同模块**。"""

    def __init__(self):
        super().__init__()
        self.sub = Sub()
        self.a = nn.Parameter(torch.ones(2, 4) * 2)

    def forward(self, x):
        return self.sub(x) + self.a


class TwoSubs(nn.Module):
    """两个子模块里各一个同形状权重：互换后两个 parent_id 都错。"""

    def __init__(self):
        super().__init__()
        self.s1 = Sub()
        self.s2 = Sub()

    def forward(self, x):
        return self.s1(x) + self.s2(x)


class SameModule(nn.Module):
    """同模块、同形状、同 dtype：互换后 trace 里确实没有任何字段差异。"""

    def __init__(self):
        super().__init__()
        self.a = nn.Parameter(torch.ones(2, 4))
        self.b = nn.Parameter(torch.ones(2, 4) * 3)

    def forward(self, x):
        return x + self.a + self.b


class Ambiguous(nn.Module):
    """a_b 与 a.b 压平后同名：名字反推不唯一，这道关**跳过不猜**。"""

    def __init__(self):
        super().__init__()
        self.a_b = nn.Parameter(torch.ones(2, 4))
        self.a = nn.Module()
        self.a.b = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.a_b + self.a.b


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


class PList(nn.Module):
    def __init__(self):
        super().__init__()
        self.ws = nn.ParameterList([nn.Parameter(torch.ones(2, 4)) for _ in range(2)])

    def forward(self, x):
        return x + self.ws[0] + self.ws[1]


class PDict(nn.Module):
    def __init__(self):
        super().__init__()
        self.ws = nn.ParameterDict({"a": nn.Parameter(torch.ones(2, 4))})

    def forward(self, x):
        return x + self.ws["a"]


class PlainList(nn.Module):
    def __init__(self):
        super().__init__()
        self.ws = [torch.ones(2, 4), torch.ones(2, 4)]

    def forward(self, x):
        return x + self.ws[0] + self.ws[1]


class NonPersist(nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("tmp", torch.ones(2, 4), persistent=False)

    def forward(self, x):
        return x + self.tmp


class ConstAttr(nn.Module):
    def __init__(self):
        super().__init__()
        self.c = torch.ones(2, 4)

    def forward(self, x):
        return x + self.c


class Deep(nn.Module):
    def __init__(self):
        super().__init__()
        self.l1 = nn.Module()
        self.l1.l2 = Sub()

    def forward(self, x):
        return self.l1.l2(x)


def _swap(exported, kinds=WEIGHT_KINDS):
    """就地改**真**产物的 input_specs：互换前两个同类 spec 的 target。"""
    specs = exported.graph_signature.input_specs
    idx = [i for i, s in enumerate(specs) if s.kind in kinds]
    a, b = idx[0], idx[1]
    specs[a].target, specs[b].target = specs[b].target, specs[a].target
    return exported


def _gates(module, exported, plan):
    """前面几关（含形状核对）在互换后**全都过**——证明新关不是重复劳动。"""
    holders = [n for n in exported.graph.nodes if n.op == "placeholder"]
    names = [n.name for n in holders]
    params = dict(module.named_parameters(remove_duplicate=False))
    buffers = dict(module.named_buffers(remove_duplicate=False))
    check_contract(names, plan, params, buffers)
    check_plan_source(plan, input_plan(exported))
    check_plan_table(classify(plan), classify(input_plan(exported)))
    args = [
        {**params, **buffers}[i["target"]] if i["kind"] == "param"
        else dict(exported.constants or {}).get(i["target"], ONE[0])
        for i in plan
    ]
    for node, value in zip(holders, args):
        check_value_shape(node, value, plan[names.index(node.name)].get("target"))


# ------------------------------------------------- I-1 跨模块同形状互换

@pytest.mark.parametrize("cls", [ParentSwap, TwoSubs], ids=["root-vs-sub", "sub-vs-sub"])
def test_cross_module_same_shape_swap_is_refused(cls):
    module, exported = _exported(cls(), ONE)
    _swap(exported)
    plan = input_plan(exported)
    _gates(module, exported, plan)
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, plan, ONE)
    text = str(info.value)
    assert "名字" in text and "target" in text and "被改过" in text, text
    assert "父模块" in text, text


def test_the_swap_really_would_write_the_wrong_parent_id():
    """先证明这个洞是真的：不装新关时，trace 的 parent_id 确实互换（而计数全 0）。

    这里直接按 spec_owner 复算 parent，不调用被新关保护的 placeholder_args。
    """
    from papertrace.parse_code.fx_signature import module_of_target

    module, exported = _exported(ParentSwap(), ONE)
    real = {i["name"]: module_of_target(i["target"]) for i in input_plan(exported)}
    _swap(exported)
    forged = {i["name"]: module_of_target(i["target"]) for i in input_plan(exported)}
    assert real == {"p_a": "", "p_sub_w": "sub", "x": ""}, real
    assert forged == {"p_a": "sub", "p_sub_w": "", "x": ""}, forged
    assert real != forged


def test_cli_exits_2_when_same_shape_targets_are_swapped(monkeypatch, capsys):
    repo = _write_repo("fourteenth-parent", PARENT_SWAP_REPO)
    out_dir = scratch_dir("fourteenth-parent-out")
    real_export = torch.export.export

    def tampered(module, args, **kwargs):
        return _swap(real_export(module, args, **kwargs))

    monkeypatch.setattr(torch.export, "export", tampered)
    assert _build(repo, out_dir) == 2
    err = capsys.readouterr().err
    assert "名字" in err and "对不上" in err, err
    assert "Traceback" not in err, err
    assert not (out_dir / "trace.json").exists()


def test_cli_without_tampering_still_builds(capsys):
    """反向对照：同一个仓库不篡改就 exit 0，证明上一条不是恒真拒绝。"""
    repo = _write_repo("fourteenth-clean", PARENT_SWAP_REPO)
    out_dir = scratch_dir("fourteenth-clean-out")
    assert _build(repo, out_dir) == 0
    assert (out_dir / "trace.json").exists()


PARENT_SWAP_REPO = """import torch
import torch.nn as nn


class Sub(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.sub = Sub()
        self.a = nn.Parameter(torch.ones(2, 4) * 2)

    def forward(self, x):
        return self.sub(x) + self.a

    def example_inputs(self):
        return (torch.zeros(2, 4),)


def build_model():
    return M().eval()
"""


# ------------------------------------------------- M-1 不可观测边界：整份 trace 比较

def test_same_module_same_shape_swap_is_also_refused():
    """名字反推与模块无关：同模块的同形状互换一样被拒（比评审要求的更强）。

    第十三轮把这种情况写成「不可观测」，那是错的——见下面两条 trace 级用例。
    """
    module, exported = _exported(SameModule(), ONE)
    _swap(exported)
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, input_plan(exported), ONE)
    assert "名字" in str(info.value) and "p_a" in str(info.value)


def test_ambiguous_swap_really_does_change_parent_id(monkeypatch):
    """**残余洞的 trace 级证据**：压平撞名时新关跳过，parent_id 确实会写反。

    不假装封死：这条用例把「跳过不猜」的代价钉成可见事实，README 同口径写明。
    """
    module = Ambiguous().eval()
    clean = trace_module(module, list(ONE))
    real_export = torch.export.export
    monkeypatch.setattr(
        torch.export, "export", lambda m, a, **k: _swap(real_export(m, a, **k))
    )
    swapped = trace_module(module, list(ONE))
    before = {n["label"]: n["parent_id"] for n in clean["nodes"] if n.get("kind") == "param"}
    after = {n["label"]: n["parent_id"] for n in swapped["nodes"] if n.get("kind") == "param"}
    assert before != after, (before, after)
    assert swapped["runtime"]["counts"]["shape_broken"] == 0


def test_cross_module_swap_would_change_parent_id(monkeypatch):
    """跨模块时**有**可见差异：把新关绕开（直接比 spec_owner）就能看到 parent 写反。

    这条与上一条一起，把「同模块不可观测 / 跨模块可观测」的边界钉成两个方向。
    """
    module = ParentSwap().eval()
    clean = trace_module(module, list(ONE))
    parents = {n["label"]: n["parent_id"] for n in clean["nodes"] if n.get("kind") == "param"}
    assert parents == {"root.p_a": "root", "root.p_sub_w": "root/sub"}, parents


def test_parameter_list_target_swap_is_refused():
    """ws.0 / ws.1 压平后**本来就带数字**：必须先按全名查，不能先剥 _N 后缀。

    这条钉死「先全名、后剥后缀」的顺序：剥错了就会把 ws_0 当成 ws 而查不到，
    于是静默跳过，同形状互换又变成可观测的错误数据。
    """
    module, exported = _exported(PList(), ONE)
    _swap(exported)
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, input_plan(exported), ONE)
    text = str(info.value)
    assert "p_ws_0" in text and "ws.1" in text, text


# ------------------------------------------------- 歧义边界：压平撞名时名字区分不了

def test_ambiguous_flattening_is_not_refused():
    """a_b 与 a.b 正向映射到同一个 base：合法模型必须通过，而且取到的张量是对的。"""
    module, exported = _exported(Ambiguous(), ONE)
    plan = input_plan(exported)
    args = placeholder_args(module, exported, plan, ONE)
    assert len(args) == 3, args
    assert args[0] is module.a_b and args[1] is module.a.b, args


def test_ambiguous_flattening_swap_is_not_guessed():
    """压平撞名是**唯一**剩下的洞：互换后名字核对通过，取到的张量真的换了。

    评审 I-2 说原来只断言 len(args)==3 太弱。这里直接证明洞是可观测的：
    args[0] 变成了 a.b（本该是 a_b）。不假装封死。
    """
    module, exported = _exported(Ambiguous(), ONE)
    _swap(exported)
    plan = input_plan(exported)
    args = placeholder_args(module, exported, plan, ONE)
    assert len(args) == 3, args
    assert args[0] is module.a.b and args[1] is module.a_b, args


# ------------------------------------------------- 正向对照：合法模型一个都不许误杀

@pytest.mark.parametrize("cls,example", [
    (ParentSwap, ONE), (TwoSubs, ONE), (SameModule, ONE), (Nested, (torch.zeros(2, 4), torch.zeros(2, 4))),
    (Tied, ONE), (PList, ONE), (PDict, ONE), (PlainList, ONE), (NonPersist, ONE),
    (ConstAttr, ONE), (Deep, ONE),
], ids=["parent-swap", "two-subs", "same-module", "nested", "tied", "parameter-list",
        "parameter-dict", "plain-list", "non-persistent", "const-attr", "deep"])
def test_legitimate_models_pass_the_name_gate(cls, example):
    module, exported = _exported(cls(), example)
    plan = input_plan(exported)
    holders = [n for n in exported.graph.nodes if n.op == "placeholder"]
    check_name_target(holders, plan)
    args = placeholder_args(module, exported, plan, example)
    assert len(args) == len(holders), (cls.__name__, args)


# ------------------------------------------------- strip_name / 名字核对的单元边界

class _N:
    def __init__(self, name):
        self.name = name


def _plan(*items):
    return [{"name": n, "kind": k, "target": t} for n, k, t in items]


@pytest.mark.parametrize("target,expected", [
    ("sub.w", "sub_w"),
    ("self_attn.weight", "attn_weight"),
    ("sub.self_attn.weight", "sub_self_attn_weight"),
    ("L__self___foo.bar", "foo_bar"),
    ("a-b.weight", "a_b_weight"),
    ("W", "w"),
    ("ws.0", "ws_0"),
    ("self_", ""),
    ("self_x", "x"),
], ids=["dotted", "leading-self", "nested-self", "L-self", "hyphen", "upper",
        "numeric", "empty-after-strip", "self-x"])
def test_strip_name_follows_torch(target, expected):
    """期望值来自 pydeps/torch/_export/utils.py:1113-1119 与 :1168 的规则，
    并在 tests/test_fifteenth_review.py 里与 torch **真实生成的名字**交叉核对。"""
    assert strip_name(target) == expected


def test_name_gate_refuses_a_mismatch():
    with pytest.raises(BuildError) as info:
        check_name_target([_N("p_a")], _plan(("p_a", "param", "sub.w")))
    text = str(info.value)
    assert "p_a" in text and "sub.w" in text and "a" in text, text


@pytest.mark.parametrize("name,kind,target", [
    ("p_sub_w", "param", "sub.w"),
    ("p_a_b", "param", "a.b"),
    ("p_a_b", "param", "a_b"),
    ("p_a_b_1", "param", "a_b"),
    ("p_ws_0", "param", "ws.0"),
    ("p_attn_weight", "param", "self_attn.weight"),
    ("p_attn_weight_1", "param", "attn.weight"),
    ("p_w", "param", "W"),
    ("p_a_b_weight", "param", "a-b.weight"),
    ("b_tmp", "param", "tmp"),
    ("c_const", "const", "const"),
    ("p_", "param", "self_"),
    ("x", "input", None),
], ids=["dotted", "ambiguous-dot", "ambiguous-underscore", "collision-suffix",
        "numeric-tail", "leading-self", "collision-after-self", "upper", "hyphen",
        "non-persistent-buffer", "const", "empty-base", "user-input"])
def test_name_gate_accepts_consistent_pairs(name, kind, target):
    check_name_target([_N(name)], _plan((name, kind, target)))


@pytest.mark.parametrize("name,target", [
    ("p_a", "b"),
    ("p_a_weight", "self_b.weight"),
    ("p_ws_0", "ws.1"),
    ("p_attn_weight", "attn.bias"),
    ("obj_foo", "bar"),
    ("obj_foo", "foo"),
    ("weird", "a"),
    ("p_ghost", None),
], ids=["simple", "self-prefix-modules", "numeric-tail", "same-module",
        "custom-obj-mismatch", "custom-obj-unknown-prefix", "unknown-prefix",
        "no-target"])
def test_name_gate_refuses_inconsistent_pairs(name, target):
    """第十六轮 I-1/I-2：认不出前缀（含 obj_）与没有 target 都拒绝，不静默跳过。"""
    with pytest.raises(BuildError) as info:
        check_name_target([_N(name)], _plan((name, "param", target)))
    assert name in str(info.value)
