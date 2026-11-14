"""第七轮评审的回归测试：兜底 fail-closed、`*_like` 常量派生、input_specs 契约校验。

C1  没有 `input_specs` 时不再按 mangled 名猜：有 placeholder 就拒绝出图；
    真的没有 placeholder（常量模型）仍能出图。
I1  `ones_like/zeros_like` 产出常量：它自己不算数据入参，下游 shape_in 也不能取它的形状。
I2  `placeholder_args` 必须核对 spec 完整性、example_inputs 数量与 forward 形参顺序。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import torch  # noqa: E402

from papertrace.build_trace import build_trace  # noqa: E402
from papertrace.exceptions import BuildError, TraceUnsupported  # noqa: E402
from papertrace.parse_code.fx_nodes import build_op_nodes  # noqa: E402
from papertrace.parse_code import fx_trace  # noqa: E402
from papertrace.parse_code.fx_signature import (  # noqa: E402
    classify,
    input_plan,
    placeholder_args,
)
from papertrace.parse_code.fx_trace import _ensure_export_cache  # noqa: E402
from papertrace.schema_validate import validate_trace  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY = "model:build_model"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "papertrace", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(REPO_ROOT),
    )


def _write_repo(name: str, source: str) -> Path:
    repo = scratch_dir(name)
    (repo / "model.py").write_text(source, encoding="utf-8")
    return repo


def _by_kind(doc: dict, kind: str) -> list[dict]:
    return [n for n in doc["nodes"] if n["level"] == "op" and n.get("kind") == kind]


def _op(doc: dict, op: str) -> dict:
    for node in doc["nodes"]:
        if node["level"] == "op" and node["op"] == op:
            return node
    raise AssertionError("图里没有 " + op + "：" + "、".join(
        n["op"] for n in doc["nodes"] if n["level"] == "op"
    ))


# ---------------------------------------------------------------- C1

def test_no_input_specs_but_placeholders_is_refused():
    """C1：图里有 placeholder 却没有 spec → BuildError，绝不猜。"""

    class M(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.w = torch.nn.Parameter(torch.ones(4))

        def forward(self, x):
            return x + self.w

    _ensure_export_cache()
    exported = torch.export.export(M().eval(), (torch.ones(4),))
    with pytest.raises(BuildError) as info:
        build_op_nodes(exported.graph, "root", {"root": "root"}, "root", plan={})
    assert "input_specs" in str(info.value), str(info.value)
    assert "拒绝出图" in str(info.value), str(info.value)


def test_constant_only_model_still_builds_with_empty_plan():
    """C1 的反向边界：图里没有 placeholder（纯常量模型）时，空 plan 是合法的。"""

    class ConstOnly(torch.nn.Module):
        def forward(self):
            return torch.ones(2, 4) + 1

    _ensure_export_cache()
    exported = torch.export.export(ConstOnly().eval(), ())
    assert not [n for n in exported.graph.nodes if n.op == "placeholder"]
    nodes, by_name, _ = build_op_nodes(exported.graph, "root", {"root": "root"}, "root", plan={})
    assert nodes, "常量模型也该有算子节点"
    assert all(n["kind"] == "op" for n in nodes), [n["kind"] for n in nodes]


def test_classify_empty_cannot_bypass_the_guard():
    """I-2：真实调用传的是 classify(plan)，空 spec 时它是非空 dict——守卫必须看覆盖，不能看真假。"""

    class M(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.w = torch.nn.Parameter(torch.ones(4))

        def forward(self, x):
            return x + self.w

    _ensure_export_cache()
    exported = torch.export.export(M().eval(), (torch.ones(4),))
    with pytest.raises(BuildError) as info:
        build_op_nodes(
            exported.graph, "root", {"root": "root"}, "root", plan=classify([])
        )
    assert "没有 input_specs 覆盖" in str(info.value), str(info.value)


def test_partial_plan_is_refused_instead_of_labeling_rest_as_input():
    """I-2：只覆盖了一部分 placeholder 的 plan 也要拒绝，不能把剩下的参数当输入。"""

    class M(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.w = torch.nn.Parameter(torch.ones(4))

        def forward(self, x):
            return x + self.w

    _ensure_export_cache()
    exported = torch.export.export(M().eval(), (torch.ones(4),))
    full = classify(input_plan(exported))
    partial = dict(full)
    partial["params"] = set()
    with pytest.raises(BuildError) as info:
        build_op_nodes(exported.graph, "root", {"root": "root"}, "root", plan=partial)
    assert "没有 input_specs 覆盖" in str(info.value), str(info.value)


# ---------------------------------------------------------------- I2

class _TwoInputs(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.w = torch.nn.Parameter(torch.ones(4))

    def forward(self, a, b):
        return a + b + self.w


class _OneInput(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.w = torch.nn.Parameter(torch.ones(4))

    def forward(self, a):
        return a + self.w


def test_placeholder_args_refuses_a_plan_missing_a_placeholder():
    """I2：spec 缺项时不能把缺的那项当普通输入 pop 掉，必须拒绝（契约错误 → exit 2）。"""
    _ensure_export_cache()
    module = _TwoInputs().eval()
    example_inputs = (torch.ones(4), torch.ones(4))
    exported = torch.export.export(module, example_inputs)
    plan = input_plan(exported)
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, plan[:-1], example_inputs)
    assert "缺少 placeholder" in str(info.value), str(info.value)


def test_placeholder_args_refuses_a_plan_with_unknown_placeholder():
    """I2：spec 里有图里不存在的名字，说明 spec 不是这张图的，拒绝。"""
    _ensure_export_cache()
    module = _OneInput().eval()
    example_inputs = (torch.ones(4),)
    exported = torch.export.export(module, example_inputs)
    plan = input_plan(exported) + [{"name": "ghost", "kind": "input", "target": None}]
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, plan, example_inputs)
    assert "不存在的 placeholder" in str(info.value), str(info.value)


def test_placeholder_args_refuses_wrong_example_input_count():
    """I2：example_inputs 少一项就明说「按 forward 形参顺序给」，不静默对齐。"""
    _ensure_export_cache()
    module = _TwoInputs().eval()
    exported = torch.export.export(module, (torch.ones(4), torch.ones(4)))
    with pytest.raises(TraceUnsupported) as info:
        placeholder_args(module, exported, input_plan(exported), (torch.ones(4),))
    assert "按 forward 形参顺序" in str(info.value), str(info.value)


def test_placeholder_args_refuses_a_reordered_plan():
    """M-3：spec 顺序与 placeholder 顺序不一致时必须拒绝，不能按位置静默喂错。"""
    _ensure_export_cache()
    module = _TwoInputs().eval()
    example_inputs = (torch.ones(4), torch.ones(4))
    exported = torch.export.export(module, example_inputs)
    plan = input_plan(exported)
    reordered = [plan[1], plan[0]] + plan[2:]
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, reordered, example_inputs)
    assert "顺序" in str(info.value), str(info.value)


def test_placeholder_args_lists_missing_and_extra_together():
    """M-3：同时缺项和多项时一次说全，别让用户改一遍再撞一次。"""
    _ensure_export_cache()
    module = _OneInput().eval()
    example_inputs = (torch.ones(4),)
    exported = torch.export.export(module, example_inputs)
    plan = input_plan(exported)
    broken = plan[:-1] + [{"name": "ghost", "kind": "input", "target": None}]
    with pytest.raises(BuildError) as info:
        placeholder_args(module, exported, broken, example_inputs)
    text = str(info.value)
    assert "缺少 placeholder" in text and "多出图里不存在" in text, text


def test_cli_exits_2_and_writes_nothing_when_specs_are_missing(monkeypatch, capsys):
    """I-1：spec 对不上是契约错误，CLI 与 build_op_nodes 同为 exit 2；且绝不写 trace。"""
    from papertrace import cli

    repo = _write_repo("sig-nospec-cli", """import torch
import torch.nn as nn


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.x = nn.Parameter(torch.ones(2, 4))

    def forward(self, p_x):
        return p_x + 1

    def example_inputs(self):
        return torch.ones(1, 4)


def build_model():
    return M().eval()
""")
    out_dir = scratch_dir("sig-nospec-cli-out")
    monkeypatch.setattr(fx_trace, "input_plan", lambda exported: [])
    code = cli.main(["build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir)])
    assert code == 2, code
    assert "缺少 placeholder" in capsys.readouterr().err
    assert not (out_dir / "trace.json").exists(), "拒绝出图时不能留下 trace"


def test_placeholder_args_returns_real_tensors_in_forward_order():
    """I2：正常路径下，参数拿的是模块真实的 Parameter，数据输入按 forward 顺序。"""
    _ensure_export_cache()
    module = _TwoInputs().eval()
    a, b = torch.arange(4.0), torch.arange(4.0) + 10
    exported = torch.export.export(module, (a, b))
    args = placeholder_args(module, exported, input_plan(exported), (a, b))
    spec = input_plan(exported)
    values = {item["name"]: value for item, value in zip(spec, args)}
    param_name = next(item["name"] for item in spec if item["kind"] == "param")
    assert values[param_name] is module.w, values[param_name]
    user_values = [values[item["name"]] for item in spec if item["kind"] == "input"]
    assert torch.equal(user_values[0], a) and torch.equal(user_values[1], b), user_values


# ---------------------------------------------------------------- I1

_LIKE = """import torch
import torch.nn as nn


class Like(nn.Module):
    def forward(self, x, y):
        return torch.cat([%s, y], dim=-1)

    def example_inputs(self):
        return (torch.ones(2, 4), torch.ones(2, 6))


def build_model():
    return Like().eval()
"""

_LIKE_CASES = [
    ("ones_like", "torch.ones_like(x)"),
    ("zeros_like", "torch.zeros_like(x)"),
    ("full_like", "torch.full_like(x, 1.0)"),
]


@pytest.mark.parametrize("op,expr", _LIKE_CASES, ids=[c[0] for c in _LIKE_CASES])
def test_like_constant_is_not_a_data_input(op, expr):
    """I1：cat([ones_like(x), y]) 的 shape_in 必须是 y 的 (2, 6)，不是 x 的 (2, 4)。"""
    repo = _write_repo("sig-like-" + op, _LIKE % expr)
    doc = build_trace(repo, entry=ENTRY)
    cat = _op(doc, "cat")
    assert cat["inputs"] == [[2, 6]], cat["inputs"]
    assert cat["shape_in"] == [2, 6], cat
    like = _op(doc, op)
    assert like["inputs"] == [], like["inputs"]
    assert like["shape_in"] == [], like
    # inputs 记空，但形状依赖不能丢：x -> like 这条边必须还在（M-4）
    assert any(e["dst"] == like["id"] for e in doc["edges"]), [e["label"] for e in doc["edges"]]
    # like 自己产出常量，但它是算子而不是 const 节点；数据输入仍然是 x 和 y
    assert len(_by_kind(doc, "input")) == 2, _by_kind(doc, "input")
    validate_trace(doc)


@pytest.mark.parametrize("expr", ["torch.rand_like(x)", "torch.randn_like(x)"])
def test_random_like_is_still_a_data_input(expr):
    """I1 反向对照：rand_like 产出随机数，不能当常量忽略，否则 shape_in 又会取错。"""
    repo = _write_repo("sig-rand-like-" + expr.split(".")[1].split("(")[0], _LIKE % expr)
    doc = build_trace(repo, entry=ENTRY)
    cat = _op(doc, "cat")
    assert cat["inputs"] == [[2, 4], [2, 6]], cat["inputs"]
    assert cat["shape_in"] == [2, 4], cat
    assert len(_by_kind(doc, "input")) == 2, _by_kind(doc, "input")


def test_like_constant_cli_summary_counts_two_inputs():
    """I1：x、y 都是真输入；ones_like 不能把它们顶掉，也不能算成第三个输入。"""
    repo = _write_repo("sig-like-cli", _LIKE % "torch.ones_like(x)")
    out_dir = scratch_dir("sig-like-cli-out")
    built = _run_cli("build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir))
    assert built.returncode == 0, built.stderr
    summary = [line for line in built.stdout.splitlines() if "已写出" in line][0]
    assert "输入 2" in summary, summary
    assert "权重 0" in summary, summary
    dumped = _run_cli("dump", "--trace", str(out_dir / "trace.json"))
    assert dumped.returncode == 0, dumped.stderr

def test_literal_constant_source_is_not_an_orphan():
    """M-2：torch.ones(2,4) 没有数据入边是本职，不该被算成 orphan（孤点）。"""
    source = """import torch
import torch.nn as nn


class Lit(nn.Module):
    def forward(self, x):
        return torch.cat([torch.ones(2, 4), x])

    def example_inputs(self):
        return torch.ones(1, 4)


def build_model():
    return Lit().eval()
"""
    repo = _write_repo("sig-orphan-lit", source)
    doc = build_trace(repo, entry=ENTRY)
    assert doc["meta"]["runtime"]["counts"]["orphan"] == 0, doc["meta"]["runtime"]["counts"]