"""S9 端到端：`build --paper` 把论文脊柱接进 trace（brief Step 1 的具名测试 + R76/R68）。

纪律（与 tests/test_spine_judge.py、tests/test_spine_retrieve.py 完全一致）：
- 全程不联网：judge / embed 一律注入假后端，且假后端**单实例跨调用**——
  每次新建实例会重置计数器，让人误判「实现漏了某条路径」；
- 注入后**必须断言调用计数 +1**，否则测到的是 offline 兜底路径，结论是假的；
- 不用 pytest 的 tmp_path / --basetemp（沙箱递归删除 WinError 5），
  临时目录走 tests/_tmp.py::scratch_dir 并自行收尾。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from papertrace.align import embed as embed_module
from papertrace.align import judge as judge_module
from papertrace.align.score import confidence
from papertrace.align.struct_signal import StructSignal
from papertrace.build_trace import build_trace, load_entry
from papertrace.exceptions import LLMUnavailable
from papertrace.ingest.paper import IngestError
from papertrace.llm.client import ChatResult
from papertrace.llm.prompts import JUDGE_PROMPT_VERSION
from papertrace.schema_validate import load_trace, validate_trace
from papertrace.spine import attach_paper
from tests._tmp import scratch_dir

# 不依赖 cwd：从哪个目录跑 pytest 都得找得到夹具
FIXTURE = str(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nanogpt")
PAPER = str(
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "papers"
    / "vaswani2017"
    / "attention.tex"
)

#: 黄金夹具实测（控制器跑过，期望值必须与之一致）
GOLD_PAIRS = [(0, "root/@037"), (1, "root/@038"), (2, "root/@043"), (3, "root/@045")]

#: GC8：不带 --paper 时逐项不变
GC8_NODES = 128
GC8_EDGES = 101
GC8_COUNTS = {
    "operators": 75,
    "degraded": 2,
    "fused": 0,
    "orphan": 0,
    "shape_broken": 0,
    "shape_unchecked": 0,
}


class _YesBackend:
    """答 yes 的假后端（单实例跨调用，计数器累积）。"""

    name = "fake-yes"

    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    def chat(self, prompt, *, system=None):
        self.calls += 1
        self.prompts.append(prompt)
        return ChatResult(text="Verdict: yes\nEvidence: 同一算子", model="fake-yes", backend="fake-yes")


class _NoBackend:
    """答 no 的假后端。"""

    name = "fake-no"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, prompt, *, system=None):
        self.calls += 1
        return ChatResult(text="Verdict: no\nEvidence: 不是同一个算子", model="fake-no", backend="fake-no")


class _Embedding404:
    """配了 openai、但 /embeddings 返回 404 的假后端（R76）。"""

    name = "openai"

    def chat(self, prompt, *, system=None):
        return ChatResult(text="Verdict: yes\nEvidence: 同一算子", model="m", backend="openai")

    def embed(self, texts):
        raise LLMUnavailable(
            "OpenAI 兼容后端返回 HTTP 404（https://api.example.com/v1/embeddings）："
            "没有这个端点"
        )


class _SameVectorsBackend:
    """所有文本都给同一个向量的假后端：每个 cosine 都是 1.0 → s_retr=1.0。

    用来把绿线门（c≥0.75 且 s_struct≥0.50）真正逼到降级分支——不注入它，
    s_retr=0.0 会让 confidence 掉到 0.5，走的是 c≥0.45 那条普通黄线，
    根本没测到「绿线被 s_struct 拖下来」这件事。
    """

    name = "fake-same"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, prompt, *, system=None):
        raise AssertionError("这条测试只该走 embedding，不该走 chat")

    def embed(self, texts):
        self.calls += 1
        return [[1.0, 0.0] for _ in texts]


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.pop("PAPERTRACE_LLM_BACKEND", None)
    env.pop("PAPERTRACE_LLM", None)
    return subprocess.run(
        [sys.executable, "-m", "papertrace", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _offline_build(monkeypatch) -> tuple[dict, subprocess.CompletedProcess]:
    """真跑一次 `build --paper <黄金夹具>`（offline），返回 (trace, CLI 结果)。"""
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    out_dir = scratch_dir("s9-offline")
    result = _run_cli(
        "build", "--repo", FIXTURE, "--paper", PAPER, "--out", str(out_dir), "--force"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return load_trace(out_dir / "trace.json"), result


def _fresh_doc():
    """真跑一次 build_trace + load_entry（R79：节点来自第一次追踪，模块再取一次）。"""
    return build_trace(FIXTURE), load_entry(FIXTURE, "model:build_model")


# ---------------------------------------------------------------- Step 1 具名测试


def test_offline_build_exits_zero(monkeypatch):
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    out_dir = scratch_dir("s9-exit")
    result = _run_cli(
        "build", "--repo", FIXTURE, "--paper", PAPER, "--out", str(out_dir), "--force"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (out_dir / "trace.json").is_file()
    assert "Traceback" not in result.stderr


def test_offline_trace_is_schema_valid(monkeypatch):
    doc, _ = _offline_build(monkeypatch)
    # validate_trace 抛 TraceSchemaError 即失败；再走一遍 load_trace 的解析
    validate_trace(doc)


def test_offline_has_no_anchors(monkeypatch):
    doc, _ = _offline_build(monkeypatch)
    assert doc["anchors"] == []


def test_offline_has_four_unresolved_terms(monkeypatch):
    doc, _ = _offline_build(monkeypatch)
    unresolved = doc["unresolved"]
    assert [u["ref"] for u in unresolved] == [
        "S3.2-eq-attn-t0",
        "S3.2-eq-attn-t1",
        "S3.2-eq-attn-t2",
        "S3.2-eq-attn-t3",
    ]
    for entry in unresolved:
        assert entry["kind"] == "paper_unit"
        assert entry["reason"].strip() != ""


def test_meta_paper_is_tex(monkeypatch):
    doc, _ = _offline_build(monkeypatch)
    paper = doc["meta"]["paper"]
    assert paper["ingest_mode"] == "tex"
    assert paper["unit_count"] == 1
    assert paper["source"] == PAPER


def test_symbols_are_filled(monkeypatch):
    doc, _ = _offline_build(monkeypatch)
    code_names = {row["symbol"] for row in doc["symbols"]["code"]}
    assert {"B", "T", "D", "H", "Dh"} <= code_names
    assert {row["symbol"] for row in doc["symbols"]["paper"]} == {"d_k"}
    matched = [m for m in doc["symbols"]["mapping"] if m["status"] == "matched"]
    assert len(matched) == 1
    assert matched[0]["paper_symbol"] == "d_k"
    assert matched[0]["code_var"] == "Dh"
    assert matched[0]["value"] == 8
    assert len([m for m in doc["symbols"]["mapping"] if m["status"] == "code_only"]) == 4


def test_yes_backend_produces_yellow_anchor(monkeypatch):
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _YesBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    doc, model = _fresh_doc()
    returned = attach_paper(doc, PAPER, model)
    assert returned is doc
    yellow = [a for a in doc["anchors"] if a["tier"] == "yellow"]
    assert len(yellow) == 4
    anchor = yellow[0]
    assert 0.45 <= anchor["confidence"] < 0.75
    assert anchor["confidence"] == pytest.approx(0.654753, abs=1e-6)
    assert anchor["signals"] == {"s_retr": 0.0, "s_judge": 1.0, "s_struct": 0.8}
    assert anchor["source"] == "model"
    assert anchor["evidence"].strip() != ""
    # 注入的假后端必须真的被走到（否则测的是 offline 兜底）
    assert backend.calls == 4
    assert len(backend.prompts) == 4


def test_green_gate_downgrades_in_real_trace(monkeypatch):
    """绿线门：s_struct=0 但 c≥0.75 → 降黄线，且 tier_reason 写清为什么。"""
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _YesBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    embedder = _SameVectorsBackend()
    monkeypatch.setattr(embed_module, "get_llm", lambda: embedder)

    def _no_structure(nodes, terms, config):
        return StructSignal(0.0, [], ["同构未命中"], GOLD_PAIRS)

    monkeypatch.setattr("papertrace.spine.struct_signal", _no_structure)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    assert len(doc["anchors"]) == 4
    for anchor in doc["anchors"]:
        assert anchor["tier"] == "yellow"
        assert anchor["signals"]["s_struct"] == 0.0
        assert anchor["signals"]["s_retr"] == 1.0
        assert anchor["signals"]["s_judge"] == 1.0
        # confidence(1,1,0)=0.768525 实测值：≥0.75 本可绿，被 s_struct 拖成黄
        assert anchor["confidence"] == pytest.approx(0.768525, abs=1e-6)
        assert "绿线降为黄线" in anchor["evidence"]
        assert anchor["source"] == "model"
    # 判定的桩确实被走到（4 个公式项各一次；t0 命中第一个 yes 就早退）
    assert backend.calls == 4
    # embedding 的桩确实被走到（retrieve_bidirectional 对 code 侧、paper 侧各调一次）
    assert embedder.calls == 2


def test_code_expr_range_uses_node_ids_not_source_lines(monkeypatch):
    """R68：code_expr_range 填 pairs 的 node_id 区间，绝不编 file:line。"""
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _YesBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)

    def _two_nodes_for_first_term(nodes, terms, config):
        pairs = [(0, "root/@037"), (0, "root/@038")] + GOLD_PAIRS[1:]
        return StructSignal(0.8, ["同构"], [], pairs)

    monkeypatch.setattr("papertrace.spine.struct_signal", _two_nodes_for_first_term)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    anchor = next(a for a in doc["anchors"] if a["formula_term_index"] == 0)
    assert anchor["code_expr_range"] == "root/@037..root/@038"
    assert anchor["aten_ops"] == ["matmul", "mul"]
    assert "model.GPT" not in anchor["code_expr_range"]
    assert ":" not in anchor["code_expr_range"]
    others = [a for a in doc["anchors"] if a["formula_term_index"] != 0]
    assert all(a["code_expr_range"] == dict(GOLD_PAIRS)[a["formula_term_index"]] for a in others)
    # t0 有两个候选节点，但 _judge_pairs 命中第一个 yes 就早退（省 API、
    # M1b 多项候选时取第一个 yes 的依据），所以总共只调 4 次而不是 5 次。
    assert backend.calls == 4


def test_no_paper_flag_is_unchanged(monkeypatch):
    """Constraint 8：不带 --paper 时 M1a 行为逐项不变。"""
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    out_dir = scratch_dir("s9-gc8")
    result = _run_cli(
        "build", "--repo", FIXTURE, "--paper", "none", "--out", str(out_dir), "--force"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    doc = load_trace(out_dir / "trace.json")
    assert len(doc["nodes"]) == GC8_NODES
    assert len(doc["edges"]) == GC8_EDGES
    counts = doc["meta"]["runtime"]["counts"]
    for key, expected in GC8_COUNTS.items():
        assert counts[key] == expected, (key, counts[key], expected)
    assert doc["anchors"] == []
    assert doc["unresolved"] == []
    assert doc["meta"]["paper"] == {"source": "none", "unit_count": 0, "ingest_mode": "none"}


def test_ingest_error_becomes_unresolved_not_traceback():
    doc, model = _fresh_doc()
    returned = attach_paper(doc, "arxiv:1706.03762", model)
    assert returned is doc
    entries = [u for u in doc["unresolved"] if u["kind"] == "paper_unit"]
    assert entries
    entry = entries[0]
    assert entry["ref"] == "arxiv:1706.03762"
    assert entry["reason"].strip() != ""
    assert doc["meta"]["paper"]["ingest_mode"] == "none"
    validate_trace(doc)
    # ingest 失败时 doc 的骨架必须原样还在（不能顺手清空 nodes）
    assert len(doc["nodes"]) == GC8_NODES


# ---------------------------------------------------------------------- R76 一条


def test_openai_embedding_404_reason_names_configured_backend(monkeypatch):
    """R76：配了 openai 但 embeddings 404，reason 必须点名 openai，不能谎称 offline。"""
    from papertrace.align import retrieve as retrieve_module

    monkeypatch.setenv("PAPERTRACE_LLM_BACKEND", "openai")
    monkeypatch.setenv("PAPERTRACE_OPENAI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("PAPERTRACE_OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("PAPERTRACE_LLM", "deepseek-chat")
    backend = _Embedding404()
    monkeypatch.setattr(embed_module, "get_llm", lambda: backend)
    out = retrieve_module.retrieve_bidirectional(
        [{"code_id": "root/@037", "text": "matmul"}],
        [{"term_id": "S3.2-eq-attn-t0", "text": "QK^{T}"}],
    )
    assert out["s_retr"] == 0.0
    reason = out["reason"]
    assert isinstance(reason, str) and reason.strip() != ""
    assert "embedding" in reason
    assert "openai" in reason
    assert "offline 后端不提供" not in reason
    assert "404" in reason


def test_retrieve_reason_stays_offline_when_backend_is_offline(monkeypatch):
    """R76 的既有契约不许破：真 offline 时 reason 仍含「embedding」与 offline 措辞。"""
    from papertrace.align import retrieve as retrieve_module

    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    out = retrieve_module.retrieve_bidirectional(
        [{"code_id": "root/@037", "text": "matmul"}],
        [{"term_id": "S3.2-eq-attn-t0", "text": "QK^{T}"}],
    )
    assert out["s_retr"] == 0.0
    assert "embedding" in out["reason"]
    assert "offline" in out["reason"]


def test_model_meta_records_judge_prompt_version(monkeypatch):
    """R70：prompt_version 必须写 JUDGE_PROMPT_VERSION，不是默认 "0"。"""
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    assert doc["meta"]["model"]["prompt_version"] == JUDGE_PROMPT_VERSION
    assert doc["meta"]["model"]["name"] == "offline"
    assert doc["meta"]["model"]["embed_model"] == "none"


def test_no_structural_pairs_never_asks_judge_even_with_embeddings(monkeypatch):
    """R37 的硬边界：pairs 空 → 一个 judge 都不问，哪怕检索有候选、哪怕问了就能绿。

    反面对照（写进注释，别当成已测路径）：若拿检索 top1 当候选去问 judge，
    s_retr=1.0 + s_judge=1.0 + s_struct=0.60 → confidence=0.8428 ≥ 0.75 且
    s_struct ≥ 0.50，会出**绿线**——可这一项的结构同构根本没命中。那样的绿线
    是 embedding 相似度撑起来的，不是公式项与算子对上了账。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _YesBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    embedder = _SameVectorsBackend()
    monkeypatch.setattr(embed_module, "get_llm", lambda: embedder)

    def _no_isomorphism(nodes, terms, config):
        return StructSignal(0.6, [], ["算子序列与公式项顺序同构：没有任何算子组能匹配"], [])

    monkeypatch.setattr("papertrace.spine.struct_signal", _no_isomorphism)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    assert doc["anchors"] == []
    assert [u["ref"] for u in doc["unresolved"]] == [
        "S3.2-eq-attn-t0",
        "S3.2-eq-attn-t1",
        "S3.2-eq-attn-t2",
        "S3.2-eq-attn-t3",
    ]
    for entry in doc["unresolved"]:
        assert "结构同构未命中，没有可判断的候选对" in entry["reason"]
        assert "s_struct=0.60" in entry["reason"]
    # 两条注入都被真的走到：embedding 跑了（否则测的是 offline 归零），judge 一次都没跑
    assert embedder.calls == 2
    assert backend.calls == 0


def test_ingest_error_does_not_depend_on_model():
    """IngestError 与 model 无关：model=None 也要落 unresolved，不冒 traceback。"""
    from papertrace.ingest.paper import ingest_paper

    with pytest.raises(IngestError):
        ingest_paper("arxiv:1706.03762")
    doc = {"meta": {}, "nodes": [], "edges": []}
    attach_paper(doc, "arxiv:1706.03762", None)
    assert any(
        u["kind"] == "paper_unit" and u["ref"] == "arxiv:1706.03762" for u in doc["unresolved"]
    )