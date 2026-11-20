"""第十六轮评审的回归测试：名字关不许 fail-open，没验证过的种类不许写成「支持」。

I-1 认不出前缀就拒绝：原来 `prefix is None` 直接 continue，等于 torch 一旦改命名
    规则、或直接 API 传个怪名字，第八关就**静默失效**（评审 probe_prefix.py 实测
    `check_name_target([N("weird")], kind=param, target=a)` 被接受）。当前 torch 2.15
    的前缀表覆盖 p_/b_/c_/obj_/token，所以 CLI 主路径不触发——但「认不出」应当是
    显式失败。本文件用**真的把图上的 placeholder 改名**（node.name 是可写成员）来
    模拟「torch 换了命名规则」，并钉到 CLI 级 exit 2。
I-2 CUSTOM_OBJ 先 fail-closed：第十一轮把它映射成 const，但从来没有真实导出背书
    （torch 2.15 把 ScriptObject 的调用常量折叠了）。没有验证过的分支不该写成已支持，
    所以移到 fx_kinds.REFUSED_KINDS，M1b 补真实导出用例再放开。
M-1 `_matches` 允许任意 `_数字` 后缀，所以**单独调这一关**时 p_a_1 配 target='a'
    会被接受；端到端由 check_contract 的「恰好认领一次/未认领」拒绝。两层都钉死，
    不假装这一关是完整权威。
M-2 报错要同时给出观察到的 base 与按 target 应当得到的 base，否则 strip_name(target)
    恰好等于 target 时两个值印成一样，用户看不出为什么被拒。
M-3 PARENTS 期望表用**导出器的 spec + 模块自己的 named_modules** 独立推导一次，
    不只信 trace 管线。
"""

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import json  # noqa: E402

import torch  # noqa: E402
from torch import nn  # noqa: E402
from torch.export.graph_signature import InputKind  # noqa: E402

from papertrace.exceptions import BuildError  # noqa: E402
from papertrace.parse_code.fx_contract import check_contract  # noqa: E402
from papertrace.parse_code.fx_kinds import KIND_MAP, REFUSED_KINDS  # noqa: E402
from papertrace.parse_code.fx_names import (  # noqa: E402
    PREFIXES,
    check_name_target,
)
from papertrace.parse_code.fx_signature import input_plan  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402
from tests.review.test_fifteenth_review import MODELS, PARENTS  # noqa: E402
from tests.review.test_seventh_review import _write_repo  # noqa: E402
from tests.review.test_twelfth_review import _build, _exported  # noqa: E402

ONE = (torch.zeros(2, 4),)


class _N:
    def __init__(self, name):
        self.name = name


def _plan(*rows):
    return [{"name": n, "kind": k, "target": t} for n, k, t in rows]


# ------------------------------------------------------- I-1 认不出前缀就拒绝

@pytest.mark.parametrize("name", ["weird", "obj_foo", "token_x", "P_w", "weight"],
                         ids=["plain", "custom-obj", "token", "upper-prefix", "no-prefix"])
def test_unknown_prefix_is_refused_not_skipped(name):
    with pytest.raises(BuildError) as info:
        check_name_target([_N(name)], _plan((name, "param", "a")))
    text = str(info.value)
    assert "认不出前缀" in text and name in text, text


@pytest.mark.parametrize("name,kind,target", [
    ("p_w", "param", "w"), ("b_tmp", "param", "tmp"), ("c_const", "const", "const"),
], ids=["param", "buffer", "const"])
def test_known_prefixes_are_still_accepted(name, kind, target):
    """反向对照：上一条不是「什么都拒绝」。"""
    check_name_target([_N(name)], _plan((name, kind, target)))


def test_prefixes_and_refused_kinds_pin_the_decision():
    assert PREFIXES == ("p_", "b_", "c_"), PREFIXES
    assert "CUSTOM_OBJ" in REFUSED_KINDS and "CUSTOM_OBJ" not in KIND_MAP
    assert "TOKEN" in REFUSED_KINDS


def test_missing_target_is_refused_not_skipped():
    with pytest.raises(BuildError) as info:
        check_name_target([_N("p_ghost")], _plan(("p_ghost", "param", None)))
    assert "没给 target" in str(info.value)


def _rename_first_weight(exported, new_name):
    """把图上第一个权重 placeholder 改名，并同步 spec.arg.name。

    模拟「torch 换了命名规则」：覆盖率/顺序/认领都仍然自洽，只有名字关能发现。
    """
    node = next(n for n in exported.graph.nodes
                if n.op == "placeholder" and n.name.startswith("p_"))
    old = node.name
    node.name = new_name
    for spec in exported.graph_signature.input_specs:
        if spec.arg.name == old:
            spec.arg.name = new_name
    return exported


SIMPLE_REPO = """import torch
import torch.nn as nn


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w

    def example_inputs(self):
        return (torch.zeros(2, 4),)


def build_model():
    return M().eval()
"""


def test_cli_exits_2_when_the_graph_uses_an_unknown_prefix(monkeypatch, capsys):
    repo = _write_repo("sixteenth-rename", SIMPLE_REPO)
    out_dir = scratch_dir("sixteenth-rename-out")
    real_export = torch.export.export

    def tampered(module, args, **kwargs):
        return _rename_first_weight(real_export(module, args, **kwargs), "weird")

    monkeypatch.setattr(torch.export, "export", tampered)
    assert _build(repo, out_dir) == 2
    err = capsys.readouterr().err
    assert "认不出前缀" in err and "weird" in err, err
    assert "Traceback" not in err, err
    assert not (out_dir / "trace.json").exists()


def test_the_same_repo_without_renaming_still_builds(capsys):
    repo = _write_repo("sixteenth-rename-clean", SIMPLE_REPO)
    out_dir = scratch_dir("sixteenth-rename-clean-out")
    assert _build(repo, out_dir) == 0, capsys.readouterr().err
    assert (out_dir / "trace.json").exists()


# ------------------------------------------------------- I-2 CUSTOM_OBJ 拒绝

CONST_REPO = """import torch
import torch.nn as nn


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = torch.ones(2, 4)

    def forward(self, x):
        return x + self.w

    def example_inputs(self):
        return (torch.zeros(2, 4),)


def build_model():
    return M().eval()
"""


def test_cli_exits_2_on_custom_obj(monkeypatch, capsys):
    repo = _write_repo("sixteenth-custom-obj", CONST_REPO)
    out_dir = scratch_dir("sixteenth-custom-obj-out")
    real_export = torch.export.export

    def tampered(module, args, **kwargs):
        exported = real_export(module, args, **kwargs)
        for spec in exported.graph_signature.input_specs:
            if spec.kind == InputKind.CONSTANT_TENSOR:
                spec.kind = InputKind.CUSTOM_OBJ
        return exported

    monkeypatch.setattr(torch.export, "export", tampered)
    assert _build(repo, out_dir) == 2
    err = capsys.readouterr().err
    assert "CUSTOM_OBJ" in err and "ScriptObject" in err, err
    assert "Traceback" not in err, err
    assert not (out_dir / "trace.json").exists()


def test_the_same_constant_repo_without_the_mutation_still_builds(capsys):
    repo = _write_repo("sixteenth-const-clean", CONST_REPO)
    out_dir = scratch_dir("sixteenth-const-clean-out")
    assert _build(repo, out_dir) == 0, capsys.readouterr().err
    trace = json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))
    kinds = {n["label"]: n["kind"] for n in trace["nodes"] if n.get("kind") == "const"}
    assert kinds == {"root.c_w": "const"}, kinds


# ------------------------------------------------------- M-1 后缀规则的两层

class Two(nn.Module):
    def __init__(self):
        super().__init__()
        self.a = nn.Parameter(torch.ones(2, 4))
        self.a_1 = nn.Parameter(torch.ones(2, 4) * 2)

    def forward(self, x):
        return x + self.a + self.a_1


class One(nn.Module):
    def __init__(self):
        super().__init__()
        self.a_1 = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.a_1


def test_suffix_forgery_is_accepted_by_the_name_gate_alone():
    """钉死单关边界：p_a_1 配 target='a' 在这一关是接受的（评审 M-1）。

    这不是洞的许可，而是把「这一关不是完整权威」写成显式用例：端到端由
    check_contract 拒绝，见下面两条。
    """
    check_name_target([_N("p_a_1")], _plan(("p_a_1", "param", "a")))


def _contract(module, exported):
    plan = input_plan(exported)
    check_contract([n.name for n in exported.graph.nodes if n.op == "placeholder"],
                   plan, dict(module.named_parameters(remove_duplicate=False)),
                   dict(module.named_buffers(remove_duplicate=False)))


@pytest.mark.parametrize("cls,fragment", [
    (Two, "认领了多次"), (One, "没被任何"),
], ids=["two-params-duplicate", "one-param-unclaimed"])
def test_suffix_forgery_is_refused_end_to_end(cls, fragment):
    module, exported = _exported(cls(), ONE)
    for spec in exported.graph_signature.input_specs:
        if str(spec.target) == "a_1":
            spec.target = "a"
    with pytest.raises(BuildError) as info:
        _contract(module, exported)
    assert fragment in str(info.value), str(info.value)


def test_unforged_suffix_models_pass_the_contract():
    """反向对照：合法的 a/a_1 与只有 a_1 的模型都不该被拒。"""
    for cls in (Two, One):
        module, exported = _exported(cls(), ONE)
        _contract(module, exported)


# ------------------------------------------------------- M-2 报错要能看懂

def test_error_shows_both_the_observed_base_and_the_expected_one():
    with pytest.raises(BuildError) as info:
        check_name_target([_N("p_x")], _plan(("p_x", "param", "a")))
    text = str(info.value)
    assert "base 是 'x'" in text, text
    assert "应当是 'a'" in text, text


# ------------------------------------------------------- M-3 期望表独立推导

@pytest.mark.parametrize("cls", MODELS, ids=[c.__name__ for c in MODELS])
def test_parents_table_is_derived_from_the_module_not_the_trace(cls):
    """用导出器的 spec + 模块自己的 named_modules 推 parent，不经 trace 管线。"""
    module, exported = _exported(cls(), ONE)
    owners = {name for name, _ in module.named_modules()}
    expected = {}
    for item in input_plan(exported):
        if item["kind"] == "input":
            continue
        owner = str(item["target"]).rpartition(".")[0]
        assert owner in owners, (owner, sorted(owners))
        expected["root." + item["name"]] = "root" + ("/" + owner if owner else "")
    assert expected == PARENTS[cls.__name__], (expected, PARENTS[cls.__name__])


# ------------------------------------------- M-3（第十七轮）期望表要真正独立

# 手写表：placeholder 名 → **模块里的属性路径**。依据是六个模型类的源码结构
# （self_attn=Linear、attn=Linear、add_module('a-b') 等），不是 input_plan 的输出。
# 第十七轮评审指出原来那条用例「半独立」：它用被测的 input_plan 取 target，
# 所以抓得到 trace 管线写错 parent，却抓不到 input_plan 自己把 name→target 映射错。
# 这张表补上那一层：先核每个 target 真的是模块的参数/缓冲键，再核 input_plan 与表一致。
TARGETS = {
    "SelfAttnClash": {
        "p_attn_weight": "self_attn.weight", "p_attn_bias": "self_attn.bias",
        "p_attn_weight_1": "attn.weight", "p_attn_bias_1": "attn.bias",
    },
    "SelfAB": {"p_a_weight": "self_a.weight", "p_b_weight": "self_b.weight"},
    "Hyphen": {"p_a_b_weight": "a-b.weight", "p_a_b_weight_1": "a_b.weight"},
    "Upper": {"p_w": "W", "p_w_1": "w"},
    "NestedSelf": {
        "p_sub_self_attn_weight": "sub.self_attn.weight",
        "p_sub_self_attn_bias": "sub.self_attn.bias",
        "p_sub_attn_weight": "sub.attn.weight",
        "p_sub_attn_bias": "sub.attn.bias",
    },
    "SelfX": {"p_x": "x", "p_x_1": "self_x"},
}


@pytest.mark.parametrize("cls", MODELS, ids=[c.__name__ for c in MODELS])
def test_hand_written_targets_are_real_module_attributes_and_match_input_plan(cls):
    """地面真相是模块自己的参数/缓冲注册表，不是被测代码的映射。"""
    module, exported = _exported(cls(), ONE)
    registry = {n for n, _ in module.named_parameters(remove_duplicate=False)}
    registry |= {n for n, _ in module.named_buffers(remove_duplicate=False)}
    table = TARGETS[cls.__name__]
    for name, target in table.items():
        assert target in registry, (name, target, sorted(registry))
    from_plan = {
        i["name"]: i["target"] for i in input_plan(exported) if i["kind"] != "input"
    }
    assert from_plan == table, (from_plan, table)
    owners = {name for name, _ in module.named_modules()}
    expected = {}
    for name, target in table.items():
        owner = target.rpartition(".")[0]
        assert owner in owners, (owner, sorted(owners))
        expected["root." + name] = "root" + ("/" + owner if owner else "")
    assert expected == PARENTS[cls.__name__], (expected, PARENTS[cls.__name__])