"""第二轮评审的回归测试：每条都对应一个「测试曾经证明不了」的失效模式。"""

import json
import os
import subprocess
import sys

import pytest

from papertrace.parse_code.fx_edges import build_edges
from papertrace.parse_code.fx_graph import fused_items
from tests._tmp import scratch_dir

FIXTURE = "tests/fixtures/nanogpt"
ENTRY = "model:build_model"


class _FakeNode:
    def __init__(self, name, op, args=(), kwargs=None):
        self.name = name
        self.op = op
        self.args = list(args)
        self.kwargs = dict(kwargs or {})


class _FakeGraph:
    def __init__(self, nodes):
        self.nodes = nodes


def _edge_pair(consumer_shape, producer_shape):
    """伪造一次观察：消费者拿到的形状与生产者输出的形状可以不一致。"""
    producer = _FakeNode("producer", "call_function")
    consumer = _FakeNode("consumer", "call_function", args=[producer])
    graph = _FakeGraph([producer, consumer])
    observed = {
        "producer": {"args": [], "kwargs": {}, "out": {"t": list(producer_shape)}},
        "consumer": {
            "args": [{"t": list(consumer_shape)}],
            "kwargs": {},
            "out": {"t": list(consumer_shape)},
        },
    }
    edges = build_edges(
        graph,
        {"producer": "A", "consumer": "B"},
        [],
        {"A": [producer_shape], "B": [consumer_shape]},
        observed=observed,
    )
    assert len(edges) == 1
    return edges[0]


def test_edge_shape_compares_consumer_against_producer():
    """C1：两侧都独立取到形状时，不一致必须判 False——不是「有形状就 True」。"""
    broken = _edge_pair(consumer_shape=[2, 4, 8, 4], producer_shape=[2, 4, 8, 8])
    assert broken["checked"] is True
    assert broken["shape"] == [2, 4, 8, 4], "边的形状必须是消费者真正拿到的形状"
    assert broken["producer_shape"] == [2, 4, 8, 8]
    assert broken["shape_consistent"] is False

    same = _edge_pair(consumer_shape=[2, 4, 8, 8], producer_shape=[2, 4, 8, 8])
    assert same["checked"] is True
    assert same["shape_consistent"] is True


def test_edge_without_observation_is_unchecked_not_consistent():
    """看不见就写「未核实」，不能默认一致。"""
    producer = _FakeNode("producer", "call_function")
    consumer = _FakeNode("consumer", "call_function", args=[producer])
    edges = build_edges(
        _FakeGraph([producer, consumer]), {"producer": "A", "consumer": "B"}, [], {}
    )
    assert edges and edges[0]["checked"] is False
    assert edges[0]["shape_consistent"] is False


def test_inplace_then_transpose_is_not_a_broken_edge():
    """C2：add_ 之后转置是合法图，旧规则会误报 shape_broken=1。"""
    torch = pytest.importorskip("torch")
    from papertrace.parse_code.fx_trace import trace_module

    class _InplaceThenTranspose(torch.nn.Module):
        def forward(self, x):
            return x.add_(1).transpose(0, 1)

    doc = trace_module(_InplaceThenTranspose(), (torch.randn(2, 3),))
    counts = doc["runtime"]["counts"]
    assert counts["shape_broken"] == 0, [
        e for e in doc["edges"] if not e["shape_consistent"]
    ]
    assert counts["shape_unchecked"] == 0


def test_fused_table_matches_real_aten_names():
    """I4：融合名单必须认 torch 真实的 aten 名，否则永远查不到。"""
    items = ("matmul", "scale", "mask", "softmax")
    for name in (
        "scaled_dot_product_attention",
        "_scaled_dot_product_flash_attention",
        "_scaled_dot_product_flash_attention_for_cpu",
        "_scaled_dot_product_efficient_attention",
        "_scaled_dot_product_cudnn_attention",
        "_efficient_attention_forward",
        "_flash_attention_forward",
    ):
        assert fused_items(name) == items, name
    assert fused_items("matmul") is None
    assert fused_items("view") is None


def test_bare_tensor_example_inputs_is_not_split_into_dimensions():
    """I6：example_inputs() 返回裸张量时不能被 tuple() 拆成多个参数。"""
    torch = pytest.importorskip("torch")
    from papertrace.build_trace import _as_input_tuple

    tensor = torch.zeros(2, 3)
    wrapped = _as_input_tuple(tensor)
    assert len(wrapped) == 1 and wrapped[0].shape == (2, 3)
    assert _as_input_tuple((tensor,)) == (tensor,)
    assert _as_input_tuple([tensor]) == (tensor,)


def test_runtime_records_requested_separately_from_actual():
    """I3：模型自带 example_inputs 时，runtime 的 batch 必须是实际喂进去的 2，而不是请求的 5。"""
    pytest.importorskip("torch")
    from papertrace.build_trace import build_trace

    repo = scratch_dir("requested-inputs")
    (repo / "model.py").write_text(
        "import torch\n"
        "import torch.nn as nn\n"
        "class Tiny(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.lin = nn.Linear(8, 8)\n"
        "    def forward(self, x):\n"
        "        return self.lin(x)\n"
        "    def example_inputs(self):\n"
        "        return torch.zeros(2, 4, 8)\n"
        "def build_model():\n"
        "    return Tiny()\n",
        encoding="utf-8",
    )
    doc = build_trace(repo, entry="model:build_model", batch=5)
    runtime = doc["meta"]["runtime"]
    assert runtime["batch"] == 2 and runtime["seq_len"] == 4
    assert runtime["example_inputs"] == [[2, 4, 8]]
    assert runtime["requested"] == {"batch": 5, "seq_len": None}
    assert runtime["real_execution"]["ok"] is True


def _env_without_torch():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    return env


def test_missing_torch_exits_4_before_importing_repo():
    """I1：仓库顶层 import torch 时，缺 torch 必须报「缺运行时」（4），不是「仓库写错」（2）。

    夹具通过一个排在最前面的 torch 桩模拟「没装 torch」——pydeps 里的 jsonschema 还得能用。
    """
    blocker = scratch_dir("torch-blocker")
    (blocker / "torch").mkdir(parents=True, exist_ok=True)
    (blocker / "torch" / "__init__.py").write_text(
        "raise ImportError('torch is not installed (blocked for this test)')\n",
        encoding="utf-8",
    )
    env = _env_without_torch()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(blocker), *[p for p in (os.environ.get("PYTHONPATH") or "").split(os.pathsep) if p]]
    )
    out_dir = scratch_dir("no-torch")
    r = subprocess.run(
        [sys.executable, "-m", "papertrace", "build",
         "--repo", FIXTURE, "--entry", ENTRY, "--out", str(out_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env,
    )
    assert r.returncode == 4, (r.returncode, r.stdout, r.stderr)
    assert "torch" in r.stderr
    assert not (out_dir / "trace.json").exists()


def _run_cli(*args, env=None):
    base = _env_without_torch()
    base["PYTHONPATH"] = os.pathsep.join(
        p for p in (os.environ.get("PYTHONPATH") or "").split(os.pathsep) if p
    )
    return subprocess.run(
        [sys.executable, "-m", "papertrace", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env or base,
    )


def test_summary_counts_operators_separately_from_params():
    """I5：摘要里的「算子」不能把权重/输入节点也算进去。"""
    pytest.importorskip("torch")
    out_dir = scratch_dir("counts")
    r = _run_cli("build", "--repo", FIXTURE, "--entry", ENTRY, "--out", str(out_dir))
    assert r.returncode == 0, r.stderr
    doc = json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))
    kinds = {"op": 0, "param": 0, "input": 0}
    for node in doc["nodes"]:
        if node["level"] == "op":
            kinds[node["kind"]] += 1
    summary = [line for line in r.stdout.splitlines() if "已写出" in line][0]
    assert f"算子 {kinds['op']} / 权重 {kinds['param']} / 输入 {kinds['input']}" in summary
    assert f"degraded=" in r.stdout and "shape_unchecked=" in r.stdout


def test_dump_ops_marks_unknown_input_distinctly_from_scalar():
    """M1：(?) 是「没观察到」，() 是 0 维标量，两者不能打成一个样子。"""
    from papertrace.schema_validate import minimal_trace

    doc = minimal_trace()
    doc["nodes"] = [
        {
            "id": "root", "parent_id": None, "level": "module", "op": "Seq",
            "label": "", "loc": "m.py:1", "shape_in": [], "shape_out": [],
            "dtype": None, "inplace": False, "source": "static",
            "degraded": False, "repeat": 1, "stale": False,
        },
        {
            "id": "root/@000", "parent_id": "root", "level": "op", "op": "sum",
            "label": "s", "loc": "m.py:1", "kind": "op",
            "shape_in": [], "inputs": [], "shape_out": [], "outputs": [[]],
            "dtype": "float32", "inplace": False, "source": "runtime",
            "degraded": False, "degraded_reason": None, "repeat": 1, "stale": False,
        },
    ]
    path = scratch_dir("unknown-input") / "trace.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    r = _run_cli("dump", "--trace", str(path), "--ops")
    assert r.returncode == 0, r.stderr
    assert "(?) -> ()" in r.stdout
