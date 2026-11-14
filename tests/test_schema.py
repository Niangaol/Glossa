import json
from pathlib import Path

import pytest

from papertrace.exceptions import TraceSchemaError
from papertrace.schema_validate import (
    dump_trace,
    load_trace,
    minimal_trace,
    validate_trace,
)
from tests._tmp import scratch_dir

ROOT_KEYS = [
    "meta",
    "symbols",
    "nodes",
    "edges",
    "anchors",
    "mismatches",
    "unresolved",
    "annotations",
    "conflicts",
    "view_state",
]


def test_minimal_trace_passes():
    validate_trace(minimal_trace())


def test_minimal_trace_has_all_root_keys():
    doc = minimal_trace()
    assert sorted(doc) == sorted(ROOT_KEYS)
    assert doc["nodes"] == []
    assert doc["edges"] == []
    assert doc["meta"]["paper"]["ingest_mode"] == "none"
    assert doc["meta"]["paper"]["unit_count"] == 0
    assert doc["meta"]["model"]["name"] == "offline"
    assert len(doc["meta"]["repo"]["commit"]) >= 7


def test_missing_source_rejected():
    doc = minimal_trace()
    doc["nodes"].append(
        {
            "id": "attn.0.matmul_qk",
            "level": "op",
            "op": "aten::matmul",
            "label": "QK^T",
            "loc": "model.py:1-1",
            "shape_in": [["B", "H", "T", "Dk"], ["B", "H", "Dk", "T"]],
            "shape_out": [["B", "H", "T", "T"]],
            "dtype": "float32",
            "inplace": False,
            "degraded": False,
            "repeat": 1,
            "stale": False,
        }
    )
    with pytest.raises(TraceSchemaError) as excinfo:
        validate_trace(doc)
    assert any("source" in e for e in excinfo.value.errors)


def test_empty_evidence_rejected():
    doc = minimal_trace()
    doc["anchors"].append(
        {
            "paper_unit_id": "S3.2-eq-attn",
            "formula_term_index": 0,
            "code_expr_range": "model.py:30-30",
            "aten_ops": ["aten::matmul"],
            "confidence": 0.9,
            "source": "model",
            "evidence": "",
        }
    )
    with pytest.raises(TraceSchemaError) as excinfo:
        validate_trace(doc)
    assert any("evidence" in e for e in excinfo.value.errors)


def test_all_errors_collected_not_just_first():
    doc = minimal_trace()
    del doc["symbols"]
    del doc["conflicts"]
    with pytest.raises(TraceSchemaError) as excinfo:
        validate_trace(doc)
    joined = " ".join(excinfo.value.errors)
    assert "symbols" in joined and "conflicts" in joined


def test_dump_roundtrip():
    doc = minimal_trace()
    target = scratch_dir("dump-roundtrip") / "trace.json"
    dump_trace(doc, target)
    assert target.is_file()
    loaded = load_trace(target)
    validate_trace(loaded)
    assert loaded["meta"]["version"] == "1.0"


def test_schema_file_exists():
    p = Path(__file__).resolve().parents[1] / "schema" / "trace.schema.json"
    assert p.is_file() and p.stat().st_size > 1000
    json.loads(p.read_text(encoding="utf-8"))
