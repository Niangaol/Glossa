"""第十二轮评审的回归测试：权威必须来自导出器、顺序不变量、恰好认领一次、退出码。

I-1 check_plan_source/check_plan_table 的 expected 是从**调用方传进来的** exported 重生的，
    传一个 SimpleNamespace 就能让 plan 与 expected 一起错。三道防线：
    ① require_real_export 类型守卫（拒替身）；
    ② torch.export 自己写死的顺序不变量（权重/缓冲/常量全部排在数据输入之前）；
    ③ 每个参数/常量恰好被认领一次（Counter，不是 set）。
    ②③ 在**真** ExportedProgram 上就地改 input_specs 也复现过，所以类型守卫单独不够。
I-3 TOKEN → exit 2（契约错误）、forward 内 no_grad → exit 5（能力边界），都要有 CLI 用例。
Minor 字典输出也算被引用；mutation 的结果不在 output 里也不算孤点；zoo 断言改集合相等。
"""

from collections import Counter
from types import SimpleNamespace

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import torch  # noqa: E402
from torch import nn  # noqa: E402
from torch.export.graph_signature import InputKind, InputSpec, TokenArgument  # noqa: E402

from papertrace import cli  # noqa: E402
from papertrace.exceptions import BuildError  # noqa: E402
from papertrace.parse_code import fx_trace  # noqa: E402
from papertrace.parse_code.fx_contract import check_contract  # noqa: E402
from papertrace.parse_code.fx_edges import finish_nodes, output_node_ids  # noqa: E402
from papertrace.parse_code.fx_nodes import build_op_nodes  # noqa: E402
from papertrace.parse_code.fx_signature import (  # noqa: E402
    classify,
    input_plan,
    placeholder_args,
)
from papertrace.parse_code.fx_trace import _ensure_export_cache, trace_module  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402
from tests.papertrace.test_model_zoo import ZOO  # noqa: E402
from tests.review.test_seventh_review import ENTRY, _write_repo  # noqa: E402

ONE = (torch.zeros(2, 4),)


def _exported(module, example):
    _ensure_export_cache()
    module = module.eval()
    return module, torch.export.export(module, example)


def _stand_in(exported):
    """鸭子类型的替身：三个属性都真，只有类型不是 ExportedProgram。"""
    return SimpleNamespace(
        graph=exported.graph,
        graph_signature=exported.graph_signature,
        constants=exported.constants,
    )


class Shadowed(nn.Module):
    """参数名与 forward 形参名同名：p_x 是权重、x 是数据输入。"""

    def __init__(self):
        super().__init__()
        self.x = nn.Parameter(torch.zeros(2, 4))

    def forward(self, x):
        return x + self.x


class TwoWeights(nn.Module):
    def __init__(self):
        super().__init__()
        self.a = nn.Parameter(torch.ones(2, 4))
        self.b = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.a + self.b


# ------------------------------------------------- I-1 ① 类型守卫：拒绝替身

def test_a_hand_built_stand_in_is_refused_at_the_entry():
    module, exported = _exported(Shadowed(), ONE)
    fake = _stand_in(exported)
    plan = input_plan(fake)  # 替身照样能摊平出 plan——所以不能靠「能不能用」判断
    assert [i["kind"] for i in plan] == ["param", "input"], plan
    with pytest.raises(BuildError) as info:
        placeholder_args(module, fake, plan, ONE)
    text = str(info.value)
    assert "ExportedProgram" in text and "替身" in text, text


def test_build_op_nodes_also_refuses_a_stand_in():
    _, exported = _exported(Shadowed(), ONE)
    plan = classify(input_plan(exported))
    with pytest.raises(BuildError) as info:
        build_op_nodes(
            exported.graph, "root", {"root": "root"}, "root",
            plan=plan, exported=_stand_in(exported),
        )
    assert "ExportedProgram" in str(info.value)


def test_the_real_export_is_still_accepted():
    """反向对照：守卫不是恒真拒绝，真产物照常拿到模块里的参数。"""
    module, exported = _exported(Shadowed(), ONE)
    assert isinstance(exported, torch.export.ExportedProgram)
    args = placeholder_args(module, exported, input_plan(exported), ONE)
    assert args[0] is module.x and args[1] is ONE[0], args


# ------------------------------- I-1 ② 顺序不变量：真产物上就地互换也要拒绝

def test_swapping_specs_inside_a_real_export_is_refused():
    module, exported = _exported(Shadowed(), ONE)
    assert isinstance(exported, torch.export.ExportedProgram), "类型守卫这一关是过的"
    for spec in exported.graph_signature.input_specs:
        if spec.kind == InputKind.PARAMETER:
            spec.kind, spec.target = InputKind.USER_INPUT, None
        elif spec.kind == InputKind.USER_INPUT:
            spec.kind, spec.target = InputKind.PARAMETER, "x"
    plan = input_plan(exported)
    assert [i["kind"] for i in plan] == ["input", "param"], plan
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, plan, ONE)
    text = str(info.value)
    assert "顺序约定" in text and "标反" in text, text


# ------------------------------- I-1 ③ 恰好认领一次：重复 target 也要拒绝

def test_claiming_one_weight_twice_is_refused():
    module, exported = _exported(TwoWeights(), ONE)
    params = [s for s in exported.graph_signature.input_specs if s.kind == InputKind.PARAMETER]
    assert len(params) == 2, params
    params[1].target = params[0].target  # 两个 placeholder 都指向 a
    plan = input_plan(exported)
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, plan, ONE)
    text = str(info.value)
    assert "认领了多次" in text and "a" in text, text


@pytest.mark.parametrize("name,cls,example,expected", ZOO, ids=[z[0] for z in ZOO])
def test_real_models_obey_the_ordering_and_claim_each_weight_once(name, cls, example, expected):
    """正向对照：18 个真实模型都不该被这两条新不变量误杀（probe13b 量过 24 个）。"""
    module, exported = _exported(cls(), example)
    plan = input_plan(exported)
    kinds = [i["kind"] for i in plan]
    first = kinds.index("input") if "input" in kinds else len(kinds)
    assert all(k == "input" for k in kinds[first:]), (name, plan)
    targets = [i["target"] for i in plan if i["kind"] in ("param", "const") and i.get("target")]
    assert all(n == 1 for n in Counter(targets).values()), (name, targets)
    placeholders = [n.name for n in exported.graph.nodes if n.op == "placeholder"]
    check_contract(
        placeholders, plan,
        dict(module.named_parameters(remove_duplicate=False)),
        dict(module.named_buffers(remove_duplicate=False)),
    )
    args = placeholder_args(module, exported, plan, example)
    assert len(args) == len(placeholders), (name, args)


class DictIn(nn.Module):
    def forward(self, d):
        return d["a"] + d["b"]


class ListIn(nn.Module):
    def forward(self, items):
        return items[0] + items[1]


class VarArgs(nn.Module):
    def forward(self, *args):
        return args[0] + args[1]


@pytest.mark.parametrize("cls,example,flat", [
    (DictIn, ({"a": torch.zeros(2, 4), "b": torch.zeros(2, 4)},), (torch.zeros(2, 4),) * 2),
    (ListIn, ([torch.zeros(2, 4), torch.zeros(2, 4)],), (torch.zeros(2, 4),) * 2),
    (VarArgs, (torch.zeros(2, 4), torch.zeros(2, 4)), (torch.zeros(2, 4),) * 2),
], ids=["dict-in", "list-in", "varargs"])
def test_pytree_inputs_are_not_refused_by_the_new_invariants(cls, example, flat):
    """pytree 会被摊平成多个 USER_INPUT：顺序不变量与认领判据都不该误杀。"""
    module, exported = _exported(cls(), example)
    plan = input_plan(exported)
    assert [i["kind"] for i in plan] == ["input", "input"], plan
    placeholders = [n.name for n in exported.graph.nodes if n.op == "placeholder"]
    check_contract(placeholders, plan, {}, {})
    assert len(placeholder_args(module, exported, plan, flat)) == 2


# ------------------------------------------------- I-3 退出码：CLI 级用例

SIMPLE = """import torch
import torch.nn as nn


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w

    def example_inputs(self):
        return torch.zeros(2, 4)


def build_model():
    return M().eval()
"""

TWO_WEIGHTS = SIMPLE.replace(
    "        self.w = nn.Parameter(torch.ones(2, 4))",
    "        self.a = nn.Parameter(torch.ones(2, 4))\n"
    "        self.b = nn.Parameter(torch.ones(2, 4))",
).replace("return x + self.w", "return x + self.a + self.b")

NO_GRAD = SIMPLE.replace(
    "        return x + self.w",
    "        with torch.no_grad():\n            return x + self.w",
)

MUTATION = """import torch
import torch.nn as nn


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.register_buffer("acc", torch.zeros(2, 4))

    def forward(self, x):
        self.acc.add_(x)
        return self.acc * 2

    def example_inputs(self):
        return torch.zeros(2, 4)


def build_model():
    return M().eval()
"""


def _build(repo, out_dir):
    return cli.main(["build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir)])


def test_cli_exits_2_when_the_exporter_emits_a_token(monkeypatch, capsys):
    """TOKEN 是契约错误（本切片不支持这种 spec），不是「torch 追不动」→ exit 2。"""
    repo = _write_repo("twelfth-token-cli", SIMPLE)
    out_dir = scratch_dir("twelfth-token-cli-out")
    real_plan = fx_trace.input_plan

    def with_token(exported):
        exported.graph_signature.input_specs.append(
            InputSpec(kind=InputKind.TOKEN, arg=TokenArgument(name="tok"), target=None)
        )
        return real_plan(exported)

    monkeypatch.setattr(fx_trace, "input_plan", with_token)
    assert _build(repo, out_dir) == 2
    err = capsys.readouterr().err
    assert "TOKEN" in err and "TokenArgument" in err, err
    assert not (out_dir / "trace.json").exists(), "拒绝出图时不能留下 trace"


def test_cli_exits_5_for_no_grad_inside_forward(capsys):
    """forward 里的 no_grad 被导出器包成子模块：能力边界 → exit 5，且提示可操作。"""
    repo = _write_repo("twelfth-nograd-cli", NO_GRAD)
    out_dir = scratch_dir("twelfth-nograd-cli-out")
    assert _build(repo, out_dir) == 5
    err = capsys.readouterr().err
    assert "子模块" in err and "no_grad" in err, err
    assert "Traceback" not in err, err
    assert not (out_dir / "trace.json").exists()


def test_cli_exits_2_when_a_weight_is_claimed_twice(monkeypatch, capsys):
    repo = _write_repo("twelfth-dup-cli", TWO_WEIGHTS)
    out_dir = scratch_dir("twelfth-dup-cli-out")
    real_plan = fx_trace.input_plan

    def duplicated(exported):
        params = [s for s in exported.graph_signature.input_specs if s.kind == InputKind.PARAMETER]
        params[1].target = params[0].target
        return real_plan(exported)

    monkeypatch.setattr(fx_trace, "input_plan", duplicated)
    assert _build(repo, out_dir) == 2
    err = capsys.readouterr().err
    assert "认领了多次" in err, err
    assert not (out_dir / "trace.json").exists()


def test_cli_mutation_result_is_not_an_orphan(capsys):
    """mutation 的结果没被 return，但它有入边：不算孤点（本切片不做死代码检测）。"""
    repo = _write_repo("twelfth-mutation-cli", MUTATION)
    out_dir = scratch_dir("twelfth-mutation-cli-out")
    assert _build(repo, out_dir) == 0, capsys.readouterr().err
    import json

    doc = json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))
    counts = doc["meta"]["runtime"]["counts"]
    assert counts["orphan"] == 0, counts
    assert counts["shape_broken"] == 0, counts


# ------------------------------------------------- Minor 字典输出也算被引用

class DictOut(nn.Module):
    def forward(self, x):
        return {"a": torch.ones(2, 4), "b": torch.arange(4)}


def test_dict_output_references_are_all_counted_as_used():
    module, exported = _exported(DictOut(), ONE)
    plan = classify(input_plan(exported))
    ops, by_name, _ = build_op_nodes(exported.graph, "root", {"root": "root"}, "root", plan=plan)
    used = output_node_ids(exported.graph, by_name)
    assert len(used) == 2, used
    assert finish_nodes(ops, [], outputs=used)["orphan"] == 0
    assert finish_nodes(ops, [])["orphan"] == 2, "不传 outputs 就会误报——这条证明参数有用"


def test_dict_output_model_traces_with_zero_orphans():
    traced = trace_module(DictOut(), ONE)
    counts = traced["runtime"]["counts"]
    assert counts["orphan"] == 0, counts
    assert traced["edges"] == [], "直接输出的常量确实没有边"

# ------------------------------- 能力边界：pytree 输入不自动摊平（CLI 级）

DICT_IN = """import torch
import torch.nn as nn


class M(nn.Module):
    def forward(self, d):
        return d["a"] + d["b"]

    def example_inputs(self):
        return {"a": torch.zeros(2, 4), "b": torch.zeros(2, 4)}


def build_model():
    return M().eval()
"""


def test_cli_exits_5_when_pytree_inputs_are_not_flattened(capsys):
    """导出器把 dict 摊成 d_a/d_b 两个数据输入，example_inputs() 给的是一个容器。

    本切片不猜容器的摊平顺序（自定义 pytree 的 flatten 顺序不由我们决定），
    所以 fail-closed：exit 5、点名图里有几个数据输入、不写 trace。
    """
    repo = _write_repo("twelfth-dictin-cli", DICT_IN)
    out_dir = scratch_dir("twelfth-dictin-cli-out")
    assert _build(repo, out_dir) == 5
    err = capsys.readouterr().err
    assert "2 个数据输入" in err and "d_a" in err and "d_b" in err, err
    assert not (out_dir / "trace.json").exists()
