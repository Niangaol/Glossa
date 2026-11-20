"""第六轮评审的回归测试：input_specs 接管参数/常量/输入的判定。

C1  mangled 名（p_sub_x）仍会撞车：`sub.x` 与根上的 `sub_x` 压成同一个名字
C1  `self.x` + `forward(p_x)`：export 图里 p_x_1 是 PARAMETER、p_x 是 USER_INPUT，
    按名字猜会正好反过来，把唯一的数据输入丢掉
I2  常量（`torch.ones(...)`、`self.const = torch.ones(...)`）被当成数据输入
I3  只有参数、没有算子的子模块不会出现在任何节点的 nn_module_stack 里，parent 掉回 root
C1  没有 input_specs 的老 torch 走 mangled 兜底时，撞名必须 BuildError 而不是静默错位
Minor  `dump --ops` 不显示 kind，param/input 互换时终端看不出来
Minor  字段类型用例缺 edge.dst 与「nodes 里混进非对象」
"""
from tests.common import ROOT

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import torch  # noqa: E402

from papertrace.build.trace import build_trace  # noqa: E402
from papertrace.exceptions import BuildError  # noqa: E402
from papertrace.parse_code.fx_nodes import build_op_nodes  # noqa: E402
from papertrace.parse_code.fx_trace import _ensure_export_cache  # noqa: E402
from papertrace.schema.validate import minimal_trace, validate_trace  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402

REPO_ROOT = ROOT
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


def _summary(text: str) -> str:
    lines = [line for line in text.splitlines() if "已写出" in line]
    assert lines, text
    return lines[0]


def _by_kind(doc: dict, kind: str) -> list[dict]:
    return [n for n in doc["nodes"] if n["level"] == "op" and n.get("kind") == kind]


def _module_ids(doc: dict) -> dict[str, dict]:
    return {n["id"]: n for n in doc["nodes"] if n["level"] == "module"}


def _op(doc: dict, op: str) -> dict:
    for node in doc["nodes"]:
        if node["level"] == "op" and node["op"] == op:
            return node
    raise AssertionError("图里没有 " + op + "：" + "、".join(
        n["op"] for n in doc["nodes"] if n["level"] == "op"
    ))


# ---------------------------------------------------------------- C1

_COLLISION = """import torch
import torch.nn as nn


class Sub(nn.Module):
    def __init__(self):
        super().__init__()
        self.x = nn.Parameter(torch.ones(2, 4))


class M(nn.Module):
    def __init__(self):
        super().__init__()
        self.sub = Sub()
        self.sub_x = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + self.sub.x + self.sub_x

    def example_inputs(self):
        return torch.ones(1, 4)


def build_model():
    return M().eval()
"""


def test_submodule_param_and_root_param_stay_two_weights():
    """C1：sub.x 与 sub_x 会压成同一个 p_sub_x，但计数必须是权重 2、输入 1。"""
    repo = _write_repo("sig-collision", _COLLISION)
    doc = build_trace(repo, entry=ENTRY)
    params, inputs = _by_kind(doc, "param"), _by_kind(doc, "input")
    assert len(params) == 2, [(n["id"], n.get("label")) for n in params]
    assert len(inputs) == 1, inputs
    assert inputs[0]["shape_out"] == [1, 4], inputs[0]
    # 两个权重都必须真的拿到值（不是 None 占位），shape 也不能被数据输入串掉
    assert [n["shape_out"] for n in params] == [[2, 4], [2, 4]], params
    add = _op(doc, "add")
    assert add["shape_in"] == [1, 4], add


def test_submodule_param_hangs_under_its_submodule():
    """I3：只有参数没有算子的 Sub 也要建模块节点，权重挂在 root/sub 下而不是 root。"""
    repo = _write_repo("sig-collision-parent", _COLLISION)
    doc = build_trace(repo, entry=ENTRY)
    modules = _module_ids(doc)
    assert "root/sub" in modules, sorted(modules)
    params = _by_kind(doc, "param")
    parents = sorted(n["parent_id"] for n in params)
    assert parents == ["root", "root/sub"], parents


def test_missing_input_specs_refuses_to_guess():
    """C1：没有 input_specs 时直接拒绝出图，不再按 mangled 名猜（猜错是整类标反）。"""

    class Sub(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.x = torch.nn.Parameter(torch.ones(2, 4))

    class M(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.sub = Sub()
            self.sub_x = torch.nn.Parameter(torch.ones(2, 4))

        def forward(self, x):
            return x + self.sub.x + self.sub_x

    _ensure_export_cache()  # 本机 TORCHINDUCTOR_CACHE_DIR 指向不可写目录，export 会 PermissionError
    exported = torch.export.export(M().eval(), (torch.ones(1, 4),))
    with pytest.raises(BuildError) as info:
        build_op_nodes(exported.graph, "root", {"root": "root"}, "root", plan={})
    assert "input_specs" in str(info.value), str(info.value)


def test_cli_summary_counts_two_weights_and_one_input():
    """C1：摘要的计数是给人看的最后一道关，撞名时不能显示「权重 1 / 输入 2」。"""
    repo = _write_repo("sig-collision-cli", _COLLISION)
    out_dir = scratch_dir("sig-collision-cli-out")
    r = _run_cli("build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir))
    assert r.returncode == 0, r.stderr
    summary = _summary(r.stdout)
    assert "权重 2" in summary, summary
    assert "输入 1" in summary, summary


_NAME_SHADOW = """import torch
import torch.nn as nn


class Shadow(nn.Module):
    def __init__(self):
        super().__init__()
        self.x = nn.Parameter(torch.ones(2, 4))

    def forward(self, p_x):
        # 这个函数体故意不用 self.x：export 图里 p_x_1 是 PARAMETER、p_x 是 USER_INPUT，
        # 顺序和名字正好相反，按名字猜就会把唯一的数据输入丢掉。
        return p_x + 1

    def example_inputs(self):
        return torch.ones(1, 4)


def build_model():
    return Shadow().eval()
"""


def test_local_variable_named_like_a_param_is_still_the_input():
    """C1：forward(p_x) 的 p_x 是 USER_INPUT，不能因为存在 p_x_1 参数就被判成权重。"""
    repo = _write_repo("sig-shadow", _NAME_SHADOW)
    doc = build_trace(repo, entry=ENTRY)
    inputs, params = _by_kind(doc, "input"), _by_kind(doc, "param")
    assert len(inputs) == 1 and len(params) == 1, (inputs, params)
    assert inputs[0]["shape_out"] == [1, 4], inputs[0]
    assert params[0]["shape_out"] == [2, 4], params[0]
    add = _op(doc, "add")
    assert add["inputs"] == [[1, 4]], add["inputs"]


# ---------------------------------------------------------------- I2

_CONST_LITERAL = """import torch
import torch.nn as nn


class Lit(nn.Module):
    def forward(self, x):
        return torch.cat([torch.ones(2, 4), x])

    def example_inputs(self):
        return torch.ones(1, 4)


def build_model():
    return Lit().eval()
"""

_CONST_ATTR = """import torch
import torch.nn as nn


class Attr(nn.Module):
    def __init__(self):
        super().__init__()
        self.const = torch.ones(2, 4)

    def forward(self, x):
        return torch.cat([self.const, x])

    def example_inputs(self):
        return torch.ones(1, 4)


def build_model():
    return Attr().eval()
"""


@pytest.mark.parametrize("name,source", [("sig-const-lit", _CONST_LITERAL), ("sig-const-attr", _CONST_ATTR)])
def test_constants_are_not_data_inputs(name, source):
    """I2：常量（字面量或 self.const）不占 inputs，cat 的 shape_in 是数据形状。"""
    repo = _write_repo(name, source)
    doc = build_trace(repo, entry=ENTRY)
    assert len(_by_kind(doc, "param")) == 0, _by_kind(doc, "param")
    assert len(_by_kind(doc, "input")) == 1, _by_kind(doc, "input")
    cat = _op(doc, "cat")
    assert cat["inputs"] == [[1, 4]], cat["inputs"]
    assert cat["shape_in"] == [1, 4], cat
    validate_trace(doc)


def test_constant_attribute_is_marked_const_not_param():
    """I2：self.const 是 CONSTANT_TENSOR，必须 kind=const；标成 param 会让人以为它可训练。"""
    repo = _write_repo("sig-const-kind", _CONST_ATTR)
    doc = build_trace(repo, entry=ENTRY)
    consts = _by_kind(doc, "const")
    assert len(consts) == 1, [(n["id"], n["kind"]) for n in doc["nodes"] if n["level"] == "op"]
    assert consts[0]["shape_out"] == [2, 4], consts[0]
    assert _by_kind(doc, "param") == [], _by_kind(doc, "param")
    # const 必须在 schema 允许的 kind 里，否则 dump 会拒收 build 自己写出的 trace
    validate_trace(doc)


def test_constant_attribute_cli_summary_counts_one_input():
    """I2：self.const 曾经让摘要显示「输入 2 / 权重 0」。"""
    repo = _write_repo("sig-const-attr-cli", _CONST_ATTR)
    out_dir = scratch_dir("sig-const-attr-cli-out")
    r = _run_cli("build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir))
    assert r.returncode == 0, r.stderr
    summary = _summary(r.stdout)
    assert "输入 1" in summary, summary
    assert "常量 1" in summary, summary
    assert "权重 0" in summary, summary
    # build 的产物必须能被自己的 dump 校验：schema 的 kind enum 漏掉 const 会在这里炸
    dumped = _run_cli("dump", "--trace", str(out_dir / "trace.json"))
    assert dumped.returncode == 0, dumped.stderr


# ---------------------------------------------------------------- Minor

def test_ops_view_prints_kind_so_a_swap_is_visible():
    """Minor：param/input 互换时终端要能看出来，--ops 每行带 kind。"""
    repo = _write_repo("sig-ops-kind", _COLLISION)
    out_dir = scratch_dir("sig-ops-kind-out")
    built = _run_cli("build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir))
    assert built.returncode == 0, built.stderr
    r = _run_cli("dump", "--trace", str(out_dir / "trace.json"), "--ops")
    assert r.returncode == 0, r.stderr
    assert "kind=param" in r.stdout, r.stdout
    assert "kind=input" in r.stdout, r.stdout


def _bad_payloads() -> list[tuple[str, str]]:
    def base() -> dict:
        doc = minimal_trace()
        doc["nodes"] = [
            {
                "id": "root", "parent_id": None, "level": "module", "op": "M",
                "label": "root", "loc": "m.py:1", "shape_in": [], "shape_out": [],
                "dtype": None, "inplace": False, "source": "static",
                "degraded": False, "repeat": 1, "stale": False,
            },
            {
                "id": "root/@000", "parent_id": "root", "level": "op", "op": "add",
                "label": "root.add", "loc": "m.py:1", "kind": "op",
                "shape_in": [2, 4], "inputs": [[2, 4]], "shape_out": [2, 4],
                "outputs": [[2, 4]], "dtype": "float32", "inplace": False,
                "source": "runtime", "degraded": False, "degraded_reason": None,
                "repeat": 1, "stale": False,
            },
        ]
        doc["edges"] = [
            {
                "id": "e:root/@000->root/@000:x", "src": "root/@000", "dst": "root/@000",
                "label": "args[0]", "shape": [2, 4], "producer_shape": [2, 4],
                "checked": True, "dtype": "float32", "inplace": False,
                "shape_consistent": True,
            },
        ]
        return doc

    cases = []
    doc = base()
    doc["edges"][0]["dst"] = 7
    cases.append(("edge-dst-int", json.dumps(doc)))
    doc = base()
    doc["nodes"].append("oops")
    cases.append(("node-not-object", json.dumps(doc)))
    return cases


@pytest.mark.parametrize("name,payload", _bad_payloads(), ids=[c[0] for c in _bad_payloads()])
def test_dump_refuses_more_wrong_shapes_of_field(name, payload):
    """Minor：edge.dst 是 int、「nodes 里混进字符串」也要 exit 2，不能 TypeError。"""
    path = scratch_dir("sig-bad-" + name) / "trace.json"
    path.write_text(payload, encoding="utf-8")
    r = _run_cli("dump", "--trace", str(path))
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "Traceback" not in r.stderr, r.stderr
    assert "不是合法 trace" in r.stderr, r.stderr
