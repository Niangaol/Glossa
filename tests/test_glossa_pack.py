"""A3：段素材包（pack.py）的五键契约与四条硬边界。

契约来自派发书 §1：段包五键 repo/section/facts/patterns/sources；facts 带原样 numbers；
sources 只取 doc["files"] 里真存在的路径、secrets_seen 一个字节都不读；超 8KB 先砍 sources
尾部再砍 facts 尾部并置 truncated；单段最多 6 个片段。
"""
import json
import pathlib

import pytest

from glossa.explain import pack as pack_mod
from glossa.explain import patterns
from tests._tmp import scratch_dir


@pytest.fixture()
def work():
    """沙箱友好：不用 pytest 的 tmp_path / --basetemp（递归删除 WinError 5），走 tests/_tmp。"""
    return scratch_dir("a3pack")


def _write(root, rel, lines):
    path = pathlib.Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _doc(paths, *, facts=None, edges=(), secrets=(), lines=3):
    """最小 repo.json：正好是 pack 会读到的那些键（meta/totals/files/graph/excluded/facts）。"""
    files = [{"path": p, "lines": lines} for p in paths]
    return {
        "meta": {"repo": {"url": "demo", "commit": "a" * 40, "root_name": "demo",
                          "language": "python"}},
        "totals": {"files": len(files), "symbols": 2, "imports": 1, "degraded": 0},
        "files": files,
        "graph": {"level": "file", "nodes": [{"id": p} for p in paths],
                  "edges": [dict(edge) for edge in edges], "project_edges": [],
                  "cycles": [], "layers": [[p] for p in paths], "unreachable": [],
                  "truncated": False},
        "excluded": {"secrets_seen": [{"path": p, "bytes": 9} for p in secrets]},
        "facts": dict(facts or {}),
    }


def test_pack_has_the_five_contract_keys(work):
    _write(work, "a.py", ["x = 1", "y = 2"])
    doc = _doc(["a.py"], facts={"fact:file:a.py": {"text": "a.py 有 2 行。", "numbers": [2]}})
    out = pack_mod.build_pack(doc, {"index": 1, "title": "入口", "goal": "讲入口"}, work)
    assert {"repo", "section", "facts", "patterns", "sources"} <= set(out)
    assert out["section"] == {"index": 1, "title": "入口", "goal": "讲入口"}
    assert out["repo"]["root_name"] == "demo" and out["repo"]["commit"] == "a" * 40
    assert isinstance(out["truncated"], bool) and isinstance(out["notes"], list)


def test_facts_keep_numbers_and_patterns_carry_no_example(work):
    _write(work, "a.py", ["x = 1"])
    doc = _doc(["a.py"], facts={"fact:file:a.py": {"text": "a.py 有 1 行。", "numbers": [1, 3, 7]}})
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "facts": ["fact:file:a.py", "fact:nope"]}, work)
    assert out["facts"] == [{"id": "fact:file:a.py", "text": "a.py 有 1 行。", "numbers": [1, 3, 7]}]
    assert any("fact:nope" in note for note in out["notes"])
    assert [row["name"] for row in out["patterns"]] == list(patterns.PATTERNS)
    for row in out["patterns"]:
        assert set(row) == {"name", "fields", "summary"}, row
        assert row["fields"] == patterns.PATTERNS[row["name"]]["fields"]


def test_sources_only_come_from_doc_files(work):
    _write(work, "a.py", ["A"])
    _write(work, "ghost.py", ["G"])          # 盘上真有，但不在 doc["files"] 里
    doc = _doc(["a.py"])
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": ["a.py", "ghost.py"]}, work)
    assert [src["path"] for src in out["sources"]] == ["a.py"]
    assert "ghost.py" not in json.dumps(out, ensure_ascii=False)


def test_secrets_seen_paths_are_never_read(work):
    _write(work, ".env", ["TOKEN=deadbeef"])
    _write(work, "a.py", ["A"])
    doc = _doc([".env", "a.py"], secrets=[".env"])
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": [".env", "a.py"]}, work)
    assert [src["path"] for src in out["sources"]] == ["a.py"]
    blob = json.dumps(out, ensure_ascii=False)
    assert "deadbeef" not in blob and "TOKEN" not in blob
    assert any(".env" in note and "secrets_seen" in note for note in out["notes"])


def test_oversize_pack_is_truncated_under_the_byte_cap(work):
    big = ["第 %03d 行：%s" % (i, "内容" * 20) for i in range(1, 41)]
    paths = ["f%d.py" % i for i in range(8)]
    for path in paths:
        _write(work, path, big)
    facts = {"fact:n%02d" % i: {"text": "第 %d 条事实：" % i + "说明" * 40, "numbers": [i]}
             for i in range(20)}
    doc = _doc(paths, facts=facts)
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": paths}, work)
    assert out["truncated"] is True
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) <= pack_mod.MAX_PACK_BYTES
    assert len(out["sources"]) < len(paths)                     # sources 按份额截断
    assert len(out["facts"]) < len(facts)                       # 份额之后仍超限：砍事实并置 truncated
    assert any("字节" in note for note in out["notes"])


def test_facts_are_dropped_once_the_sources_have_paid_their_share(work):
    """R511 改了顺序：源码先按 40% 份额留好，超限时砍的是事实，不是把源码全弃掉。"""
    paths = ["g%d.py" % i for i in range(6)]
    for path in paths:
        _write(work, path, ["行 %d" % i for i in range(40)])
    facts = {"fact:big%02d" % i: {"text": "第 %d 条：" % i + "长" * 900, "numbers": [i]}
             for i in range(12)}
    doc = _doc(paths, facts=facts)
    out = pack_mod.build_pack(doc, {"index": 1, "title": "t", "goal": "", "sources": paths}, work)
    assert out["truncated"] is True
    assert 0 < len(out["facts"]) < len(facts)
    assert len(out["sources"]) > 0, "源码已按份额留好，砍的该是事实"
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) <= pack_mod.MAX_PACK_BYTES


def test_at_most_six_source_slices(work):
    paths = ["s%d.py" % i for i in range(9)]
    for path in paths:
        _write(work, path, ["x = 1"])
    doc = _doc(paths, lines=1)
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": paths}, work)
    assert len(out["sources"]) == pack_mod.MAX_SOURCES == 6
    assert [src["path"] for src in out["sources"]] == paths[:6]
    assert out["truncated"] is False


def test_unreadable_file_is_reported_in_notes(work):
    doc = _doc(["gone.py"])
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": ["gone.py"]}, work)
    assert out["sources"] == []
    assert any("gone.py" in note and "读不到" in note for note in out["notes"])


def test_source_slice_runs_from_start_for_forty_lines(work):
    _write(work, "big.py", ["L%03d" % i for i in range(1, 101)])
    doc = _doc(["big.py"], lines=100)
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": [{"path": "big.py", "start": 11}]},
        work)
    src = out["sources"][0]
    lines = src["text"].splitlines()
    assert (src["start"], src["end"]) == (11, 50)
    assert lines[0] == "L011" and lines[-1] == "L050"
    assert len(lines) == pack_mod.MAX_SOURCE_LINES == 40


def test_graph_fact_carries_edges_from_the_graph(work):
    _write(work, "a.py", ["A"])
    _write(work, "b.py", ["B"])
    doc = _doc(["a.py", "b.py"],
               facts={"fact:graph": {"text": "依赖图 2 个节点、1 条边。", "numbers": [2, 1]}},
               edges=[{"from": "a.py", "to": "b.py", "kind": "import"}])
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "facts": ["fact:graph"]}, work)
    assert out["facts"] == [{"id": "fact:graph", "text": "依赖图 2 个节点、1 条边。",
                             "numbers": [2, 1], "has_edges": True,
                             "edges": [{"from": "a.py", "to": "b.py", "label": "import"}]}]


def test_pack_for_plan_carries_summaries_and_sampled_facts(work):
    doc = _doc(["a.py", "b.py"], edges=[{"from": "a.py", "to": "b.py"}])
    plan = pack_mod.pack_for_plan(doc)
    assert set(plan) == {"repo", "totals", "graph", "facts", "has_edges", "truncated"}
    assert plan["totals"]["files"] == 2 and plan["has_edges"] is True
    assert plan["graph"] == {"level": "file", "nodes": 2, "edges": 1, "project_edges": 0,
                             "cycles": 0, "layers": 2, "unreachable": 0, "truncated": False}
def test_graph_fact_keeps_edges_when_the_pack_is_over_budget(work):
    """PokemonData 的真形：边很长，整条图事实单体就超 8KB——砍边，别丢事实（R511：这算预算）。"""
    paths = ["h%d.py" % i for i in range(6)]
    for path in paths:
        _write(work, path, ["第 %02d 行：%s" % (i, "内容" * 16) for i in range(1, 41)])
    names = ["pkg/very_long_directory_name_%02d/another_long_directory_module_%02d/"
             "file_with_a_long_name_for_edges.py" % (i, i + 1) for i in range(60)]
    edges = [{"from": names[i], "to": names[(i + 1) % 60], "kind": "import"} for i in range(60)]
    doc = _doc(paths, facts={"fact:graph": {"text": "依赖图 60 条边。", "numbers": [60]}},
               edges=edges)
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "facts": ["fact:graph"], "sources": paths}, work)
    assert out["truncated"] is False, "砍边是预算内的取舍，事实一条没少（R511）"
    assert [row["id"] for row in out["facts"]] == ["fact:graph"]   # 图事实不许被整条丢掉
    assert 0 < len(out["facts"][0]["edges"]) < pack_mod.MAX_EDGES  # 边被砍半到装得下
    assert out["facts"][0]["has_edges"] is True
    assert any("图边" in note or "图的边" in note for note in out["notes"]), out["notes"]
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) <= pack_mod.MAX_PACK_BYTES

