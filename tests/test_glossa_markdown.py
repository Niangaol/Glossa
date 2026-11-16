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


def test_empty_text_returns_empty_string_and_no_notes():
    assert markdown.render_markdown("") == ("", [])
    assert markdown.render_markdown("   \n\n  ") == ("", [])
