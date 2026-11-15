"""S9 端到端：`build --paper` 把论文脊柱接进 trace（brief Step 1 的具名测试 + R76/R68）。

纪律（与 tests/test_spine_judge.py、tests/test_spine_retrieve.py 完全一致）：
- 全程不联网：judge / embed 一律注入假后端，且假后端**单实例跨调用**——
  每次新建实例会重置计数器，让人误判「实现漏了某条路径」；
- 注入后**必须断言调用计数 +1**，否则测到的是 offline 兜底路径，结论是假的；
- 不用 pytest 的 tmp_path / --basetemp（沙箱递归删除 WinError 5），
  临时目录走 tests/_tmp.py::scratch_dir 并自行收尾。
"""

from __future__ import annotations

import hashlib
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
from papertrace.exceptions import BuildError, LLMUnavailable
from papertrace.ingest.paper import IngestError, ingest_paper
from papertrace.llm.client import ChatResult
from papertrace.llm.prompts import JUDGE_PROMPT_VERSION
from papertrace.parse_paper.split_terms import split_formula
from papertrace.schema_validate import load_trace, validate_trace
from papertrace.spine import ALTERNATIVE_LIMIT, attach_paper
from papertrace.spine_claims import CLAIMED_REASON
from papertrace.spine_fallback import RANGE_SEP, pairs_or_fallback
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


class _NoWithEmbeddingBackend:
    """答 no 的假后端 + 恒定向量：s_judge=0.0、s_retr=1.0（单实例跨调用，双计数器）。

    用来钉死「回退路径上判断题全答 no 也照样出黄线」的那条路：
    c=sigmoid(4·(0.30·1.0+0.50·0+0.20·s_struct−0.5)) 在 s_struct=0.8 时是
    0.460085 ≥ 0.45，anchor 出得来，而 judge 确认的节点是 None。
    """

    name = "fake-no-embed"

    def __init__(self) -> None:
        self.calls = 0
        self.embed_calls = 0

    def chat(self, prompt, *, system=None):
        self.calls += 1
        return ChatResult(text="Verdict: no\nEvidence: 不是同一个算子", model="fake-no", backend="fake-no")

    def embed(self, texts):
        self.embed_calls += 1
        return [[1.0, 0.0] for _ in texts]


class _YesWithBucketEmbeddingBackend:
    """答 yes 的假后端 + sha256(text) 分桶向量（单实例跨调用，双计数器）。

    F5 专用：判断题答 yes（结构路径上 judge 必须确认，否则 anchor 出不来），
    embedding 按 sha256(text) 前 8 字节分桶成定长 list[float]——同一份文本永远
    得到同一个向量，跑多少次都可复现；不同文本几乎正交，于是 top-k 的次序由
    文本内容决定，而不是被常量向量拖成「全员同分、按 id 排序」的退化情形。

    向量只由文本决定，而 text 里带 loc（本机绝对路径），所以换一台机器 top-k
    会变：任何依赖检索次序的期望值都必须用产品自己的 retrieve_bidirectional
    现算，不许把节点 id 写死在测试里（写死 = 换机器就过期）。
    """

    name = "fake-yes-embed"

    def __init__(self) -> None:
        self.calls = 0
        self.embed_calls = 0

    def chat(self, prompt, *, system=None):
        self.calls += 1
        return ChatResult(text="Verdict: yes\nEvidence: 同一算子", model="fake-yes", backend="fake-yes")

    def embed(self, texts):
        self.embed_calls += 1
        return [[b / 255 for b in hashlib.sha256(t.encode("utf-8")).digest()[:8]]
                for t in texts]


def _run_cli(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.pop("PAPERTRACE_LLM_BACKEND", None)
    env.pop("PAPERTRACE_LLM", None)
    if cwd is not None:
        # 仓外构建：`-m papertrace` 不能靠 cwd 找包，用 PYTHONPATH 钉死仓库根
        env["PYTHONPATH"] = os.pathsep.join(
            [str(Path(__file__).resolve().parents[1]), env.get("PYTHONPATH") or ""]
        ).strip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-m", "papertrace", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=cwd,
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
    source = paper["source"]
    # R140/R145：写出的是相对构建目录（cwd）的便携路径，不是发件人机器的绝对路径
    assert not Path(source).is_absolute(), source
    assert "\\" not in source, source
    # R145-1：期望值是手算常量，不是从产品输出反推的自证循环
    assert source == "tests/fixtures/papers/vaswani2017/attention.tex", source


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
        # R135：同一算子至多归一个公式项，所以 t0 的两个节点不能和 t1 的候选重叠
        pairs = [(0, "root/@037"), (0, "root/@038"), (1, "root/@039"),
                 (2, "root/@043"), (3, "root/@045")]
        return StructSignal(0.8, ["同构"], [], pairs)

    monkeypatch.setattr("papertrace.spine.struct_signal", _two_nodes_for_first_term)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    anchor = next(a for a in doc["anchors"] if a["formula_term_index"] == 0)
    assert anchor["code_expr_range"] == "root/@037..root/@038"
    assert anchor["aten_ops"] == ["matmul", "mul"]
    assert "model.GPT" not in anchor["code_expr_range"]
    assert ":" not in anchor["code_expr_range"]
    # 期望从 GOLD_PAIRS 派生，只覆写本用例改动的 t1（@038→@039）：同一事实一份副本。
    # t0 的两节点区间在上面第 323 行单独断言，不进这张表。
    expected = dict(GOLD_PAIRS)  # R145-2 输入调整：t1 候选 @038→@039，只覆写这一项
    expected[1] = "root/@039"
    others = [a for a in doc["anchors"] if a["formula_term_index"] != 0]
    assert {a["formula_term_index"] for a in others} == {1, 2, 3}, "四项都该出线"
    assert all(a["code_expr_range"] == expected[a["formula_term_index"]] for a in others)
    # t0 有两个候选节点，但 spine_claims.judge_first_yes 命中第一个 yes 就早退
    # （省 API），所以总共只调 4 次而不是 5 次。
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


def _no_isomorphism(nodes, terms, config):
    """结构同构不命中的替身：pairs 为空、score 固定 0.60（真实夹具实测值）。"""
    return StructSignal(0.6, [], ["算子序列与公式项顺序同构：没有任何算子组能匹配"], [])


def test_structural_miss_falls_back_to_kind_candidates_but_never_green(monkeypatch):
    """R115：结构同构不命中时 judge 仍然工作（S15），但**绝不出绿线**（R112）。

    回退候选来自算子类型过滤 + 词法排序，没有形状与序列依据。s_retr=1.0 与
    s_judge=1.0 把 confidence 推到 0.8429（≥0.75，且 s_struct=0.60 ≥ 0.50，
    纯算分本来是绿的）——封的是 tier，不是分数：分数照实写，绿线不许发。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _YesBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    embedder = _SameVectorsBackend()
    monkeypatch.setattr(embed_module, "get_llm", lambda: embedder)
    monkeypatch.setattr("papertrace.spine.struct_signal", _no_isomorphism)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    assert len(doc["anchors"]) == 4, "四项都该有回退候选，否则测的不是回退路径"
    assert doc["unresolved"] == []
    # R117：回退路径只写 judge 确认的那**一个**节点 id。期望值用产品自己的候选生成器
    # 算出来（不手捏 anchor、不硬编码节点 id）：假后端对每个候选都答 yes，所以
    # judge 确认的是该 term 组里第一个**还没被前序项认领**的节点（R135/R147）。
    expected_first: dict[str, str] = {}
    for unit in ingest_paper(PAPER).units:
        unit_terms = split_formula(unit.latex)
        if not unit_terms:
            continue
        signal = _no_isomorphism(doc["nodes"], unit_terms, None)
        grouped, is_fallback = pairs_or_fallback(signal, unit_terms, doc["nodes"])
        assert is_fallback, "这条测试必须走在退路径上"
        claimed: set[str] = set()  # 认领状态按公式单元重建；跨单元允许共享（R136）
        for term in unit_terms:
            group = [nid for nid in grouped.get(term.index) or [] if nid not in claimed]
            assert group, "每个公式项都该有未被认领的回退候选"
            expected_first["%s-t%s" % (unit.unit_id, term.index)] = group[0]
            claimed.add(group[0])
    node_ids = {str(n["id"]) for n in doc["nodes"]}
    for anchor in doc["anchors"]:
        assert anchor["tier"] == "yellow", "R112：回退产的线最高到黄"
        assert anchor["confidence"] >= 0.75, "分数本身够绿，被降的是 tier"
        assert "最高黄线" in anchor["evidence"], "降级理由必须写在用户看得见的地方"
        term_id = "%s-t%s" % (anchor["paper_unit_id"], anchor["formula_term_index"])
        code_range = str(anchor["code_expr_range"])
        # 原来是 assert ":" not in code_expr_range——节点 id 里本来就没有冒号，
        # 首尾区间 root/@037..root/@071 同样不含冒号，那条断言是空转的（D-M-2）。
        assert code_range.count(RANGE_SEP) == 0, (
            "R117：回退路径只写一个节点 id，不是首尾区间：%r" % code_range)
        assert code_range in node_ids, "R117：写的必须是 trace 里真实存在的节点 id：%r" % code_range
        assert code_range == expected_first[term_id], (
            "R117：回退路径写的必须是 judge 确认的那一个节点：%r != %r"
            % (code_range, expected_first[term_id]))
        assert anchor["code_expr_range"].startswith("root/@")
        assert set(anchor["signals"]) == {"s_retr", "s_judge", "s_struct"}
    # 两条注入都被真的走到：embedding 跑了（否则测的是 offline 归零），judge 也真的问了
    assert embedder.calls == 2
    assert backend.calls >= 1


def test_offline_structural_miss_stays_honestly_empty(monkeypatch):
    """offline + 结构不命中：回退候选拿不到 yes，四项都不许出 anchor，且原因自报回退。"""
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
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
    expected = "置信度 %.4f" % confidence(0.0, 0.0, 0.6)
    for entry in doc["unresolved"]:
        assert "回退候选没拿到判断题 yes" in entry["reason"], "别让人以为结构对上了"
        assert "结构同构未命中" in entry["reason"]
        assert "s_struct=0.60" in entry["reason"]
        assert expected in entry["reason"]


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

# ------------------------------------------- S9 fix round 1：I-1（逐项 s_retr）/ I-2（meta.model）


class _PerTermVectorsBackend:
    """逐项正交向量的假后端：兄弟项命中 1.0 时，本项仍可能是 0.0。

    形状照抄控制器复现 I-1 的探针（output/controller-probes/s9_i1_verify2.py）：
    论文项 t0/t1/t2/t3 各占一个正交方向；算子节点只有 matmul / softmax 与对应
    论文项同向，其余一律零向量（cosine 对零向量返回 0.0）。上一版自错正是
    「给所有非 QK 项与所有非 matmul 算子同一个向量」，结果全员 cosine 1.0，
    根本构造不出「兄弟项命中、本项零检索」。
    """

    name = "fake-per-term"

    def __init__(self) -> None:
        self.chat_calls = 0
        self.embed_calls = 0

    def chat(self, prompt, *, system=None):
        self.chat_calls += 1
        return ChatResult(text="Verdict: yes\nEvidence: 第 68 行的矩乘",
                          model="fake-per-term", backend="fake-per-term")

    def embed(self, texts):
        self.embed_calls += 1
        return [_per_term_vector(t) for t in texts]


def _per_term_vector(text: str) -> list[float]:
    r"""逐项正交：t0 QK^{T} / t1 \sqrt{d_k} / t2 \mathrm{softmax} / t3 V。"""
    lowered = text.lower()
    if "qk" in lowered:
        return [1.0, 0.0, 0.0, 0.0]
    if "sqrt" in lowered:
        return [0.0, 1.0, 0.0, 0.0]
    if "softmax" in lowered:
        return [0.0, 0.0, 1.0, 0.0]
    if text.strip() == "V":
        return [0.0, 0.0, 0.0, 1.0]
    if "matmul" in lowered:
        return [1.0, 0.0, 0.0, 0.0]
    return [0.0, 0.0, 0.0, 0.0]


def test_retrieval_is_scored_per_formula_term(monkeypatch):
    """I-1：s_retr 必须逐项算——兄弟项命中不能把零检索的项抬上绿线。

    控制器复现用的可达路径：s_struct=0.8、s_judge=1、t0/t2 逐项 s_retr=1.0、
    t1/t3 逐项 s_retr=0.0。应有的结果是 t0/t2 green c=0.862949、t1/t3 yellow
    c=0.654753；注水版会把 4 条全写成 green c=0.862949（被注水 2/4 条，
    而 validate_trace 仍 errors=None——schema 只校验 signals 自洽，
    抓不到「自洽但来源错」）。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _PerTermVectorsBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    monkeypatch.setattr(embed_module, "get_llm", lambda: backend)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    # 注入的假后端必须真的被走到（否则测的是 offline 兜底路径，结论是假的）
    assert backend.chat_calls >= 1
    assert backend.embed_calls >= 1
    by_index = {a["formula_term_index"]: a for a in doc["anchors"]}
    assert set(by_index) == {0, 1, 2, 3}
    for index in (0, 2):  # 逐项检索真命中的两项：保持绿线，证明不是把所有人压黄
        anchor = by_index[index]
        assert anchor["signals"]["s_retr"] == 1.0
        assert anchor["tier"] == "green", index
        assert anchor["confidence"] == pytest.approx(0.862949, abs=1e-6)
    for index in (1, 3):  # 逐项检索零命中的两项：必须掉回黄线
        anchor = by_index[index]
        assert anchor["signals"]["s_retr"] == 0.0, index
        assert anchor["tier"] == "yellow", index
        assert 0.45 <= anchor["confidence"] < 0.75
        assert anchor["confidence"] == pytest.approx(0.654753, abs=1e-6)
    validate_trace(doc)


def test_missing_forward_key_does_not_inherit_unit_scalar(monkeypatch):
    """I-1：forward 缺该 term_id 键 → s_retr=0.0，绝不回落到单元级标量。

    构造一个 retrieval dict：单元级 s_retr=1.0（S6 契约：forward+backward 全条目
    最大值），而 forward 只给 t0 一项且分数 0.0，其余三个 term_id 的键整个缺失。
    若实现仍读单元级标量，4 条会全成 green c=0.862949。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _YesBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)

    def _unit_scalar_only(code_units, paper_terms, k=5):
        return {"forward": {"S3.2-eq-attn-t0": [{"code_id": "root/@037", "score": 0.0}]},
                "backward": {}, "s_retr": 1.0, "conflicts": [], "reason": None}

    monkeypatch.setattr("papertrace.spine.retrieve_bidirectional", _unit_scalar_only)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    assert backend.calls == 4  # 判定的桩确实被走到（t0 命中第一个 yes 就早退）
    for anchor in doc["anchors"]:
        assert anchor["signals"]["s_retr"] == 0.0
        assert anchor["tier"] == "yellow"
        assert anchor["confidence"] == pytest.approx(0.654753, abs=1e-6)
    validate_trace(doc)


def test_ingest_failure_records_backend_meta_not_default_zero(monkeypatch):
    """I-2：ingest 失败早退也要写 meta.model，不能留 minimal_trace 的 prompt_version='0'。

    配了 openai 而 --paper 路径错时，旧行为让 trace.json 谎称 offline 后端——
    与 R76 判过的「解释与实际配置矛盾」同族。
    """
    monkeypatch.setenv("PAPERTRACE_LLM_BACKEND", "openai:deepseek")
    monkeypatch.setenv("PAPERTRACE_LLM", "deepseek-chat")
    missing = str(Path(PAPER).with_name("no-such-paper-for-i2.tex"))
    doc, model = _fresh_doc()
    returned = attach_paper(doc, missing, model)
    assert returned is doc
    entries = [u for u in doc["unresolved"] if u["kind"] == "paper_unit"]
    assert entries and entries[0]["ref"] == missing
    model_meta = doc["meta"]["model"]
    assert model_meta["name"] == "openai"
    assert model_meta["prompt_version"] == JUDGE_PROMPT_VERSION
    assert model_meta["prompt_version"] != "0"
    assert doc["meta"]["paper"]["ingest_mode"] == "none"
    validate_trace(doc)
    assert len(doc["nodes"]) == GC8_NODES


# ------------------------------------------- S20 认领唯一性 / S21 路径便携化（R135–R151）


def test_two_terms_never_claim_the_same_node(monkeypatch):
    """R135：同单元内两个 kind 相同的项绝不连到同一个算子。

    回退路径上 QK^T（t0）与 V（t3）的候选列表**逐字相同**（candidates.py 只按
    kind + 词法排序给候选，不做跨项唯一性）。认领后 t0 拿走候选组第一个，
    t3 只能拿下一个——这正是上一片演示暴露的「两项都指 root/@037」不许再发生。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _YesBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    monkeypatch.setattr("papertrace.spine.struct_signal", _no_isomorphism)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    assert backend.calls >= 1, "假后端必须真的被问到，否则测的是 offline 兜底"
    by_index = {a["formula_term_index"]: str(a["code_expr_range"]) for a in doc["anchors"]}
    assert set(by_index) == {0, 1, 2, 3}, by_index
    assert by_index[0] == "root/@037", by_index
    assert by_index[3] == "root/@045", "t3 的候选组被 t0 占掉第一个后应取下一个"
    assert by_index[0] != by_index[3]
    assert len(set(by_index.values())) == len(by_index), "一个算子至多归属一个公式项"


def test_exhausted_candidates_report_claim_not_absence(monkeypatch):
    """R137/R146：候选全被前序项认领时，理由必须说「认领」，不能说「没候选」。

    两条 matmul 项都被指到**同一个**节点 root/@037：t0 先问并认领它，t3 的
    可用候选为空。这时若走 _record_unresolved 会被包成「置信度 < 0.45」，
    用户读到的是「分数不够」，真相是「候选被占了」——两件事结论完全不同。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _YesBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    monkeypatch.setattr(
        "papertrace.spine.struct_signal",
        lambda nodes, terms, config: StructSignal(0.6, [], ["结构同构未命中"], []),
    )
    monkeypatch.setattr(
        "papertrace.spine.pairs_or_fallback",
        lambda signal, terms, nodes: ({0: ["root/@037"], 3: ["root/@037"]}, True),
    )
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    assert backend.calls == 1, "只该为 t0 问一次；t3 没有可用候选就不许再问"
    claimed = [a for a in doc["anchors"] if a["formula_term_index"] == 0]
    assert len(claimed) == 1 and claimed[0]["code_expr_range"] == "root/@037"
    reasons = {u["ref"]: u["reason"] for u in doc["unresolved"]}
    t3 = reasons["S3.2-eq-attn-t3"]
    assert t3 == CLAIMED_REASON, t3
    assert "认领" in t3
    assert "置信度" not in t3, "别把「候选被占」写成「分数不够」"


def test_structural_duplicate_is_a_build_error(monkeypatch):
    """R144：结构路径（fallback=False）出现重复节点是**契约错误**，响亮报错。

    回退路径的跨项重复是正常输入（R144 明确只守结构路径），所以这里把
    pairs_or_fallback 钉成非回退 + 重复候选，单独验证守门本身。
    """
    monkeypatch.setattr(
        "papertrace.spine.pairs_or_fallback",
        lambda signal, terms, nodes: ({0: ["root/@037"], 1: ["root/@037"]}, False),
    )
    doc, model = _fresh_doc()
    with pytest.raises(BuildError, match="一个算子只归一个公式项"):
        attach_paper(doc, PAPER, model)


def test_cli_duplicate_claim_is_reported_not_a_traceback(monkeypatch, capsys):
    """R148：契约错误走到 CLI 时是一行人话 + exit 2，不是裸 traceback。"""
    from papertrace import cli

    def _boom(doc, paper_src, model):
        raise BuildError("结构配对出现重复节点，一个算子只归一个公式项：['root/@037']")

    monkeypatch.setattr(cli, "attach_paper", _boom)
    out_dir = scratch_dir("s20-cli-dup")
    code = cli.main([
        "build", "--repo", FIXTURE, "--paper", PAPER, "--out", str(out_dir), "--force",
    ])
    captured = capsys.readouterr()
    assert code == 2, captured.out + captured.err
    assert "一个算子只归一个公式项" in captured.err
    assert "Traceback" not in captured.err
    assert not (out_dir / "trace.json").is_file(), "契约错误不写 trace"


def test_cli_trace_has_no_drive_letters(monkeypatch):
    """GC14/R139-R141：写盘的 trace.json 里不许有本机绝对路径。

    四处路径字段（meta.repo.url / meta.paper.source / nodes[*].loc /
    symbols.code[*].defined_at）在 dump 前统一相对化；盘符与反斜杠是
    「把发件人机器的目录结构送出去」的直接证据。cwd 钉在仓库根（R150）。
    """
    import re

    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    out_dir = scratch_dir("s21-no-drive")
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.pop("PAPERTRACE_LLM_BACKEND", None)
    env.pop("PAPERTRACE_LLM", None)
    result = subprocess.run(
        [sys.executable, "-m", "papertrace", "build", "--repo",
         "tests/fixtures/nanogpt", "--paper",
         "tests/fixtures/papers/vaswani2017/attention.tex",
         "--out", str(out_dir), "--force"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(root),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    raw = (out_dir / "trace.json").read_text(encoding="utf-8")
    assert re.findall(r"[A-Za-z]:[\\/]", raw) == [], "trace.json 里出现了盘符"
    doc = load_trace(out_dir / "trace.json")
    assert doc["meta"]["paper"]["source"] == "tests/fixtures/papers/vaswani2017/attention.tex"
    assert doc["meta"]["repo"]["url"] == "tests/fixtures/nanogpt"
    locs = {n["loc"] for n in doc["nodes"]}
    assert "tests/fixtures/nanogpt/model.py:142" in locs, sorted(locs)[:5]
    defined = {s["defined_at"] for s in doc["symbols"]["code"]}
    assert defined and all(not Path(d.split(":")[0]).is_absolute() for d in defined), defined
    # 反斜杠只在 JSON 转义里合法（论文标题里有引号）；路径字段本身必须是 / 分隔
    for value in [doc["meta"]["repo"]["url"], doc["meta"]["paper"]["source"]] + sorted(locs) + sorted(defined):
        assert "\\" not in value, value
    validate_trace(doc)


def test_cli_says_nothing_when_every_path_is_relative(monkeypatch):
    """F1/R155 的反向对照：cwd 在仓库根时全部相对化成功，stderr 不许喊狼来了。"""
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    out_dir = scratch_dir("s21-in-root")
    result = _run_cli(
        "build", "--repo", FIXTURE, "--paper", PAPER, "--out", str(out_dir), "--force",
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "条路径不在构建目录" not in result.stderr, result.stderr


def test_cli_warns_when_paths_stay_absolute(monkeypatch):
    """F1/R155：cwd 不在被测仓库之下时，仍然绝对的路径必须当面提示。

    GC14 授权这些路径原样保留（不硬造 '..\\..'），但**静默保留**就是把发件人
    机器的目录结构悄悄送出去——用户以为自己分享了一份便携 trace。
    """
    import re

    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    outside = scratch_dir("s21-outside")
    out_dir = scratch_dir("s21-outside-out")
    result = _run_cli(
        "build", "--repo", FIXTURE, "--paper", PAPER, "--out", str(out_dir), "--force",
        cwd=str(outside),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r"(\d+) 条路径不在构建目录", result.stderr)
    assert match, "R155：仓外构建必须提示仍然绝对的路径，stderr 实际是：%r" % result.stderr
    assert int(match.group(1)) > 0, result.stderr
    assert "GC14" in result.stderr, "提示必须说明这是 GC14 授权的原样保留：%r" % result.stderr
    # GC14：原样保留就意味着 trace.json 里真的有盘符，两头必须对得上
    raw = (out_dir / "trace.json").read_text(encoding="utf-8")
    assert re.search(r"[A-Za-z]:[\\/]", raw), "仓外构建时盘符按 GC14 原样保留"
    # 退出码与 stdout 不许被这条提示动到（F1 只要提示，不要改变契约）
    assert "已写出" in result.stdout


def test_structural_path_anchors_are_the_golden_four(monkeypatch):
    """GC16：同一公式单元内，任意两条 anchor 的 code_expr_range 不共享节点。

    走**结构路径**（不替换 struct_signal）：四项同构命中、judge 全答 yes，
    anchor 的 code_expr_range 是 judge 确认的那一个节点 id，四条必须互不相同。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _YesBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    assert backend.calls >= 1
    ranges = [str(a["code_expr_range"]) for a in doc["anchors"]]
    assert len(ranges) == 4, ranges
    assert len(set(ranges)) == len(ranges), "两条 anchor 认领了同一个算子：%r" % (ranges,)
    assert ranges == ["root/@037", "root/@038", "root/@043", "root/@045"], ranges
    validate_trace(doc)


def test_fallback_without_yes_never_spans_a_range(monkeypatch):
    """R158 / 集成 I-1：回退路径上判断题全答 no，range 也一律单节点。

    这条路上 anchor **照样出**（s_retr=1.0、s_judge=0.0、s_struct=0.8 →
    c=sigmoid(4·(0.30−0+0.16−0.5))=0.460085 ≥ 0.45，黄线），而 judge 确认的
    节点是 None。实现在这里写的是 first..last（root/@037..root/@071），
    把三个没人审过的节点画成一条线——GC16 的「不共享节点」在字符串层面
    看不出来，但节点集合上两项会重叠，所以必须钉成单节点。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    backend = _NoWithEmbeddingBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    monkeypatch.setattr(embed_module, "get_llm", lambda: backend)

    def _no_isomorphism_scored(nodes, terms, config):
        # 与 _no_isomorphism 同型，只把 s_struct 钉在 0.80：c=0.460085，压线黄线
        return StructSignal(0.8, [], ["算子序列与公式项顺序同构：没有任何算子组能匹配"], [])

    monkeypatch.setattr("papertrace.spine.struct_signal", _no_isomorphism_scored)
    doc, model = _fresh_doc()
    attach_paper(doc, PAPER, model)
    # 两路注入都必须真的被走到，否则测的是 offline 归零
    assert backend.calls >= 1, "假后端必须真的被问到，否则测的是 offline 兜底"
    assert backend.embed_calls >= 1, "embedding 桩必须真的被走到，否则 s_retr=0 到不了黄线"
    assert len(doc["anchors"]) >= 2, "至少两条 anchor 才谈得上『不共享节点』"
    for anchor in doc["anchors"]:
        assert anchor["tier"] == "yellow", "回退产的线最高到黄（R112）"
        assert anchor["confidence"] == pytest.approx(0.460085, abs=1e-6), anchor["confidence"]
        assert anchor["confidence"] == pytest.approx(confidence(1.0, 0.0, 0.8), abs=1e-12)
        code_range = str(anchor["code_expr_range"])
        assert code_range.count(RANGE_SEP) == 0, (
            "R158：回退路径一律单节点，不是首尾区间：%r" % code_range)
        assert code_range in {str(n["id"]) for n in doc["nodes"]}, code_range
    ranges = [str(a["code_expr_range"]) for a in doc["anchors"]]
    assert len(set(ranges)) == len(ranges), "两条 anchor 认领了同一个算子：%r" % (ranges,)
    validate_trace(doc)


#: F2/R136：两条公式的临时夹具（写进 scratch_dir，不动仓库里的 attention.tex）。
#: 同一个算式写两遍，两个单元各自拆出同样的四项，于是「同一个算子被两个单元
#: 各自认领」可以被正面断言——R136 说的是跨单元**允许**共享，不是状态共享。
TWO_UNIT_TEX = r"""% 两单元夹具：R136 跨单元共享（F2）。同一算式写两遍，两个单元各自认领。
% papertrace-id: s20-unit-a

\begin{equation}
\mathrm{Attention}(Q, K, V) = \mathrm{softmax}\left(\frac{QK^{T}}{\sqrt{d_k}}\right)V
\label{eq:attention}
\end{equation}

% papertrace-id: s20-unit-b

\begin{equation}
\mathrm{Attention}(Q, K, V) = \mathrm{softmax}\left(\frac{QK^{T}}{\sqrt{d_k}}\right)V
\label{eq:attention-two}
\end{equation}
"""


def test_two_units_may_share_a_node(monkeypatch):
    """R136：认领状态按公式单元重建，跨单元允许共享同一个算子节点。

    这条语义今天（claims 评审 I1）的全部保障是 spine.py:115 的一行注释加
    candidates.py 的 docstring。把 `claimed` 提到单元循环外做「全局去重」是
    一次很自然的重构：第二个单元的项会收到文案写着「同一公式单元内」的
    CLAIMED_REASON，用户读到一句结构上不可能为真的解释，而零条测试会红。
    本测试就是那条网。

    两个单元用**同一个算式**，四项的候选节点因此完全相同；跨单元允许共享
    就意味着两个单元能各自认领 root/@037 等同一批节点。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    root = Path(__file__).resolve().parents[1]
    paper_dir = scratch_dir("s20-two-units")
    paper = paper_dir / "two_units.tex"
    paper.write_text(TWO_UNIT_TEX, encoding="utf-8")
    # ① 真 CLI（cwd 钉在仓库根，R150）：两个单元都得 ingest 进来。offline 下
    #    零 anchor——这条断言同时钉住「后面的注入确实有效」，否则分不清是
    #    「跨单元共享」还是「压根没出线」。
    out_dir = scratch_dir("s20-two-units-out")
    result = _run_cli(
        "build", "--repo", FIXTURE, "--paper", str(paper), "--out", str(out_dir),
        "--force", cwd=str(root),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    offline = load_trace(out_dir / "trace.json")
    assert offline["meta"]["paper"]["unit_count"] == 2, "夹具必须是两个公式单元"
    assert offline["anchors"] == [], "offline 下不该出线，否则后面的注入没有区分力"
    # ② 注入假 yes 后端（单实例跨调用）：两个单元各自认领
    backend = _YesBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    doc, model = _fresh_doc()
    attach_paper(doc, str(paper), model)
    assert backend.calls >= 1, "假后端必须真的被问到，否则测的是 offline 兜底"
    anchors = doc["anchors"]
    assert len(anchors) >= 2, "两个单元至少各出一条线：%d" % len(anchors)
    unit_ids = {a["paper_unit_id"] for a in anchors}
    assert len(unit_ids) == 2, "两个公式单元都要出线：%r" % (unit_ids,)
    # ③ 跨单元共享被允许：两个单元命中同一个 node id
    by_unit: dict[str, set[str]] = {}
    for anchor in anchors:
        by_unit.setdefault(anchor["paper_unit_id"], set()).add(
            str(anchor["code_expr_range"]))
    shared = set.intersection(*by_unit.values())
    assert shared, "R136：两个单元必须能共享同一个算子节点：%r" % (by_unit,)
    # ④ 跨单元共享不是「第二个单元被第一个单元占光」：CLAIMED_REASON 一个都不许有
    reasons = {u["reason"] for u in doc["unresolved"]}
    assert CLAIMED_REASON not in reasons, (
        "跨单元不允许互斥；收到 CLAIMED_REASON 说明 claimed 被提到了单元外："
        + repr(sorted(reasons)))
    # ⑤ 反向对照：同单元独占仍然成立（一个算子至多归一个公式项）
    for unit_id, ranges in by_unit.items():
        terms = {a["formula_term_index"] for a in anchors
                 if a["paper_unit_id"] == unit_id}
        assert len(ranges) == len(terms), (
            "同一单元内一个算子至多归一个公式项：%s -> %r" % (unit_id, sorted(ranges)))
    validate_trace(doc)


def test_yellow_alternatives_exclude_claimed(monkeypatch):
    """R151：黄线备选必须过滤掉「本项候选」与「同单元其他项已认领」的节点。

    F5（控制器发现）：spine.py:166-172 这个过滤器今天**零测试**。offline 与
    DeepSeek（无 embeddings）下 retrieval.forward 是空表，alternatives 恒为
    []；控制器在「yes + 真 embeddings」下实测黄金夹具的自然数据，not in
    claimed 那一半也从来没被练到——四项的 embedding top-k 与四项的候选节点几乎
    不相交（t2 的 top5 第 2 名 @043 只被 not in available 挡下过）。删掉
    claimed 那一半，今天一条测试都不会红。本测试就是那条网。

    构造：自己喂结构 pairs，让 t0 认领的节点 X **同时**是 t1 forward top-k 的
    第一名。X 于是既是「同单元另一个公式项已经认领的算子」（claimed 过滤器该
    挡），又是「本项检索分数最高的候选」（不过滤就会当上备选第一名）——两个
    过滤器各管一半，删哪个都看得见。备选上限 ≤2 与「本项候选不当自己备选」
    （available 那一半）同场钉住。

    pairs 与期望值都不硬编码节点 id：向量由 sha256(text) 决定，而 text 里带
    loc（本机绝对路径），换一台机器 top-k 会变。期望值用产品自己的
    retrieve_bidirectional 现算，装配口径与 spine.py:105-110 逐字相同。
    """
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM", raising=False)
    from papertrace.align import retrieve as retrieve_module
    from papertrace.spine_claims import node_text

    backend = _YesWithBucketEmbeddingBackend()
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    monkeypatch.setattr(embed_module, "get_llm", lambda: backend)
    doc, model = _fresh_doc()
    # 期望值用产品自己的检索现算：同一份 doc、同一个假后端 → 与产品内部那次调用逐项相同
    unit = ingest_paper(PAPER).units[0]
    unit_terms = split_formula(unit.latex)
    assert len(unit_terms) >= 2, "夹具至少要拆出两项才谈得上跨项认领：%d" % len(unit_terms)
    code_units = [{"code_id": n["id"], "text": node_text(n)} for n in doc["nodes"] or []
                  if isinstance(n, dict) and n.get("level") == "op"
                  and n.get("kind") == "op" and n.get("id")]
    retrieval = retrieve_module.retrieve_bidirectional(code_units, [
        {"term_id": f"${unit.unit_id}-t{t.index}", "text": t.latex} for t in unit_terms])
    t1_top = [h["code_id"] for h in retrieval["forward"][f"${unit.unit_id}-t1"]]
    assert len(t1_top) >= 3, "top-k 至少三名才谈得上『过滤掉前两名』：%r" % (t1_top,)
    claimed_by_t0 = t1_top[0]  # X：t0 认领它，而它在 t1 的检索里排第一
    t1_candidate = t1_top[1]   # Y：t1 的结构候选（available 过滤器该挡的那一半）
    assert claimed_by_t0 != t1_candidate
    pairs = [(0, claimed_by_t0), (1, t1_candidate)]

    def _two_pairs(nodes, terms, config):
        # s_struct=0.40 < GREEN_STRUCT_MIN(0.50)：分数本身够绿，被门压成黄线
        # （R151 只长在黄线上，绿线没有备选）
        return StructSignal(0.4, [], ["结构同构命中前两项（测试自喂）"], pairs)

    monkeypatch.setattr("papertrace.spine.struct_signal", _two_pairs)
    attach_paper(doc, PAPER, model)
    # 两路注入都必须真的被走到，否则测的是 offline 兜底
    assert backend.calls >= 1, "假后端必须真的被问到，否则测的是 offline 兜底"
    assert backend.embed_calls >= 1, "embedding 桩必须真的被走到，否则 forward 是空表"
    anchors = [a for a in doc["anchors"] if a["paper_unit_id"] == unit.unit_id]
    assert len(anchors) == 2, "只喂了两项 pairs，就该只出两条 anchor：%d" % len(anchors)
    t1_anchor = [a for a in anchors if a["formula_term_index"] == 1][0]
    assert t1_anchor["tier"] == "yellow", "R151 只长在黄线上：%r" % t1_anchor["tier"]
    alternatives = [a["code_id"] for a in t1_anchor["alternatives"]]
    # ① claimed 过滤器：t0 已认领的节点不许出现在 t1 的备选里（R151 本体）
    assert claimed_by_t0 not in alternatives, (
        "R151：%r 已被同一单元的 t0 认领，却出现在 t1 的黄线备选里：%r"
        % (claimed_by_t0, alternatives))
    # ② available 过滤器：本项自己的候选也不该当自己的备选
    assert t1_candidate not in alternatives, (
        "本项候选 %r 不该出现在自己的备选里：%r" % (t1_candidate, alternatives))
    # ③ 期望值现算：top-k 扣掉上面两类，再按 ALTERNATIVE_LIMIT 截断
    expected = [c for c in t1_top if c not in {claimed_by_t0, t1_candidate}][:ALTERNATIVE_LIMIT]
    assert alternatives == expected, (
        "备选必须与产品自己的 top-k 一致：%r != %r" % (alternatives, expected))
    assert len(alternatives) <= ALTERNATIVE_LIMIT, "备选条数上限 %d" % ALTERNATIVE_LIMIT
    assert alternatives, "备选为空等于什么都没过滤，这条测试是空转的"
    # ④ 有牙：去掉 claimed 过滤器后的备选会和实测不同，否则 ① 是空转断言
    without_claim = [c for c in t1_top if c != t1_candidate][:ALTERNATIVE_LIMIT]
    assert without_claim != expected, (
        "claimed 过滤器没改变任何结果，① 不可能红：%r" % (without_claim,))
    validate_trace(doc)
