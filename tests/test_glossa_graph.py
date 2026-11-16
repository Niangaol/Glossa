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
    # R432：5 个没进图，其中 3 个 package.json 永远不会产生 import 边（口径不许错报成事实）
    assert any("5 个文件没有进入关系图（其中 3 个是清单、文档等不产生 import 的文件）" in d["reason"]
               for d in doc["degraded"]), doc["degraded"]
    # R430：没截断就是 0（页面靠这个字段决定要不要显示「截断未画」那一行）
    assert g["truncated"] is False and g["truncated_nodes"] == 0


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
    # R425：环内节点同层（SCC 缩点），层内按 id 升序；不再「所有未出队节点归最后一层」
    ring = [{"from": "a.ts", "to": "b.ts", "kind": "internal", "count": 1},
            {"from": "b.ts", "to": "a.ts", "kind": "internal", "count": 1}]
    assert graph.longest_layers(["a.ts", "b.ts"], ring) == [["a.ts", "b.ts"]]


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


def test_same_project_name_resolves_to_the_first_csproj_by_path():
    root = scratch_dir("glossa-t7-dupe-csproj")
    bodies = {
        "src/App/App.csproj": '<Project><PropertyGroup><OutputType>Exe</OutputType>'
                              "</PropertyGroup><ItemGroup>"
                              '<ProjectReference Include="..\\Demo.Core\\Demo.Core.csproj" />'
                              "</ItemGroup></Project>",
        "src/Alt/Demo.Core.csproj": "<Project />",
        "src/Demo.Core/Demo.Core.csproj": "<Project />",
    }
    for rel, body in bodies.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    doc = facts.build_repo_doc(root)
    assert doc["graph"]["level"] == "project"
    assert doc["graph"]["edges"][0]["to"] == "src/Alt/Demo.Core.csproj", \
        "同名 csproj 必须按路径升序取第一个，不许取最后一个"
    assert any("项目名 Demo.Core 对应多个 csproj，按 csproj 升序取第一个" in d["reason"]
               for d in doc["degraded"]), doc["degraded"]


def test_graph_fills_totals_and_still_passes_schema():
    doc = _doc("ts-monorepo")
    assert doc["totals"]["edges"] == 6
    assert doc["totals"]["cycles"] == 0
    assert doc["totals"]["unreachable"] == 2
    schema_repo.validate_repo(doc)
    again = graph.build_graph(doc)
    assert again["layers"] == doc["graph"]["layers"]   # 可复现

_MIXED = {
    "src/App/App.csproj": '<Project><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup>'
                          '<ItemGroup><ProjectReference Include="..\\Core\\Core.csproj" />'
                          '<ProjectReference Include="..\\Tests\\Tests.csproj" />'
                          "</ItemGroup></Project>",
    "src/Tests/Tests.csproj": '<Project><ItemGroup>'
                              '<ProjectReference Include="..\\Core\\Core.csproj" />'
                              "</ItemGroup></Project>",
    "src/Core/Core.csproj": "<Project />",
    "web/a.ts": 'import { b } from "./b";\nexport const a = b;\n',
    "web/b.ts": "export const b = 2;\n",
}


def _mixed():
    """R479 夹具：PokemonData 式混合仓——csproj 有 ProjectReference，.ts 有文件级 import。"""
    root = scratch_dir("glossa-r479-mixed")
    for rel, body in _MIXED.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return facts.build_repo_doc(root)


def test_mixed_repo_keeps_project_edges_visible_while_drawing_files():
    """R479：混合仓仍画文件级图，但 3 条项目引用边必须落进产物（静默省略就是谎报）。"""
    doc = _mixed()
    g = doc["graph"]
    assert g["level"] == "file" and len(g["edges"]) == 1   # 决策不变，只画文件级 import
    pairs = {(e["from"], e["to"]) for e in g["project_edges"]}
    assert pairs == {("src/App/App.csproj", "src/Core/Core.csproj"),
                     ("src/App/App.csproj", "src/Tests/Tests.csproj"),
                     ("src/Tests/Tests.csproj", "src/Core/Core.csproj")}
    assert {e["kind"] for e in g["project_edges"]} == {"internal_project"}
    fact = doc["facts"]["fact:graph"]               # R479/R322：3 必须能在 fact 里溯源
    assert 3 in fact["numbers"] and "另有 3 条项目引用（ProjectReference）没有画进图" in fact["text"]


def test_project_edges_are_present_even_when_empty_or_project_level():
    """R479：键恒在（空的也写空数组）；project 级时它就是 edges，Fact 里不再补那句。"""
    assert _doc("ts-monorepo")["graph"]["project_edges"] == []
    doc = _doc("cs-solution")
    g = doc["graph"]
    assert g["level"] == "project" and g["project_edges"] == g["edges"]
    assert "项目引用（ProjectReference）没有画进图" not in doc["facts"]["fact:graph"]["text"]