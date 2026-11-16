"""T7：关系图。数字来自真跑夹具 + 控制器推算（见计划）。"""
import shutil
from pathlib import Path

from glossa import facts, graph, schema_repo
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"


def _copy(name):
    dst = scratch_dir("glossa-t7-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst


def _doc(name):
    return facts.build_repo_doc(_copy(name))


def test_file_graph_edges_come_only_from_resolved_imports():
    g = _doc("ts-monorepo")["graph"]
    assert g["level"] == "file"
    assert len(g["edges"]) == 6
    pairs = {(e["from"], e["to"], e["kind"]) for e in g["edges"]}
    assert ("packages/a/src/server.ts", "packages/a/src/circuit.ts",
            "internal") in pairs
    assert ("packages/a/src/server.ts", "packages/b/src/index.ts",
            "workspace") in pairs
    assert ("packages/a/src/server.ts", "packages/a/src/lazy.ts",
            "dynamic") in pairs
    # builtin / external / unresolved 不许产生边
    for e in g["edges"]:
        assert e["kind"] in {"internal", "workspace", "dynamic",
                             "internal_project"}
        assert e["count"] >= 1


def test_isolated_files_are_counted_not_silently_dropped():
    doc = _doc("ts-monorepo")
    g = doc["graph"]
    assert len(g["nodes"]) == 8
    assert g["omitted_isolated"] == 5
    assert g["omitted_isolated"] == doc["totals"]["files"] - len(g["nodes"])
    ids = {n["id"] for n in g["nodes"]}
    assert "packages/a/src/comments.ts" not in ids
    assert "packages/b/src/index.test.ts" in ids   # 入口目标，虽无 import
    assert any("未画进图" in d["reason"] for d in doc["degraded"])


def test_cycles_are_found_and_rotation_normalized():
    ids = ["a.ts", "b.ts", "c.ts"]
    edges = [{"from": "a.ts", "to": "b.ts", "kind": "internal", "count": 1},
             {"from": "b.ts", "to": "a.ts", "kind": "internal", "count": 1},
             {"from": "c.ts", "to": "a.ts", "kind": "internal", "count": 1}]
    cyc = graph.find_cycles(ids, edges)
    assert cyc == [["a.ts", "b.ts"]]        # 从最小 id 开始，且只算一个环
    assert graph.find_cycles(ids, list(reversed(edges))) == cyc  # 顺序无关
    assert graph.find_cycles(["x.ts"], []) == []
    # 归一化本体：从非最小节点进入的环也必须从环内最小 id 起（否则 M3 会假绿）
    tail = [{"from": "t.ts", "to": "z.ts", "kind": "internal", "count": 1},
            {"from": "z.ts", "to": "y.ts", "kind": "internal", "count": 1},
            {"from": "y.ts", "to": "z.ts", "kind": "internal", "count": 1}]
    assert graph.find_cycles(["t.ts", "y.ts", "z.ts"], tail) == [["y.ts", "z.ts"]]


def test_layers_are_topological_and_deterministic():
    ids = ["d.ts", "c.ts", "b.ts", "a.ts"]
    edges = [{"from": "a.ts", "to": "b.ts", "kind": "internal", "count": 1},
             {"from": "b.ts", "to": "c.ts", "kind": "internal", "count": 1},
             {"from": "a.ts", "to": "c.ts", "kind": "internal", "count": 1}]
    layers = graph.longest_layers(ids, edges)
    assert layers == [["a.ts", "d.ts"], ["b.ts"], ["c.ts"]]
    assert graph.longest_layers(list(reversed(ids)), edges) == layers
    # 环内节点不许消失：归到最后一层
    ring = [{"from": "a.ts", "to": "b.ts", "kind": "internal", "count": 1},
            {"from": "b.ts", "to": "a.ts", "kind": "internal", "count": 1}]
    got = graph.longest_layers(["a.ts", "b.ts"], ring)
    assert sorted(n for layer in got for n in layer) == ["a.ts", "b.ts"]


def test_reachable_ignores_compound_command_entries():
    doc = _doc("ts-monorepo")
    g = doc["graph"]
    assert len(g["reachable_from_entries"]) == 6
    assert g["unreachable"] == ["apps/web/App.vue",
                                "packages/a/src/multiline.ts"]
    # check 是复合命令（typecheck && test），target=None，不作起点
    check = [e for e in doc["entries"] if e["name"] == "check"][0]
    assert check["target"] is None
    assert any("复合命令" in d["reason"] for d in doc["degraded"])


def test_cs_solution_graph_is_project_level():
    g = _doc("cs-solution")["graph"]
    assert g["level"] == "project"
    assert len(g["nodes"]) == 2
    assert all(n["kind"] == "project" for n in g["nodes"])
    assert len(g["edges"]) == 1
    e = g["edges"][0]
    assert e["kind"] == "internal_project"
    assert e["from"].endswith("Demo.App.csproj")
    assert e["to"].endswith("Demo.Core.csproj")
    assert g["omitted_isolated"] == 0
    assert g["unreachable"] == []


def test_truncation_is_flagged_and_counted():
    ids = [f"f{i:03d}.ts" for i in range(130)]
    edges = [{"from": ids[0], "to": i, "kind": "internal", "count": 1}
             for i in ids[1:]]
    g = graph.build_graph_from(ids, edges, entries=[], level="file",
                               total_files=130)
    assert g["truncated"] is True
    assert len(g["nodes"]) == graph.MAX_GRAPH_NODES == 120
    assert all(e["from"] in {n["id"] for n in g["nodes"]} and
               e["to"] in {n["id"] for n in g["nodes"]} for e in g["edges"])


def test_graph_fills_totals_and_still_passes_schema():
    doc = _doc("ts-monorepo")
    assert doc["totals"]["edges"] == 6
    assert doc["totals"]["cycles"] == 0
    assert doc["totals"]["unreachable"] == 2
    schema_repo.validate_repo(doc)
    again = graph.build_graph(doc)
    assert again["layers"] == doc["graph"]["layers"]   # 可复现
