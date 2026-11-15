"""S10 公式项清单的行构造：一条 anchor 一行，逐层展开不许合并。

R166：从 render_html.py 拆出来。原 _terms 拿 term_id 当字典键，两层的同名项
（S3.2-eq-attn-t0 在 h.0 与 h.1 各一条 anchor）被后写覆盖，8 条 anchor 只剩
4 行，h.1 整层从页面上静默消失——OBS-L3-1。R161 逐层展开后一项一层各占一行；
层列取 anchor["code_group"] 去掉顶层模块前缀（第一段及其 /）后的组路径
（R163/R176：结构路径必填、回退路径不写这个键，
显示 U+2014 破折号）。排序先 term_id 再 layer，两层相邻且顺序稳定。
"""

from __future__ import annotations

import re

_TERM_REF = re.compile(r"^(?P<unit>.+)-t(?P<index>\d+)$")
_NO_LAYER = "—"  # U+2014：回退路径 / unresolved 行没有层可言


def _layer_of(anchor: dict) -> str:
    """R161/R163/R176：层列去掉顶层模块前缀（第一段及其 /）后的组路径。

    回退路径没有 code_group → 破折号；组 id 没有 / 时原样返回（不发明截断规则）。
    """
    group = str(anchor.get("code_group") or "")
    if "/" in group:
        return group.split("/", 1)[1]
    return group or _NO_LAYER


def term_rows(doc: dict) -> list[dict]:
    """R82：项清单 = anchors（一行一条）∪ unresolved 里形如 *-t<N> 的 paper_unit。

    每行键：term_id / tier / confidence / aten_ops / evidence / layer。
    layer 取 anchor["code_group"] 去掉顶层模块前缀后的组路径
    （"transformer.h.1.attn"）；回退路径的 anchor 没有
    code_group → "—"（U+2014），unresolved 行的 layer 同样是 "—"。
    排序先 term_id 再 layer（"transformer.h.0.attn" < "transformer.h.1.attn"），保证确定性。
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for anchor in doc.get("anchors") or []:
        term_id = "%s-t%s" % (anchor.get("paper_unit_id"), anchor.get("formula_term_index"))
        seen.add(term_id)
        rows.append({"term_id": term_id, "tier": anchor.get("tier") or "none",
                     "confidence": anchor.get("confidence"),
                     "aten_ops": ", ".join(anchor.get("aten_ops") or []) or "-",
                     "evidence": anchor.get("evidence") or "",
                     "layer": _layer_of(anchor)})
    for entry in doc.get("unresolved") or []:
        ref = str(entry.get("ref") or "")
        if entry.get("kind") == "paper_unit" and _TERM_REF.match(ref) and ref not in seen:
            seen.add(ref)
            rows.append({"term_id": ref, "tier": "none", "confidence": None,
                         "aten_ops": "-", "evidence": entry.get("reason") or "",
                         "layer": _NO_LAYER})
    rows.sort(key=lambda row: (row["term_id"], row["layer"]))
    return rows
