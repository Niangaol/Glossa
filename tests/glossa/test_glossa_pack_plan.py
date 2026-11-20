"""A7 / R501：分节素材包按种类抽样——每组至少 1 条，再轮转补到 60 条或 8000 字节。

派发书 R501 的病灶是事实顺序：真仓前 60 条除 totals/files 全是 fact:file:*，唯一带边的
fact:graph 永远进不了窗口，于是三个真仓都只出 3 节、0 张图。这里把「种类」当不变量钉住：
不论台账把哪一类排在最前面，包里都至少能看到每一类的一条；图事实还必须带 edges 与
has_edges，模型才画得出关系图。
"""
import json

from glossa.explain import pack as pack_mod

KINDS = ("totals", "files", "graph", "pkg", "project", "entry", "degraded", "file",
         "symbol", "source", "bonus", "import", "namespace", "excluded")
REPS = {"totals": "fact:totals", "files": "fact:files", "graph": "fact:graph",
        "degraded": "fact:degraded", "bonus": "fact:bonus"}


def _kind(fact_id):
    return fact_id.split(":")[1]


def _row(text, numbers):
    return {"text": text, "numbers": list(numbers)}


def _doc(facts, *, edges=(), level="file"):
    return {"meta": {"repo": {"url": "demo", "commit": "c" * 40, "root_name": "demo",
                              "language": "python"}},
            "totals": {"files": 2, "symbols": 3},
            "graph": {"level": level, "nodes": [], "edges": [dict(edge) for edge in edges],
                      "project_edges": [], "cycles": [], "layers": [], "unreachable": [],
                      "truncated": False},
            "facts": dict(facts)}


def _tail_facts(count):
    """每类一条尾巴事实：id 形状与真仓一致（两段 id 也要认得出种类）。"""
    out = {}
    for kind in KINDS:
        fact_id = REPS.get(kind, "fact:%s:x" % kind)
        out[fact_id] = _row("第 %d 类事实。" % len(out), [len(out)])
    return out


def _size(pack):
    return len(json.dumps(pack, ensure_ascii=False).encode("utf-8"))


def test_every_kind_is_seen_even_when_files_crowd_the_front():
    facts = {"fact:file:f%03d.py" % i: _row("f%d.py 共 %d 行。" % (i, i), [i]) for i in range(80)}
    facts.update(_tail_facts(len(facts)))          # 其余种类排在 80 条 file 之后
    pack = pack_mod.pack_for_plan(_doc(facts))
    seen = {_kind(row["id"]) for row in pack["facts"]}
    assert seen == set(KINDS), "每一类都必须至少进包一条：缺 %s" % sorted(set(KINDS) - seen)


def test_rotation_fills_the_sixty_fact_window_fairly():
    facts = {}
    for kind in KINDS:
        for i in range(10):
            facts[REPS.get(kind, "fact:%s:i%d" % (kind, i))] = _row("%s 第 %d 条。" % (kind, i), [i])
    pack = pack_mod.pack_for_plan(_doc(facts))
    counted = {}
    for row in pack["facts"]:
        counted[_kind(row["id"])] = counted.get(_kind(row["id"]), 0) + 1
    assert len(pack["facts"]) == pack_mod.MAX_PLAN_FACTS == 60
    assert set(counted) == set(KINDS)
    big = {kind: count for kind, count in counted.items() if kind not in REPS}   # 只有一条的类不比
    assert min(big.values()) >= 4, "轮转要按层补齐，不是把某一类先吃满：%r" % counted


def test_byte_cap_wins_over_the_sixty_fact_window():
    facts = {"fact:file:%03d.py" % i: _row("第 %d 条：" % i + "长" * 400, [i]) for i in range(100)}
    pack = pack_mod.pack_for_plan(_doc(facts))
    assert _size(pack) <= pack_mod.MAX_PACK_BYTES
    assert pack["truncated"] is True
    assert len(pack["facts"]) < pack_mod.MAX_PLAN_FACTS


def test_graph_fact_carries_a_usable_edge_list_and_has_edges():
    edges = [{"from": "a%d.py" % i, "to": "b%d.py" % i, "kind": "import"} for i in range(100)]
    facts = {"fact:graph": _row("依赖图 100 个节点、100 条边。", [100])}
    pack = pack_mod.pack_for_plan(_doc(facts, edges=edges))
    graph = next(row for row in pack["facts"] if row["id"] == "fact:graph")
    assert graph["has_edges"] is True and pack["has_edges"] is True
    assert 0 < len(graph["edges"]) <= pack_mod.MAX_PLAN_EDGES
    assert {"from", "to", "label"} <= set(graph["edges"][0])


def test_graph_fact_without_edges_says_so():
    facts = {"fact:graph": _row("依赖图 0 条边。", [0])}
    pack = pack_mod.pack_for_plan(_doc(facts))
    graph = next(row for row in pack["facts"] if row["id"] == "fact:graph")
    assert graph["edges"] == [] and graph["has_edges"] is False
    assert pack["has_edges"] is False
