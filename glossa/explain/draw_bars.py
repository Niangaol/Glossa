"""R512：条形图与卡片图的真绘制（draw_bars.py）。

draw.py 只管节点/边那四种范式；bars 与 cards 的数据长在 fig["bars"] / fig["cards"] 上，
画法也不同（比例宽度、两列卡片），所以单独一份：

- bars：标签一列、条一列、数值一列；条宽按值比例给，最大值占满条区，值标在条右侧；
- cards：两列，逐行排；一张卡一行标题、一行摘要。

口径与 draw.py 一致：颜色只来自 CSS :root 的令牌（palette 传进来），标签先 html.escape 再按
显示宽度截断（汉字算 2 宽），坐标全是整数、不出 viewBox，同一输入两次逐字节相同——
所以三套风格的同一张条形图只差颜色。
"""

from __future__ import annotations

import html

PAD, GAP = 16, 18
ROW_H, LABEL_W, VALUE_W = 30, 150, 58      # 一行 30 高、标签列 150 宽、数值列 58 宽
CARD_H, CARD_GAP = 76, 14


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def clip(text: str, limit: int) -> str:
    """按显示宽度截断并加省略号：汉字/全角算 2 宽、其它算 1（limit 是宽度单位）。"""
    text, kept, used = str(text), [], 0
    for char in text:
        used += 2 if ord(char) > 0x2E7F else 1
        if used > limit:
            return "".join(kept) + "…"
        kept.append(char)
    return text


def text(x: int, y: int, size: int, body: str, color: str, anchor: str = "middle") -> str:
    return ('<text x="%d" y="%d" font-size="%d" fill="%s" text-anchor="%s">%s</text>'
            % (x, y, size, color, anchor, esc(body)))


def value_text(value) -> str:
    """值文本：整数不带小数点，小数最多一位且去掉末尾的 0。"""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return ("%.1f" % number).rstrip("0").rstrip(".")


def bar_width(value, widest, avail: int) -> int:
    """按值比例给宽度：最大值占满 avail；0 与负数给 0（照画一条，不藏数据）。"""
    if value <= 0 or widest <= 0:
        return 0
    return max(3, int(round(avail * float(value) / float(widest))))


def _open(width: int, height: int, aria: str) -> list[str]:
    return ['<svg class="graph" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d"'
            ' role="img" aria-label="%s">' % (width, height, esc(aria))]


def bars_svg(bars: list, width: int, pal: dict, aria: str) -> str:
    """真条形：每行一条，条宽 = 值 / 最大值 × 条区宽，值文本贴在条右侧。"""
    rows = [row for row in bars or () if isinstance(row, dict)]
    values = [float(row.get("value") or 0) for row in rows]
    widest = max(values or [0])
    left = PAD + LABEL_W
    avail = max(24, width - left - VALUE_W - PAD)
    out = _open(width, PAD * 2 + max(1, len(rows)) * ROW_H, aria)
    for pos, (row, value) in enumerate(zip(rows, values)):
        y = PAD + pos * ROW_H
        out.append(text(PAD, y + ROW_H // 2 + 4, 11,
                        clip(row.get("label") or "", (LABEL_W - 8) // 6), pal["ink"], "start"))
        out.append('<rect x="%d" y="%d" width="%d" height="%d" rx="4" fill="%s" stroke="%s"/>'
                   % (left, y + 6, bar_width(value, widest, avail), ROW_H - 12,
                      pal["accent"], pal["secondary"]))
        out.append(text(left + avail + 6, y + ROW_H // 2 + 4, 11, value_text(value),
                        pal["ink"], "start"))
    return "".join(out) + "</svg>"


def cards_svg(cards: list, width: int, pal: dict, aria: str) -> str:
    """两列卡片：左一张、右一张地往下排；标题一行、摘要一行，都按卡片宽度截断。"""
    rows = [row for row in cards or () if isinstance(row, dict)]
    card_w = (width - 2 * PAD - GAP) // 2
    lines = max(1, (len(rows) + 1) // 2)
    out = _open(width, PAD * 2 + lines * CARD_H + (lines - 1) * CARD_GAP, aria)
    for pos, row in enumerate(rows):
        x = PAD + (pos % 2) * (card_w + GAP)
        y = PAD + (pos // 2) * (CARD_H + CARD_GAP)
        out.append('<rect x="%d" y="%d" width="%d" height="%d" rx="6" fill="%s" stroke="%s"/>'
                   % (x, y, card_w, CARD_H, pal["paper"], pal["secondary"]))
        out.append(text(x + 10, y + 26, 12,
                        clip(row.get("label") or "", (card_w - 20) // 6), pal["ink"], "start"))
        out.append(text(x + 10, y + 52, 10,
                        clip(row.get("text") or "", (card_w - 20) // 6), pal["ink"], "start"))
    return "".join(out) + "</svg>"
