"""S15 候选生成器：按公式项的 kind 过滤代码算子，再做确定性词法排序。

为什么要有它：S5 的结构同构只认「一条组内顺序完全匹配」，同构不命中就一个候选都
没有。本模块补的是**非结构候选**：按冻结的 KIND_TO_OPS 映射筛出算子，再用纯词法
重叠度排序。它只提议候选，不判定对齐——判定仍归 judge。

契约（brief 与控制器裁决，逐字权威）：
- 候选池只收 `level == "op"` 且 `kind == "op"` 的节点；权重（kind=param）与输入
  （kind=input）是占位符，永不进候选。
- 资格 = `node["op"] in KIND_TO_OPS.get(term.kind, ())`。未知 kind 用 `.get` 兜底成
  零候选 + 一条 miss，绝不 KeyError、绝不猜。
- 排序 = `lexical_rank(term.latex, node)` 降序，同分按 `node["id"]` 升序。这条排序
  是确定性契约：两个实现者必须产出同一份 trace.json。
- 预算按 `term.index` 升序分配（与 terms 入参顺序无关），每项最多 per_term_limit、
  合计最多 total_limit；被截断的 term 只记一条 miss，不按被砍候选数重复记账。
- **不做跨 term 唯一性约束**：term0（QK^{T}, matmul）与 term3（V, matmul）候选集
  完全相同是正确行为——同一个算子可以同时服务两个公式项，去重等于编造「唯一归属」。
- **hits/misses 不被 spine 消费**（spine 只消费 pairs）。它们只是给人看的中文短句，
  供测试、调试与将来的 evidence 使用。

纯函数：不读环境变量、不读文件、不缓存跨调用状态、不联网、不调 LLM，也不 import
torch 或 papertrace.parse_code。
"""

import re
from typing import NamedTuple

from papertrace.align.struct_signal import KIND_TO_OPS

#: 词法单元：字母/下划线开头的标识符（brief 冻结定义，两个实现者同一口径）。
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


class Candidates(NamedTuple):
    """候选对 + 人看的说明。pairs 是 spine 唯一消费的字段。"""

    pairs: list[tuple[int, str]]
    hits: list[str]
    misses: list[str]


def candidate_pairs(
    terms: list,
    nodes: list[dict],
    *,
    per_term_limit: int = 3,
    total_limit: int = 12,
) -> Candidates:
    """按 term.index 升序，为每个公式项给出至多 per_term_limit 个候选节点。"""
    misses: list[str] = []
    if not terms:
        misses.append("公式没拆出任何项，候选为空，绝不凑对")
        return Candidates([], [], misses)
    pool = [n for n in nodes if n.get("level") == "op" and n.get("kind") == "op"]
    if not pool:
        misses.append("没有算子节点（level=op 且 kind=op），候选为空，绝不凑对")
        return Candidates([], [], misses)

    pairs: list[tuple[int, str]] = []
    hits: list[str] = []
    remaining = total_limit
    for term in sorted(terms, key=lambda t: t.index):
        wanted = KIND_TO_OPS.get(term.kind, ())
        eligible = [n for n in pool if n.get("op") in wanted]
        if not eligible:
            # A-Minor-1：零候选有两种成因，文案必须分开说，不许一句「映射里没有」蒙过去 ——
            # ① kind 根本不在冻结映射里；② 映射里有，但当前 trace 没有这类算子节点。
            if term.kind not in KIND_TO_OPS:
                misses.append(
                    f"term {term.index}（{term.kind}）不在冻结的算子类型映射里，"
                    "零候选，绝不凑对"
                )
            else:
                misses.append(
                    f"term {term.index}（{term.kind}）在冻结映射里对应算子 "
                    f"{'/'.join(wanted)}，但当前 trace 没有这类算子节点，零候选，绝不凑对"
                )
            continue
        ranked = sorted(
            eligible, key=lambda n: (-lexical_rank(term.latex, n), str(n.get("id")))
        )
        take = max(0, min(per_term_limit, len(ranked), remaining))
        ops = "/".join(sorted({str(n.get("op")) for n in ranked}))
        hits.append(
            f"term {term.index}（{term.kind}）：{len(ranked)} 个资格候选，算子 {ops}"
        )
        pairs.extend((term.index, node["id"]) for node in ranked[:take])
        remaining -= take
        if take < len(ranked):
            misses.append(
                f"term {term.index} 有 {len(ranked)} 个资格候选，按上限截断，"
                f"丢弃 {len(ranked) - take} 个"
            )
    return Candidates(pairs, hits, misses)


def lexical_rank(text: str, node: dict) -> float:
    """两段文本的标识符词法重叠度：交集 / 较大者；任一为空集返回 0.0。

    这是 brief 冻结的确定性定义——只排序、不过滤，分数高不代表任何对齐语义。
    实现取 `node.get("op", "") / node.get("label", "")`，冻结定义写的是 `node["op"] /
    node["label"]`：**对格式良好的节点两者逐字等价**；只在畸形节点（缺 `op` / `label`
    键）上把 KeyError 变成 0.0——方向安全，分数低不会凭空造出对齐，也绝不会把候选踢出
    池子（资格判定在 `candidate_pairs` 里另做，不走本函数）。
    """
    left = set(_TOKEN.findall(text.lower()))
    right = set(_TOKEN.findall(f"{node.get('op', '')} {node.get('label', '')}".lower()))
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))
