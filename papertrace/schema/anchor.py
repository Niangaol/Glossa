"""anchor 的跨字段不变量：tier 不得高于 signals 重算的门（RF3 + R171）。

门长在生成侧的 tier() 里，但 trace.json 是可以手改的文件：把 yellow 涂成 green
只需要改一个字符串。JSON Schema 只能校验单对象形状，管不了「tier 是否等于
confidence(signals) 过门的结果」这种跨字段约束，所以放这里，由
schema_structure.structural_errors 在末尾调用，validate_trace 自动执行。

R171：判据从「必须相等」改成「不得高于重算结果」——秩 none < yellow < green。
升格（把档位涂高）是往多断言的方向造假，必须抓；降格（把档位涂低）是产品自己
的保守下调：spine_fallback.cap_tier 在回退路径上按 R112 把 green 封顶成 yellow，
signals 重算 green、落盘 yellow 完全合法。旧判据「必须相等」会把这份合法配置判成
「手改涂色」，让构建在最后一步崩掉，报错文案还完全误导。

旧 trace 没有 tier：不校验，必须通过——这是纯增量改动的底线。
"""

from __future__ import annotations

from papertrace.align.score import confidence
from papertrace.align.tier import tier

_SIGNAL_KEYS = ("s_retr", "s_judge", "s_struct")

# R171：档位高低只看秩 none < yellow < green——字符串就是 tier() 的返回值，
# 不引入新档位。stored 高于 expected 是升格造假；低于则是保守下调，合法。
_TIER_RANK = {"none": 0, "yellow": 1, "green": 2}


def _signal_shape_errors(index: int, signals: dict) -> list[str]:
    """signals 必须含三项、每项是 [0,1] 内的数字；形状不对就谈不上重算。"""
    errors: list[str] = []
    for key in _SIGNAL_KEYS:
        if key not in signals:
            errors.append(f"anchors[{index}]: signals 缺少 {key}（复核分档需要三项齐全）")
    for key in _SIGNAL_KEYS:
        if key not in signals:
            continue
        value = signals[key]
        # JSON 的 true/false 在 Python 里是 bool（int 的子类），不是数字
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(
                f"anchors[{index}]: signals.{key} 必须是数字，实际是 {type(value).__name__}"
            )
        elif not 0.0 <= float(value) <= 1.0:
            errors.append(f"anchors[{index}]: signals.{key} 必须在 [0,1]，实际是 {value!r}")
    return errors


def _anchor_tier_errors(index: int, anchor: dict) -> list[str]:
    """带了 tier 的 anchor：signals 必须齐、必须合法、tier 不得高于重算结果。"""
    signals = anchor.get("signals")
    if not isinstance(signals, dict):
        return [
            f"anchors[{index}]: 带了 tier 就必须同时带 signals 对象，"
            f"实际是 {type(signals).__name__}（没有 signals 就无法复核分档）"
        ]
    errors = _signal_shape_errors(index, signals)
    if errors:
        # 形状已经不对，重算只会制造二手错误，直接返回形状错误
        return errors
    c = confidence(signals["s_retr"], signals["s_judge"], signals["s_struct"])
    expected = tier(c, signals["s_struct"])
    stored = anchor.get("tier")
    rank = _TIER_RANK.get(stored)
    # 枚举外的 tier 由 JSON Schema 的 enum 拦，这里不重复报；.get 也避免 KeyError
    if rank is not None and rank > _TIER_RANK[expected]:
        errors.append(
            f"anchors[{index}]: tier={stored!r} 高于 signals 重算结果 {expected!r}"
            f"（升格必须被抓到；降格是产品自己的保守下调，合法）"
        )
    return errors


def anchor_errors(doc: dict) -> list[str]:
    """anchor 的跨字段不变量；没问题返回 []。形状错误交给 JSON Schema。"""
    if not isinstance(doc, dict):
        return []
    anchors = doc.get("anchors")
    if not isinstance(anchors, list):
        return []
    errors: list[str] = []
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            continue  # 形状错误由 schema 报
        if "tier" not in anchor:
            continue  # 旧 trace 没有 tier：不校验，必须通过
        errors.extend(_anchor_tier_errors(index, anchor))
    return errors
