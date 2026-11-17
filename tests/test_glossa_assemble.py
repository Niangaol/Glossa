"""A5：assemble.py + ai_page.html.j2 —— 外壳、目录与风格注入（派发书 §3）。

口径：<main> 里的标记（section/id、h2 两位序号、class）与风格无关，风格只进 <style>
与图配色（draw.palette 读 CSS :root 的墨/纸/主色/次色）。所以「逐字节相同」在无图的节
上直接比；有图的节另比「把颜色换成占位符后逐字节相同」，两种都证明内容不随风格变。
"""

import re

import pytest

from glossa.explain import assemble, gates, styles
from papertrace.exceptions import BuildError

NAMES = ("magazine", "report", "cards")
_SECTION = re.compile(r'<section class="sec" id="s-(\d+)">')
_HREF = re.compile(r'<a href="#s-(\d+)">')
_H2NO = re.compile(r'<h2><span class="no">(\d\d)</span>')
_STYLE = re.compile(r"<style>(.*?)</style>", re.S)
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _doc():
    return {"totals": {"files": 12, "symbols": 3400, "packages": 3, "entries": 2},
            "meta": {"repo": {"root_name": "SafeTrace"}}}


def _fig():
    return {"pattern": "layered", "caption": "谁依赖谁", "groups": [],
            "nodes": [{"id": "a", "label": "a.ts"}, {"id": "b", "label": "b.ts"}],
            "edges": [{"from": "a", "to": "b", "label": "import"}]}


def _sections(count=3, figures=False):
    return [{"title": "第 %d 节" % pos, "html": '<p class="lead">正文 %d</p>' % pos,
             "figures": [_fig()] if figures else [], "notes": ["旁注 %d" % pos]}
            for pos in range(count)]


def test_section_count_matches_the_number_of_ai_sections():
    page = assemble.build_page(_doc(), _sections(4), "report", mode="ai")
    assert len(_SECTION.findall(page)) == 4
    assert _SECTION.findall(page) == ["1", "2", "3", "4"]


def test_toc_has_one_link_per_section_pointing_at_its_id():
    page = assemble.build_page(_doc(), _sections(5), "report", mode="ai")
    links = _HREF.findall(page)
    assert len(links) == 5 and links == _SECTION.findall(page)
    assert page.index('<nav class="toc"') < page.index('<main>')


def test_every_h2_starts_with_a_two_digit_number():
    page = assemble.build_page(_doc(), _sections(3), "cards", mode="ai")
    assert _H2NO.findall(page) == ["01", "02", "03"]
    assert "<span class=\"no\">01</span>第 0 节" in page


def test_figures_are_drawn_as_svg_by_the_drawer():
    main = assemble.build_main(_sections(2, figures=True), "magazine")
    assert main.count('<figure class="fig" data-pattern="layered">') == 2
    assert main.count('<svg class="graph" xmlns="http://www.w3.org/2000/svg"') == 2
    assert main.count("<rect ") == 4


def test_notes_land_inside_their_own_section_only():
    page = assemble.build_page(_doc(), _sections(3), "report", mode="ai")
    parts = page.split('<section class="sec"')[1:]
    assert "旁注 0" in parts[0] and "旁注 1" not in parts[0]
    assert "旁注 2" in parts[2]
    assert '<p class="note">旁注 1</p>' in parts[1]


def test_three_styles_give_byte_identical_main_markup():
    outputs = {name: assemble.build_main(_sections(3), name) for name in NAMES}
    assert len(set(outputs.values())) == 1, {n: len(o) for n, o in outputs.items()}


def test_figures_change_only_their_colours_across_the_three_styles():
    outputs = {name: assemble.build_main(_sections(1, figures=True), name) for name in NAMES}
    assert len(set(outputs.values())) == 3, "图配色应当随风格变（draw.palette）"
    plain = {name: _HEX.sub("#-", out) for name, out in outputs.items()}
    assert len(set(plain.values())) == 1, "除颜色外，图与正文的标记必须逐字节相同"


def test_three_styles_embed_different_css_but_the_same_style_element():
    pages = {name: assemble.build_page(_doc(), _sections(2), name, mode="ai") for name in NAMES}
    styles_seen = {name: _STYLE.search(page).group(1) for name, page in pages.items()}
    assert len(set(styles_seen.values())) == 3
    for name, css in styles_seen.items():
        assert css == styles.load_css(name)
        assert _STYLE.findall(pages[name]) == [css], "只能有一个内联 <style>"


def test_page_is_offline_no_script_and_no_link_except_the_svg_namespace():
    page = assemble.build_page(_doc(), _sections(2, figures=True), "magazine", mode="ai")
    assert "<script" not in page.lower()
    assert "https://" not in page
    assert page.replace('xmlns="http://www.w3.org/2000/svg"', "").count("http://") == 0


def test_empty_sections_still_render_an_honest_page():
    page = assemble.build_page(_doc(), [], "report", mode="program")
    assert "<section" not in page
    assert assemble.EMPTY_TEXT in page
    assert '<nav class="toc"' not in page
    assert assemble.build_main([], "cards") == '<p class="lead">%s</p>' % assemble.EMPTY_TEXT


def test_oversized_page_raises_build_error_before_writing(monkeypatch):
    monkeypatch.setattr(gates, "MAX_PAGE_BYTES", 400)
    with pytest.raises(BuildError) as info:
        assemble.build_page(_doc(), _sections(3), "report", mode="ai")
    message = str(info.value)
    assert "400" in message and "字节" in message


def test_unknown_style_raises_value_error_listing_the_three():
    with pytest.raises(ValueError) as info:
        assemble.build_page(_doc(), _sections(1), "brutalist", mode="ai")
    for name in NAMES:
        assert name in str(info.value)
    with pytest.raises(ValueError):
        assemble.build_main(_sections(1, figures=True), "brutalist")


def test_mode_and_note_are_rendered_in_the_page_header():
    page = assemble.build_page(_doc(), _sections(1), "report", mode="ai",
                              note="本页由离线桩生成，未调用真实模型")
    assert assemble.MODES["ai"] in page and 'class="badge ai"' in page
    assert "本页由离线桩生成，未调用真实模型" in page
    program = assemble.build_page(_doc(), _sections(1), "report", mode="program")
    assert assemble.MODES["program"] in program and 'class="badge program"' in program


def test_badge_numbers_come_from_doc_totals_and_are_thousands_separated():
    page = assemble.build_page(_doc(), _sections(1), "report", mode="ai")
    assert "12 文件" in page and "3,400 符号" in page and "3 包" in page
    blank = assemble.build_page({"totals": {}}, _sections(1), "report", mode="ai")
    assert "统计未登记" in blank


def test_same_input_twice_is_byte_identical():
    first = assemble.build_page(_doc(), _sections(2, figures=True), "cards", mode="ai")
    second = assemble.build_page(_doc(), _sections(2, figures=True), "cards", mode="ai")
    assert first == second


def test_a_section_that_is_not_an_object_is_reported_not_swallowed():
    with pytest.raises(BuildError):
        assemble.build_main([{"title": "ok", "html": "", "figures": [], "notes": []}, None],
                            "report")
    with pytest.raises(BuildError) as info:
        assemble.build_page(_doc(), _sections(1), "report", mode="model")
    assert "model" in str(info.value)
