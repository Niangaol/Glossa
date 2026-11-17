"""A4：六种图表范式的确定性程序绘制（draw.py）。

输入是 A2 的 clean_fig（validate_figure 洗过：pattern/caption/nodes/edges/groups），
这里只管坐标、箭头、颜色与标签截断——AI 不写一个坐标。六种范式与 patterns.PATTERNS
同名：layered 按 groups 横向分层、flow 从左到右逐步、matrix 两列网格、tree 自顶向下、
bars 单列条形清单、cards 两列卡片。（派发书里的 layers/chain/radial 在 A2 契约里不存在。）

配色不写死：STYLES 只带版式参数，颜色是 CSS :root 的令牌，所以解析
styles.load_css(style) 的墨/纸/主色/次色再落到 SVG，代码里没有 hex。同一输入两次输出
逐字节相同：不取时间、不遍历无序集合；标签先 html.escape 再按显示宽度截断（中文按 2 宽估）。
所有坐标是整数，节点 x + 宽 <= width，60 个节点也不溢出 viewBox。
"""

from __future__ import annotations

import html
import re

from glossa.explain import styles
from glossa.explain.patterns import PATTERNS

PAD, GAP, BOX_H, STEP, MIN_BOX = 16, 18, 30, 40, 40
_ROOT = re.compile(r":root\s*\{(.*?)\}", re.S)
_TOKEN = re.compile(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;")
_ALIASES = {"ink": ("--ink",), "paper": ("--paper", "--bg"),
            "accent": ("--zhu", "--accent", "--tone"),
            "secondary": ("--dai", "--accent2", "--song")}


def _esc(text) -> str:
    return html.escape(str(text), quote=True)


def palette(style: str) -> dict:
    """风格 → 墨/纸/主色/次色；颜色只在 CSS 的 :root 令牌里有真源，缺了不猜。"""
    block = _ROOT.search(styles.load_css(style))
    tokens = dict(_TOKEN.findall(block.group(1) if block else ""))
    out = {key: next((tokens[name] for name in names if name in tokens), "")
           for key, names in _ALIASES.items()}
    if not all(out.values()):
        raise ValueError("风格 %r 的 CSS 缺少墨/纸/主色/次色之一" % (style,))
    return out


def _clip(text: str, limit: int) -> str:
    """按显示宽度截断并加省略号：汉字/全角算 2 宽、其它算 1（limit 是宽度单位）。"""
    text, kept, used = str(text), [], 0
    for char in text:
        used += 2 if ord(char) > 0x2E7F else 1
        if used > limit:
            return "".join(kept) + "…"
        kept.append(char)
    return text


def _chunks(items: list, size: int) -> list:
    return [items[pos:pos + size] for pos in range(0, len(items), size)]


def _box(item: dict, x: int, y: int, w: int, h: int) -> dict:
    """一个方框：标签取 label/path/id，第二行小字取 kind 或 summary。"""
    label = item.get("label") or item.get("path") or item.get("id") or ""
    sub = item.get("summary") or item.get("kind") or ""
    return {"id": str(item.get("id") or ""), "label": str(label), "sub": str(sub),
            "x": x, "y": y, "w": w, "h": h}


def _stack(rows: list, width: int, box_h: int, step: int) -> tuple:
    """行 → (宽, 高, 方框)：列宽按最宽一行平分、每行居中；一行太宽就折成几行。"""
    limit = max(1, (width - 2 * PAD + GAP) // (MIN_BOX + GAP))
    rows = [part for row in rows for part in _chunks(row, limit)]
    if not rows:
        return width, 2 * PAD + box_h, []
    widest = max(len(row) for row in rows)
    box_w = max(24, (width - 2 * PAD - (widest - 1) * GAP) // widest)
    boxes = []
    for index, row in enumerate(rows):
        left = max(PAD, (width - (len(row) * box_w + (len(row) - 1) * GAP)) // 2)
        boxes += [_box(item, left + col * (box_w + GAP), PAD + index * step, box_w, box_h)
                  for col, item in enumerate(row)]
    return width, PAD + (len(rows) - 1) * step + box_h + PAD, boxes


def _layered(nodes: list, width: int, groups: list) -> tuple:
    """横向分层：groups 是层（A2 示例按包分组）；没给分组就每 4 个节点一层。"""
    columns = [[node for node in nodes
                if str(node.get("id")) in {str(m) for m in group.get("members") or ()}]
               for group in groups]
    columns = [row for row in columns if row]
    placed = {str(node.get("id")) for row in columns for node in row}
    columns += _chunks([node for node in nodes if str(node.get("id")) not in placed], 4)
    if len(columns) > 5:                  # 60 节点极限链：退化成 5 列，不许溢出
        return _stack(_chunks(nodes, 5), width, BOX_H, BOX_H + 40)
    box_w = max(24, (width - 2 * PAD - (len(columns) - 1) * GAP) // max(1, len(columns)))
    boxes = [_box(node, PAD + col * (box_w + GAP), PAD + row * (BOX_H + 14), box_w, BOX_H)
             for col, column in enumerate(columns) for row, node in enumerate(column)]
    bottom = max([box["y"] + box["h"] for box in boxes] or [PAD + BOX_H])
    return width, max(bottom + PAD, 2 * PAD + BOX_H), boxes


def _tree(nodes: list, width: int) -> tuple:
    """自顶向下：同一父亲深度成一行，每行居中；parent 成环/不存在就停在当前行。"""
    by_id = {str(node.get("id")): node for node in nodes}

    def depth(node, seen):
        parent = node.get("parent")
        return 0 if parent not in by_id or parent in seen else 1 + depth(
            by_id[parent], seen | {parent})

    rows: dict = {}
    for node in nodes:
        rows.setdefault(depth(node, {str(node.get("id"))}), []).append(node)
    return _stack([rows[key] for key in sorted(rows)], width, BOX_H, STEP)


def _layout(fig: dict, pattern: str, width: int) -> tuple:
    """范式 → (宽, 高, 方框)；坐标只在这里算一次，渲染只照抄。"""
    nodes = [node for node in fig.get("nodes") or () if isinstance(node, dict)]
    if pattern == "flow":
        order = sorted(enumerate(nodes), key=lambda pair: (pair[1].get("step") or 0, pair[0]))
        return _stack(_chunks([node for _, node in order], 4), width, BOX_H, BOX_H + 40)
    if pattern == "layered":
        groups = [group for group in fig.get("groups") or () if isinstance(group, dict)]
        return _layered(nodes, width, groups)
    if pattern == "tree":
        return _tree(nodes, width)
    height, per_row = (24, 1) if pattern == "bars" else (56, 2) if pattern == "cards" else (36, 2)
    return _stack(_chunks(nodes, per_row), width, height, height + 18)


def _anchors(src: dict, dst: dict) -> tuple:
    """连线两端落在方框边缘：横向差大走左右边，否则走上下边。"""
    sx, sy = src["x"] + src["w"] // 2, src["y"] + src["h"] // 2
    tx, ty = dst["x"] + dst["w"] // 2, dst["y"] + dst["h"] // 2
    if abs(tx - sx) >= abs(ty - sy):
        return ((src["x"] + src["w"] if tx > sx else src["x"], sy),
                (dst["x"] if tx > sx else dst["x"] + dst["w"], ty))
    return ((sx, src["y"] + src["h"] if ty > sy else src["y"]),
            (tx, dst["y"] if ty > sy else dst["y"] + dst["h"]))


def _text(x: int, y: int, size: int, text: str, color: str) -> str:
    return ('<text x="%d" y="%d" font-size="%d" fill="%s" text-anchor="middle">%s</text>'
            % (x, y, size, color, _esc(text)))


def _svg(pattern: str, width: int, height: int, boxes: list, edges: list, pal: dict,
         aria: str) -> str:
    """画布：marker 定义 + 边 + 方框 + 文字；除了 xmlns 不引任何外链（GC23）。"""
    marker = "fig-arrow-%s" % pattern
    out = ['<svg class="graph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d"'
           ' role="img" aria-label="%s">' % (width, height, _esc(aria)),
           '<defs><marker id="%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6"'
           ' markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker></defs>'
           % (marker, pal["secondary"])]
    place = {box["id"]: box for box in boxes if box["id"]}
    for edge in edges:
        src, dst = place.get(str(edge.get("from"))), place.get(str(edge.get("to")))
        if not src or not dst or src is dst:
            continue
        (x1, y1), (x2, y2) = _anchors(src, dst)
        out.append('<path d="M%d %d L%d %d" fill="none" stroke="%s" stroke-width="1.2"'
                   ' marker-end="url(#%s)"/>' % (x1, y1, x2, y2, pal["secondary"], marker))
        if edge.get("label"):
            out.append(_text((x1 + x2) // 2, (y1 + y2) // 2 - 4, 9,
                             _clip(edge["label"], 15), pal["secondary"]))
    for box in boxes:
        shown = _clip(box["label"], (box["w"] - 12) // 6)
        out.append('<g><title>%s</title><rect x="%d" y="%d" width="%d" height="%d" rx="6"'
                   ' fill="%s" stroke="%s"/></g>' % (_esc(shown), box["x"], box["y"], box["w"],
                                                    box["h"], pal["paper"], pal["secondary"]))
        out.append(_text(box["x"] + box["w"] // 2, box["y"] + box["h"] // 2 + 4, 11, shown,
                         pal["ink"]))
    return "".join(out) + "</svg>"


def draw_figure(fig: dict, style: str, *, width: int = 720) -> str:
    """clean_fig → <figure class="fig" data-pattern=…>；未知范式 ValueError 并列六种。"""
    pattern = fig.get("pattern") if isinstance(fig, dict) else None
    if pattern not in PATTERNS:
        raise ValueError("不认识的图表范式 %r；只有六种：%s" % (pattern, "、".join(PATTERNS)))
    if int(width) < 200:
        raise ValueError("图表宽度至少 200px，收到 %r" % (width,))
    canvas_w, height, boxes = _layout(fig, pattern, int(width))
    caption = str(fig.get("caption") or "")
    return ('<figure class="fig" data-pattern="%s">%s<figcaption>%s</figcaption></figure>'
            % (pattern, _svg(pattern, canvas_w, height, boxes, fig.get("edges") or [],
                             palette(style), caption or "图表：%s" % pattern), _esc(caption)))
