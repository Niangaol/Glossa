"""从论文里抽符号表：符号 → 含义 → 数值 → 首次出现的单元。

契约（R2，别传错参数）：本函数的 `bundle` 是 **S2 的 PaperBundle**（读 `.units`），
不是 build_trace() 的 trace dict。
"""

from __future__ import annotations

import re

#: 只抽下标标识符：字母开头，一个下划线，后接字母数字（LaTeX 的 d_k 就长这样）。
#: Q/K/V 没有下标，冻结映射表也不覆盖它们，抽了就是自作主张（R22）。
_SUBSCRIPTED = re.compile(r"[A-Za-z]+_[A-Za-z0-9]+")


def build_paper_symbols(bundle) -> list[dict]:
    """按单元顺序抽下标符号，按 symbol 去重（保留首次出现）。

    - `bundle` 是 **S2 的 PaperBundle**（R2）：source / ingest_mode /
      unit_count / title / units；`units` 是 PaperUnit(unit_id, latex, label)。
    - `first_seen` = 该符号第一次出现的那个单元的 `unit_id`。
    - `meaning` / `value` 一律 None：公式体里没有含义解释，也没有数值，
      猜一个数就是假数据（R22）。要补含义得靠论文正文，不是本切片的输入。
    """
    seen = {}
    for unit in getattr(bundle, "units", None) or []:
        latex = getattr(unit, "latex", "") or ""
        for match in _SUBSCRIPTED.finditer(latex):
            name = match.group(0)
            if name not in seen:
                seen[name] = {
                    "symbol": name,
                    "meaning": None,
                    "value": None,
                    "first_seen": unit.unit_id,
                }
    return list(seen.values())
