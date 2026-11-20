"""分档：confidence 与结构信号一起决定绿 / 黄 / 不连线（U1 门）。

为什么门长在这里而不是 HTML 渲染里：渲染时手上只有一个 confidence 数字，
执行不了「绿线还要求 s_struct >= GREEN_STRUCT_MIN」这条判据。只有分档函数
同时见过 c 和 s_struct，门才可能被诚实执行。trace.json 被人手改涂色的问题
由校验侧的 papertrace/schema/anchor.py 兜底（RF3）——两边都长，缺一边，
「生成时守规矩、手改就能绕」或者「校验得到、生成时没这回事」就会发生。

门的语义（派发裁决）：
- green 需要 c >= CONF_GREEN 且 s_struct >= GREEN_STRUCT_MIN
- yellow 需要 c >= CONF_YELLOW（不受门影响）
- none 是 c < CONF_YELLOW
"""

from __future__ import annotations

from papertrace.constants import CONF_GREEN, CONF_YELLOW, GREEN_STRUCT_MIN


def tier(confidence: float, s_struct: float) -> str:
    """返回 "green" | "yellow" | "none"。门只降不升。"""
    if confidence >= CONF_GREEN and s_struct >= GREEN_STRUCT_MIN:
        return "green"
    if confidence >= CONF_YELLOW:
        return "yellow"
    return "none"


def tier_reason(confidence: float, s_struct: float) -> str:
    """只在**被门降级**时返回非空原因（<=40 字符，供 anchor.evidence 用）。

    黄虚线和「不连线」是置信度自己的事，不是门降的，所以返回空串——
    否则每条黄线的 evidence 都会挂着一条误导人的结构原因。
    """
    if confidence >= CONF_GREEN and s_struct < GREEN_STRUCT_MIN:
        return f"结构信号 {s_struct:.4f} 低于 {GREEN_STRUCT_MIN:.2f}，绿线降为黄线"
    return ""
