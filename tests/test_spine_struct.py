"""S5：结构信号 s_struct（确定性，offline 也算得出来）+ 同构候选对 pairs。

契约要点（控制器裁决，别传错参数）：
- `struct_signal(nodes, terms, config)` 的 nodes 是 **trace dict 的 nodes**（不是
  算子子集），terms 是 S3 的 list[Term]，config 是实例化后的 mod.config。
- R23：本切片没有论文正文、也没有论文声明的形状，所以「N 层」与「shape 冲突」
  两条**不触发也不扣分**，只进 misses；双向检索那条 offline 无检索结果，同样只进
  misses。绝不发明论文侧证据凑分。本切片上限 0.5+0.1+0.2=0.8，仍过绿线门 0.5。
- R24：「超参名在 config 出现」读作**代码侧**超参名 n_layer/n_head/n_embd/block_size，
  四个全在才 +0.1，只加一次。
- R25/R25a：同构判定按 parent_id 分组、组内做贪心子序列匹配；`pairs` 取 nodes
  顺序里**第一个**匹配的组，代码侧多出的算子允许被跳过（因果掩码 masked_fill
  就夹在中间）。L2 起 `StructSignal.groups` 报出**全部**命中组（两层都同构时
  报两个），`pairs` 与 `score` 仍只认首组、只加一次 +0.2（首匹配语义不变）。
- R37：结构路径上 pairs 是 judge 的唯一候选来源；同构不命中 → pairs == []。
  S15 之后由 kind 过滤 + 词法排序的回退候选接管（papertrace/spine_fallback.py），
  那条路的 tier 上限锁 yellow（R112）——结构没对上账，就不发绿线。
- R38：hits/misses 是给人看的短中文句子，供测试与调试；spine 只消费 score 与 pairs，
  它们不进 HTML、也不进 anchor.evidence。
- loc 是 file:line（M1b 后）或模块路径（回落时）；判据只看算子名与组内顺序，配对回传 node_id。
"""

import pathlib

import pytest

pytest.importorskip("torch", reason="本切片要真实例化模型，CPU 版 torch 即可")

from papertrace.align import struct_signal as struct_signal_module  # noqa: E402
from papertrace.align.struct_signal import StructSignal, struct_signal  # noqa: E402
from papertrace.build_trace import build_trace, load_entry  # noqa: E402
from papertrace.ingest.paper import ingest_paper  # noqa: E402
from papertrace.parse_paper.split_terms import Term, split_formula  # noqa: E402

HERE = pathlib.Path(__file__).resolve()
REPO = str(HERE.parents[1] / "tests" / "fixtures" / "nanogpt")
ENTRY = "model:build_model"
TEX = HERE.parents[1] / "tests" / "fixtures" / "papers" / "vaswani2017" / "attention.tex"

#: R25 实测：h.0.attn 组内 22 个真算子（夹具 n_layer=2，h.1.attn 完全同构）。
ATTN_GROUP = "root/transformer.h.0.attn"
ATTN_OPS = [
    "split", "getitem", "getitem", "getitem", "view", "transpose", "view",
    "transpose", "view", "transpose", "transpose", "matmul", "mul", "slice",
    "slice", "eq", "masked_fill", "softmax", "matmul", "transpose",
    "contiguous", "view",
]

#: 四项的 kind → 期望命中的算子名（测试侧独立写死，不 import 产品里的映射表）。
EXPECTED_OP_FOR_INDEX = {0: "matmul", 1: "mul", 2: "softmax", 3: "matmul"}

#: 贪心首匹配的确定性落点（h.0.attn 组内的 node_id）。
EXPECTED_NODE_IDS = ["root/@037", "root/@038", "root/@043", "root/@045"]


@pytest.fixture(scope="module")
def fixture():
    """真模型 + 真 trace + 真公式项（夹具三件套，一个 build 全程复用）。"""
    mod = load_entry(REPO, entry=ENTRY)
    doc = build_trace(REPO, entry=ENTRY)
    units = ingest_paper(TEX).units
    assert len(units) == 1
    terms = split_formula(units[0].latex)
    assert [(t.index, t.kind) for t in terms] == [
        (0, "matmul"),
        (1, "scale"),
        (2, "norm"),
        (3, "matmul"),
    ]
    return mod, doc, terms


def test_attention_sequence_is_isomorphic(fixture):
    """+0.2 同构那条必须命中：四个项按序落到 h.0.attn 的算子序列上。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], terms, mod.config)
    assert isinstance(sig, StructSignal)
    assert any("同构" in h and "+0.2" in h for h in sig.hits)
    # 初值 0.5 + 超参 0.1 + 同构 0.2；另三条在本切片不可判定（R23）
    assert sig.score == pytest.approx(0.8)


def test_extra_mask_op_does_not_break_isomorphism(fixture):
    """RF：因果掩码夹在中间，同构判定必须允许代码侧多出算子。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], terms, mod.config)
    ops = _group_ops(doc)
    assert ops == ATTN_OPS  # 先证明夹具真的长这样，再证明匹配不受掩码影响
    by_id = {n["id"]: n["op"] for n in doc["nodes"]}
    assert [by_id[nid] for _, nid in sig.pairs] == ["matmul", "mul", "softmax", "matmul"]
    lo = ops.index("mul")
    hi = ops.index("softmax", lo)
    assert "masked_fill" in ops[lo:hi]  # 掩码就在两个命中算子之间，被跳过了


def test_wrong_order_is_not_isomorphic(fixture):
    """顺序打乱 → 同构不命中，pairs 为空，分数掉回 0.5+0.1。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], list(reversed(terms)), mod.config)
    assert not any("同构" in h for h in sig.hits)
    assert any("同构" in m for m in sig.misses)
    assert sig.pairs == []
    assert sig.score == pytest.approx(0.6)


def test_score_starts_at_half():
    """空 terms + 空 nodes：没有任何证据，分数就是初值 0.5。"""
    sig = struct_signal([], [], None)
    assert sig.score == pytest.approx(0.5)
    assert sig.pairs == []


def test_score_is_clamped(fixture, monkeypatch):
    """分数永远落在 [0,1]：confidence() 会拒收越界值。

    光断言「五组可达输入的分数在 [0,1] 内」是杀不死的：本切片可达区间只有
    [0.5, 0.8]（R23 让三条惩罚/加分常量零引用），把 clamp 删掉、写反甚至改成
    return 0.0 都照样绿。所以这里用 monkeypatch 把模块级权重顶出 [0,1]，
    让 clamp 真正承重：上界把 BASE_SCORE 顶到 1.5、把 BONUS_ISOMORPHIC 顶到
    2.0；下界把 BASE_SCORE 压到 -0.5——后者正是 M4 打开两条惩罚后的越界形态
    （0.5-0.4-0.3 = -0.2）。monkeypatch 的 setattr 测试结束自动还原。
    """
    mod, doc, terms = fixture

    # 可达区间断言（保留）：五组输入都不得越界。
    cases = [
        ([], [], None),
        (doc["nodes"], terms, mod.config),
        (doc["nodes"], list(reversed(terms)), mod.config),
        (doc["nodes"], [], None),
        (_fake_nodes(), _fake_terms(), None),
    ]
    for nodes, case_terms, config in cases:
        assert 0.0 <= struct_signal(nodes, case_terms, config).score <= 1.0

    base = struct_signal_module.BASE_SCORE
    bonus = struct_signal_module.BONUS_ISOMORPHIC

    # 上界①：初值 1.5（+0.1 超参 +0.2 同构 = 1.8）→ 被钳到 1.0。
    monkeypatch.setattr(struct_signal_module, "BASE_SCORE", 1.5)
    assert struct_signal(doc["nodes"], terms, mod.config).score == 1.0

    # 上界②：只把同构加分顶到 2.0（0.5+0.1+2.0 = 2.6）→ 仍被钳到 1.0。
    monkeypatch.setattr(struct_signal_module, "BASE_SCORE", base)
    monkeypatch.setattr(struct_signal_module, "BONUS_ISOMORPHIC", 2.0)
    assert struct_signal(doc["nodes"], terms, mod.config).score == 1.0

    # 下界：初值压到 -0.5（-0.5+0.1+0.2 = -0.2）→ 被钳到 0.0。
    monkeypatch.setattr(struct_signal_module, "BONUS_ISOMORPHIC", bonus)
    monkeypatch.setattr(struct_signal_module, "BASE_SCORE", -0.5)
    assert struct_signal(doc["nodes"], terms, mod.config).score == 0.0


def test_no_retrieval_means_rule_not_fired(fixture):
    """-0.3 双向检索那条在 misses 里，且**没有被扣分**（R23）。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], terms, mod.config)
    assert any("检索" in m for m in sig.misses)
    assert sig.score == pytest.approx(0.8)  # 没被扣掉 0.3


def test_hits_are_human_readable(fixture):
    """R38：每条 hit/miss 都是能进 evidence 的短中文句子，点名规则与原因。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], terms, mod.config)
    assert sig.hits
    for line in sig.hits + sig.misses:
        assert isinstance(line, str)
        assert line.strip()
        assert len(line) <= 80
        assert any("\u4e00" <= ch <= "\u9fff" for ch in line)  # 中文句子
        assert line not in ("R23", "R24", "R25")  # 不许是光秃秃的规则号
    assert any("超参" in h for h in sig.hits)
    assert any("同构" in h for h in sig.hits)
    # 三条不可判定的规则都在 misses 里说清了原因
    assert any("层数" in m for m in sig.misses)
    assert any("形状" in m for m in sig.misses)
    assert any("检索" in m for m in sig.misses)


def test_pairs_has_exactly_four_entries_for_vaswani(fixture):
    """R37：同构命中时 pairs 恰好四对，index 是 0..3，node_id 真在 nodes 里。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], terms, mod.config)
    assert len(sig.pairs) == 4
    assert [i for i, _ in sig.pairs] == [0, 1, 2, 3]
    by_id = {n["id"]: n for n in doc["nodes"]}
    for term, (index, node_id) in zip(terms, sig.pairs):
        assert index == term.index
        node = by_id[node_id]
        assert node["level"] == "op" and node["kind"] == "op"  # R25a：不是权重/输入
        assert node["op"] == EXPECTED_OP_FOR_INDEX[index]
        assert node["parent_id"] == ATTN_GROUP  # 首匹配组，不是别处
    # 确定性：四个落点固定（证明选的是 h.0.attn 而不是 h.1.attn）
    assert [node_id for _, node_id in sig.pairs] == EXPECTED_NODE_IDS


def test_no_isomorphism_means_no_pairs(fixture):
    """R37：同构不命中 → pairs == []，judge 拿不到瞎凑的候选。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], list(reversed(terms)), mod.config)
    assert sig.pairs == []


def test_hyperparam_rule_fires_once_for_fixture_config(fixture):
    """R24：四个超参名全在 config 上时 +0.1，且只加一次（空 terms 排掉同构分）。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], [], mod.config)
    assert any("超参" in h and "+0.1" in h for h in sig.hits)
    assert sig.score == pytest.approx(0.6)
    assert sig.pairs == []


def test_missing_hyperparam_does_not_fire(fixture):
    """R24：缺一个名字就不触发，原因写进 misses，不按名字数加分。"""
    mod, doc, terms = fixture

    class _Partial:
        n_layer = 2
        n_embd = 32
        block_size = 16

    sig = struct_signal(doc["nodes"], [], _Partial())
    assert not any("超参" in h for h in sig.hits)
    assert any("n_head" in m for m in sig.misses)
    assert sig.score == pytest.approx(0.5)


def test_exact_sequence_without_extra_ops_matches():
    """干净的四算子链也必须命中——证明判据不是恒真。"""
    sig = struct_signal(_fake_nodes(), _fake_terms(), None)
    assert [nid for _, nid in sig.pairs] == ["n0", "n1", "n2", "n3"]
    assert sig.score == pytest.approx(0.7)  # 0.5 + 同构 0.2（config 为 None）


def _group_ops(doc: dict) -> list[str]:
    """h.0.attn 组内**真算子**的 op 名（R25a：权重与 input 的 op 是 placeholder）。"""
    return [
        n["op"]
        for n in doc["nodes"]
        if n.get("parent_id") == ATTN_GROUP
        and n.get("level") == "op"
        and n.get("kind") == "op"
    ]


def _fake_nodes() -> list[dict]:
    """测试替身（Constraint 2：只准出现在 tests/ 下）：四个算子一条链。"""
    return [
        {"id": f"n{i}", "parent_id": "g", "level": "op", "kind": "op", "op": op}
        for i, op in enumerate(["matmul", "mul", "softmax", "matmul"])
    ]


def _fake_terms() -> list[Term]:
    return [
        Term(0, "QK^{T}", "matmul"),
        Term(1, "\\sqrt{d_k}", "scale"),
        Term(2, "\\mathrm{softmax}", "norm"),
        Term(3, "V", "matmul"),
    ]


# --- L2：报出全部同构组（B 方案逐层展开的候选来源）--------------------------


def test_every_attention_layer_is_reported(fixture):
    """B 方案：两层都同构时，groups 要如实给出两个组，不许只报首层。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], terms, mod.config)
    assert [m.group for m in sig.groups] == [
        "root/transformer.h.0.attn", "root/transformer.h.1.attn"]


def test_pairs_still_come_from_the_first_group(fixture):
    """pairs 是 S7 的候选来源，逐层展开不许改变它的语义（R25a 首匹配）。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], terms, mod.config)
    assert sig.groups[0].pairs == sig.pairs


def test_score_does_not_grow_with_more_layers(fixture):
    """两组同构也只加一次 +0.2：0.5+0.1+0.2=0.8，不许变成 1.0。"""
    mod, doc, terms = fixture
    assert struct_signal(doc["nodes"], terms, mod.config).score == pytest.approx(0.8)


def test_no_isomorphism_means_no_groups(fixture):
    """顺序打乱 → 一组都匹配不上，groups 为空（回退路径没有层可言）。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], list(reversed(terms)), mod.config)
    assert sig.groups == ()


def test_single_group_reports_exactly_one():
    """单组夹具：groups 恰好一组，且它就是 pairs 的来源。"""
    sig = struct_signal(_fake_nodes(), _fake_terms(), None)
    assert len(sig.groups) == 1
    assert [nid for _, nid in sig.groups[0].pairs] == ["n0", "n1", "n2", "n3"]
