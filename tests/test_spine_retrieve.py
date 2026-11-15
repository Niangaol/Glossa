"""S6：双向检索 + embed 接口（offline 诚实归零）。

契约要点（控制器裁决 R40–R45，原文照录在 task-S6-report.md）：
- R40：code_units / paper_terms 都是「稳定 id + 文本」的 dict 列表，由 S9 装配，
  本模块不碰 trace schema、不 import Term/PaperUnit：
    code_units = [{"code_id": str, "text": str}, ...]   # code_id 是 trace 节点 id
    paper_terms = [{"term_id": str, "text": str}, ...]  # term_id = f"{unit_id}-t{term.index}"
- R41：s_retr = forward 与 backward 两个 top-k 列表**所有条目**里的最大分数，clip 到
  [0,1]；两个列表都空 → 0.0。不是两个最大值取平均，也不是所有分数取平均
  （平均正是规格书禁止的分数注水）。
- R42：冲突只记录，不参与 s_retr，也绝不被平均掉（规格 Task 11：冲突不得把
  confidence 抬过 0.75）。
- R43：测试后端用 monkeypatch 换掉 embed.py 自己引用的 get_llm，不改 client.py。
- R44：embed_texts 只转调 get_llm().embed 并让 LLMUnavailable 原样上抛；
  retrieve_bidirectional 是唯一捕获点 → 归零 + 空表 + reason。
- R45：embed_texts 返回 list[list[float]]（S17），不许借第三方数组类型（Constraint 13）。
- 测试全程不联网：offline 走真 OfflineBackend，有向量走测试替身（Constraint 2）。
"""

import pathlib

import pytest

from papertrace.align import embed as embed_module
from papertrace.align.embed import embed_texts
from papertrace.align.retrieve import cosine, retrieve_bidirectional
from papertrace.align.score import confidence
from papertrace.constants import CONF_GREEN
from papertrace.exceptions import LLMUnavailable
from papertrace.llm.client import OfflineBackend, get_llm

REPO = pathlib.Path(__file__).resolve().parents[1]


class FakeBackend:
    """实现 LLMBackend 协议的测试后端：按文本返回可控向量，不联网（Constraint 2）。"""

    name = "fake"

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors
        self.seen: list[list[str]] = []

    def chat(self, prompt: str, *, system: str | None = None):
        raise AssertionError("检索路径不该调 chat")

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.seen.append(list(texts))
        return [list(self.vectors[t]) for t in texts]


def _patch(monkeypatch, vectors: dict[str, list[float]]) -> FakeBackend:
    backend = FakeBackend(vectors)
    monkeypatch.setattr(embed_module, "get_llm", lambda: backend)
    return backend


#: 互为镜像的一组单位向量：attn 与 softmax 正交，matmul 与 qk 互为镜像。
_MIRROR = {
    "attn": [1.0, 0.0],
    "softmax": [0.8, 0.6],
    "matmul": [0.8, 0.6],
    "qk": [0.6, 0.8],
}

#: 冲突场景的期望值（手算，不抄实现）：
#   forward  t0(matmul) → softmax 1.0 ；t1(qk) → softmax 0.96
#   backward softmax     → t0 1.0      ；attn      → t0 0.8
#   t1 的正向 top1 是 softmax，而 softmax 的反向 top1 是 t0 → 记冲突
_CONFLICT_UNITS = [
    {"code_id": "root/@037", "text": "attn"},
    {"code_id": "root/@038", "text": "softmax"},
]
_CONFLICT_TERMS = [
    {"term_id": "S3.2-eq-attn-t0", "text": "matmul"},
    {"term_id": "S3.2-eq-attn-t1", "text": "qk"},
]


def test_offline_retrieve_scores_zero_with_reason(monkeypatch):
    """RF2：后端抛 LLMUnavailable → 诚实归零，不兜底成 0.5、不返回假向量。"""
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    result = retrieve_bidirectional(_CONFLICT_UNITS, _CONFLICT_TERMS)
    assert result["s_retr"] == 0.0
    assert result["forward"] == {}
    assert result["backward"] == {}
    assert result["conflicts"] == []
    assert isinstance(result["reason"], str) and result["reason"].strip()
    assert "embedding" in result["reason"]


def test_cosine_of_identical_vectors_is_one():
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0
    assert cosine([0.6, 0.8], [0.6, 0.8]) == 1.0
    assert cosine([0.8, 0.6], [0.8, 0.6]) == 1.0


def test_cosine_of_zero_vector_is_zero():
    """零向量不抛异常：分母为 0 时返回 0.0（没有证据 = 没有分数）。"""
    assert cosine([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == 0.0
    assert cosine([1.0, 2.0, 3.0], [0.0, 0.0, 0.0]) == 0.0
    assert cosine([0.0, 0.0], [0.0, 0.0]) == 0.0


def test_cosine_is_clamped():
    """余弦必须落在 [-1,1]：浮点会把相同向量算成 1.0000000000000002。

    越界值会被 papertrace.align.score.confidence 直接拒收（ValueError），
    所以这里钳住，而不是让上游去猜。
    """
    assert cosine([1.0, 1.0, 1.0], [1.0, 1.0, 1.0]) == 1.0
    assert cosine([1.0, 1.0, 1.0], [-1.0, -1.0, -1.0]) == -1.0
    assert -1.0 <= cosine([0.3, -1.7, 2.2], [-0.4, 0.9, 1.1]) <= 1.0


def test_cosine_refuses_mismatched_dimensions():
    """维度不齐 → 明说，不许悄悄截断后算一个没人验证过的分数。"""
    with pytest.raises(ValueError):
        cosine([1.0, 0.0], [1.0, 0.0, 0.0])


def test_bidirectional_conflict_is_recorded(monkeypatch):
    """R42：top1 对不上就记冲突，且带 term_id / code_id / backward_top1 三个键。"""
    _patch(monkeypatch, _MIRROR)
    result = retrieve_bidirectional(_CONFLICT_UNITS, _CONFLICT_TERMS, k=1)
    assert result["conflicts"] == [
        {
            "term_id": "S3.2-eq-attn-t1",
            "code_id": "root/@038",
            "backward_top1": "S3.2-eq-attn-t0",
        }
    ]
    # 正向侧确实是把 softmax 排在第一
    assert result["forward"]["S3.2-eq-attn-t1"] == [
        {"code_id": "root/@038", "score": pytest.approx(0.96)}
    ]


def test_conflict_does_not_raise_confidence(monkeypatch):
    """R42：冲突只记录。s_retr 是所有条目里的最大值，绝不被平均抬高。"""
    _patch(monkeypatch, _MIRROR)
    result = retrieve_bidirectional(_CONFLICT_UNITS, _CONFLICT_TERMS, k=1)
    scores = [
        entry["score"]
        for table in (result["forward"], result["backward"])
        for entries in table.values()
        for entry in entries
    ]
    assert scores
    assert result["s_retr"] == pytest.approx(max(scores)) == 1.0
    # 把冲突那一对的正反分数平均掉会得到 0.98——那是注水，不是分数
    assert result["s_retr"] != pytest.approx(0.98)
    # 规格 Task 11：冲突不得把 confidence 抬过 0.75。检索单项到顶也过不了绿线，
    # 叠加本切片 s_struct 的上限 0.8 仍然过不去。
    assert confidence(result["s_retr"], 0.0, 0.0) < CONF_GREEN
    assert confidence(result["s_retr"], 0.0, 0.8) < CONF_GREEN


def test_embed_returns_list_not_ndarray(monkeypatch):
    """R45/Constraint 13：返回 list[list[float]]，不借第三方数组类型。"""
    backend = _patch(monkeypatch, {"attn": [1.0, 0.0], "softmax": [0.0, 1.0]})
    out = embed_texts(["attn", "softmax"])
    assert isinstance(out, list)
    assert isinstance(out[0], list)
    assert all(isinstance(v, float) for row in out for v in row)
    assert out == [[1.0, 0.0], [0.0, 1.0]]
    assert backend.seen == [["attn", "softmax"]]
    source = (REPO / "papertrace" / "align" / "embed.py").read_text(encoding="utf-8")
    assert "numpy" not in source


def test_embed_lets_llm_unavailable_propagate(monkeypatch):
    """R44：embed_texts 只转调，不捕获、不兜底——承重点只剩 retrieve 那一处。"""
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    assert isinstance(get_llm(), OfflineBackend)
    with pytest.raises(LLMUnavailable):
        embed_texts(["attn"])


def test_bidirectional_agreement_scores_the_mutual_top1(monkeypatch):
    """正反向 top1 互为同一对 → 无冲突，s_retr 就是那一条的分数，reason 为 None。"""
    _patch(monkeypatch, _MIRROR)
    result = retrieve_bidirectional(
        [{"code_id": "c-attn", "text": "attn"}],
        [{"term_id": "t-attn", "text": "attn"}],
        k=5,
    )
    assert result["conflicts"] == []
    assert result["forward"]["t-attn"] == [{"code_id": "c-attn", "score": 1.0}]
    assert result["backward"]["c-attn"] == [{"term_id": "t-attn", "score": 1.0}]
    assert result["s_retr"] == 1.0
    assert result["reason"] is None


def test_topk_is_capped_and_ordered(monkeypatch):
    """k 截断 + 按分数降序，且 s_retr 取两张表里的最大值而不是平均值。"""
    vectors = {
        "attn": [1.0, 0.0],
        "softmax": [0.0, 1.0],
        "matmul": [0.6, 0.8],
        "scale": [0.5, 0.5],
    }
    _patch(monkeypatch, vectors)
    units = [
        {"code_id": "root/@037", "text": "attn"},
        {"code_id": "root/@038", "text": "softmax"},
        {"code_id": "root/@039", "text": "matmul"},
    ]
    terms = [
        {"term_id": "S3.2-eq-attn-t0", "text": "scale"},
        {"term_id": "S3.2-eq-attn-t1", "text": "matmul"},
    ]
    result = retrieve_bidirectional(units, terms, k=2)
    # 截断：3 个代码单元只留 2 条
    assert len(result["forward"]["S3.2-eq-attn-t0"]) == 2
    assert len(result["backward"]["root/@039"]) == 2
    # 降序
    for table in (result["forward"], result["backward"]):
        for entries in table.values():
            scores = [e["score"] for e in entries]
            assert scores == sorted(scores, reverse=True)
    # scale 与 matmul 的余弦 = (0.3+0.4)/0.7071 = 0.98995，是全场最高
    assert result["forward"]["S3.2-eq-attn-t0"][0] == {
        "code_id": "root/@039",
        "score": pytest.approx(0.98995, abs=1e-4),
    }
    # 所有条目的平均值 ≠ s_retr；s_retr 就是最大值
    scores = [
        e["score"]
        for table in (result["forward"], result["backward"])
        for entries in table.values()
        for e in entries
    ]
    assert result["s_retr"] == pytest.approx(max(scores))
    assert result["s_retr"] > sum(scores) / len(scores)


class _ShortBackend:
    """故意少返回一条向量的后端（R54）。

    模拟的是 S8 之后 OpenAICompatBackend 解析 HTTP JSON 时最典型的失误：返回条数
    与请求条数不一致。按 R43 用 monkeypatch 换掉 embed.py 自己引用的 get_llm，
    绝不改 client.py，绝不联网（Constraint 2）。
    """

    name = "short"

    def __init__(self, vectors: dict[str, list[float]], drop_last_text: str):
        self.vectors = vectors
        self.drop_last_text = drop_last_text

    def chat(self, prompt: str, *, system: str | None = None):
        raise AssertionError("检索路径不该调 chat")

    def embed(self, texts: list[str]) -> list[list[float]]:
        rows = [list(self.vectors[t]) for t in texts]
        if texts and texts[-1] == self.drop_last_text:
            rows = rows[:-1]  # 少返回一条：数量与请求对不上
        return rows


def _patch_short(monkeypatch, vectors: dict[str, list[float]], drop_last_text: str):
    backend = _ShortBackend(vectors, drop_last_text)
    monkeypatch.setattr(embed_module, "get_llm", lambda: backend)
    return backend


def test_term_vector_shortfall_is_refused(monkeypatch):
    """R54：后端少返回一条论文项向量 → ValueError，不许静默把 term 踢出计分。

    静默截断会让 s_retr 变成一个「在没人验证过的子集上算出来的最大值」，看起来
    完全合法——那正是本项目要防止的那类失败。
    """
    _patch_short(monkeypatch, _MIRROR, drop_last_text="qk")
    with pytest.raises(ValueError, match=r"后端返回向量数与输入数不一致：1 != 2"):
        retrieve_bidirectional(
            [{"code_id": "root/@037", "text": "attn"}],
            _CONFLICT_TERMS,
            k=5,
        )


def test_code_vector_shortfall_is_refused(monkeypatch):
    """R54：后端少返回一条代码向量 → ValueError，与 cosine 的维度守卫同标准同语气。"""
    _patch_short(monkeypatch, _MIRROR, drop_last_text="softmax")
    with pytest.raises(ValueError, match=r"后端返回向量数与输入数不一致：1 != 2"):
        retrieve_bidirectional(
            _CONFLICT_UNITS,
            [{"term_id": "S3.2-eq-attn-t0", "text": "matmul"}],
            k=5,
        )


def test_empty_inputs_are_zero_not_a_crash(monkeypatch):
    """空输入 → 空表 + 0.0 + reason，不许抛异常也不许假装有结果。"""
    _patch(monkeypatch, _MIRROR)
    result = retrieve_bidirectional([], [], k=5)
    assert result["forward"] == {}
    assert result["backward"] == {}
    assert result["s_retr"] == 0.0
    assert result["conflicts"] == []
    assert isinstance(result["reason"], str) and result["reason"].strip()


class _LongBackend:
    """故意**多**返回一条向量的后端（m8：R54 的对称侧）。

    与 _ShortBackend 镜像：少返回一条要拒，多返回一条同样要拒——数量对不上就是
    对不上，静默 zip 截断会让某个单元被悄悄踢出计分，算出一个在没人验证过的
    子集上的 s_retr。单实例跨调用记录 seen，用来断言 embed 路径真被走到。
    """

    name = "long"

    def __init__(self, vectors: dict[str, list[float]], long_text: str):
        self.vectors = vectors
        self.long_text = long_text
        self.seen: list[list[str]] = []

    def chat(self, prompt: str, *, system: str | None = None):
        raise AssertionError("检索路径不该调 chat")

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.seen.append(list(texts))
        rows = [list(self.vectors[t]) for t in texts]
        if self.long_text in texts:
            rows = rows + [list(rows[0])]  # 多返回一条：数量与请求对不上
        return rows


def _patch_long(monkeypatch, vectors: dict[str, list[float]], long_text: str):
    backend = _LongBackend(vectors, long_text)
    monkeypatch.setattr(embed_module, "get_llm", lambda: backend)
    return backend


def test_term_vector_surplus_is_refused(monkeypatch):
    """m8：后端多返回一条论文项向量 → ValueError，与少返回同标准（R54 对称侧）。"""
    backend = _patch_long(monkeypatch, _MIRROR, long_text="qk")
    with pytest.raises(ValueError, match=r"后端返回向量数与输入数不一致：3 != 2"):
        retrieve_bidirectional(
            [{"code_id": "root/@037", "text": "attn"}],
            _CONFLICT_TERMS,
            k=5,
        )
    # 被测路径真被走到：两次 embed 调用都发生了，不是空输入短路
    assert backend.seen == [["attn"], ["matmul", "qk"]]


def test_code_vector_surplus_is_refused(monkeypatch):
    """m8：后端多返回一条代码向量 → ValueError（term 侧先过，code 侧后炸）。"""
    backend = _patch_long(monkeypatch, _MIRROR, long_text="softmax")
    with pytest.raises(ValueError, match=r"后端返回向量数与输入数不一致：3 != 2"):
        retrieve_bidirectional(
            _CONFLICT_UNITS,
            [{"term_id": "S3.2-eq-attn-t0", "text": "matmul"}],
            k=5,
        )
    assert backend.seen == [["attn", "softmax"], ["matmul"]]
