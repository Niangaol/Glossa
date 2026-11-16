"""T8：custom 守卫与未溯源标记。removed 计数口径见 R307。"""
from glossa.explain import guard


def test_script_and_event_attrs_are_removed_and_counted():
    src = '<div onclick="x()">你好<script>bad()</script></div>'
    clean, removed, notes = guard.sanitize_html(src)
    assert "<script" not in clean
    assert "onclick" not in clean
    assert "你好" in clean            # 内容不许被连带丢掉
    assert removed == 2              # script 标签 1 + onclick 属性 1
    assert notes


def test_external_links_and_embeds_are_removed():
    src = ('<a href="https://x">外</a><a href="//y">协议相对</a>'
           '<iframe src="https://z"></iframe><object data="a"></object>'
           '<embed src="b"><a href="javascript:alert(1)">js</a>'
           '<img src="data:image/png;base64,AAA">')
    clean, removed, notes = guard.sanitize_html(src)
    for bad in ("https://", "//y", "<iframe", "<object", "<embed",
                "javascript:", "data:"):
        assert bad not in clean, bad
    assert "外" in clean              # 去 href 保文字（R307）
    assert removed == 7              # 2 个 href + iframe + object + embed + js href + img


def test_inline_style_and_custom_tags_survive():
    src = ('<section class="blk" style="color:#123">'
           '<my-card data-x="1"><p>内</p></my-card></section>')
    clean, removed, notes = guard.sanitize_html(src)
    assert removed == 0 and notes == []
    assert 'style="color:#123"' in clean
    assert "<my-card" in clean and "内" in clean


def test_untraced_numbers_are_marked_but_kept():
    html = "<p>共 486 个文件，另有 999 个不明。</p>"
    out, n = guard.mark_untraced(html, {486})
    assert n == 1
    assert out == ('<p>共 486 个文件，另有 '
                   '<mark class="untraced">999</mark> 个不明。</p>')
    # 逗号与百分号归一化后比对
    assert guard.mark_untraced("<p>29,856 与 50%</p>", {29856, 50}) == (
        "<p>29,856 与 50%</p>", 0)


def test_code_subtrees_are_skipped():
    html = "<p>看 <code>999</code> 与 999。</p>"
    out, n = guard.mark_untraced(html, set())
    assert n == 1
    assert "<code>999</code>" in out
    assert '<mark class="untraced">999</mark>' in out
    # 嵌套 code 也要整段跳过
    nested = "<code>a<code>123</code>b</code> 456"
    out2, n2 = guard.mark_untraced(nested, set())
    assert n2 == 1
    assert "<code>a<code>123</code>b</code>" in out2
