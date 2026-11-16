"""T7 修复轮 3（R425/R427/R428/R430/R431）：分层按 SCC 缩点，截断与 count 合并要有看守。

每条都钉「能区分实现」的不变量：按裁决把实现改回去必须红（R400）。
"""
from glossa import graph, graph_layers


def _edge(src, dst, count=1, kind="internal"):
    return {"from": src, "to": dst, "kind": kind, "count": count}


def test_layers_place_downstream_after_the_cycle():
    ids = ["x.ts", "a.ts", "b.ts", "c.ts", "d.ts"]
    edges = [_edge("x.ts", "a.ts"), _edge("a.ts", "b.ts"), _edge("b.ts", "a.ts"),
             _edge("a.ts", "c.ts"), _edge("c.ts", "d.ts")]
    assert graph.longest_layers(ids, edges) == [["x.ts"], ["a.ts", "b.ts"],
                                                ["c.ts"], ["d.ts"]]


def test_self_loop_keeps_its_own_layer():
    ids = ["a.ts", "b.ts", "c.ts"]
    edges = [_edge("a.ts", "a.ts"), _edge("a.ts", "b.ts"),
             _edge("b.ts", "c.ts"), _edge("c.ts", "b.ts")]
    assert graph.longest_layers(ids, edges) == [["a.ts"], ["b.ts", "c.ts"]]


def test_scc_merges_two_overlapping_rings_into_one_layer():
    ids = ["a.ts", "b.ts", "c.ts"]
    edges = [_edge("a.ts", "b.ts"), _edge("b.ts", "a.ts"),
             _edge("b.ts", "c.ts"), _edge("c.ts", "b.ts")]
    assert graph.find_cycles(ids, edges) == [["a.ts", "b.ts"], ["b.ts", "c.ts"]]
    assert graph_layers.strongly_connected_components(ids, edges) == [["a.ts", "b.ts", "c.ts"]]
    assert graph.longest_layers(ids, edges) == [["a.ts", "b.ts", "c.ts"]]


def test_truncation_keeps_the_hub_and_its_edges():
    hub = "z-hub.ts"
    ids = [hub] + [f"a{i:03d}.ts" for i in range(124)]
    edges = [_edge(name, hub) for name in ids[1:]]
    got = graph.build_graph_from([], edges, entries=[], level="file", total_files=130)
    drawn = {node["id"] for node in got["nodes"]}
    assert got["truncated"] is True and len(drawn) == graph.MAX_GRAPH_NODES == 120
    assert hub in drawn, "按 id 取前 120 会丢掉排序末位的枢纽，119 条边跟着静默消失"
    assert len(got["edges"]) == 119
    assert got["truncated_nodes"] == 5
    assert got["omitted_isolated"] == 5, "孤立只算没进图的 5 个文件，不含被截断的 5 个"
    assert got["unreachable"] == []


def test_truncated_nodes_counts_what_was_dropped():
    ids = [f"f{i:03d}.ts" for i in range(130)]
    got = graph.build_graph_from(ids, [], entries=[], level="file", total_files=130)
    assert got["truncated"] is True and len(got["nodes"]) == 120
    assert got["truncated_nodes"] == 10
    fine = graph.build_graph_from(["a.ts"], [], entries=[], level="file", total_files=1)
    assert fine["truncated"] is False and fine["truncated_nodes"] == 0


def test_merged_edges_sum_their_counts():
    edges = [_edge("a.ts", "b.ts", 1), _edge("a.ts", "b.ts", 2)]
    got = graph.build_graph_from([], edges, entries=[], level="file", total_files=2)
    assert got["edges"] == [{"from": "a.ts", "to": "b.ts", "kind": "internal", "count": 3}]


def test_no_entry_point_means_unreachable_does_not_apply():
    edges = [_edge("a.ts", "b.ts")]
    got = graph.build_graph_from([], edges, entries=[], level="file", total_files=2)
    assert got["reachable_from_entries"] == [] and got["unreachable"] == [], \
        "没有入口时「从入口不可达」不成立，不许把全部节点报成不可达"
    served = graph.build_graph_from([], edges, entries=[{"target": "file:a.ts"}],
                                    level="file", total_files=2)
    assert served["reachable_from_entries"] == ["a.ts", "b.ts"] and served["unreachable"] == []


def test_graph_degrades_when_there_is_no_entry_point():
    doc = {"files": [{"path": "a.py", "lang": "python"}, {"path": "b.py", "lang": "python"}],
           "imports": [{"from": "a.py", "target": "file:b.py", "kind": "internal"}],
           "entries": [], "projects": [], "degraded": []}
    got = graph.build_graph(doc)
    assert len(got["nodes"]) == 2 and got["unreachable"] == []
    assert any(row["reason"] == "仓里没有可解析的入口，unreachable 不适用"
               for row in doc["degraded"])
