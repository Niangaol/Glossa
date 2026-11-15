"""认领唯一性：一个算子至多被一个公式项认领（S15 独占语义）。

动机：`papertrace/align/candidates.py` 对两个 kind 都是 matmul 的公式项给出
**逐字相同**的候选列表，回退路径上两项都会选中同一个算子节点（演示实录：
`QK^{T}` 项与 `V` 项都连上 `root/@037`）。anchor 是「归属」断言不是「相关性」
断言——一个算子不能同时是两个公式项的归属实现。本模块把「已认领」状态与挑选
逻辑从 `papertrace/spine.py` 搬出来（spine.py 已 200 行，加不动了），并加上
独占语义：judge 确认过的节点写进 `claimed`，后续项跳过它。

铁律不变：宁可报「对不上」也绝不编造对齐——候选全被认领就一个都不问，交回
`(0.0, "", None)`，由调用方记 unresolved（理由用 `CLAIMED_REASON`）。
"""

from __future__ import annotations

from papertrace.align.judge import judge, judge_score

#: 全部候选已被同一公式单元内的其他项认领时，调用方写进 unresolved 的理由。
CLAIMED_REASON = "该算子已被同一公式单元内的另一个公式项认领，一个算子至多归属一个公式项"


def node_text(node: dict) -> str:
    """算子节点的一段自描述文本（喂给检索与判断题）。

    与 `papertrace/spine._node_text` 逐字等价（原样搬来，输出必须一致）。
    """
    return (f"{node.get('op','')} {node.get('label','')} {node.get('loc','')} "
            f"in={node.get('shape_in')} out={node.get('shape_out')}").strip()


def unclaimed(node_ids: list[str], claimed: set[str]) -> list[str]:
    """保序返回还没被认领的 node_id（输入顺序），**不改入参**、不抛异常。"""
    return [node_id for node_id in node_ids if node_id not in claimed]


def judge_first_yes(term_text: str, node_ids: list[str], by_id: dict,
                    claimed: set[str]) -> tuple[float, str, str | None]:
    """按 `node_ids` 顺序找第一个「未认领且 judge 答 yes」的节点。

    跳过 ①已在 `claimed` 里的 id（独占语义：一个算子至多归属一个公式项）；
    ②`by_id` 里没有的 id。命中返回 `(1.0, evidence, node_id)` 并**把 node_id
    加进 `claimed`**；全不中返回 `(0.0, "", None)`，且不往 claimed 加任何东西。

    **有副作用**：命中时会修改调用方传入的 `claimed` 集合——它就是认领状态的
    载体，按公式单元建一个 set、跨公式项共享。
    """
    for node_id in node_ids:
        if node_id in claimed:
            continue
        node = by_id.get(node_id)
        if node is None:
            continue
        result = judge(term_text, node_text(node))
        if judge_score(result) > 0:
            claimed.add(node_id)
            return 1.0, result.evidence.strip(), node_id
    return 0.0, "", None


def duplicate_claims(grouped: dict[int, list[str]]) -> list[str]:
    """报告在同一公式单元内出现 ≥2 次的 node_id（升序、去重）。

    只报告不抛异常：空输入或全不重复返回 `[]`。调用方据此记 unresolved 或
    人工复核，绝不静默去重——重复认领是要给人看的事实。
    """
    counts: dict[str, int] = {}
    for node_ids in grouped.values():
        for node_id in node_ids:
            counts[node_id] = counts.get(node_id, 0) + 1
    return sorted(node_id for node_id, times in counts.items() if times >= 2)
