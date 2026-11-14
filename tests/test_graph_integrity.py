"""图完整性：评审里那几条「看起来通过、其实恒真」的失效模式，一条一条钉住。

每条测试都构造一个能让旧实现出错的图，并且断言的是**具体数值**，不是「存在某个节点」。
"""

import json

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch")

import torch  # noqa: E402
import torch.nn as nn  # noqa: E402

from papertrace.exceptions import TraceSchemaError  # noqa: E402
from papertrace.parse_code.fx_trace import trace_module  # noqa: E402
from papertrace.schema_validate import minimal_trace, validate_trace  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402


class _Cat(nn.Module):
    def forward(self, a, b):
        return torch.cat([a, b], dim=-1)


class _Emb(nn.Module):
    def __init__(self):
        super().__init__()
        self.wte = nn.Embedding(64, 32)

    def forward(self, idx):
        return self.wte(idx)


class _Scalar(nn.Module):
    def forward(self, x):
        return x.sum()


def _op_nodes(doc, name=None):
    return [
        n for n in doc["nodes"]
        if n["level"] == "op" and (name is None or n["op"] == name)
    ]


def _by_id(doc):
    return {n["id"]: n for n in doc["nodes"]}


def test_cat_list_argument_keeps_both_edges():
    """旧实现只遍历 args 里的直接节点，cat([a, b]) 整条边丢失，build 照样报成功。"""
    doc = trace_module(_Cat(), (torch.randn(2, 4), torch.randn(2, 4)))

    cats = _op_nodes(doc, "cat")
    assert len(cats) == 1, [n["op"] for n in doc["nodes"]]
    incoming = [e for e in doc["edges"] if e["dst"] == cats[0]["id"]]
    assert len(incoming) == 2, f"cat 只收到 {len(incoming)} 条入边"
    assert sorted(e["shape"] for e in incoming) == [[2, 4], [2, 4]]
    assert cats[0]["shape_out"] == [2, 8]
    assert cats[0]["shape_in"] == [2, 4]


def test_embedding_shape_in_is_tokens_not_weights():
    """embedding 的输入是 token id (2,8)，不是权重 (64,32)。"""
    doc = trace_module(_Emb(), (torch.randint(0, 64, (2, 8)),))

    emb = _op_nodes(doc, "embedding")[0]
    assert emb["shape_in"] == [2, 8], emb
    assert emb["shape_out"] == [2, 8, 32]

    param_edges = [e for e in doc["edges"] if e["dst"] == emb["id"] and e["shape"] == [64, 32]]
    assert len(param_edges) == 1, "权重的入边不该被当成主输入，但也不能丢"


def test_zero_dim_output_is_scalar_not_unknown():
    """x.sum() 的输出是标量 []，不是「形状未知」。"""
    doc = trace_module(_Scalar(), (torch.randn(2, 4),))

    sums = _op_nodes(doc, "sum")
    assert len(sums) == 1, [n["op"] for n in doc["nodes"]]
    node = sums[0]
    assert node["shape_out"] == []
    assert node["outputs"] == [[]], "标量要记成 [[]]，无输出才是 []"
    assert node["degraded"] is False, node["degraded_reason"]


def test_param_nodes_belong_to_their_owning_module():
    """权重节点挂在自己的模块下，别一律挂 root（否则层级图骗人）。"""
    doc = trace_module(_Emb(), (torch.randint(0, 64, (2, 8)),))
    by_id = _by_id(doc)

    # export 把权重抬成图输入（placeholder 名 p_wte_weight），仍必须认成 param
    params = [n for n in doc["nodes"] if n.get("kind") == "param"]
    assert params, "embedding 的权重必须被认成 param，不能混进 input"
    assert [n["shape_out"] for n in params] == [[64, 32]]
    node = params[0]
    assert node["parent_id"] == "root/wte", node["parent_id"]
    assert by_id[node["parent_id"]]["level"] == "module"


def test_operator_and_module_ids_cannot_collide():
    """模块 id 用 / 路径，算子 id 用 /@序号：self.op000 这种命名也撞不上。"""
    class _Named(nn.Module):
        def __init__(self):
            super().__init__()
            self.op000 = nn.Linear(4, 4)

        def forward(self, x):
            return self.op000(x)

    doc = trace_module(_Named(), (torch.randn(2, 4),))
    ids = [n["id"] for n in doc["nodes"]]
    assert len(ids) == len(set(ids)), "节点 id 撞车"
    assert "root/op000" in ids, "模块 id 保留原名"
    op_ids = [n["id"] for n in _op_nodes(doc)]
    assert all("/@" in i for i in op_ids), op_ids[:3]


def test_duplicate_ids_and_dangling_edges_are_rejected():
    doc = minimal_trace()
    node = {
        "id": "root/@000", "level": "op", "op": "matmul", "label": "a", "loc": "m.py:1",
        "shape_in": [], "shape_out": [2, 2], "dtype": None, "inplace": False,
        "source": "runtime", "degraded": False, "repeat": 1, "stale": False,
    }
    doc["nodes"] = [node, dict(node)]
    with pytest.raises(TraceSchemaError) as excinfo:
        validate_trace(doc)
    assert any("重复" in e for e in excinfo.value.errors), excinfo.value.errors

    doc["nodes"] = [dict(node, id="root/@001")]
    doc["edges"] = [
        {
            "id": "e:root/@000->root/@001:args[0]", "src": "root/@000", "dst": "root/@001",
            "shape": [2, 2], "dtype": None, "inplace": False, "shape_consistent": True,
        }
    ]
    with pytest.raises(TraceSchemaError) as excinfo:
        validate_trace(doc)
    assert any("端点不存在" in e for e in excinfo.value.errors), excinfo.value.errors

    # parent 指向不存在的节点也要拒绝：否则 UI 的层级树会断
    doc["edges"] = []
    doc["nodes"] = [dict(node, parent_id="root/nope")]
    with pytest.raises(TraceSchemaError) as excinfo:
        validate_trace(doc)
    assert any("parent_id" in e for e in excinfo.value.errors), excinfo.value.errors


def test_inconsistent_edge_is_visible_in_dump():
    """断链要能被打出来，不能只在 JSON 里躺着。"""
    from tests.test_cli import run_cli

    doc = minimal_trace()
    doc["nodes"] = [
        {
            "id": "root/@000", "level": "op", "op": "matmul", "label": "a", "loc": "m.py:1",
            "shape_in": [], "shape_out": [2, 2], "dtype": None, "inplace": False,
            "source": "runtime", "degraded": False, "repeat": 1, "stale": False,
        },
        {
            "id": "root/@001", "level": "op", "op": "add", "label": "b", "loc": "m.py:1",
            "shape_in": [2, 2], "shape_out": [2, 2], "dtype": None, "inplace": False,
            "source": "runtime", "degraded": False, "repeat": 1, "stale": False,
        },
    ]
    doc["edges"] = [
        {
            "id": "e:root/@000->root/@001:args[0]", "src": "root/@000", "dst": "root/@001",
            "shape": [2, 2], "dtype": None, "inplace": False, "shape_consistent": False,
        }
    ]
    path = scratch_dir("bad-trace") / "bad.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    r = run_cli("dump", "--trace", str(path), "--edges")
    assert r.returncode == 0, r.stderr
    assert "shape_broken=1" in r.stdout
    assert "!" in r.stdout


def test_dump_refuses_invalid_trace_with_exit_2():
    from tests.test_cli import run_cli

    path = scratch_dir("broken-trace") / "broken.json"
    path.write_text('{"meta": {}}', encoding="utf-8")
    r = run_cli("dump", "--trace", str(path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "不是合法 trace" in r.stderr


def test_runtime_meta_records_how_the_trace_was_made():
    """同一个 trace 必须能回答：用哪版 torch、什么 dtype、batch/seq 多少。"""
    from papertrace.build_trace import build_trace

    doc = build_trace("tests/fixtures/nanogpt", entry="model:build_model")
    runtime = doc["meta"]["runtime"]
    assert runtime["ok"] is True
    assert runtime["torch_version"].startswith("2.")
    assert runtime["dtype"] == "int64"
    assert runtime["batch"] == 2
    assert runtime["seq_len"] == 8
    assert runtime["entry"] == "model:build_model"
    assert runtime["example_inputs"] == [[2, 8]]
    assert runtime["counts"]["operators"] > 10
    validate_trace(doc)
