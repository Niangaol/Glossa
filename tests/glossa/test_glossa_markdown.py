"""T8：受限 markdown。期望 HTML 逐字冻结，不许放宽。"""
from glossa.explain import markdown


def test_supported_subset_renders():
    src = "## 标题\n\n这是**粗体**与 `code`。\n\n- 甲\n- 乙\n\n1. 一\n2. 二\n"
    html, notes = markdown.render_markdown(src)
    assert html == (
        "<h2>标题</h2>\n"
        "<p>这是<strong>粗体</strong>与 <code>code</code>。</p>\n"
        "<ul><li>甲</li><li>乙</li></ul>\n"
        "<ol><li>一</li><li>二</li></ol>"
    )
    assert notes == []
    # R422：标题不要求独占一块；四级标题仍走纯文本 + note
    html2, notes2 = markdown.render_markdown("## 标题\n正文")
    assert html2 == "<h2>标题</h2>\n<p>正文</p>" and notes2 == []
    html3, notes3 = markdown.render_markdown("#### 四级标题")
    assert html3 == "<p>#### 四级标题</p>" and notes3


def test_unsupported_constructs_are_kept_as_text_with_notes():
    src = ("看 [文档](https://x) 与 ![图](a.png)。\n\n"
           "| a | b |\n| - | - |\n\n> 引用\n\n脚注[^1]\n\n"
           "<b>裸 HTML</b>\n")
    html, notes = markdown.render_markdown(src)
    assert "[文档](https://x)" in html      # 原样保留，不静默丢
    assert "![图](a.png)" in html
    assert "| a | b |" in html
    assert "<b>" not in html and "&lt;b&gt;" in html
    assert len(notes) >= 4
    assert all(isinstance(n, str) and n for n in notes)


def test_html_is_escaped_before_tags_are_inserted():
    src = "<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n"
    html, notes = markdown.render_markdown(src)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img" not in html
    assert notes                      # 裸 HTML 当纯文本，要有提示


def test_heading_may_share_a_block_with_body():
    html, notes = markdown.render_markdown("## 标题\n正文一行\n\n- 甲\n- 乙")
    assert html == ("<h2>标题</h2>\n"
                    "<p>正文一行</p>\n"
                    "<ul><li>甲</li><li>乙</li></ul>")
    assert notes == []
    # #### 仍当纯文本 + note，不许静默当四级标题
    html2, notes2 = markdown.render_markdown("#### 四级")
    assert html2 == "<p>#### 四级</p>"
    assert notes2 == ["不支持的构造「标题层级（只支持 ##/###）」已按纯文本保留"]


def test_empty_text_returns_empty_string_and_no_notes():
    assert markdown.render_markdown("") == ("", [])
    assert markdown.render_markdown("   \n\n  ") == ("", [])
