"""双向检索：论文项找代码单元、代码单元找论文项，各取 Top-k。

输入契约（控制器裁决 R40，别传错形状）：
- code_units = [{"code_id": str, "text": str}, ...]，由 S9 装配。code_id 是 trace
  节点 id（如 "root/@037"），text 是算子名 + label + loc。
- paper_terms = [{"term_id": str, "text": str}, ...]，由 S9 装配。term_id 形如
  "S3.2-eq-attn-t0"（即 f"{unit_id}-t{term.index}"），text 是该项的 latex，
  可带少量上下文。
本模块不碰 trace schema，也不 import/构造 Term/PaperUnit：它真正需要的只是
「稳定 id + 一段文本」，那会让它依赖 S2/S3 的内部形状。

输出：
- forward: {term_id: [{"code_id": ..., "score": ...}, ...]}  每个论文项的 Top-k 代码单元
- backward: {code_id: [{"term_id": ..., "score": ...}, ...]}  每个代码单元的 Top-k 论文项
- s_retr: float。R41 —— forward 与 backward 两个 top-k 列表里**所有条目**的最大
  分数，clip 到 [0,1]；两个列表都空 → 0.0。不是两个最大值取平均，也不是所有
  分数取平均：平均正是规格书禁止的分数注水。
- conflicts: list[dict]。R42 —— 某 term_id 的正向 top1 的 code_id，在 backward 里
  的 top1 不是同一个 term_id 时，记录 {"term_id": ..., "code_id": ...,
  "backward_top1": ...}。冲突只记录，不参与 s_retr，绝不被平均掉（规格 Task 11：
  冲突不得把 confidence 抬过 0.75）。
- reason: str | None。没有可检索内容、或后端拿不到 embedding 时写清原因；正常
  跑完是 None。R76：这个原因必须如实点名**实际配置的后端**与**真实失败原因**。

R44：`LLMUnavailable` 只在这里捕获一次 → s_retr=0.0、forward/backward 空 dict、
reason 说清是哪个后端、为什么没拿到 embedding。不兜底成 0.5，不返回假向量（RF2）。
R76：不许再硬编码「offline 后端不提供 embedding」——用户配了 openai 而
/embeddings 返回 404 时，那句话与实际配置矛盾：分数和 tier 都是对的，错的只有
解释，而一个撒谎的原因比没有原因更糟（与 R64 要求 _offline_hint 如实化同族）。
"""

from __future__ import annotations

import math

from papertrace.align.embed import embed_texts
from papertrace.exceptions import LLMUnavailable
from papertrace.llm.client import configured_backend

#: 配置值本身不合法时（configured_backend 抛 ValueError）也不能冒充 offline。
UNKNOWN_BACKEND = "unknown"
#: 没有可检索的内容时也要给原因：空结果和「算过了但没有命中」不是一回事。
_EMPTY_REASON = "代码单元或论文项为空：没有可检索的内容，s_retr=0.0"


def _unavailable_reason(exc: BaseException) -> str:
    """R76：如实点名实际配置的后端 + 真实失败原因，不许留空让上游以为是偶发故障。"""
    try:
        backend = configured_backend()
    except ValueError:
        backend = UNKNOWN_BACKEND
    detail = str(exc).strip() or type(exc).__name__
    return (
        f"{backend} 后端拿不到 embedding：{detail}"
        "（双向检索无结果，s_retr=0.0，不兜底成假分数）"
    )


def cosine(a: list[float], b: list[float]) -> float:
    """纯 Python 余弦相似度（Constraint 13：不借第三方数组类型）。

    - 任一向量模为 0 → 0.0，不抛 ZeroDivisionError：没有证据就是没有分数。
    - 结果钳到 [-1,1]：浮点会把相同向量算成 1.0000000000000002，而越界值会被
      `papertrace.align.score.confidence` 直接拒收。
    - 两侧维度不一致 → ValueError。同一后端出来的向量必须同维，悄悄截断等于
      算一个没人验证过的分数。
    """
    if len(a) != len(b):
        raise ValueError(f"向量维度不一致：{len(a)} != {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


def retrieve_bidirectional(code_units: list, paper_terms: list, k: int = 5) -> dict:
    """R40 的 dict 列表进，R41/R42 的 forward/backward/s_retr/conflicts 出。"""
    try:
        # R44：embed_texts 不捕获，所以这里是 offline 归零的唯一位置
        code_vectors = embed_texts([unit["text"] for unit in code_units])
        term_vectors = embed_texts([term["text"] for term in paper_terms])
    except LLMUnavailable as exc:
        # R76：reason 跟着实际配置的后端走，不再谎称 offline
        return _zero(_unavailable_reason(exc))

    # R54：先验数量，再配对。少返回（或多返回）一条向量就抛，绝不让任何单元被
    # 静默踢出计分——那会得到一个在没人验证过的子集上算出来的 s_retr。
    _require_paired(term_vectors, paper_terms)
    _require_paired(code_vectors, code_units)

    forward = {
        term["term_id"]: _topk(
            vector, code_units, code_vectors, "code_id", k
        )
        for term, vector in zip(paper_terms, term_vectors)
    }
    backward = {
        unit["code_id"]: _topk(
            vector, paper_terms, term_vectors, "term_id", k
        )
        for unit, vector in zip(code_units, code_vectors)
    }
    scores = [
        entry["score"]
        for table in (forward, backward)
        for entries in table.values()
        for entry in entries
    ]
    if not scores:
        return _zero(_EMPTY_REASON, forward, backward)
    return {
        "forward": forward,
        "backward": backward,
        # R41：所有条目取最大，再钳一遍——钳的是 cosine 的负值那一侧
        "s_retr": min(1.0, max(0.0, max(scores))),
        "conflicts": _conflicts(forward, backward),
        "reason": None,
    }


def _require_paired(vectors: list, units: list) -> None:
    """后端返回的向量数必须与输入条数一致，否则抛 ValueError（R54）。

    与 cosine 的维度守卫同一标准、同一语气：维度不齐明抛，数量不齐也明抛。
    不许静默补齐、不许截断、不许兜底成 0.0、不许返回部分结果（fail-closed，
    与 R21/R36 一脉相承）。

    为什么两处就够、不在 _topk 里再查一遍：这两对校验正好覆盖全部三处 zip——
    forward 的键配对 (paper_terms, term_vectors)、backward 的键配对
    (code_units, code_vectors)，以及 _topk 内部的 (units, vectors)。_topk 是模块
    私有函数，喂给它的只有这两对已经校验过的组合，在它里面再查只是重复校验同一
    件事；而只查 _topk 又会漏掉两处键配对造成的静默丢键。
    """
    if len(vectors) != len(units):
        raise ValueError(
            f"后端返回向量数与输入数不一致：{len(vectors)} != {len(units)}"
        )


def _zero(reason: str, forward: dict | None = None, backward: dict | None = None) -> dict:
    """归零形态：s_retr=0.0、冲突为空，reason 说清为什么没有分数。"""
    return {
        "forward": forward or {},
        "backward": backward or {},
        "s_retr": 0.0,
        "conflicts": [],
        "reason": reason,
    }


def _topk(vector, units, vectors, id_key: str, k: int) -> list[dict]:
    """一个向量对一批单位的 Top-k：按分数降序，同分按 id 稳定（可复现）。"""
    scored = [
        (cosine(vector, other), unit[id_key])
        for unit, other in zip(units, vectors)
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {id_key: ident, "score": score}
        for score, ident in scored[: k if k > 0 else 0]
    ]


def _conflicts(forward: dict, backward: dict) -> list[dict]:
    """R42：正向 top1 的 code_id，其反向 top1 不是同一个 term_id 就记一条。"""
    conflicts = []
    for term_id, entries in forward.items():
        if not entries:
            continue
        code_id = entries[0]["code_id"]
        reverse = backward.get(code_id) or []
        if not reverse:
            continue
        backward_top1 = reverse[0]["term_id"]
        if backward_top1 != term_id:
            conflicts.append(
                {
                    "term_id": term_id,
                    "code_id": code_id,
                    "backward_top1": backward_top1,
                }
            )
    return conflicts
