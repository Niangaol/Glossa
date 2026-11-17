"""A4：gates.py —— 四道闸（派发书 §2）。

安全闸复用 guard.sanitize（R307/R419/R420）；溯源闸只标记不删（R308），program 版传空集
必须计 0（R309/R314）；连线闸直接复用 patterns.validate_figure；体积闸只报不截断。
"""
from glossa.explain import gates, guard, patterns
from glossa.explain.gates import MAX_PAGE_BYTES

_FIG = {"pattern": "layered", "caption": "谁依赖谁", "groups": [],
        "nodes": [{"id": "a", "label": "a.ts"}, {"id": "b", "label": "b.ts"}],
        "edges": [{"from": "a", "to": "b", "label": "import", "fact": "fact:import:1"}]}


def test_script_is_removed_and_noted():
    clean, notes = gates.gate_html('<p>正文</p><script>alert(1)</script>')
    assert "<script>" not in clean and "alert(1)" not in clean
    assert "<p>正文</p>" in clean
    assert any("script" in note for note in notes), notes


def test_event_attribute_is_removed_and_noted():
    clean, notes = gates.gate_html('<img src="x.png" onerror="alert(1)">')
    assert "onerror" not in clean.lower()
    assert clean.count("<img") == 1 and 'src="x.png"' in clean
    assert any("onerror" in note.lower() for note in notes), notes


def test_style_block_is_removed():
    clean, notes = gates.gate_html('<style>.untraced{visibility:hidden}</style><p>ok</p>')
    assert "<style>" not in clean and "visibility" not in clean
    assert clean == "<p>ok</p>"
    assert notes


def test_normal_html_is_left_alone():
    html = '<p class="lead">共 3 个文件，<code>x = 1</code>。</p>'
    clean, notes = gates.gate_html(html)
    assert clean == html
    assert notes == []


def test_number_without_a_source_is_marked_and_counted():
    marked, count = gates.gate_numbers("<p>真实值是 128 个文件。</p>", {"129"})
    assert count == 1
    assert '<mark class="untraced">128</mark>' in marked
    assert "128" in marked


def test_number_from_the_allowed_set_is_not_marked():
    marked, count = gates.gate_numbers("<p>真实值是 128 个文件。</p>", {"128"})
    assert count == 0
    assert "<mark" not in marked and marked == "<p>真实值是 128 个文件。</p>"


def test_program_mode_passes_an_empty_set_and_counts_zero():
    html = "<p>共 128 个节点、101 条边，29,856 次估算。</p>"
    marked, count = gates.gate_numbers(html, set())
    assert (marked, count) == (html, 0)


def test_allowed_numbers_may_arrive_as_ledger_strings():
    marked, count = gates.gate_numbers("<p>共 29,856 次、50% 覆盖。</p>", {"29,856", "50%"})
    assert count == 0 and "<mark" not in marked


def test_edge_without_a_matching_fact_edge_is_dropped_and_named():
    clean, notes = gates.gate_edges(_FIG, {("b", "a")})
    assert clean["edges"] == []
    assert any("a" in note and "b" in note and "→" in note for note in notes), notes


def test_edge_with_a_matching_fact_edge_is_kept_with_its_own_fact():
    clean, notes = gates.gate_edges(_FIG, {("a", "b")})
    assert len(clean["edges"]) == 1
    assert clean["edges"][0]["fact"] == "fact:import:1"
    assert notes == []


def test_page_over_the_byte_limit_reports_true_without_truncating():
    over = "x" * (MAX_PAGE_BYTES + 1)
    html, too_big = gates.gate_size(over)
    assert html == over and too_big is True
    assert gates.gate_size("<p>ok</p>") == ("<p>ok</p>", False)


def test_gate_html_reuses_guard_sanitize():
    html = '<p onclick="x()">a</p>'
    assert gates.gate_html(html)[0] == guard.sanitize_html(html)[0]


def test_gate_edges_uses_the_pattern_contract_and_keeps_a_clean_fig():
    clean, notes = gates.gate_edges(_FIG, {("a", "b")})
    assert set(clean) == set(patterns.validate_figure({"facts": {}}, _FIG | {"edges": []})[0])
    assert clean["pattern"] == "layered"
