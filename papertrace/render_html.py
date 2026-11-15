"""S10：把 trace.json 渲染成单文件离线 HTML（零外部引用，CSS/SVG 全内联）。

五块：meta 契约来源 / 代码算子图（静态 SVG，按 parent_id 分组，标真实形状，
anchor 画彩线）/ 论文公式项清单 / 未对齐清单 / 符号表。
裁决口径：R96 形状口径（fmt_shape 与 report.fmt_shape 逐输入一致：None → (?)、
[] → () 是 0 维标量；inputs 数据入参三态照抄 print_ops）、R75 xmlns 是命名空间标识符
不是资源引用、R82 项清单取并集、R83 超 HTML_MAX_BYTES 抛 BuildError 绝不静默截断。
完整裁决记录见 .superpowers/sdd/2026-11-14-papertrace-spine/task-S10-report.md。
公式项清单的行构造在 papertrace/render_terms.py（R166 拆出：一条 anchor 一行，
逐层展开，OBS-L3-1）。
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from papertrace.constants import HTML_MAX_BYTES
from papertrace.exceptions import BuildError
from papertrace.render_terms import term_rows

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "htm", "j2")),
    # R98：模板路径笔误必须响亮抛 UndefinedError，不许静默渲染成空串
    undefined=StrictUndefined,
)

# tier → 线条样式；缺 tier / tier==none 一律不画线（R84：绝不许把 none 画成绿线）
_TIER_STYLE = {"green": ("lnk-green", "#1a7f37", False), "yellow": ("lnk-yellow", "#9a6700", True)}


def fmt_shape(shape) -> str:
    """R96：int 列表 → Python tuple repr；None → (?)；空列表 → ()（0 维标量）。

    R96 取代 R71 的空列表条款：必须与 papertrace/report.py 的 fmt_shape
    逐输入一致。「-」只属于 inputs（数据入参列表）的三态，绝不属于 shape——
    report.py:17 docstring：() 是 0 维标量；(?) 是形状未知。两者不能混为一谈。
    一致性由 test_spine_html.py::test_fmt_shape_matches_report 钉住；不许
    import report（它顶层 import build_trace，会把 torch 拖进纯渲染器的 import 图）。
    """
    if shape is None:
        return "(?)"
    if not shape:
        return "()"
    return "(" + ", ".join(str(dim) for dim in shape) + ")"


def _node_label(node: dict) -> str:
    if node.get("kind") == "op" and node.get("op"):
        return str(node["op"])
    label = node.get("label")
    return str(label) if label else str(node.get("id", ""))


def _loc_text(node: dict) -> tuple[str, str]:
    """R116：算子行显示 basename:line，完整路径留在 SVG <title> 里悬停可见。

    绝对路径不进正文：它会泄露本机目录，而正文要给人读。模块节点的 loc 是模块名
    （不是 file:line），原样不显示——同一字段两种语义是既有设计，不编模块行号。
    """
    short, full = _where_texts(str(node.get("loc") or ""))
    return (short, full) if full else ("", "")


def _where_texts(loc: str) -> tuple[str, str]:
    """R116 同口径：`<path>:<line>` → (basename:line, 完整路径)；形状不合法 → (原样, "")。"""
    head, sep, line = loc.rpartition(":")
    return ("%s:%s" % (Path(head).name, line), loc) if sep and line.isdigit() and head else (loc, "")


def _shape_texts(node: dict) -> tuple[str, str]:
    """inputs 三态口径与 papertrace/report.py 的 print_ops 逐字一致（R71 这半句没错）。"""
    known_out = bool(node.get("outputs")) or bool(node.get("shape_out"))
    shown_out = fmt_shape(node.get("shape_out")) if known_out else "(?)"
    if node.get("kind") != "op":
        shown_in = "-"
    elif node.get("inputs"):
        shown_in = fmt_shape(node.get("shape_in"))
    elif "inputs" in node:
        shown_in = "-"
    else:
        shown_in = "(?)"
    return shown_in, shown_out


def _groups(doc: dict) -> list[dict]:
    """按 parent_id 分组画 SVG；anchor 在该算子右侧画一条彩线并标 term_id。"""
    buckets: dict[str, list[dict]] = {}
    for node in doc.get("nodes") or []:
        if node.get("level") == "op":
            buckets.setdefault(str(node.get("parent_id") or ""), []).append(node)

    style_of: dict[str, tuple] = {}
    label_of: dict[str, str] = {}
    for anchor in doc.get("anchors") or []:
        code_id, tier = str(anchor.get("code_expr_range") or ""), anchor.get("tier")
        if code_id and tier in _TIER_STYLE:
            style_of[code_id] = _TIER_STYLE[tier]
            label_of[code_id] = "%s-t%s" % (
                anchor.get("paper_unit_id"), anchor.get("formula_term_index"))

    groups: list[dict] = []
    for parent in sorted(buckets):
        rows = sorted(buckets[parent], key=lambda n: str(n.get("id", "")))
        y_of = {str(node["id"]): 12 + 32 * i for i, node in enumerate(rows)}
        box_w = max([60] + [len(_node_label(n)) * 7 + 16 for n in rows])
        nodes_out, width = [], 0
        for node in rows:
            code_id = str(node["id"])
            shown_in, shown_out = _shape_texts(node)
            text = shown_in + " → " + shown_out
            right = box_w + 12 + len(text) * 6.5
            loc_short, loc_full = _loc_text(node)
            loc_x = int(right + 8) if loc_short else None
            if loc_short:
                right = loc_x + len(loc_short) * 6.5
            link = None
            if code_id in style_of:
                cls, stroke, dash = style_of[code_id]
                link = {"cls": cls, "stroke": stroke, "dash": dash,
                        "x": int(right + 6), "label": label_of[code_id]}
                right += 30 + len(link["label"]) * 6.5
            width = max(width, int(right))
            nodes_out.append({"y": y_of[code_id], "box_w": box_w, "label": _node_label(node),
                              "shape_in": shown_in, "shape_out": shown_out, "link": link,
                              "loc_short": loc_short, "loc_full": loc_full, "loc_x": loc_x})
        groups.append({"parent": parent or "（无 parent_id）", "width": width + 8,
                       "height": 12 + 32 * len(rows), "nodes": nodes_out})
    return groups


def _symbol_rows(doc: dict) -> list[dict]:
    """代码侧 / 论文侧符号与映射；骨架模式代码侧为空，如实显示（R116：where 只显 basename:line）。"""
    symbols = doc.get("symbols") or {}
    rows: list[dict] = []
    for s in symbols.get("code") or []:
        where, where_full = _where_texts(str(s.get("defined_at") or "-"))
        rows.append({"side": "代码", "name": s.get("var") or s.get("symbol"), "value": s.get("value"),
                     "meaning": s.get("symbol") or "-", "where": where, "where_full": where_full, "maps_to": "-"})
    for s in symbols.get("paper") or []:
        where, where_full = _where_texts(str(s.get("first_seen") or "-"))
        rows.append({"side": "论文", "name": s.get("symbol"),
                     "value": s.get("value") if s.get("value") is not None else "-",
                     "meaning": s.get("meaning") or "-", "where": where, "where_full": where_full, "maps_to": "-"})
    for m in symbols.get("mapping") or []:
        code_var = m.get("code_var") or "?"
        paper_symbol = m.get("paper_symbol")
        rows.append({"side": "映射", "name": "%s → %s" % (code_var, paper_symbol or "-"),
                     "value": m.get("value") if m.get("value") is not None else "-",
                     "meaning": m.get("status") or "-", "where": "-", "where_full": "",
                     "maps_to": paper_symbol or "-"})
    return rows


def render_html(doc: dict) -> str:
    """把 trace dict 渲染成单文件离线 HTML；超 HTML_MAX_BYTES 抛 BuildError（R83）。"""
    meta = doc.get("meta") or {}
    html = _ENV.get_template("spine.html.j2").render(
        repo_name=Path(str((meta.get("repo") or {}).get("url") or "unknown")).name,
        doc=doc, groups=_groups(doc), terms=term_rows(doc), symbol_rows=_symbol_rows(doc),
    )
    size = len(html.encode("utf-8"))
    if size > HTML_MAX_BYTES:
        raise BuildError(
            "渲染出的 HTML 有 %d 字节，超过上限 %d；不静默截断，请缩小 trace 或调高上限"
            % (size, HTML_MAX_BYTES)
        )
    return html


def write_html(doc: dict, out_dir) -> Path:
    """R74：index.html 是派生产物，每次 build 都覆盖，不受 --force 约束。

    dump_trace 的 overwrite 只管 trace.json；这里永远重写。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "index.html"
    target.write_text(render_html(doc) + "\n", encoding="utf-8")
    return target
