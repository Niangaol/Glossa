"""第十五轮评审的回归测试：第八道关的命名映射必须与 torch 一致。

C1 误杀：torch 生成 placeholder 名字时先剥**开头**的 `L__self___`/`self_`、把非字母
    数字换成 `_`、再 `lower()`（pydeps/torch/_export/utils.py:1113-1119、:1168）。
    第十四轮只按 `target.replace(".", "_")` 反推，于是 `self_attn`+`attn`、`a-b`+`a_b`、
    `W`+`w`、`x`+`self_x` 这些**合法**模型全部 exit 2（评审 output/review14/repos/）。
C2 漏检：`self_a`/`self_b` 的 base 在反推索引里查不到 → 静默跳过 → 互换 target 后
    parent_id 写反而 CLI exit 0。这不是已文档化的压平歧义，是映射缺失。

修法：反推索引 → **正向核对**（fx_names.strip_name + _matches）。本文件用六个真实
模型钉死两件事：①合法模型一个都不许误杀，且 parent_id 必须正确；②我们的 strip_name
与 torch **真实生成的名字**逐个交叉核对——评审说得对，「地面真相独立」不等于「我的
映射正确」，所以期望值取自导出器的实际输出，不是取自我自己的实现。

诚实边界：压平撞名（self_attn.weight 与 attn.weight 都映射到 attn_weight）时互换
仍然抓不到，本文件把它钉成 trace 级证据，不假装封死。
"""

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import json  # noqa: E402

import torch  # noqa: E402
from torch import nn  # noqa: E402

from papertrace.exceptions import BuildError  # noqa: E402
from papertrace.parse_code.fx_contract import (  # noqa: E402
    check_contract,
    check_plan_source,
    check_plan_table,
)
from papertrace.parse_code.fx_names import PREFIXES, strip_name  # noqa: E402
from papertrace.parse_code.fx_signature import (  # noqa: E402
    classify,
    input_plan,
    module_of_target,
    placeholder_args,
)
from papertrace.parse_code.fx_trace import trace_module  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402
from tests.test_seventh_review import ENTRY, _write_repo  # noqa: E402
from tests.test_twelfth_review import _build, _exported  # noqa: E402

ONE = (torch.zeros(2, 4),)


class Sub4(nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(4))

    def forward(self, x):
        return x + self.weight


class SelfAttnClash(nn.Module):
    """self_attn 与 attn：剥掉开头的 self_ 之后撞基名（评审 C1 的反例）。"""

    def __init__(self):
        super().__init__()
        self.self_attn = nn.Linear(4, 4)
        self.attn = nn.Linear(4, 4)

    def forward(self, x):
        return self.self_attn(x) + self.attn(x)


class SelfAB(nn.Module):
    """self_a 与 self_b：剥掉 self_ 之后**不**撞名（评审 C2 的反例）。"""

    def __init__(self):
        super().__init__()
        self.self_a = Sub4()
        self.self_b = Sub4()

    def forward(self, x):
        return self.self_a(x) + self.self_b(x)


class Hyphen(nn.Module):
    """a-b 与 a_b：非字母数字被 sanitize 成 _ 之后撞基名。"""

    def __init__(self):
        super().__init__()
        self.add_module("a-b", Sub4())
        self.add_module("a_b", Sub4())

    def forward(self, x):
        return getattr(self, "a-b")(x) + self.a_b(x)


class Upper(nn.Module):
    """W 与 w：torch 会 lower()。"""

    def __init__(self):
        super().__init__()
        self.W = nn.Parameter(torch.ones(4))
        self.w = nn.Parameter(torch.zeros(4))

    def forward(self, x):
        return x + self.W + self.w


class NestedSelf(nn.Module):
    """嵌套的 self_ **不剥**：只剥开头那一个。"""

    def __init__(self):
        super().__init__()
        self.sub = SelfAttnClash()

    def forward(self, x):
        return self.sub(x)


class SelfX(nn.Module):
    """参数 x 与 self_x：剥掉 self_ 之后撞基名。"""

    def __init__(self):
        super().__init__()
        self.x = nn.Parameter(torch.ones(4))
        self.self_x = nn.Parameter(torch.zeros(4))

    def forward(self, t):
        return t + self.x + self.self_x


# 期望值来自 output/probes/probe18.py 的实测（不是从被测代码反推）。
PARENTS = {
    "SelfAttnClash": {
        "root.p_attn_weight": "root/self_attn", "root.p_attn_bias": "root/self_attn",
        "root.p_attn_weight_1": "root/attn", "root.p_attn_bias_1": "root/attn",
    },
    "SelfAB": {"root.p_a_weight": "root/self_a", "root.p_b_weight": "root/self_b"},
    "Hyphen": {"root.p_a_b_weight": "root/a-b", "root.p_a_b_weight_1": "root/a_b"},
    "Upper": {"root.p_w": "root", "root.p_w_1": "root"},
    "NestedSelf": {
        "root.p_sub_self_attn_weight": "root/sub.self_attn",
        "root.p_sub_self_attn_bias": "root/sub.self_attn",
        "root.p_sub_attn_weight": "root/sub.attn",
        "root.p_sub_attn_bias": "root/sub.attn",
    },
    "SelfX": {"root.p_x": "root", "root.p_x_1": "root"},
}
MODELS = [SelfAttnClash, SelfAB, Hyphen, Upper, NestedSelf, SelfX]
IDS = [c.__name__ for c in MODELS]


def _parents(trace):
    return {n["label"]: n["parent_id"] for n in trace["nodes"]
            if n.get("kind") in ("param", "const")}


@pytest.mark.parametrize("cls", MODELS, ids=IDS)
def test_legitimate_naming_is_not_refused_and_parents_are_right(cls):
    """C1：六个模型以前有四个 exit 2。现在必须建得出来，而且 parent_id 是对的。"""
    trace = trace_module(cls().eval(), list(ONE))
    assert _parents(trace) == PARENTS[cls.__name__], _parents(trace)
    assert trace["runtime"]["counts"]["shape_broken"] == 0
    ids = {n["id"] for n in trace["nodes"]}
    assert all(n["parent_id"] in ids for n in trace["nodes"] if n.get("parent_id"))


@pytest.mark.parametrize("cls", MODELS, ids=IDS)
def test_strip_name_reproduces_torchs_actual_placeholder_names(cls):
    """把我们的映射与导出器**真实生成的名字**逐个对照（评审：独立不等于正确）。

    断言里的后缀规则是独立写出来的，不调用被测的 _matches。
    """
    module, exported = _exported(cls(), ONE)
    checked = 0
    for item in input_plan(exported):
        if item["kind"] == "input":
            continue
        prefix = next(p for p in PREFIXES if item["name"].startswith(p))
        base = item["name"][len(prefix):]
        want = strip_name(item["target"])
        head, sep, tail = base.rpartition("_")
        assert base == want or (sep and tail.isdigit() and head == want), (item, want)
        checked += 1
    non_input = sum(1 for i in input_plan(exported) if i["kind"] != "input")
    assert checked == non_input and checked > 0, (checked, non_input)


def _swap_weights(exported):
    """只互换 target 以 .weight 结尾的那两条 spec（同形状，形状关看不见）。"""
    specs = exported.graph_signature.input_specs
    idx = [i for i, s in enumerate(specs) if str(s.target).endswith(".weight")]
    assert len(idx) == 2, idx
    a, b = idx
    specs[a].target, specs[b].target = specs[b].target, specs[a].target
    return exported


def _older_gates(module, exported, plan):
    named = {**dict(module.named_parameters(remove_duplicate=False)),
             **dict(module.named_buffers(remove_duplicate=False))}
    check_contract([n.name for n in exported.graph.nodes if n.op == "placeholder"],
                   plan, named, dict(exported.constants or {}))
    check_plan_source(plan, input_plan(exported))
    check_plan_table(classify(plan), classify(input_plan(exported)))


def test_self_prefix_module_swap_is_now_refused():
    """C2：self_a/self_b 以前静默跳过，互换后 parent_id 写反且 CLI exit 0。"""
    module, exported = _exported(SelfAB(), ONE)
    _swap_weights(exported)
    plan = input_plan(exported)
    _older_gates(module, exported, plan)  # 前几关确实全过，证明是新关抓住的
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, plan, ONE)
    text = str(info.value)
    assert "名字" in text and "target" in text and "被改过" in text, text
    assert "p_a_weight" in text and "self_b.weight" in text, text


def test_the_self_prefix_swap_really_would_write_the_wrong_parent_id():
    """不只看报错：把伪造 plan 的 owner 算出来，证明错误是**可见**的。"""
    module, exported = _exported(SelfAB(), ONE)
    real = {i["name"]: module_of_target(i["target"]) for i in input_plan(exported)
            if i["kind"] != "input"}
    _swap_weights(exported)
    forged = {i["name"]: module_of_target(i["target"]) for i in input_plan(exported)
              if i["kind"] != "input"}
    assert real == {"p_a_weight": "self_a", "p_b_weight": "self_b"}, real
    assert forged == {"p_a_weight": "self_b", "p_b_weight": "self_a"}, forged
    assert real != forged


def test_flattening_clash_swap_is_still_not_observable_by_name(monkeypatch):
    """诚实边界：self_attn.weight 与 attn.weight 正向映射到同一个 base，互换抓不到。

    这里构建整份 trace 证明 parent_id 确实写反（评审要求洞要有证据，不能只写文档）。
    trace_module 内部会自己重新 export，所以篡改必须落在 torch.export.export 上。
    """
    module, exported = _exported(SelfAttnClash(), ONE)
    clean = _parents(trace_module(module, list(ONE)))
    _swap_weights(exported)
    plan = input_plan(exported)
    args = placeholder_args(module, exported, plan, ONE)  # 不抛：名字区分不了
    assert len(args) == 5, args
    real_export = torch.export.export
    monkeypatch.setattr(
        torch.export, "export",
        lambda m, a, **k: _swap_weights(real_export(m, a, **k)))
    tampered = trace_module(SelfAttnClash().eval(), list(ONE))
    forged = _parents(tampered)
    assert forged["root.p_attn_weight"] == "root/attn", forged
    assert forged["root.p_attn_weight_1"] == "root/self_attn", forged
    assert forged["root.p_attn_bias"] == "root/self_attn", forged
    assert forged != clean
    assert tampered["runtime"]["counts"]["shape_broken"] == 0


# ------------------------------------------------------------------ CLI 级

CLASH_REPO = """import torch
import torch.nn as nn


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.self_attn = nn.Linear(4, 4)
        self.attn = nn.Linear(4, 4)

    def forward(self, x):
        return self.self_attn(x) + self.attn(x)

    def example_inputs(self):
        return (torch.zeros(2, 4),)


def build_model():
    return M().eval()
"""

SELF_AB_REPO = """import torch
import torch.nn as nn


class Sub(nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(4))

    def forward(self, x):
        return x + self.weight


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.self_a = Sub()
        self.self_b = Sub()

    def forward(self, x):
        return self.self_a(x) + self.self_b(x)

    def example_inputs(self):
        return (torch.zeros(2, 4),)


def build_model():
    return M().eval()
"""

HYPHEN_REPO = """import torch
import torch.nn as nn


class Sub(nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(4))

    def forward(self, x):
        return x + self.weight


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.add_module("a-b", Sub())
        self.add_module("a_b", Sub())

    def forward(self, x):
        return getattr(self, "a-b")(x) + self.a_b(x)

    def example_inputs(self):
        return (torch.zeros(2, 4),)


def build_model():
    return M().eval()
"""


@pytest.mark.parametrize("name,source,parents", [
    ("fifteenth-clash", CLASH_REPO, PARENTS["SelfAttnClash"]),
    ("fifteenth-selfab", SELF_AB_REPO, PARENTS["SelfAB"]),
    ("fifteenth-hyphen", HYPHEN_REPO, PARENTS["Hyphen"]),
], ids=["self-attn-clash", "self-a-self-b", "hyphen"])
def test_cli_builds_legitimate_naming(name, source, parents, capsys):
    repo = _write_repo(name, source)
    out_dir = scratch_dir(name + "-out")
    assert _build(repo, out_dir) == 0, capsys.readouterr().err
    trace = json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))
    got = {n["label"]: n["parent_id"] for n in trace["nodes"]
           if n.get("kind") in ("param", "const")}
    assert got == parents, got


def test_cli_exits_2_when_self_prefix_targets_are_swapped(monkeypatch, capsys):
    """篡改 torch.export.export 的返回值：所有 input_plan 绑定看到同一份坏 spec。"""
    repo = _write_repo("fifteenth-selfab-swap", SELF_AB_REPO)
    out_dir = scratch_dir("fifteenth-selfab-swap-out")
    real_export = torch.export.export

    def tampered(module, args, **kwargs):
        return _swap_weights(real_export(module, args, **kwargs))

    monkeypatch.setattr(torch.export, "export", tampered)
    assert _build(repo, out_dir) == 2
    err = capsys.readouterr().err
    assert "名字" in err and "对不上" in err, err
    assert "Traceback" not in err, err
    assert not (out_dir / "trace.json").exists()
