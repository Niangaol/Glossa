"""第三轮评审的回归测试：每一条都对应一个「测出来会失败」的真实失效模式。

C1  observe 失败仍冒充 runtime（exit 0 + 真实追踪）
I1  用户代码/畸形 trace 抛裸 traceback（exit 1）
I2  inputs/shape_in 把权重冒充成数据输入
I3  结构校验放过 module 边和自环
M2  融合表里有 torch 里根本不存在的死键
M3  测试依赖 cwd
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

import torch  # noqa: E402

from papertrace.build_trace import BuildError, build_trace  # noqa: E402
from papertrace.exceptions import TraceSchemaError, TraceUnsupported  # noqa: E402
from papertrace.parse_code.fx_graph import FUSED_OPS, fused_items  # noqa: E402
from papertrace.parse_code.fx_trace import trace_module  # noqa: E402
from papertrace.schema_validate import minimal_trace, validate_trace  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = str(REPO_ROOT / "tests" / "fixtures" / "nanogpt")
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


# ---------------------------------------------------------------- C1

def test_observe_failure_raises_untraceable(monkeypatch):
    """C1：第二遍真实执行失败时，不能照常产出「runtime」trace。"""
    import papertrace.parse_code.fx_trace as fx_trace

    monkeypatch.setattr(
        fx_trace, "observe", lambda *a, **k: ({}, "RuntimeError: fake observe failure")
    )
    with pytest.raises(TraceUnsupported) as excinfo:
        build_trace(FIXTURE, entry=ENTRY)
    message = str(excinfo.value)
    assert "无法再真实执行" in message, message
    assert "fake observe failure" in message


_BOOM_MODEL = '''import torch
import torch.nn as nn

lib = torch.library.Library("ptboom", "DEF")
lib.define("boom(Tensor x) -> Tensor")


@torch.library.impl(lib, "boom", "CPU")
def _boom_cpu(x):
    raise RuntimeError("boom on real CPU execution")


@torch.library.register_fake("ptboom::boom")
def _boom_fake(x):
    return torch.empty_like(x)


class Boom(nn.Module):
    def forward(self, x):
        return torch.ops.ptboom.boom(x)

    def example_inputs(self):
        return torch.randn(2, 4)


def build_model():
    return Boom()
'''


def test_custom_op_failing_real_execution_exits_5_and_keeps_old_trace():
    """C1：自定义算子真跑会炸 → exit 5，且 --force 也不许覆盖已有 trace。"""
    repo = _write_repo("boom-repo", _BOOM_MODEL)
    out_dir = scratch_dir("boom-out")
    trace_path = out_dir / "trace.json"
    trace_path.write_text("sentinel", encoding="utf-8")

    r = _run_cli(
        "build", "--repo", str(repo), "--entry", ENTRY,
        "--out", str(out_dir), "--force",
    )
    assert r.returncode == 5, (r.returncode, r.stdout, r.stderr)
    assert "无法再真实执行" in r.stderr, r.stderr
    assert "Traceback" not in r.stderr
    assert trace_path.read_text(encoding="utf-8") == "sentinel", "追不动时不许动旧 trace"


# ---------------------------------------------------------------- I1

def test_factory_exception_becomes_build_error():
    repo = _write_repo(
        "factory-boom",
        "def build_model():\n    raise RuntimeError('factory exploded')\n",
    )
    with pytest.raises(BuildError) as excinfo:
        build_trace(repo, entry=ENTRY)
    assert "factory exploded" in str(excinfo.value)


def test_example_inputs_exception_becomes_build_error():
    repo = _write_repo(
        "example-boom",
        "import torch\n"
        "import torch.nn as nn\n"
        "class Tiny(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.lin = nn.Linear(8, 8)\n"
        "    def forward(self, x):\n"
        "        return self.lin(x)\n"
        "    def example_inputs(self):\n"
        "        raise ValueError('example inputs exploded')\n"
        "def build_model():\n"
        "    return Tiny()\n",
    )
    with pytest.raises(BuildError) as excinfo:
        build_trace(repo, entry=ENTRY)
    assert "example inputs exploded" in str(excinfo.value)


def test_module_top_level_exception_becomes_build_error():
    repo = _write_repo("import-boom", "raise RuntimeError('module exploded')\n")
    with pytest.raises(BuildError) as excinfo:
        build_trace(repo, entry=ENTRY)
    assert "module exploded" in str(excinfo.value)


def test_factory_exception_cli_exits_2_without_traceback():
    repo = _write_repo(
        "factory-boom-cli",
        "def build_model():\n    raise RuntimeError('factory exploded')\n",
    )
    out_dir = scratch_dir("factory-boom-out")
    r = _run_cli("build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir))
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "factory exploded" in r.stderr
    assert "Traceback" not in r.stderr
    assert not (out_dir / "trace.json").exists()


def test_dump_malformed_json_exits_2():
    path = scratch_dir("bad-json") / "trace.json"
    path.write_text("not json at all", encoding="utf-8")
    r = _run_cli("dump", "--trace", str(path), "--ops")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "读不成 JSON" in r.stderr
    assert "Traceback" not in r.stderr


# ---------------------------------------------------------------- I3

def _module(node_id: str, parent: str | None) -> dict:
    return {
        "id": node_id, "parent_id": parent, "level": "module", "op": "Root",
        "label": node_id, "loc": "m.py:1", "shape_in": [], "shape_out": [],
        "dtype": None, "inplace": False, "source": "static",
        "degraded": False, "repeat": 1, "stale": False,
    }


def _op(node_id: str) -> dict:
    return {
        "id": node_id, "parent_id": "root", "level": "op", "op": "matmul",
        "label": node_id, "loc": "m.py:1", "shape_in": [2, 2], "shape_out": [2, 2],
        "dtype": None, "inplace": False, "source": "runtime",
        "degraded": False, "repeat": 1, "stale": False,
        "kind": "op", "inputs": [[2, 2]], "outputs": [[2, 2]], "degraded_reason": None,
    }


def _edge(src: str, dst: str) -> dict:
    return {
        "id": f"e:{src}->{dst}:args[0]", "src": src, "dst": dst, "label": "args[0]",
        "shape": [2, 2], "producer_shape": [2, 2], "checked": True,
        "dtype": None, "inplace": False, "shape_consistent": True,
    }


def _edge_doc(src: str, dst: str, nodes: list[dict]) -> dict:
    doc = minimal_trace()
    doc["nodes"] = nodes
    doc["edges"] = [_edge(src, dst)]
    return doc


@pytest.mark.parametrize(
    "src,dst,must_say",
    [
        ("root/a", "root/@000", "必须是算子节点"),   # module -> op
        ("root/@000", "root/a", "必须是算子节点"),   # op -> module
        ("root/@000", "root/@000", "自环"),          # op 自环
        ("root/a", "root/a", "自环"),                # module 自环
    ],
)
def test_edges_must_join_two_distinct_operators(src, dst, must_say):
    """I3：边是算子之间的数据流；接模块、接自己也接住 = 形状链是假的。"""
    doc = _edge_doc(src, dst, [_module("root", None), _module("root/a", "root"), _op("root/@000")])
    with pytest.raises(TraceSchemaError) as excinfo:
        validate_trace(doc)
    assert any(must_say in e for e in excinfo.value.errors), excinfo.value.errors


# ---------------------------------------------------------------- I2

class _Lin(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.lin = torch.nn.Linear(8, 16)

    def forward(self, x):
        return self.lin(x)


class _ParamOnly(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.w = torch.nn.Parameter(torch.ones(4, 4))

    def forward(self, x):
        return self.w * 3.0


def test_linear_inputs_exclude_the_weight():
    """I2：linear 的 inputs 只放数据，shape_in 不能是权重形状。"""
    doc = trace_module(_Lin(), (torch.randn(2, 4, 8),))
    lin = [n for n in doc["nodes"] if n["op"] == "linear"][0]
    assert lin["inputs"] == [[2, 4, 8]], lin["inputs"]
    assert lin["shape_in"] == [2, 4, 8]
    # Linear 有 weight [16,8] 和 bias [16]，两者都是 param，都不能进 inputs
    param_shapes = sorted(n["shape_out"] for n in doc["nodes"] if n.get("kind") == "param")
    assert param_shapes == [[16], [16, 8]]


def test_param_only_operator_has_no_data_input():
    """I2：只用权重的算子不能说「输入是权重」——宁可空着打 (?)。"""
    doc = trace_module(_ParamOnly(), (torch.randn(2, 4),))
    muls = [n for n in doc["nodes"] if n["op"] == "mul"]
    assert len(muls) == 1, [n["op"] for n in doc["nodes"]]
    node = muls[0]
    assert node["inputs"] == [], node["inputs"]
    assert node["shape_in"] == [], node["shape_in"]
    assert node["degraded"] is False, node["degraded_reason"]


# ---------------------------------------------------------------- M2

@pytest.mark.parametrize("name", sorted(FUSED_OPS))
def test_every_fused_name_exists_in_aten(name):
    """M2：融合表不能再有「torch 里根本没有」的死键。"""
    assert hasattr(torch.ops.aten, name), f"{name} 不是真实的 aten 算子"


def test_fused_prefix_fallback_still_reports_new_variants():
    """前缀兜底：torch 升级换了后缀也不能漏报。"""
    assert fused_items("_scaled_dot_product_some_new_backend") == (
        "matmul", "scale", "mask", "softmax",
    )
    assert fused_items("_flash_attention_forward_v99") == (
        "matmul", "scale", "mask", "softmax",
    )
    assert fused_items("matmul") is None


# ---------------------------------------------------------------- 汇总口径

def test_real_build_still_has_no_broken_or_unchecked_edges():
    """C1/I2 修完，黄金路径仍是 0 断链 0 未核实，且 runtime 是真实执行。"""
    doc = build_trace(FIXTURE, entry=ENTRY)
    validate_trace(doc)
    counts = doc["meta"]["runtime"]["counts"]
    assert counts["shape_broken"] == 0, [
        e for e in doc["edges"] if e["checked"] and not e["shape_consistent"]
    ]
    assert counts["shape_unchecked"] == 0
    assert doc["meta"]["runtime"]["real_execution"] == {"ok": True, "reason": None}
