"""结构信号 s_struct：不碰任何模型，纯确定性，offline 也算得出来。

规则（工程计划书 :663-669 冻结，权重不许改）：
    初值 0.5
    +0.2 论文说「N 层」且代码有 range(n_layer)（本切片不触发，R23）
    +0.1 超参名在 config 出现
    +0.2 算子序列与公式项顺序同构（matmul→scale→softmax→matmul）
    -0.4 shape 与论文声明冲突（本切片不触发，R23）
    -0.3 双向检索 top1 不是同一对（本切片不触发，R23）
    结果 clamp 到 [0,1]

控制器裁决（原文照录，实现与之一一对应）：
- R23：本函数只收算子节点、公式项与 config，没有论文正文、也没有论文声明的形状。
  「N 层」与「shape 冲突」两条在本切片不可判定——不触发、不扣分，只记 misses；
  「双向检索」本条 offline 无检索结果，同样只记 misses。绝不为了凑分发明论文侧
  证据，也不改签名把论文文本偷渡进来。本切片上限 0.5+0.1+0.2=0.8，仍
  >= GREEN_STRUCT_MIN=0.5，绿档可达；论文侧证据由 M4 补。
- R24：「超参名在 config 出现」只能读成代码侧超参名（论文符号 d_k 永远不会出现在
  Python config 里）。冻结名单四个名字全在 config 上时 +0.1，只加一次。
- R25：同构判定取 level=='op' 且 kind=='op' 的算子（18 个权重与 1 个 input 的 op
  名是 'placeholder'，不是算子），按 parent_id 分组、组内单独匹配，取 nodes 顺序
  里第一个匹配的组；拉平成一条序列会产生跨模块假匹配。匹配是贪心从左到右的子序列：
  代码侧多出的算子允许被跳过（因果掩码 masked_fill 就夹在中间）。term.kind 不在
  冻结映射里时永远匹配不上。
- R25a：只配第一层。h.0.attn 与 h.1.attn 完全同构且都能匹配，首匹配规则选
  h.0.attn。这是本切片的已知局限（逐层对齐是 M4）：签名不变，也不返回多个组。
- R37：pairs 是判断题（S7）唯一的候选来源。同构不命中 → pairs == [] → s_judge=0。
  绝不为了给 judge 凑候选而编造 pairs：不做全配对，不引入词法候选生成器（S15 未批）。
- R38：hits / misses 是给人看的短中文句子，会作为 evidence 展示在 HTML 报告里；
  每条都点名规则、说清为什么中或为什么不中。
- loc 不是行号（夹具里是 'model.GPT'）：判据只看算子名与组内顺序，配对回传 node_id，
  不依赖 loc。

产出 StructSignal(score, hits, misses, pairs)；pairs 是 [(term.index, node_id)]。
"""

from __future__ import annotations

from typing import NamedTuple

#: R24：代码侧超参名（冻结）。论文符号 d_k 之类不会出现在 Python config 里。
HYPERPARAM_NAMES = ("n_layer", "n_head", "n_embd", "block_size")

#: R25：term.kind → 代码侧算子名（冻结映射，不许扩）。
KIND_TO_OPS = {
    "matmul": ("matmul",),
    "scale": ("mul", "div"),
    "norm": ("softmax",),
    "act": ("gelu", "relu", "sigmoid", "tanh"),
    "transpose": ("transpose",),
    "concat": ("cat",),
}

#: 冻结权重（工程计划书 :663-669）。后三条本切片不可判定（R23），只声明不累加，
#: 免得 M4 补论文侧证据时有人顺手改权重。
BASE_SCORE = 0.5
BONUS_LAYERS = 0.2
BONUS_CONFIG = 0.1
BONUS_ISOMORPHIC = 0.2
PENALTY_SHAPE = -0.4
PENALTY_RETRIEVAL = -0.3

_LAYER_MISS = (
    "论文层数规则：本切片只看算子节点、公式项与 config，看不到论文正文里"
    "「几层」的声明，无法判定，不加减分"
)
_SHAPE_MISS = (
    "形状规则：本切片拿不到论文声明的形状，无法与代码侧 shape_in/shape_out 比对，不扣分"
)
_RETRIEVAL_MISS = "双向检索规则：offline 没有检索结果，top1 是否同一对无从比对，不扣分"


class StructSignal(NamedTuple):
    """结构信号。pairs 是 judge 的唯一候选来源（R37）。"""

    score: float
    hits: list[str]
    misses: list[str]
    pairs: list[tuple[int, str]]


def struct_signal(nodes: list[dict], terms: list, config) -> StructSignal:
    """算子节点 + 公式项 + config → 确定性结构信号。不碰模型、不联网。"""
    score = BASE_SCORE
    hits: list[str] = []
    misses: list[str] = [_LAYER_MISS, _SHAPE_MISS, _RETRIEVAL_MISS]
    pairs: list[tuple[int, str]] = []

    # R24：超参名在 config 出现（四个全在才 +0.1，只加一次）
    if config is None:
        misses.append("超参名在 config 出现：调用方没给 config，无法核对超参名，不加分")
    else:
        absent = [name for name in HYPERPARAM_NAMES if not hasattr(config, name)]
        if absent:
            misses.append(
                "超参名在 config 出现：config 上缺 " + "/".join(absent) + "，不加分"
            )
        else:
            score += BONUS_CONFIG
            hits.append(
                "超参名在 config 出现：" + "/".join(HYPERPARAM_NAMES) + " 四个都在（+0.1）"
            )

    # R25/R25a：组内贪心子序列同构 + 首匹配组；R37：pairs 由这条规则顺带产出
    if not terms:
        misses.append(
            "算子序列与公式项顺序同构：公式没拆出任何项，无从比对，不加分，候选对为空"
        )
    else:
        pairs, group_id, matched = _first_isomorphic_group(nodes, terms)
        if pairs:
            score += BONUS_ISOMORPHIC
            hits.append(
                f"算子序列与公式项同构：{group_id} 组内 "
                + "→".join(matched)
                + " 依次命中（+0.2）"
            )
        else:
            misses.append(
                "算子序列与公式项顺序同构：没有任何算子组的顺序能匹配公式项，"
                "不加分，候选对为空"
            )

    return StructSignal(min(1.0, max(0.0, score)), hits, misses, pairs)


def _first_isomorphic_group(nodes: list[dict], terms: list):
    """R25/R25a：按 nodes 顺序找第一个匹配的算子组；不命中返回 ([], "", [])。"""
    for group_id, ops in _groups_in_node_order(nodes):
        pairs = _greedy_subsequence(ops, terms)
        if pairs:
            by_id = {node.get("id"): node.get("op") for node in ops}
            return pairs, group_id, [by_id[node_id] for _, node_id in pairs]
    return [], "", []


def _groups_in_node_order(nodes: list[dict]) -> list[tuple[str, list[dict]]]:
    """按 parent_id 分组；组间顺序就是 nodes 顺序（dict 保插入序）。"""
    groups: dict[str, list[dict]] = {}
    for node in _operator_nodes(nodes):
        groups.setdefault(node.get("parent_id"), []).append(node)
    return list(groups.items())


def _operator_nodes(nodes: list[dict]) -> list[dict]:
    """R25a：只要真正的算子——权重与 input 的 op 名是 'placeholder'，不算算子。"""
    return [n for n in nodes if n.get("level") == "op" and n.get("kind") == "op"]


def _greedy_subsequence(ops: list[dict], terms: list) -> list[tuple[int, str]]:
    """贪心从左到右子序列匹配；任何一项匹配不上就整体失败（返回 []）。

    代码侧多出的算子被跳过——因果掩码 masked_fill 就夹在 mul 与 softmax 之间。
    """
    pairs: list[tuple[int, str]] = []
    pos = 0
    for term in terms:
        wanted = KIND_TO_OPS.get(term.kind, ())
        hit = None
        while pos < len(ops):
            node = ops[pos]
            pos += 1
            if node.get("op") in wanted:
                hit = node
                break
        if hit is None:
            return []
        pairs.append((term.index, hit.get("id")))
    return pairs
