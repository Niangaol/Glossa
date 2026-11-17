"""六种图表范式的字段契约与 validate_figure（A2，设计 §3）。

AI 只选范式 + 填内容；节点、连线、分组是它的输入，画线、坐标、颜色仍归程序（A4）。
这里只做一件事：把 AI 给的 figure 洗成「每条边都有出处、每个节点都合法」的干净结构。

规则（派发书 §3，逐条有测试）：未知 pattern 抛 BuildError 并列出六种；节点缺 id / 重复 id 抛
BuildError；节点超过 60 截断到 60 并写「另有 N 个节点未画」；边的 fact 不在 doc["facts"] 丢边并
计数；fact 在但核不上（或没有可核对的边）同样丢边、计数、点名；返回的 clean_fig 只留
pattern/caption/nodes/edges/groups。口径是「宁缺不编」：核不上就当没说，绝不画查不到出处的线。
"""

from __future__ import annotations

from papertrace.exceptions import BuildError

MAX_NODES = 60
_A = {"id": "a.ts", "label": "a.ts", "fact": "fact:file:a.ts"}
_B = {"id": "b.ts", "label": "b.ts", "fact": "fact:file:b.ts"}
_EDGE = {"from": "a.ts", "to": "b.ts", "label": "import", "fact": "fact:file:a.ts"}


def _fig(pattern: str, caption: str, nodes, edges=(), **extra) -> dict:
    """示例的构造器：节点/边各拷一份，示例之间不共享可变对象。"""
    fig = {"pattern": pattern, "caption": caption,
           "nodes": [dict(node) for node in nodes], "edges": [dict(edge) for edge in edges]}
    return fig | extra


PATTERNS: dict[str, dict] = {
    "layered": {
        "summary": "分层/拓扑图：模块分几层，箭头从左到右是依赖方向。", "fields": ["nodes", "edges", "groups"],
        "example": _fig("layered", "依赖分层：左边是被依赖的，右边是调用方", (_A, _B), (_EDGE,),
                        groups=[{"label": "根目录", "members": ["a.ts", "b.ts"]}]),
    },
    "flow": {
        "summary": "调用链时序：从入口到出口按 step 一步一步。", "fields": ["nodes", "edges"],
        "example": _fig("flow", "一次请求怎么走进来",
                        ({"id": "a.ts", "label": "a.ts 入口", "fact": "fact:file:a.ts", "step": 1},
                         {"id": "b.ts", "label": "b.ts 处理", "fact": "fact:file:b.ts", "step": 2}),
                        (_EDGE,)),
    },
    "matrix": {
        "summary": "依赖矩阵：谁依赖谁一眼看全部，格子位置由程序算。", "fields": ["nodes", "edges"],
        "example": _fig("matrix", "两个文件之间的依赖", (_A, _B), (_EDGE,)),
    },
    "tree": {
        "summary": "目录/包含树：包到文件，节点的 parent 指向上一层。", "fields": ["nodes"],
        "example": _fig("tree", "包与它下面的文件",
                        ({"id": "root", "label": "仓库根", "kind": "dir"},
                         {"id": "a.ts", "label": "a.ts", "parent": "root", "fact": "fact:file:a.ts"},
                         {"id": "b.ts", "label": "b.ts", "parent": "root", "fact": "fact:file:b.ts"})),
    },
    "bars": {
        "summary": "指标条：文件数、符号数、import 这类数字横向对比。", "fields": ["bars"],
        "example": _fig("bars", "三个数字放一起比大小", (),
                        bars=[{"label": "文件", "fact": "fact:files", "value": 2}]),
    },
    "cards": {
        "summary": "文件图鉴：每个关键文件一张卡，写路径、一行摘要、指标。", "fields": ["cards"],
        "example": _fig("cards", "关键文件一览", (),
                        cards=[{"path": "a.ts", "fact": "fact:file:a.ts", "summary": "入口"}]),
    },
}


def _list_field(fig: dict, key: str) -> list:
    value = fig.get(key) or []
    if not isinstance(value, list):
        raise BuildError("figure.%s 必须是数组，收到 %r" % (key, type(value).__name__))
    return value


def _keys(node: dict) -> set[str]:
    """一个节点可能被事实边用到的所有写法：节点 id、标签、它自己的 fact id、路径。"""
    out = set()
    for key in ("id", "label", "fact", "path", "parent"):
        value = node.get(key)
        if isinstance(value, str) and value:
            out.add(value)
    return out


def _node_index(nodes: list) -> dict:
    index: dict[str, dict] = {}
    for pos, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise BuildError("第 %d 个节点不是对象：%r" % (pos + 1, node))
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            raise BuildError("第 %d 个节点没有 id（每个节点都要有唯一 id）：%r" % (pos + 1, node))
        if node_id in index:
            raise BuildError("节点 id %r 重复了（第 %d 个与第 %d 个）：图里 id 必须唯一"
                             % (node_id, nodes.index(index[node_id]) + 1, pos + 1))
        index[node_id] = node
    return index


def _edge_verdict(facts: dict, index: dict, edge: dict) -> str:
    """'' = 这条边有出处可画；否则是丢弃原因（可读的中文）。"""
    fact_id = edge.get("fact")
    if not isinstance(fact_id, str) or fact_id not in facts:
        return "事实台账里没有 %r，这条边没有出处" % (fact_id,)
    source, target = edge.get("from"), edge.get("to")
    keys_from = _keys(index.get(source) or {}) | {source}
    keys_to = _keys(index.get(target) or {}) | {target}
    rows = (facts[fact_id] or {}).get("edges")
    rows = rows if isinstance(rows, list) else []
    if not rows:
        return "%s 上没有可核对的边（numbers/文本核对不了 %s→%s）" % (fact_id, source, target)
    if not any(isinstance(row, dict) and row.get("from") in keys_from and row.get("to") in keys_to
               for row in rows):
        return "%s 说的方向和 %s→%s 对不上" % (fact_id, source, target)
    return ""


def validate_figure(doc: dict, fig: dict) -> tuple[dict, int, list[str]]:
    """校验并清洗一张图，返回 (clean_fig, dropped_edges, notes)。"""
    if not isinstance(fig, dict):
        raise BuildError("figure 必须是对象，收到 %r" % (type(fig).__name__,))
    pattern = fig.get("pattern")
    if pattern not in PATTERNS:
        raise BuildError("不认识的图表范式 %r；只有六种：%s" % (pattern, "、".join(PATTERNS)))
    nodes = _list_field(fig, "nodes")
    index = _node_index(nodes)
    notes: list[str] = []
    kept = nodes
    if len(nodes) > MAX_NODES:
        notes.append("节点共 %d 个，只画前 %d 个：另有 %d 个节点未画"
                     % (len(nodes), MAX_NODES, len(nodes) - MAX_NODES))
        kept = nodes[:MAX_NODES]
    known = {node.get("id") for node in kept}

    facts = doc.get("facts") or {}
    clean_edges, dropped, seen = [], 0, set()
    for edge in _list_field(fig, "edges"):
        if not isinstance(edge, dict):
            raise BuildError("figure.edges 里有一项不是对象：%r" % (edge,))
        if edge.get("from") not in known or edge.get("to") not in known:
            note = "连线 %s→%s 指向的节点没有画（超上限截断或不在 nodes 里），已一并省略" % (
                edge.get("from"), edge.get("to"))
        else:
            note = _edge_verdict(facts, index, edge)
            if note:
                dropped += 1
                note = "连线 %s→%s 已丢弃：%s" % (edge.get("from"), edge.get("to"), note)
        if note:
            if note not in seen:
                seen.add(note)
                notes.append(note)
            continue
        clean_edges.append(dict(edge))

    clean = {
        "pattern": pattern,
        "caption": fig.get("caption") or "",
        "nodes": [dict(node) for node in kept],
        "edges": clean_edges,
        "groups": [dict(group) for group in _list_field(fig, "groups") if isinstance(group, dict)],
    }
    return clean, dropped, notes
