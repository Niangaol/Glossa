"""第四轮评审的回归测试：两个必修项 + 一个语义修正，每条都能真的失败。

I-1  容器（list/tuple/dict）里的权重被当成数据输入，shape_in 变权重形状
I-2  trace 根/字段类型错误时 dump 抛 AttributeError（exit 1 + traceback）
M-1  --ops 把「确实没有数据输入」和「输入未知」都打成 (?)
M-4  module.eval() 在异常翻译之外，会裸 traceback + exit 1
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

from papertrace.exceptions import TraceSchemaError, TraceUnsupported  # noqa: E402
from papertrace.parse_code.fx_trace import trace_module  # noqa: E402
from papertrace.schema.validate import minimal_trace, validate_trace  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402

REPO_ROOT = ROOT


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "papertrace", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(REPO_ROOT),
    )


def _trace(model, *inputs, module_id: str = "root") -> dict:
    # 不要在这里 eval()：trace_module 内部会做，M-4 测的就是那一步的异常翻译
    return trace_module(model, inputs, module_id=module_id)


def _op(doc: dict, op: str) -> dict:
    for node in doc["nodes"]:
        if node["level"] == "op" and node["op"] == op:
            return node
    raise AssertionError("图里没有 " + op + " 节点：" + "、".join(
        n["op"] for n in doc["nodes"] if n["level"] == "op"
    ))


# ---------------------------------------------------------------- I-1

class CatWeight(torch.nn.Module):
    """权重藏在 list 里：torch.cat([self.w, x]) / torch.cat([x, self.w])。"""

    def __init__(self, weight_first: bool) -> None:
        super().__init__()
        self.w = torch.nn.Parameter(torch.ones(2, 4))
        self.weight_first = weight_first

    def forward(self, x):
        if self.weight_first:
            return torch.cat([self.w, x])
        return torch.cat([x, self.w])


class StackWeight(torch.nn.Module):
    """权重包在 list 里传给 torch.stack：参数本身就是容器。"""

    def __init__(self) -> None:
        super().__init__()
        self.w = torch.nn.Parameter(torch.ones(2, 4))

    def forward(self, x):
        return x + torch.stack([self.w]).sum(0)


@pytest.mark.parametrize("weight_first", [True, False])
def test_weight_inside_a_list_is_not_a_data_input(weight_first):
    """I-1：列表里的权重不能算数据输入，shape_in 必须是 x 的形状。"""
    doc = _trace(CatWeight(weight_first), torch.ones(1, 4))
    cat = _op(doc, "cat")
    assert [2, 4] not in cat["inputs"], cat["inputs"]
    assert cat["shape_in"] == [1, 4], cat
    assert cat["shape_out"] == [3, 4]


def test_weight_inside_a_container_argument_is_not_a_data_input():
    """I-1：参数本身是容器（list 里只有权重）时，inputs 必须为空。"""
    doc = _trace(StackWeight(), torch.ones(2, 4))
    stack = _op(doc, "stack")
    assert stack["inputs"] == [], stack["inputs"]
    assert stack["shape_in"] == []
    assert stack["shape_out"] == [1, 2, 4]


# ---------------------------------------------------------------- I-2

_EMPTY = {"meta": {}, "edges": [], "anchors": [], "mismatches": [], "unresolved": []}


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps([1, 2, 3]),
        json.dumps("just a string"),
        json.dumps(dict(_EMPTY, nodes="x")),
        json.dumps(dict(_EMPTY, nodes=[1, 2])),
    ],
)
def test_dump_refuses_malformed_trace_instead_of_crashing(payload):
    """I-2：合法 JSON 但根/字段类型不对，必须 exit 2 且不 print traceback。"""
    path = scratch_dir("bad-root") / "trace.json"
    path.write_text(payload, encoding="utf-8")
    r = _run_cli("dump", "--trace", str(path))
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "Traceback" not in r.stderr, r.stderr
    assert "不是合法 trace" in r.stderr, r.stderr


def test_validate_trace_reports_non_object_root_as_schema_error():
    """I-2（进程内）：非对象根必须是 TraceSchemaError，不是 AttributeError。"""
    with pytest.raises(TraceSchemaError) as excinfo:
        validate_trace([1, 2, 3])
    assert "JSON 对象" in str(excinfo.value), str(excinfo.value)


# ---------------------------------------------------------------- M-1

def test_ops_without_any_data_input_are_not_marked_unknown():
    """M-1：inputs==[] 是「确实没有数据输入」，不是「输入未知」。"""
    doc = minimal_trace()
    doc["nodes"] = [
        {
            "id": "root", "parent_id": None, "level": "module", "op": "Seq",
            "label": "", "loc": "m.py:1", "shape_in": [], "shape_out": [],
            "dtype": None, "inplace": False, "source": "static",
            "degraded": False, "repeat": 1, "stale": False,
        },
        {
            "id": "root/@000", "parent_id": "root", "level": "op", "op": "slice",
            "label": "s", "loc": "m.py:1", "kind": "op",
            "shape_in": [], "inputs": [], "shape_out": [1, 1, 8, 16],
            "outputs": [[1, 1, 8, 16]],
            "dtype": "float32", "inplace": False, "source": "runtime",
            "degraded": False, "degraded_reason": None, "repeat": 1, "stale": False,
        },
    ]
    path = scratch_dir("no-data-input") / "trace.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    r = _run_cli("dump", "--trace", str(path), "--ops")
    assert r.returncode == 0, r.stderr
    assert "- -> (1, 1, 8, 16) slice" in r.stdout, r.stdout
    assert "(?)" not in r.stdout, r.stdout


# ---------------------------------------------------------------- M-4

def test_eval_failure_is_translated_not_a_traceback():
    """M-4：model.eval() 抛错也要变成 TraceUnsupported（exit 5），不是裸 traceback。"""

    class BadEval(torch.nn.Module):
        def eval(self):
            raise RuntimeError("eval exploded")

        def forward(self, x):
            return x + 1

    with pytest.raises(TraceUnsupported) as excinfo:
        _trace(BadEval(), torch.ones(2, 4))
    assert "eval exploded" in str(excinfo.value), str(excinfo.value)