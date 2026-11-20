"""S15 候选生成器：按 kind 过滤 + 确定性词法排序，绝不编造对齐。

契约要点（brief 逐字权威，别传错参数）：
- 候选池只收 `level == "op"` 且 `kind == "op"` 的节点；18 个权重（kind=param）与
  1 个输入（kind=input）永不进候选。
- 资格 = `node["op"] in KIND_TO_OPS.get(term.kind, ())`；未知 kind → 零候选 + 一条
  miss，绝不 KeyError。
- 排序 = `lexical_rank(term.latex, node)` 降序，同分按 `node["id"]` 升序——两个实现者
  必须产出同一份 trace.json。
- 预算按 `term.index` 升序分配，与 terms 入参顺序无关；被截断的 term 只记一条 miss。
- 生成器本身不做跨 term 唯一性约束：term0（QK^{T}, matmul）与 term3（V, matmul）
  候选集相同是正确行为（生成器只按 kind + 词法排序给候选）；「一个算子至多归属
  一个公式项」由 papertrace/spine/claims.py 在编排层保证（R135）。
- hits/misses 只是给人看的中文短句，spine 不消费（spine 只消费 pairs）。
"""
from tests.common import ROOT

import pathlib

import pytest

pytest.importorskip("torch", reason="真实夹具要实例化模型，CPU 版 torch 即可")

from papertrace.align.candidates import Candidates, candidate_pairs, lexical_rank  # noqa: E402
from papertrace.align.struct_signal import KIND_TO_OPS  # noqa: E402
from papertrace.build.trace import build_trace  # noqa: E402
from papertrace.ingest.paper import ingest_paper  # noqa: E402
from papertrace.parse_code.fx_trace import _ensure_export_cache  # noqa: E402
from papertrace.parse_paper import split_terms  # noqa: E402
from papertrace.parse_paper.split_terms import Term, split_formula  # noqa: E402

REPO = str(ROOT / "tests" / "fixtures" / "nanogpt")
ENTRY = "model:build_model"
TEX = ROOT / "tests" / "fixtures" / "papers" / "vaswani2017" / "attention.tex"


@pytest.fixture(scope="module")
def real():
    """真 trace + 真公式项（测试 2 与 9 必须用真实夹具，那是它们的意义）。"""
    _ensure_export_cache()
    nodes = build_trace(REPO, entry=ENTRY)["nodes"]
    terms = split_formula(ingest_paper(TEX).units[0].latex)
    assert [(t.index, t.kind) for t in terms] == [
        (0, "matmul"),
        (1, "scale"),
        (2, "norm"),
        (3, "matmul"),
    ]
    return nodes, terms


def _op(node_id, op, label=None, level="op", kind="op"):
    return {
        "id": node_id,
        "level": level,
        "kind": kind,
        "op": op,
        "label": label if label is not None else f"g.{op}",
        "parent_id": "g",
    }


def _assert_chinese_lines(cands):
    for line in list(cands.hits) + list(cands.misses):
        assert isinstance(line, str) and line.strip()
        assert any("\u4e00" <= ch <= "\u9fff" for ch in line)


def test_only_kind_compatible_operators_are_candidates(real):
    """资格判据双向承重：不合 kind 的算子、param/input 占位符都进不了 pairs。"""
    nodes, terms = real
    hand = [
        _op("hit", "matmul"),
        _op("wrong-op", "gelu"),
        _op("fake-weight", "matmul", kind="param"),
        _op("fake-input", "matmul", kind="input"),
        _op("module-level", "matmul", level="module", kind="op"),
    ]
    cands = candidate_pairs([Term(0, "QK^{T}", "matmul")], hand)
    assert isinstance(cands, Candidates)
    assert [nid for _, nid in cands.pairs] == ["hit"]
    _assert_chinese_lines(cands)

    by_id = {n["id"]: n for n in nodes}
    term_by_index = {t.index: t for t in terms}
    for index, node_id in candidate_pairs(terms, nodes).pairs:
        node = by_id[node_id]
        assert node["level"] == "op" and node["kind"] == "op"
        assert node["op"] in KIND_TO_OPS[term_by_index[index].kind]


def test_softmax_term_ranks_real_softmax_first(real):
    """真实夹具 term2（\\mathrm{softmax}, norm）：候选只有真 softmax，h.0 排前。"""
    nodes, terms = real
    cands = candidate_pairs(terms, nodes)
    by_id = {n["id"]: n for n in nodes}
    picked = [nid for i, nid in cands.pairs if i == 2]
    assert picked
    assert {by_id[nid]["op"] for nid in picked} == {"softmax"}
    softmax_ids = sorted(
        n["id"]
        for n in nodes
        if n.get("level") == "op" and n.get("kind") == "op" and n.get("op") == "softmax"
    )
    assert picked == softmax_ids[: len(picked)]
    assert lexical_rank(terms[2].latex, by_id[picked[0]]) > 0.0
    assert any("term 2" in h and "softmax" in h for h in cands.hits)


def test_matmul_terms_share_the_same_candidate_set(real):
    """诚实性：term0 与 term3 同为 matmul，生成器给出相同候选集；独占由 spine_claims 保证。"""
    nodes, terms = real
    cands = candidate_pairs(terms, nodes, per_term_limit=99, total_limit=999)
    s0 = {nid for i, nid in cands.pairs if i == 0}
    s3 = {nid for i, nid in cands.pairs if i == 3}
    expected = {
        n["id"]
        for n in nodes
        if n.get("level") == "op"
        and n.get("kind") == "op"
        and n.get("op") in KIND_TO_OPS["matmul"]
    }
    assert s0 == expected and s3 == expected
    assert len(s0) > 1


def test_ranking_is_deterministic_on_ties():
    """分数全 0 时按 node["id"] 升序；入参乱序不影响结果（两次调用一致）。"""
    nodes = [
        _op("n-c", "matmul", label="g.matmul"),
        _op("n-a", "matmul", label="g.matmul"),
        _op("n-b", "matmul", label="g.matmul"),
    ]
    term = Term(0, "\\alpha", "matmul")
    assert all(lexical_rank(term.latex, node) == 0.0 for node in nodes)
    first = candidate_pairs([term], nodes)
    second = candidate_pairs([term], list(reversed(nodes)))
    assert first.pairs == second.pairs == [(0, "n-a"), (0, "n-b"), (0, "n-c")]


def test_per_term_limit_truncates_and_records_one_miss():
    """per_term_limit=3 砍掉第 4、5 个候选，只记一条 miss（不是每条被砍候选一条）。"""
    nodes = [_op(f"m{i}", "matmul", label="g.matmul") for i in range(5)]
    cands = candidate_pairs([Term(0, "QK^{T}", "matmul")], nodes, per_term_limit=3, total_limit=12)
    assert [nid for _, nid in cands.pairs] == ["m0", "m1", "m2"]
    assert len(cands.hits) == 1
    assert len(cands.misses) == 1
    miss = cands.misses[0]
    assert "term 0" in miss and "5 个资格候选" in miss
    assert "按上限截断" in miss and "丢弃 2 个" in miss


def test_total_limit_truncates_by_term_index_order():
    """手工超预算：per_term=3/total=4，三个 term 各 3 候选，terms 乱序传入。"""
    nodes = (
        [_op(f"m{i}", "matmul", label="g.matmul") for i in range(3)]
        + [_op(f"s{i}", "mul", label="g.mul") for i in range(3)]
        + [_op(f"q{i}", "softmax", label="g.softmax") for i in range(3)]
    )
    terms = [
        Term(2, "\\mathrm{softmax}", "norm"),
        Term(0, "QK^{T}", "matmul"),
        Term(1, "\\sqrt{d_k}", "scale"),
    ]
    cands = candidate_pairs(terms, nodes, per_term_limit=3, total_limit=4)
    assert [i for i, _ in cands.pairs] == [0, 0, 0, 1]
    assert [nid for _, nid in cands.pairs] == ["m0", "m1", "m2", "s0"]
    assert len(cands.hits) == 3
    trunc = [m for m in cands.misses if "截断" in m]
    assert len(trunc) == 2
    assert any("term 1" in m and "丢弃 2 个" in m for m in trunc)
    assert any("term 2" in m and "丢弃 3 个" in m for m in trunc)


def test_unknown_kind_yields_no_candidates():
    """伪造 kind：.get 兜底成零候选 + 一条 miss，绝不 KeyError。"""
    cands = candidate_pairs([Term(0, "x", "frobnicate")], [_op("m0", "matmul")])
    assert cands.pairs == []
    assert len(cands.misses) == 1
    assert "frobnicate" in cands.misses[0] and "term 0" in cands.misses[0]
    _assert_chinese_lines(cands)


def test_zero_candidate_miss_distinguishes_unknown_kind_from_missing_operator(real):
    """A-Minor-1：零候选有两种成因，文案必须分开说，不许一句「映射里没有」蒙过去。"""
    nodes, terms = real
    # 成因②：kind 在冻结映射里（transpose → transpose），但当前 trace 没有这类算子节点。
    # 拿真实 trace 的 nodes 子集（剔掉 transpose）来造，不手捏假 trace。
    assert any(n.get("op") == "transpose" for n in nodes), "夹具里得有 transpose，否则测不到成因②"
    no_transpose = [n for n in nodes if n.get("op") != "transpose"]
    assert not any(n.get("op") == "transpose" for n in no_transpose)
    cands = candidate_pairs([Term(7, "X^{T}", "transpose")], no_transpose)
    assert cands.pairs == []
    assert len(cands.misses) == 1
    miss = cands.misses[0]
    assert "term 7" in miss and "transpose" in miss
    assert "冻结映射里对应算子" in miss, "必须说明这个 kind 在映射里是有对应算子的"
    assert "没有" in miss and "算子节点" in miss, "必须说清是当前 trace 缺这类算子节点"
    _assert_chinese_lines(cands)

    # 成因①：kind 根本不在冻结映射里（KIND_TO_OPS 的键里没有 frobnicate）。
    unknown = candidate_pairs([Term(0, "x", "frobnicate")], nodes)
    assert unknown.pairs == []
    assert len(unknown.misses) == 1
    assert "frobnicate" in unknown.misses[0] and "term 0" in unknown.misses[0]
    assert "不在冻结" in unknown.misses[0], "成因①必须说 kind 不在映射里"
    assert "算子节点" not in unknown.misses[0], "成因①不该把话头拐到 trace 缺节点上"
    _assert_chinese_lines(unknown)


def test_every_split_kind_has_an_operator_mapping():
    """KINDS 与 KIND_TO_OPS 名单同步：新 kind 不加映射就会零候选。"""
    assert set(split_terms.KINDS) <= set(KIND_TO_OPS)


def test_weight_and_input_placeholders_are_never_candidates(real):
    """真实 trace 的 18 个 param + 1 个 input 一个都不许出现在候选里。"""
    nodes, terms = real
    placeholders = [n for n in nodes if n.get("kind") in ("param", "input")]
    assert len(placeholders) == 19
    assert sum(n.get("kind") == "param" for n in placeholders) == 18
    assert all(n.get("op") == "placeholder" for n in placeholders)
    cands = candidate_pairs(terms, nodes, per_term_limit=99, total_limit=999)
    used = {nid for _, nid in cands.pairs}
    assert used
    assert used.isdisjoint({n["id"] for n in placeholders})


def test_empty_inputs_yield_empty_pairs_with_reason():
    """空 terms / 空 nodes / 全 kind 不命中：pairs 空 + misses 写清原因，绝不瞎凑。"""
    nodes = [_op("m0", "matmul")]
    terms = [Term(0, "QK^{T}", "matmul")]
    for cands in (
        candidate_pairs([], []),
        candidate_pairs([], nodes),
        candidate_pairs(terms, []),
        candidate_pairs([Term(0, "x", "frobnicate")], []),
    ):
        assert cands.pairs == []
        assert cands.misses
        _assert_chinese_lines(cands)
