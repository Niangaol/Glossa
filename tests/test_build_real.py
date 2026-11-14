"""M1a：build 必须真的把 nanoGPT 的算子图抓出来，而不是写个空骨架。"""

from pathlib import Path

import pytest

pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")

from papertrace.build_trace import BuildError, build_trace  # noqa: E402
from papertrace.schema_validate import validate_trace  # noqa: E402

FIXTURE = str(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nanogpt")
ENTRY = "model:build_model"


def test_build_traces_real_operators():
    doc = build_trace(FIXTURE, entry=ENTRY)
    validate_trace(doc)

    ops = {n["op"] for n in doc["nodes"] if n["level"] == "op"}
    for want in ("matmul", "mul", "masked_fill", "softmax"):
        assert want in ops, f"缺 {want}，抓到的是 {sorted(ops)}"
    assert any(n["level"] == "module" for n in doc["nodes"])
    assert doc["edges"], "没有边，图是散的"
    assert doc["meta"]["repo"]["entry_module"] == ENTRY


def test_build_is_deterministic():
    first = build_trace(FIXTURE, entry=ENTRY)
    second = build_trace(FIXTURE, entry=ENTRY)
    assert [(n["id"], n["op"], n["shape_out"]) for n in first["nodes"]] == [
        (n["id"], n["op"], n["shape_out"]) for n in second["nodes"]
    ]


def test_build_rejects_unknown_entry():
    with pytest.raises(BuildError):
        build_trace(FIXTURE, entry="model:NotAClass")


def test_build_rejects_class_that_needs_arguments():
    """`model:GPT` 要 config，不能靠猜；必须让用户给工厂函数。"""
    with pytest.raises(BuildError) as exc:
        build_trace(FIXTURE, entry="model:GPT")
    assert "工厂" in str(exc.value) or "无参" in str(exc.value)


def test_op_nodes_have_shapes_and_parents():
    doc = build_trace(FIXTURE, entry=ENTRY)
    by_id = {n["id"]: n for n in doc["nodes"]}
    op_nodes = [n for n in doc["nodes"] if n["level"] == "op" and n["op"] != "placeholder"]
    assert op_nodes
    for node in op_nodes:
        # 0 维标量的 shape_out 合法地是 []，所以看 outputs 里是否记录了「标量」这一项
        assert node["outputs"] or node["shape_out"], f"{node['label']} 没有输出形状"
        assert node["shape_out"] or node["outputs"] == [[]], node["label"]
        assert node["parent_id"] in by_id
