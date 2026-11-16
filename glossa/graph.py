"""依赖图（graph，T7）：把 resolved import 画成文件级/项目级图，画不下的如实计数。

R300 节点集合：有 internal_project 边且没有文件级边 → project 级（id=csproj、label=项目名、omitted_isolated=0）；
否则 file 级，nodes = 参与至少一条边的文件 ∪ 入口指向的文件，其余计入 omitted_isolated 并记 degraded（GC31：孤立是计数，不是丢了）。
R301 截断：>MAX_GRAPH_NODES 按 (度数降序, id 升序) 取前 120，被截掉的边一并丢。
R302 环：DFS 三色，节点与邻接都按 id 升序；旋转归一化 + 去重 + 按首 id 排序（可复现）。
R303 分层：Kahn + 最长路径；环内节点（拓扑序走不到的）归最后一层，不许消失。
R304 可达：只从 target 指向单文件的入口 BFS；target=None 的复合命令不作起点。
R305 边去重：(from,to,kind) 合并、count=条数；builtin/external/unresolved/namespace 不产边。
R393 项目级边：project:<name> 按 projects[i]['csproj'] 换成 id；0 命中丢边、>1 命中取 csproj 升序第一个，两种情况都记 degraded，绝不猜 id。
R406 file 级节点的 lang/package 由 doc.files 与 packages 的 path→name 映射填实（T9 按语言着色/按包分组，None 不是好默认值）。
"""
from __future__ import annotations

import collections

from glossa import facts_io, resolve_cs

MAX_GRAPH_NODES = 120
FILE_EDGE_KINDS = frozenset({"internal", "workspace", "dynamic"})

def _strip(target: str) -> str:
    """剥掉 file:/project: 前缀；没有前缀就原样返回（不猜）。"""
    return target.split(":", 1)[1] if target.startswith(("file:", "project:")) else target

def _node_set(node_ids: list[str], edges: list[dict]) -> set[str]:
    """节点击 = 显式 ids ∪ 边端点（参与边的文件一个都不许静默消失）。"""
    return set(node_ids) | {node for edge in edges for node in (edge["from"], edge["to"])}

def _neighbours(edges: list[dict], keep: set[str]) -> dict[str, list[str]]:
    """只走两端都在 keep 里的边；邻接按 id 升序（R302 的可复现前提）。"""
    adj: dict[str, set[str]] = {node: set() for node in keep}
    for edge in edges:
        if edge["from"] in keep and edge["to"] in keep:
            adj[edge["from"]].add(edge["to"])
    return {node: sorted(nxt) for node, nxt in adj.items()}

def find_cycles(node_ids: list[str], edges: list[dict]) -> list[list[str]]:
    """DFS 三色找环；输出旋转归一化、去重、按首 id 升序（逐字节可复现）。"""
    order = sorted(_node_set(node_ids, edges))
    adj = _neighbours(edges, set(order))
    color = {node: 0 for node in order}
    found: set[tuple[str, ...]] = set()
    stack: list[str] = []

    def visit(node: str) -> None:
        color[node], _ = 1, stack.append(node)
        for nxt in adj[node]:
            if color[nxt] == 1:                       # 回边：环 = 栈上从 nxt 起的那一段
                ring = stack[stack.index(nxt):]
                start = ring.index(min(ring))         # R302 旋转归一化，从环内最小 id 起
                found.add(tuple(ring[start:] + ring[:start]))
            elif color[nxt] == 0:
                visit(nxt)
        stack.pop()
        color[node] = 2

    for node in order:
        if color[node] == 0:
            visit(node)
    return [list(ring) for ring in sorted(found)]

def longest_layers(node_ids: list[str], edges: list[dict]) -> list[list[str]]:
    """Kahn 拓扑 + 最长路径；环内节点归最后一层，层内 id 升序（R303）。"""
    order = sorted(_node_set(node_ids, edges))
    succ = _neighbours(edges, set(order))
    indeg = {node: 0 for node in order}
    for nxt in (nxt for node in order for nxt in succ[node]):
        indeg[nxt] += 1
    layer = {node: 0 for node in order}
    queue = collections.deque(node for node in order if indeg[node] == 0)
    done: list[str] = []
    while queue:
        node = queue.popleft()
        done.append(node)
        for nxt in succ[node]:
            layer[nxt] = max(layer[nxt], layer[node] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    last = max((layer[node] for node in done), default=-1) + 1   # R303：环内节点归最后一层
    layer.update({node: max(last, layer[node]) for node in order if node not in set(done)})
    return [[node for node in order if layer[node] == key] for key in sorted(set(layer.values()))]

def reachable(node_ids: list[str], edges: list[dict], starts: list[str]) -> list[str]:
    """从 starts 出发 BFS（只走两端都在节点集里的边），返回升序节点 id。"""
    keep = set(node_ids)
    adj = _neighbours(edges, keep)
    queue = collections.deque(sorted({start for start in starts if start in keep}))
    seen = set(queue)
    while queue:
        node = queue.popleft()
        for nxt in adj[node]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return sorted(seen)

def build_graph_from(node_ids: list[str], edges: list[dict], *,
                     entries: list[dict], level: str,
                     total_files: int, labels: dict | None = None) -> dict:
    """纯函数版：不依赖 doc，合成测试与真夹具走同一条代码路径。"""
    labels = labels or {}
    nodes = _node_set(node_ids, edges)
    merged: collections.Counter = collections.Counter()
    for edge in edges:                                  # R305：同 (from,to,kind) 合并计数
        merged[(edge["from"], edge["to"], edge["kind"])] += int(edge.get("count") or 1)
    degree = collections.Counter(node for src, dst, _kind in merged for node in (src, dst))
    isolated = 0 if level == "project" else max(0, total_files - len(nodes))
    truncated = len(nodes) > MAX_GRAPH_NODES
    if truncated:                                       # R301：度数降序 + id 升序，确定性
        keep = sorted(sorted(nodes, key=lambda node: (-degree[node], node))[:MAX_GRAPH_NODES])
    else:
        keep = sorted(nodes)
    kept = set(keep)
    rows = [{"from": src, "to": dst, "kind": kind, "count": count}
            for (src, dst, kind), count in sorted(merged.items()) if src in kept and dst in kept]
    node_rows = [{"id": node, "kind": "project" if level == "project" else "file",
                  "label": labels.get(node, node), "lang": None, "package": None} for node in keep]
    # R304：只有 target 指向单文件的入口才是起点；target=None 的复合命令不作起点
    starts = sorted({_strip(e["target"]) for e in entries or [] if e.get("target")} & kept)
    found = reachable(keep, rows, starts)
    return {"nodes": node_rows, "edges": rows, "cycles": find_cycles(keep, rows),
            "reachable_from_entries": found, "unreachable": sorted(kept - set(found)),
            "layers": longest_layers(keep, rows), "level": level,
            "truncated": truncated, "omitted_isolated": isolated}

def _note(bucket: list[dict], scope: str, reason: str) -> None:
    """记一条 degraded；同 scope+reason 只记一次（build_graph 被调两次也不许翻倍）。"""
    if not any(row.get("scope") == scope and row.get("reason") == reason for row in bucket):
        bucket.append({"scope": scope, "reason": reason, "count": 1})

def _project_map(projects: list[dict]) -> dict[str, list[str]]:
    """R393：项目名 → csproj 相对路径（升序）；映射不唯一由 _project_id 裁决。"""
    index: dict[str, list[str]] = collections.defaultdict(list)
    for proj in projects:
        if proj.get("name") and proj.get("csproj"):
            index[str(proj["name"])].append(str(proj["csproj"]))
    return {name: sorted(paths) for name, paths in index.items()}

def _project_id(target: str, index: dict[str, list[str]], bucket: list[dict]) -> str | None:
    """project:<name> → csproj 相对路径（节点 id 口径）；0 命中丢、>1 命中取升序第一个，都记 degraded。"""
    name, hits = _strip(target), index.get(_strip(target)) or []
    if not hits:
        _note(bucket, "graph.project_edge", f"项目边指向的项目名不在已解析项目里：{name}")
        return None
    if len(hits) > 1:
        _note(bucket, "graph.project_edge", f"项目名 {name} 对应多个 csproj，按 csproj 升序取第一个")
    return hits[0]

def build_graph(doc: dict) -> dict:
    """从 doc 的 imports/entries/projects 造图，并把画不下的部分写进 doc['degraded']。"""
    files, projects = doc.get("files") or [], doc.get("projects") or []
    known, index = {row["path"] for row in files}, _project_map(projects)
    file_edges = [{"from": imp["from"], "to": _strip(imp["target"]),
                   "kind": imp["kind"], "count": 1}
                  for imp in doc.get("imports") or []
                  if imp.get("kind") in FILE_EDGE_KINDS and imp.get("target")
                  and imp.get("from") and _strip(imp["target"]) in known]
    project_edges = [{"from": _project_id(edge["from"], index, doc["degraded"]),
                      "to": _project_id(edge["to"], index, doc["degraded"]),
                      "kind": edge["kind"], "count": 1}
                     for edge in resolve_cs.project_edges(projects)]
    project_edges = [row for row in project_edges if row["from"] and row["to"]]
    level = "project" if project_edges and not file_edges else "file"
    entries, starts = doc.get("entries") or [], []
    if level == "project":
        edges = project_edges
        labels = {str(p["csproj"]): str(p["name"]) for p in projects}
        node_ids = sorted(labels)
        for entry in entries:
            pid = _project_id(entry["target"], index, doc["degraded"]) if entry.get("target") else None
            if pid in labels:
                starts.append({"target": pid})
    else:
        edges, labels, starts = file_edges, None, entries
        node_ids = sorted({edge["from"] for edge in edges} | {edge["to"] for edge in edges}
                          | {_strip(e["target"]) for e in entries
                             if e.get("target") and _strip(e["target"]) in known})
    graph = build_graph_from(node_ids, edges, entries=starts, level=level,
                             total_files=len(files), labels=labels)
    if level == "file":
        meta = facts_io.node_meta(files, doc.get("packages") or [])   # R406：lang/package 填实
        for row in graph["nodes"]:
            row.update(meta.get(row["id"]) or {"lang": None, "package": None})
        for entry in entries:
            if not entry.get("target") and entry.get("name"):
                _note(doc["degraded"], "entries:reachability",
                      f"入口 {entry['name']} 是复合命令，未指向单文件，不作为可达性起点")
        if graph["omitted_isolated"]:
            _note(doc["degraded"], "graph.isolated",
                  f"{graph['omitted_isolated']} 个文件没有 import 关系，未画进图（计数在此，不是丢了）")
    if graph["truncated"]:
        _note(doc["degraded"], "graph.truncated",
              f"图已截断：共 {len(_node_set(node_ids, edges))} 个节点，"
              f"只画了 {MAX_GRAPH_NODES} 个（按连接数与 id 选）")
    return graph
