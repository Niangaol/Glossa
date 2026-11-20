"""第十一轮评审的回归测试：kind 的权威是导出器、CUSTOM_OBJ/TOKEN、输出边界与孤点。

C1  名字覆盖齐全 + 顺序对 + 参数都被认领 + example_inputs 数量对，仍然可以把权重与
    输入**互换**标（模块有名为 x 的参数、forward 也有形参 x）。唯一的地面真相是
    torch.export 自己的 input_specs，placeholder_args 必须逐项核对传入的 plan。
I-1 CUSTOM_OBJ 是 exported.constants 里的 ScriptObject 常量，不是数据输入；
    TOKEN 是 TokenArgument，明确拒绝而不是按张量喂。
I-2 直接 return 的常量/零实参算子没有边，但被图输出引用，不是孤点。
I-3 有入边却没人用的死算子：本切片**不**做死代码检测（README 写死这条取舍）。
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import torch  # noqa: E402
from torch import nn  # noqa: E402
from torch.export.graph_signature import InputKind  # noqa: E402

from papertrace.exceptions import BuildError  # noqa: E402
from papertrace.parse_code import fx_trace  # noqa: E402
from papertrace.parse_code.fx_contract import check_contract, check_plan_source  # noqa: E402
from papertrace.parse_code.fx_edges import finish_nodes, output_node_ids  # noqa: E402
from papertrace.parse_code.fx_kinds import KIND_MAP, REFUSED_KINDS  # noqa: E402
from papertrace.parse_code.fx_signature import (  # noqa: E402
    classify,
    input_plan,
    placeholder_args,
)
from papertrace.parse_code.fx_trace import _ensure_export_cache, trace_module  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402
from tests.review.test_seventh_review import ENTRY, _write_repo  # noqa: E402


def _exported(module, example):
    _ensure_export_cache()
    module = module.eval()
    return module, torch.export.export(module, example)


class Shadowed(nn.Module):
    """参数名与 forward 形参名同名：p_x 是权重、x 是数据输入。"""

    def __init__(self):
        super().__init__()
        self.x = nn.Parameter(torch.zeros(2, 4))

    def forward(self, x):
        return x + self.x


def _swapped(plan):
    """把权重与输入的 kind/target 互换——四道旧关卡全都过得去。"""
    out = [dict(item) for item in plan]
    for item in out:
        if item["name"] == "p_x":
            item["kind"], item["target"] = "input", None
        elif item["name"] == "x":
            item["kind"], item["target"] = "param", "x"
    return out


# ---------------------------------------------------------------- C1 kind 互换

def test_swapped_kinds_fool_names_and_counts_but_break_the_ordering():
    """坏 plan 骗得过名字/顺序/认领/数量，但骗不过 torch 的「权重在前」不变量。

    第十二轮之前这里断言 check_contract **不抛**（证明旧关卡不足）；现在顺序不变量
    已经是 check_contract 的一部分，所以改成断言它抛。数量校验仍然被骗过这一点
    保留下来——它说明为什么不能只靠 example_inputs 的个数兜底。
    """
    module, exported = _exported(Shadowed(), (torch.zeros(2, 4),))
    bad = _swapped(input_plan(exported))
    placeholders = [n.name for n in exported.graph.nodes if n.op == "placeholder"]
    params = dict(module.named_parameters(remove_duplicate=False))
    buffers = dict(module.named_buffers(remove_duplicate=False))
    users = [i["name"] for i in bad if i["kind"] == "input"]
    assert users == ["p_x"], users
    assert len(users) == 1, "example_inputs 给一项就够，数量校验也被骗过"
    with pytest.raises(BuildError) as info:
        check_contract(placeholders, bad, params, buffers)
    text = str(info.value)
    assert "顺序约定" in text and "标反" in text, text


def test_swapped_kinds_are_refused_against_the_exporter():
    module, exported = _exported(Shadowed(), (torch.zeros(2, 4),))
    bad = _swapped(input_plan(exported))
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, bad, (torch.zeros(2, 4),))
    text = str(info.value)
    # 第十二轮之后顺序不变量先命中（它也是导出器的约定）；逐项核对仍是第二道。
    assert "顺序约定" in text and "标反" in text, text


def test_real_plan_still_puts_the_parameter_first():
    """反向对照：真 plan 必须照常通过，且 args 顺序与图一致（权重在前）。"""
    module, exported = _exported(Shadowed(), (torch.zeros(2, 4),))
    data = torch.zeros(2, 4)
    args = placeholder_args(module, exported, input_plan(exported), (data,))
    assert len(args) == 2, args
    assert args[0] is module.x, "第一个 placeholder 是权重，必须拿到模块里的参数"
    assert args[1] is data, "第二个才是数据输入"


def test_cli_exits_2_and_writes_no_trace_when_kinds_are_swapped(monkeypatch, capsys):
    from papertrace import cli

    repo = _write_repo("eleventh-swap-cli", """import torch
import torch.nn as nn


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.x = nn.Parameter(torch.zeros(2, 4))

    def forward(self, x):
        return x + self.x

    def example_inputs(self):
        return torch.zeros(2, 4)


def build_model():
    return M().eval()
""")
    out_dir = scratch_dir("eleventh-swap-cli-out")
    real_plan = fx_trace.input_plan
    monkeypatch.setattr(fx_trace, "input_plan", lambda exported: _swapped(real_plan(exported)))
    code = cli.main(["build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir)])
    assert code == 2, code
    assert "顺序约定" in capsys.readouterr().err
    assert not (out_dir / "trace.json").exists(), "拒绝出图时不能留下 trace"


@pytest.mark.parametrize("mutate", ["kind", "target", "order", "missing", "extra"],
                         ids=["kind", "target", "order", "missing", "extra"])
def test_check_plan_source_catches_each_mutation(mutate):
    expected = [
        {"name": "p_w", "kind": "param", "target": "w"},
        {"name": "x", "kind": "input", "target": None},
    ]
    plan = [dict(item) for item in expected]
    if mutate == "kind":
        plan[0]["kind"] = "input"
    elif mutate == "target":
        plan[0]["target"] = "sub.w"
    elif mutate == "order":
        plan.reverse()
    elif mutate == "missing":
        plan.pop()
    else:
        plan.append({"name": "ghost", "kind": "input", "target": None})
    with pytest.raises(BuildError) as info:
        check_plan_source(plan, expected)
    assert "不一致" in str(info.value), str(info.value)


def test_check_plan_source_accepts_identical_plan_with_extra_keys():
    expected = [{"name": "x", "kind": "input", "target": None}]
    check_plan_source([{"name": "x", "kind": "input", "target": None, "note": "hi"}], expected)


def test_param_target_missing_from_the_module_is_still_refused():
    """plan 与导出器一致，但调用方给了另一个模块：权重找不到仍要拒绝。"""
    module, exported = _exported(Shadowed(), (torch.zeros(2, 4),))

    class NoParam(nn.Module):
        def forward(self, x):
            return x

    with pytest.raises(BuildError) as info:
        placeholder_args(NoParam(), exported, input_plan(exported), (torch.zeros(2, 4),))
    assert "是权重" in str(info.value) and "找不到" in str(info.value), str(info.value)


# ---------------------------------------------------------------- I-1 kind 映射

def test_kind_map_values_are_pinned():
    """只查键不查值的话，CUSTOM_OBJ/TOKEN 映射错了测试照样全绿（评审 M-2）。

    第十六轮 I-2：CUSTOM_OBJ 从 KIND_MAP 移到 REFUSED_KINDS——没有真实导出背书的
    分支不该写成「已支持」。
    """
    assert KIND_MAP == {
        "PARAMETER": "param",
        "BUFFER": "param",
        "CONSTANT_TENSOR": "const",
        "USER_INPUT": "input",
    }, KIND_MAP
    assert "TOKEN" not in KIND_MAP and "CUSTOM_OBJ" not in KIND_MAP
    assert set(REFUSED_KINDS) == {"TOKEN", "CUSTOM_OBJ"}
    assert set(KIND_MAP) | set(REFUSED_KINDS) == {k.name for k in InputKind}


def _fake_exported(kind_name, target="t", name="n"):
    spec = SimpleNamespace(kind=SimpleNamespace(name=kind_name), target=target,
                           arg=SimpleNamespace(name=name))
    return SimpleNamespace(graph_signature=SimpleNamespace(input_specs=[spec]))


@pytest.mark.parametrize("kind_name,expected", [
    ("PARAMETER", "param"), ("BUFFER", "param"),
    ("CONSTANT_TENSOR", "const"), ("USER_INPUT", "input"),
])
def test_input_plan_maps_each_kind(kind_name, expected):
    assert input_plan(_fake_exported(kind_name))[0]["kind"] == expected


def test_token_is_refused_not_consumed_as_a_tensor():
    with pytest.raises(BuildError) as info:
        input_plan(_fake_exported("TOKEN"))
    text = str(info.value)
    assert "TOKEN" in text and "TokenArgument" in text, text
    assert "拒绝出图" in text, text


class _ConstAttr(nn.Module):
    """普通张量属性：导出器抬成 CONSTANT_TENSOR，值在 exported.constants 里。"""

    def __init__(self):
        super().__init__()
        self.w = torch.ones(2, 4)

    def forward(self, x):
        return x + self.w


def test_custom_obj_is_refused_because_it_has_no_real_export_backing():
    """第十六轮 I-2：CUSTOM_OBJ 在 M1a 明确拒绝，不再映射成 const。

    第十一轮把它映射成 const 时**没有真实导出用例**：torch 2.15 会把
    self.obj.add(x) 常量折叠成 x+3，造不出 CUSTOM_OBJ 的 spec。拿真导出产物就地把
    CONSTANT_TENSOR 改成 CUSTOM_OBJ，现在应当 exit 2 而不是「支持」。
    """
    module, exported = _exported(_ConstAttr(), (torch.zeros(2, 4),))
    for spec in exported.graph_signature.input_specs:
        if spec.kind == InputKind.CONSTANT_TENSOR:
            spec.kind = InputKind.CUSTOM_OBJ
    with pytest.raises(BuildError) as info:
        input_plan(exported)
    text = str(info.value)
    assert "CUSTOM_OBJ" in text and "ScriptObject" in text, text
    assert "M1b" in text and "拒绝出图" in text, text


def test_the_same_export_without_the_mutation_still_resolves_the_constant():
    """反向对照：上一条不是「什么都拒绝」——同一个真产物不改 kind 就取得到值。"""
    module, exported = _exported(_ConstAttr(), (torch.zeros(2, 4),))
    plan = input_plan(exported)
    table = classify(plan)
    assert table["consts"] == {"c_w"} and table["inputs"] == ["x"], table
    data = torch.zeros(2, 4)
    args = placeholder_args(module, exported, plan, (data,))
    assert args[0] is exported.constants["w"], args
    assert args[1] is data, args


# ---------------------------------------------------------------- I-2 输出边界

class ConstOut(nn.Module):
    def forward(self, x):
        return torch.ones(2, 4)


class ZeroArgOut(nn.Module):
    def forward(self, x):
        return torch.arange(4)


class TupleOut(nn.Module):
    def forward(self, x):
        return torch.ones(2, 4), torch.zeros(2, 4)


@pytest.mark.parametrize("model,op", [(ConstOut, "ones"), (ZeroArgOut, "arange")],
                         ids=["const-output", "zero-arg-output"])
def test_node_returned_directly_is_not_an_orphan(model, op):
    traced = trace_module(model(), (torch.zeros(2, 4),))
    counts = traced["runtime"]["counts"]
    assert counts["orphan"] == 0, counts
    assert traced["edges"] == [], "直接输出的常量确实没有边——所以不能只看边"
    assert any(n["op"] == op for n in traced["nodes"] if n.get("kind") == "op")


def test_tuple_output_references_are_all_counted_as_used():
    module, exported = _exported(TupleOut(), (torch.zeros(2, 4),))
    from papertrace.parse_code.fx_nodes import build_op_nodes

    plan = classify(input_plan(exported))
    ops, by_name, _ = build_op_nodes(
        exported.graph, "root", {"root": "root"}, "root", plan=plan
    )
    used = output_node_ids(exported.graph, by_name)
    assert len(used) == 2, used
    assert finish_nodes(ops, [], outputs=used)["orphan"] == 0
    assert finish_nodes(ops, [])["orphan"] == 2, "不传 outputs 就会误报——这条证明参数有用"


def test_outputs_argument_is_what_changes_the_answer():
    node = {"id": "k", "level": "op", "kind": "op", "op": "ones",
            "outputs": [[2, 4]], "degraded": False}
    assert finish_nodes([node], [])["orphan"] == 1
    assert finish_nodes([node], [], outputs={"k"})["orphan"] == 0


# ---------------------------------------------------------------- M-1 数量错误

def test_cli_exits_5_when_example_inputs_are_too_few():
    """两个数据输入只给一项：torch.export 先拦住，退出码 5，不写 trace。"""
    from papertrace import cli

    repo = _write_repo("eleventh-toofew", """import torch
import torch.nn as nn


class M(nn.Module):
    def forward(self, a, b):
        return a + b

    def example_inputs(self):
        return torch.zeros(2, 4)


def build_model():
    return M().eval()
""")
    out_dir = scratch_dir("eleventh-toofew-out")
    code = cli.main(["build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir)])
    assert code == 5, code
    assert not (out_dir / "trace.json").exists()


# ------------------------------------------------- I-2 CLI 级：直接输出不算孤点

CONST_OUT_REPO = """import torch
import torch.nn as nn


class M(nn.Module):
    def forward(self, x):
        return torch.ones(2, 4)

    def example_inputs(self):
        return torch.zeros(2, 4)


def build_model():
    return M().eval()
"""

ZERO_ARG_REPO = """import torch
import torch.nn as nn


class M(nn.Module):
    def forward(self):
        return torch.arange(4)

    def example_inputs(self):
        return ()


def build_model():
    return M().eval()
"""


@pytest.mark.parametrize("name,source,op", [
    ("eleventh-cli-constout", CONST_OUT_REPO, "ones"),
    ("eleventh-cli-zeroarg", ZERO_ARG_REPO, "arange"),
], ids=["const-output", "zero-arg-output"])
def test_cli_direct_output_is_not_an_orphan(name, source, op):
    """整条 CLI 走一遍：常量/零实参算子直接 return，orphan 必须是 0。"""
    import json

    from papertrace import cli

    repo = _write_repo(name, source)
    out_dir = scratch_dir(name + "-out")
    code = cli.main(["build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir)])
    assert code == 0, code
    trace = json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))
    counts = trace["meta"]["runtime"]["counts"]
    assert counts["orphan"] == 0, counts
    assert any(n["op"] == op for n in trace["nodes"] if n.get("kind") == "op"), op


def test_dead_operator_with_incoming_edges_is_not_counted():
    """已知取舍（README 写死）：有入边但没人用的死算子**不**计入 orphan。

    本切片不做死代码检测：orphan 只回答「既没人喂它、它也没喂别人、还不是输出」。
    这条用例把取舍钉住，免得以后有人以为 orphan==0 就等于没有死代码。
    """
    live = {"id": "a", "level": "op", "kind": "op", "op": "add",
            "outputs": [[2, 4]], "degraded": False}
    dead = {"id": "b", "level": "op", "kind": "op", "op": "mul",
            "outputs": [[2, 4]], "degraded": False}
    edge = {"src": "a", "dst": "b", "checked": True, "shape_consistent": True}
    counts = finish_nodes([live, dead], [edge], outputs={"a"})
    assert counts["orphan"] == 0, counts
    assert counts["operators"] == 2, counts


# --------------------------------------------- Q4 build_op_nodes 的入口断言

def _forged_table(exported):
    """把权重从 params 挪进 inputs：名字仍全覆盖，只看名字的守卫抓不到。"""
    real = classify(input_plan(exported))
    return {
        "params": set(),
        "consts": set(real["consts"]),
        "inputs": list(real["inputs"]) + sorted(real["params"]),
        "owner": {},
    }


def _kinds(ops):
    return {
        n["label"].split(".")[-1]: n["kind"]
        for n in ops if n["kind"] in ("param", "input", "const")
    }


def test_forged_table_passes_the_name_only_guard():
    """先证明不给 exported 时它真能标反——否则后面的拒绝断言可能是恒真。"""
    from papertrace.parse_code.fx_nodes import build_op_nodes

    _, exported = _exported(Shadowed(), (torch.zeros(2, 4),))
    ops, _, _ = build_op_nodes(
        exported.graph, "root", {"root": "root"}, "root", plan=_forged_table(exported)
    )
    assert _kinds(ops) == {"p_x": "input", "x": "input"}, _kinds(ops)


def test_build_op_nodes_refuses_a_forged_table_when_given_exported():
    from papertrace.parse_code.fx_nodes import build_op_nodes

    _, exported = _exported(Shadowed(), (torch.zeros(2, 4),))
    with pytest.raises(BuildError) as info:
        build_op_nodes(
            exported.graph, "root", {"root": "root"}, "root",
            plan=_forged_table(exported), exported=exported,
        )
    text = str(info.value)
    assert "与 torch.export 自己的 input_specs 不一致" in text, text
    assert "p_x" in text, text


def test_build_op_nodes_accepts_the_exporters_own_table():
    from papertrace.parse_code.fx_nodes import build_op_nodes

    _, exported = _exported(Shadowed(), (torch.zeros(2, 4),))
    ops, _, _ = build_op_nodes(
        exported.graph, "root", {"root": "root"}, "root",
        plan=classify(input_plan(exported)), exported=exported,
    )
    assert _kinds(ops) == {"p_x": "param", "x": "input"}, _kinds(ops)


@pytest.mark.parametrize("field", ["params", "consts", "inputs", "owner"],
                         ids=["params", "consts", "inputs", "owner"])
def test_check_plan_table_catches_each_table_drift(field):
    from papertrace.parse_code.fx_contract import check_plan_table

    expected = {"params": {"p_w"}, "consts": set(), "inputs": ["x"],
                "owner": {"p_w": "sub"}}
    check_plan_table({k: (set(v) if isinstance(v, set) else v) for k, v in expected.items()},
                     expected)  # 同一份必须过
    bad = {k: (set(v) if isinstance(v, set) else list(v) if isinstance(v, list) else dict(v))
           for k, v in expected.items()}
    if field == "params":
        bad["params"] = set()
        bad["inputs"] = ["x", "p_w"]
    elif field == "consts":
        bad["consts"] = {"p_w"}
        bad["params"] = set()
    elif field == "inputs":
        bad["inputs"] = ["x", "x"]
    else:
        bad["owner"] = {"p_w": ""}
    with pytest.raises(BuildError) as info:
        check_plan_table(bad, expected)
    assert field in str(info.value), str(info.value)

# 这两道关在**真实 CLI 路径**里的牙齿来自「每一级用自己的 import 绑定重算」：
# fx_trace 用 fx_trace.classify / fx_trace.input_plan，而关里的 expected 走
# fx_nodes.classify / fx_signature.input_plan，所以某一级漂移时另一级抓得住。
# 诚实的边界（output/probes/probe12d.py 实测）：
# ① 什么都不动时 plan 与 expected 是同一个纯函数算两遍，这两道关不会触发——它们防的是
#    **管线漂移**与**直接 API 传伪造 plan**，不是独立的第三方神谕；
# ② 把三处 input_plan 引用全换掉就能绕过（monkeypatch 权威本身不在威胁模型内）；
# ③ KIND_MAP 自己映射错了这两道关也抓不到（两边一起错），那靠钉死每个值的测试与 zoo 把。
class _Drift(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.w


def test_classify_drift_in_the_pipeline_is_caught_at_the_entry(monkeypatch):
    """fx_trace.classify 把权重塞进 inputs（权威 input_plan 不动）→ 入口拒绝。"""
    module = _Drift().eval()
    _ensure_export_cache()
    real = fx_trace.classify

    def drifted(plan):
        table = real(plan)
        table["inputs"] = sorted(table["params"]) + table["inputs"]
        return table

    monkeypatch.setattr(fx_trace, "classify", drifted)
    with pytest.raises(BuildError) as info:
        trace_module(module, (torch.zeros(2, 4),))
    text = str(info.value)
    assert "与 torch.export 自己的 input_specs 不一致" in text, text
    assert "inputs" in text and "p_w" in text, text


def test_classify_dropping_a_weight_is_caught_at_the_entry(monkeypatch):
    """fx_trace.classify 丢掉权重表 → 入口拒绝，而不是安静少一个权重节点。"""
    module = _Drift().eval()
    _ensure_export_cache()
    real = fx_trace.classify

    def drifted(plan):
        table = real(plan)
        table["params"] = set()
        return table

    monkeypatch.setattr(fx_trace, "classify", drifted)
    with pytest.raises(BuildError) as info:
        trace_module(module, (torch.zeros(2, 4),))
    assert "params" in str(info.value), str(info.value)


def test_unmodified_pipeline_still_labels_kinds_correctly():
    """反向对照：不动任何东西时 kind 是对的（上面两条不是恒真拒绝）。"""
    traced = trace_module(_Drift().eval(), (torch.zeros(2, 4),))
    kinds = [n["kind"] for n in traced["nodes"] if n.get("level") == "op"]
    assert sorted(kinds) == ["input", "op", "param"], kinds
