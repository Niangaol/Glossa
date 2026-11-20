"""A9 / R512：bars / cards 的真绘制（draw.py + draw_bars.py）。

派发书 §R512 的硬要求：bars 图 <rect> 数量 == 数据条数；最宽条对应最大值；值文本出现；
label 转义并截断；cards 两列；三套风格只差颜色；缺数据时退回清单形态、不许崩。
"""
import re

from glossa.explain.draw import draw_figure

_RECT = re.compile(r'<rect x="(-?\d+)" y="(-?\d+)" width="(\d+)" height="(\d+)"')
_VIEW = re.compile(r'viewBox="0 0 (\d+) (\d+)"')
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}")
BARS = [{"label": "文件", "value": 120}, {"label": "符号", "value": 40},
        {"label": "依赖", "value": 8}]


def _bars_fig(bars=None):
    return {"pattern": "bars", "caption": "三个数字放一起比大小", "nodes": [], "edges": [],
            "groups": [], "bars": [dict(row) for row in (bars if bars is not None else BARS)]}


def _cards_fig(cards=None):
    rows = cards if cards is not None else [
        {"label": "a.py", "text": "入口"}, {"label": "b.py", "text": "工具"},
        {"label": "c.py", "text": "模型"}, {"label": "d.py", "text": "测试"}]
    return {"pattern": "cards", "caption": "关键文件一览", "nodes": [], "edges": [],
            "groups": [], "cards": [dict(row) for row in rows]}


def test_one_rect_per_bar_and_the_value_text_shows_up():
    out = draw_figure(_bars_fig(), "report")
    assert out.startswith('<figure class="fig" data-pattern="bars">')
    assert len(_RECT.findall(out)) == len(BARS)
    for value in (120, 40, 8):
        assert ">%d</text>" % value in out, value
    assert "文件" in out and "符号" in out


def test_the_widest_bar_belongs_to_the_largest_value():
    out = draw_figure(_bars_fig(), "report")
    widths = [int(row[2]) for row in _RECT.findall(out)]
    assert widths[0] == max(widths)
    assert widths[0] > widths[1] > widths[2]


def test_bar_labels_are_escaped_and_clipped():
    fig = _bars_fig([{"label": "<script>&", "value": 5},
                     {"label": "超长中文标签" * 30, "value": 3}])
    out = draw_figure(fig, "report")
    assert "<script>" not in out
    assert "&lt;script&gt;&amp;" in out
    assert "…" in out


def test_zero_and_negative_values_still_draw_legal_bars():
    fig = _bars_fig([{"label": "零", "value": 0}, {"label": "负", "value": -5},
                     {"label": "正", "value": 10}])
    out = draw_figure(fig, "report")
    rects = _RECT.findall(out)
    assert len(rects) == 3
    width, height = (int(part) for part in _VIEW.search(out).groups())
    assert width == 720
    for x, y, w, h in rects:
        assert int(x) >= 0 and int(x) + int(w) <= width
        assert int(y) >= 0 and int(y) + int(h) <= height
        assert int(w) >= 0


def test_bars_without_data_fall_back_to_the_node_list():
    fig = {"pattern": "bars", "caption": "c",
           "nodes": [{"id": "n0", "label": "a.py"}, {"id": "n1", "label": "b.py"}],
           "edges": [], "groups": []}
    out = draw_figure(fig, "report")
    assert len(_RECT.findall(out)) == 2
    assert "a.py" in out and "b.py" in out


def test_cards_are_drawn_in_two_columns():
    out = draw_figure(_cards_fig(), "report")
    rects = _RECT.findall(out)
    assert len(rects) == 4
    assert len({row[0] for row in rects}) == 2, rects
    width = int(_VIEW.search(out).group(1))
    half = (width - 2 * 16 - 18) // 2                  # PAD / GAP 与 draw_bars 同一口径
    for x, _y, w, _h in rects:
        assert int(w) <= half, "一张卡不许占满整行（两列排布）"
        assert int(x) >= 0 and int(x) + int(w) <= width
    for text in ("a.py", "入口", "d.py", "测试"):
        assert text in out, text


def test_cards_without_data_fall_back_to_the_node_list():
    fig = {"pattern": "cards", "caption": "c",
           "nodes": [{"id": "n0", "label": "a.py"}], "edges": [], "groups": []}
    out = draw_figure(fig, "report")
    assert len(_RECT.findall(out)) == 1 and "a.py" in out


def test_three_styles_only_change_the_colours_of_a_bar_chart():
    outputs = {name: draw_figure(_bars_fig(), name) for name in ("magazine", "report", "cards")}
    assert len(set(outputs.values())) == 3
    stripped = {_HEX.sub("", out) for out in outputs.values()}
    assert len(stripped) == 1, "bars 的三套风格只许换颜色"
