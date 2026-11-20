"""第五轮评审的回归测试：两条必修 + 一条契约确认，每条都能真的失败。

C1  参数名与形参名相同（`self.x` + `forward(x)`）时，真输入被当成权重吞掉
I1  trace 的 id / parent_id / 边端点类型不对时，结构校验抛 TypeError（exit 1）
I2  权重派生量（`self.w[0]`、`self.w[:, :2]`）被当成数据输入，shape_in 变权重形状
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
from papertrace.exceptions import TraceSchemaError  # noqa: E402
from papertrace.parse_code.fx_trace import trace_module  # noqa: E402
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


def _op(doc: dict, op: str, kind: str | None = None) -> dict:
    for node in doc["nodes"]:
        if node["level"] == "op" and node["op"] == op and (kind is None or node["kind"] == kind):
            return node
    raise AssertionError("图里没有 " + op + " 节点：" + "、".join(
        n["op"] for n in doc["nodes"] if n["level"] == "op"
    ))


# ---------------------------------------------------------------- C1

_COLLIDE = """import torch
import torch.nn as nn


class Collide(nn.Module):
    def __init__(self):
        super().__init__()
        self.x = nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return torch.cat([x, self.x])

    def example_inputs(self):
        return torch.ones(1, 4)


def build_model():
    return Collide().eval()
"""


def test_param_named_like_the_input_does_not_swallow_the_input():
    """C1：self.x 与形参 x 同名，输入仍是 input，cat 的 shape_in 仍是数据形状。"""
    repo = _write_repo("collide", _COLLIDE)
    doc = build_trace(repo, entry=ENTRY)
    inputs = [n for n in doc["nodes"] if n["level"] == "op" and n["kind"] == "input"]
    params = [n for n in doc["nodes"] if n["level"] == "op" and n["kind"] == "param"]
    assert len(inputs) == 1, inputs
    assert len(params) == 1, params
    assert inputs[0]["shape_out"] == [1, 4], inputs[0]
    cat = _op(doc, "cat")
    assert cat["inputs"] == [[1, 4]], cat["inputs"]
    assert cat["shape_in"] == [1, 4], cat
    assert cat["shape_out"] == [3, 4]


def test_cli_summary_counts_the_input_even_when_the_param_shares_its_name():
    """C1：摘要里的「输入」不能因为同名参数变成 0。"""
    repo = _write_repo("collide-cli", _COLLIDE)
    out_dir = scratch_dir("collide-cli-out")
    r = _run_cli("build", "--repo", str(repo), "--entry", ENTRY, "--out", str(out_dir))
    assert r.returncode == 0, r.stderr
    summary = [line for line in r.stdout.splitlines() if "已写出" in line][0]
    assert "输入 1" in summary, summary


# ---------------------------------------------------------------- I2

class WIdx(torch.nn.Module):
    """`self.w[0]` 是权重派生量，不是数据输入。"""

    def __init__(self) -> None:
        super().__init__()
        self.w = torch.nn.Parameter(torch.ones(4, 2))

    def forward(self, x):
        return torch.cat([x, self.w[0]])


class WSlice(torch.nn.Module):
    """`self.w[:, :2]` 同样只是权重的切片。"""

    def __init__(self) -> None:
        super().__init__()
        self.w = torch.nn.Parameter(torch.ones(2, 2))

    def forward(self, x):
        return torch.cat([x, self.w[:, :2]])


@pytest.mark.parametrize(
    "model,example,expected",
    [
        (WIdx(), torch.ones(5), [[5]]),
        (WSlice(), torch.ones(1, 2), [[1, 2]]),
    ],
)
def test_weight_derived_tensors_are_not_data_inputs(model, example, expected):
    """I2：只由权重算出的张量不进 inputs，shape_in 仍是模型输入。"""
    doc = trace_module(model.eval(), (example,))
    cat = _op(doc, "cat")
    assert cat["inputs"] == expected, cat["inputs"]
    assert cat["shape_in"] == expected[0], cat


def test_data_tensor_getitem_still_counts_as_an_input():
    """反向守门：`x[0]` 是数据，不能被「派生量过滤」误伤成空输入。"""

    class IndexData(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.w = torch.nn.Parameter(torch.ones(4))

        def forward(self, x):
            return x[0] + self.w

    doc = trace_module(IndexData().eval(), (torch.ones(2, 4),))
    # torch.export 把 x[0] 降成 aten.select.int，不是 getitem
    select = _op(doc, "select")
    assert select["inputs"] == [[2, 4]], select["inputs"]
    assert select["shape_out"] == [4]


# ---------------------------------------------------------------- I1

def _base_doc() -> dict:
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


def _payloads() -> list[str]:
    cases = []
    doc = _base_doc()
    doc["nodes"][0]["id"] = ["bad"]
    cases.append(json.dumps(doc))
    doc = _base_doc()
    doc["nodes"][1]["parent_id"] = {"oops": 1}
    cases.append(json.dumps(doc))
    doc = _base_doc()
    doc["edges"][0]["id"] = [1, 2]
    cases.append(json.dumps(doc))
    doc = _base_doc()
    doc["edges"][0]["src"] = {"oops": 1}
    cases.append(json.dumps(doc))
    return cases


@pytest.mark.parametrize("payload", _payloads())
def test_dump_refuses_wrong_field_types_instead_of_crashing(payload):
    """I1：字段类型错也要 exit 2，不能把 TypeError 漏成 traceback。"""
    path = scratch_dir("bad-fields") / "trace.json"
    path.write_text(payload, encoding="utf-8")
    r = _run_cli("dump", "--trace", str(path))
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "Traceback" not in r.stderr, r.stderr
    assert "不是合法 trace" in r.stderr, r.stderr


def test_validate_trace_reports_wrong_field_types_as_schema_error():
    """I1（进程内）：id 是 list 时报 TraceSchemaError，不是 TypeError。"""
    doc = _base_doc()
    doc["nodes"][0]["id"] = ["bad"]
    with pytest.raises(TraceSchemaError) as excinfo:
        validate_trace(doc)
    assert "必须是字符串" in str(excinfo.value), str(excinfo.value)