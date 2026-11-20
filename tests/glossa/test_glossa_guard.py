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
           '<img src="https://evil.example/x.png">')         # R505：外链整标签丢弃
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


def test_control_chars_cannot_smuggle_dangerous_schemes():
    cases = (
        '<a href="java&#9;script:alert(1)">t</a>',        # 实体化 TAB
        '<a href="ht\ttps://evil">t</a>',                 # 真 TAB 夹在协议里
        '<a href="/\t/evil">t</a>',                       # 伪装协议相对地址
        '<a href="da\tta:image/png">t</a>',
        '<a href="\x01javascript:alert(1)">t</a>',        # C0 控制字符
        '<img src="da\tta:image/png;base64,AA">',         # img 的 src 同样规范
    )
    for src in cases:
        clean, removed, notes = guard.sanitize_html(src)
        for bad in ("javascript:", "https://", "//evil", "data:", "\t", "\x01"):
            assert bad not in clean, (src, clean)
        assert removed == 1, (src, clean, removed)   # 每次恰好丢 1 处，不许谎报 0
        assert notes, src                            # 丢了就必须说


def test_model_written_untraced_marks_are_demoted():
    out, n = guard.mark_untraced('<p>共 <mark class="untraced">999</mark> 个</p>', set())
    assert n == 1                       # 模型自写的标记不能把未溯源数刷成 0
    assert out == '<p>共 <mark><mark class="untraced">999</mark></mark> 个</p>'
    assert out.count('<mark class="untraced">') == 1      # 只剩程序加的那一个
    # 未闭合的假标记不许让其后的数字静默逃脱
    out2, n2 = guard.mark_untraced('<p>未完 <mark class="untraced">50 and rest 888</p>', set())
    assert n2 == 2
    assert '<mark class="untraced">888</mark>' in out2
    # 模型写的普通 <mark> 仍照常标记数字（不误吞用户标签）
    assert guard.mark_untraced("<mark>999</mark>", set())[1] == 1
    # 统一降级入口（R419）：带额外属性/多类名也认
    assert guard.demote_marks('<mark class="x untraced" title="t">999</mark>') == "<mark>999</mark>"


def test_style_and_meta_and_form_are_removed():
    src = ('<style>.untraced{visibility:hidden}</style><base href="//x">'
           '<meta http-equiv="refresh"><link rel="stylesheet" href="//y">'
           '<form action="//z"></form><img src="data:image/png;base64,AA" srcset="//evil 2x">'
           '<p style="color:red">正文</p>')
    clean, removed, notes = guard.sanitize_html(src)
    for bad in ("<style", "visibility:hidden", "<base", "<meta", "<link",
                "<form", "srcset", "//x", "//y", "//z", "//evil"):
        assert bad not in clean, bad
    assert 'style="color:red"' in clean        # 内联 style 属性仍放行（R420）
    assert 'src="data:image/png;base64,AA"' in clean and "正文" in clean
    assert removed == 6                        # 5 个禁标签 + 1 个 srcset 属性
    assert len(notes) >= 6


def test_untraced_numbers_are_marked_but_kept():
    html = "<p>共 486 个文件，另有 999 个不明。</p>"
    out, n = guard.mark_untraced(html, {486})
    assert n == 1
    assert out == ('<p>共 486 个文件，另有 '
                   '<mark class="untraced">999</mark> 个不明。</p>')
    # 逗号与百分号归一化后比对
    assert guard.mark_untraced("<p>29,856 与 50%</p>", {29856, 50}) == (
        "<p>29,856 与 50%</p>", 0)
    # R422：归一化只用于比对，写进页面的必须是原文（未溯源分支也要逐字保留）
    out2, n2 = guard.mark_untraced("<p>29,856 与 50%</p>", set())
    assert n2 == 2
    assert "29,856" in out2 and "29856" not in out2
    assert "50%" in out2


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
