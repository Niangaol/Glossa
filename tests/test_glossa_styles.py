"""A2：三套风格 CSS 与九个 class 词汇表（styles.py + templates/styles/*.css）。

契约来自派发书 §1/§2 与 docs/superpowers/specs/2026-11-17-glossa-styles.md：
三套 CSS 都必须覆盖全部 9 个 class、零外链零 @import、带 reduced-motion 与 720px 断点、
正文 16px / 行高 1.85 / 行宽 ≤72 字符；normalize_classes 把词汇表外的 class 改名为 x- 前缀。
"""
import pathlib
import re

import pytest

from glossa.explain import styles

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSS_DIR = ROOT / "glossa" / "templates" / "styles"
NAMES = ("magazine", "report", "cards")


def _css(name):
    return styles.load_css(name)


def test_style_names_order_is_fixed_and_styles_cover_them():
    assert styles.style_names() == NAMES
    assert tuple(styles.STYLES) == NAMES
    assert styles.CLASSES == ("lead", "grid", "card", "steps", "note", "cols", "scope", "kbd", "toc")
    for name in NAMES:
        spec = styles.STYLES[name]
        assert spec["title"] and spec["summary"] and spec["css"]
        assert isinstance(spec["layout"], dict)


def test_all_three_styles_load_and_are_real_css():
    for name in NAMES:
        css = _css(name)
        assert len(css) > 2000, (name, len(css))
        assert css.count("{") == css.count("}"), name
        assert ":root" in css and "--ink" in css, name


def test_unknown_style_error_lists_the_three_names():
    with pytest.raises(ValueError) as info:
        styles.load_css("brutalist")
    message = str(info.value)
    assert "brutalist" in message
    for name in NAMES:
        assert name in message
    with pytest.raises(ValueError):
        styles.layout("brutalist")


def test_every_style_defines_a_rule_for_each_of_the_nine_classes():
    for name in NAMES:
        css = _css(name)
        missing = [cls for cls in styles.CLASSES
                   if not re.search(r"(?<![\w-])\." + cls + r"\b", css)]
        assert not missing, (name, missing)


def test_no_import_url_external_font_or_fixed_position():
    for name in NAMES:
        css = _css(name)
        assert "@import" not in css, name
        assert "url(" not in css, name
        assert "http://" not in css and "https://" not in css, name
        assert "@font-face" not in css, name
        assert "position: fixed" not in css and "position:fixed" not in css, name


def test_each_style_has_reduced_motion_and_mobile_blocks():
    for name in NAMES:
        css = _css(name)
        assert "@media (prefers-reduced-motion: reduce)" in css, name
        block = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}",
                          css, re.S)
        assert block, name
        body = block.group(1)
        assert "animation: none" in body and "transition: none" in body, name
        mobile = re.search(r"@media \(max-width: 720px\)\s*\{(.*?)\n\}", css, re.S)
        assert mobile, name
        assert len(mobile.group(1)) > 80, name


def test_body_typography_matches_the_spec():
    for name in NAMES:
        css = _css(name)
        assert re.search(r"font-size:\s*16px", css), name
        assert "1.85" in css, name
        measures = [int(value) for value in re.findall(r"max-width:\s*(\d+)ch", css)]
        assert measures, name
        assert max(measures) <= 72, (name, measures)


PALETTE = {
    "magazine": ("#f6f3ec", "#14161a", "#b23a2a", "#2f4f52", "#d9d3c6"),
    "report": ("#ffffff", "#101318", "#e2e6ec", "#2563eb", "#0891b2"),
    "cards": ("#faf7f1", "#1b1a17", "#c2452d", "#1f4e4a", "#e0d9cc"),
}


def test_each_style_uses_the_palette_from_the_spec():
    for name, colors in PALETTE.items():
        css = _css(name).lower()
        missing = [color for color in colors if color not in css]
        assert not missing, (name, missing)


def test_every_css_file_exists_on_disk():
    for name in NAMES:
        path = CSS_DIR / (name + ".css")
        assert path.is_file(), path
        assert path.read_text(encoding="utf-8") == _css(name)


def test_normalize_classes_prefixes_unknown_and_counts():
    html = '<section><p class="lead">x</p><div class="grid cards charts">y</div></section>'
    new, renamed, notes = styles.normalize_classes(html)
    assert renamed == 2
    assert 'class="lead"' in new
    assert 'class="grid x-cards x-charts"' in new
    assert len(notes) == 2
    assert any("cards" in note and "x-cards" in note for note in notes)


def test_normalize_classes_leaves_known_classes_alone():
    html = "".join('<p class="%s">t</p>' % cls for cls in styles.CLASSES)
    new, renamed, notes = styles.normalize_classes(html)
    assert new == html
    assert renamed == 0
    assert notes == []


def test_normalize_classes_reports_a_repeated_unknown_class_only_once():
    html = '<p class="odd">a</p><p class="odd grid">b</p><p class="odd">c</p>'
    new, renamed, notes = styles.normalize_classes(html)
    assert renamed == 3
    assert new.count("x-odd") == 3
    matches = [note for note in notes if "odd" in note]
    assert len(matches) == 1, matches


def test_layout_has_the_three_keys_with_typed_values():
    for name in NAMES:
        layout = styles.layout(name)
        assert set(layout) == {"max_width", "columns", "note_side"}
        assert isinstance(layout["max_width"], int) and layout["max_width"] >= 600
        assert isinstance(layout["columns"], int) and layout["columns"] in (1, 2)
        assert isinstance(layout["note_side"], bool)
    assert styles.layout("magazine")["note_side"] is True
    assert styles.layout("report")["max_width"] == 960
    assert styles.layout("cards")["columns"] == 2
    first = styles.layout("magazine")
    first["max_width"] = 1
    assert styles.layout("magazine")["max_width"] != 1

def test_h2_numbers_come_from_markup_not_css_counters():
    """A5 把章节序号写进正文（<span class="no">01</span>）。

    CSS 若再自带 counter 编号，真页会出现「01 / 01 标题」的双序号（A5 报告 §3.1 A5-③）。
    结构类名也统一成 section.sec，不许留下 A2 草案里的 section.blk。
    """
    for name in NAMES:
        css = _css(name)
        assert "counter-increment: section" not in css, name
        assert "h2::before" not in css, name
        assert "section.blk" not in css, name
    for name in ("magazine", "cards"):
        assert "h2 .no" in _css(name), name
