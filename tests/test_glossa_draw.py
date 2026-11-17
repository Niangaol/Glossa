"""A4：draw.py —— 六种范式画出确定性的图（派发书 §1）。

只断言契约：figure/svg 外壳、范式名、节点与边画出来、同一输入逐字节相同、
三套风格只换颜色、标签转义与截断、未知范式响亮报错、60 个节点不溢出 viewBox。
"""
import re

import pytest

from glossa.explain.draw import draw_figure
from glossa.explain.patterns import PATTERNS

NAMES = ("layered", "flow", "matrix", "tree", "bars", "cards")
_RECT = re.compile(r'<rect x="(-?\d+)" y="(-?\d+)" width="(\d+)" height="(\d+)"')
_VIEW = re.compile(r'viewBox="0 0 (\d+) (\d+)"')


def _fig(pattern="layered", count=2, **extra):
    """最小 clean_fig：count 个节点 + 一条边，与 validate_figure 的返回同形。"""
    nodes = [{"id": "n%d" % i, "label": "f%d.ts" % i} for i in range(count)]
    fig = {"pattern": pattern, "caption": "谁依赖谁", "nodes": nodes,
           "edges": [{"from": "n0", "to": "n1", "label": "import"}] if count > 1 else [],
           "groups": []}
    return fig | extra


def test_six_patterns_draw_a_figure_with_their_nodes():
    for name in NAMES:
        out = draw_figure(_fig(name, 3), "report")
        assert out.startswith('<figure class="fig" data-pattern="%s">' % name), name
        assert '<svg class="graph" xmlns="http://www.w3.org/2000/svg"' in out, name
        assert out.endswith("</figure>") and "<figcaption>谁依赖谁</figcaption>" in out, name
        assert "f0.ts" in out and out.count("<rect ") == 3, name


def test_the_node_bearing_pattern_examples_still_draw_their_labels():
    expected = {"layered": "a.ts", "flow": "a.ts 入口", "matrix": "b.ts", "tree": "仓库根"}
    for name, label in expected.items():
        assert name in PATTERNS
        out = draw_figure(PATTERNS[name]["example"], "magazine")
        assert label in out, (name, label)


def test_unknown_pattern_raises_with_its_name_and_the_six_known_ones():
    with pytest.raises(ValueError) as info:
        draw_figure(_fig("sunburst"), "report")
    message = str(info.value)
    assert "sunburst" in message
    for name in NAMES:
        assert name in message, name


def test_same_input_twice_is_byte_identical():
    fig = _fig("layered", 3)
    assert draw_figure(fig, "report") == draw_figure(fig, "report")


def test_three_styles_only_change_the_palette():
    fig = _fig("layered", 3)
    outputs = {name: draw_figure(fig, name) for name in ("magazine", "report", "cards")}
    assert len(set(outputs.values())) == 3
    for name, out in outputs.items():
        assert "#000000" not in out.lower(), name
    assert "#14161a" in outputs["magazine"]      # magazine 的 --ink
    assert "#101318" in outputs["report"]        # report 的 --ink
    assert "#1b1a17" in outputs["cards"]         # cards 的 --ink


def test_label_with_markup_is_escaped():
    fig = _fig("layered", 2)
    fig["nodes"][0]["label"] = '<script>alert(1)</script>&'
    out = draw_figure(fig, "report")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;&amp;" in out
    assert "<script>" not in out


def test_long_cjk_label_is_truncated_with_an_ellipsis():
    fig = _fig("layered", 2)
    fig["nodes"][0]["label"] = "超长中文标签" * 12
    out = draw_figure(fig, "report")
    assert "…" in out
    assert "超长中文标签" * 12 not in out


def test_edges_are_drawn_as_arrowed_paths_with_their_label():
    fig = _fig("flow", 3)
    out = draw_figure(fig, "report")
    assert "<path d=" in out and 'marker-end="url(#fig-arrow-flow)"' in out
    assert ">import<" in out


def test_sixty_nodes_stay_inside_the_viewbox_for_all_six_patterns():
    for name in NAMES:
        out = draw_figure(_fig(name, 60), "cards")
        found = _VIEW.search(out)
        assert found, name
        width, height = int(found.group(1)), int(found.group(2))
        assert width == 720 and height > 0, name
        rects = _RECT.findall(out)
        assert len(rects) == 60, (name, len(rects))
        for x, y, w, h in rects:
            assert int(x) >= 0 and int(y) >= 0, name
            assert int(x) + int(w) <= width, (name, x, w, width)
            assert int(y) + int(h) <= height, (name, y, h, height)


def test_zero_nodes_still_render_a_legal_figure():
    out = draw_figure({"pattern": "tree", "caption": "", "nodes": [], "edges": [], "groups": []},
                      "report")
    assert 'data-pattern="tree"' in out and "<svg " in out
    width, height = _VIEW.search(out).groups()
    assert int(width) > 0 and int(height) > 0
