"""A2：六种图表范式的字段契约与 validate_figure 的六条规则（patterns.py）。

逐条对着派发书 §3：未知范式响亮报错、节点 id 缺失/重复报错、超 60 截断并披露、
边的事实不在台账要丢、事实在但指向对不上要丢、返回 (clean_fig, dropped, notes)。
"""
import pytest

from glossa.explain import patterns
from papertrace.exceptions import BuildError

NAMES = ("layered", "flow", "matrix", "tree", "bars", "cards")


def _doc(**facts):
    """一个最小事实台账；文件名用 fact:file:<path> 的既有口径。"""
    return {"files": [{"path": p} for p in ("a.ts", "b.ts")], "facts": facts}


def _fact(text="a.ts 的两条 import 里，一条指向 b.ts。", numbers=(1, 2), edges=None):
    row = {"text": text, "numbers": list(numbers)}
    if edges is not None:
        row["edges"] = edges
    return row


def _nodes(count, prefix="n"):
    return [{"id": "%s%d" % (prefix, i), "label": "f%d.ts" % i} for i in range(count)]


def test_six_patterns_have_the_contract_fields():
    assert tuple(patterns.PATTERNS) == NAMES
    for name in NAMES:
        row = patterns.PATTERNS[name]
        assert row["summary"] and row["fields"], name
        assert isinstance(row["example"], dict), name
        assert row["example"]["pattern"] == name, name
        assert set(row["fields"]) <= {"nodes", "edges", "groups", "bars", "cards"}, (name, row["fields"])


def test_every_pattern_example_passes_validation():
    doc = _doc(**{"fact:file:a.ts": _fact(edges=[{"from": "a.ts", "to": "b.ts", "kind": "import"}])})
    for name in NAMES:
        example = patterns.PATTERNS[name]["example"]
        clean, dropped, notes = patterns.validate_figure(doc, example)
        assert clean["pattern"] == name
        assert dropped == 0, (name, notes)
        assert notes == [], (name, notes)


def test_unknown_pattern_raises_with_all_six_names():
    with pytest.raises(BuildError) as info:
        patterns.validate_figure(_doc(), {"pattern": "sunburst", "nodes": [], "edges": []})
    message = str(info.value)
    assert "sunburst" in message
    for name in NAMES:
        assert name in message


def test_duplicate_node_id_raises():
    doc = _doc()
    fig = {"pattern": "layered", "nodes": [{"id": "a", "label": "a.ts"}, {"id": "a", "label": "b.ts"}],
           "edges": []}
    with pytest.raises(BuildError) as info:
        patterns.validate_figure(doc, fig)
    assert "a" in str(info.value)


def test_node_without_id_raises():
    with pytest.raises(BuildError):
        patterns.validate_figure(_doc(), {"pattern": "tree", "nodes": [{"label": "a.ts"}], "edges": []})


def test_more_than_sixty_nodes_is_truncated_and_disclosed():
    doc = _doc()
    clean, dropped, notes = patterns.validate_figure(
        doc, {"pattern": "matrix", "nodes": _nodes(65), "edges": []})
    assert len(clean["nodes"]) == 60
    assert dropped == 0
    assert any("另有 5 个节点未画" in note for note in notes), notes


def test_edge_fact_missing_from_ledger_is_dropped_and_counted():
    doc = _doc(**{"fact:file:a.ts": _fact()})
    fig = {"pattern": "flow", "nodes": _nodes(2),
           "edges": [{"from": "n0", "to": "n1", "label": "import", "fact": "fact:import:9"}]}
    clean, dropped, notes = patterns.validate_figure(doc, fig)
    assert clean["edges"] == []
    assert dropped == 1
    assert any("fact:import:9" in note for note in notes), notes


def test_edge_whose_fact_points_the_other_way_is_dropped_and_named():
    doc = _doc(**{"fact:import:1": _fact(edges=[{"from": "a.ts", "to": "b.ts", "kind": "import"}])})
    fig = {"pattern": "flow", "nodes": [{"id": "a", "label": "a.ts", "fact": "fact:file:a.ts"},
                                        {"id": "b", "label": "b.ts", "fact": "fact:file:b.ts"}],
           "edges": [{"from": "b", "to": "a", "label": "import", "fact": "fact:import:1"}]}
    clean, dropped, notes = patterns.validate_figure(doc, fig)
    assert clean["edges"] == []
    assert dropped == 1
    assert any("fact:import:1" in note for note in notes), notes


def test_edge_whose_fact_has_no_comparable_edge_is_dropped_and_named():
    doc = _doc(**{"fact:graph": _fact(text="依赖图：2 个节点、1 条边。", numbers=(2, 1))})
    fig = {"pattern": "layered", "nodes": _nodes(2),
           "edges": [{"from": "n0", "to": "n1", "label": "import", "fact": "fact:graph"}]}
    clean, dropped, notes = patterns.validate_figure(doc, fig)
    assert clean["edges"] == []
    assert dropped == 1
    assert any("fact:graph" in note and "核对" in note for note in notes), notes


def test_edge_matching_its_fact_edge_is_kept():
    doc = _doc(**{"fact:import:1": _fact(edges=[{"from": "a.ts", "to": "b.ts", "kind": "import"}])})
    fig = {"pattern": "layered",
           "nodes": [{"id": "a", "label": "a.ts", "fact": "fact:file:a.ts"},
                     {"id": "b", "label": "b.ts", "fact": "fact:file:b.ts"}],
           "edges": [{"from": "a", "to": "b", "label": "import", "fact": "fact:import:1"}]}
    clean, dropped, notes = patterns.validate_figure(doc, fig)
    assert len(clean["edges"]) == 1
    assert dropped == 0 and notes == [], notes


def test_clean_fig_keeps_only_the_five_contract_keys():
    doc = _doc()
    fig = {"pattern": "cards", "caption": "图鉴", "nodes": _nodes(2), "edges": [],
           "groups": [{"label": "x", "members": ["n0"]}],
           "svg": "<svg/>", "notes": ["AI 的注释"], "coords": {"n0": [1, 2]}}
    clean, dropped, notes = patterns.validate_figure(doc, fig)
    assert set(clean) == {"pattern", "caption", "nodes", "edges", "groups"}
    assert dropped == 0
    assert notes == []


def test_edge_to_a_truncated_node_is_dropped_and_disclosed():
    doc = _doc()
    nodes = _nodes(61)
    fig = {"pattern": "matrix", "nodes": nodes,
           "edges": [{"from": "n0", "to": "n60", "label": "import", "fact": "fact:graph"}]}
    clean, dropped, notes = patterns.validate_figure(doc, fig)
    assert clean["edges"] == []
    assert any("n60" in note for note in notes), notes
