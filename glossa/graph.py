"""依赖图（graph，T7）：把 resolved import 画成文件级/项目级图，画不下的如实计数。

R300 节点集合：有 internal_project 边且没有文件级边 → project 级（id=csproj、label=项目名、omitted_isolated=0）；
否则 file 级，nodes = 参与至少一条边的文件 ∪ 入口指向的文件，其余计入 omitted_isolated 并记 degraded（GC31：孤立是计数，不是丢了）。
R301 截断：>MAX_GRAPH_NODES 按 (度数降序, id 升序) 取前 120，被截掉的边一并丢；截掉几个另存
truncated_nodes（R430：页面要能分开显示「孤立未画」与「截断未画」，不许解析中文散文）。
R302 环 / R303 分层：见 glossa/graph_layers.py（R425 起按 SCC 缩点，环下游不与环同层）。
R304 可达：只从 target 指向单文件的入口 BFS；target=None 的复合命令不作起点。
R305 边去重：(from,to,kind) 合并、count=条数；builtin/external/unresolved/namespace 不产边。
R393 项目级边：project:<name> 按 projects[i]['csproj'] 换成 id；>1 命中取 csproj 升序第一个并记 degraded，绝不猜 id。
R406 file 级节点的 lang/package 由 doc.files 与 packages 的 path→name 映射填实（T9 按语言着色/按包分组）。
R431 没有可解析的入口时 unreachable 不成立：置空并记 degraded（页面不显示不存在的「全部不可达」）。
R432 omitted_isolated 的文案要说出其中有多少是清单、文档等不产生 import 的文件（口径不变，措辞不许错报）。
R485「其中 M 个是清单」只在截断前的节点集上算一次、落成 graph.omitted_manifests；degraded 句与讲解页
都只读这个键（页面不许拿自己那套截断后的节点集另算一份，两处数字必须相等）。
R479 混合仓（有 csproj 又有文件级 import）：level 仍是二选一、两种边**不混画**，但项目引用边
恒写入 graph.project_edges（空也写空数组），由 fact:graph 与讲解页如实披露，不许静默省略。
"""

from __future__ import annotations

import collections

from glossa import facts_io, resolve_cs
from glossa.exclude import SYMBOL_LANGS
from glossa.graph_layers import find_cycles, longest_layers, neighbours, node_set

MAX_GRAPH_NODES = 120
FILE_EDGE_KINDS = frozenset({"internal", "workspace", "dynamic"})

def _strip(target: str) -> str:
    """剥掉 file:/project: 前缀；没有前缀就原样返回（不猜）。"""
    return target.split(":", 1)[1] if target.startswith(("file:", "project:")) else target

def reachable(node_ids: list[str], edges: list[dict], starts: list[str]) -> list[str]:
    """从 starts 出发 BFS（只走两端都在节点集里的边），返回升序节点 id。"""
    keep = set(node_ids)
    adj = neighbours(edges, keep)
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
                     total_files: int, labels: dict | None = None,
                     omitted_manifests: int = 0) -> dict:
    """纯函数版：不依赖 doc，合成测试与真夹具走同一条代码路径。"""
    labels = labels or {}
    nodes = node_set(node_ids, edges)
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
            "reachable_from_entries": found,
            "unreachable": sorted(kept - set(found)) if found else [],   # R431
            "layers": longest_layers(keep, rows), "level": level,
            "truncated": truncated, "truncated_nodes": len(nodes) - len(keep),
            "omitted_isolated": isolated,               # R485：孤立的 M 由 build_graph 截断前算好传进来
            "omitted_manifests": int(omitted_manifests)}

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
    """>1 命中按 csproj 升序取第一个并记降级（R393/R434）。

    未解析的 ProjectReference 由 manifests_cs 记 degraded —— resolve_cs.project_edges 只对
    已解析引用产边，所以这里不会出现「0 命中」，不再留死分支（R434）。
    """
    name, hits = _strip(target), index.get(_strip(target)) or []
    if len(hits) > 1:
        _note(bucket, "graph.project_edge", f"项目名 {name} 对应多个 csproj，按 csproj 升序取第一个")
    return hits[0] if hits else None

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
    graph["project_edges"] = project_edges        # R479：无论 level 都落盘，丢弃与混画都算谎报
    if level == "file":
        meta = facts_io.node_meta(files, doc.get("packages") or [])   # R406：lang/package 填实
        for row in graph["nodes"]:
            row.update(meta.get(row["id"]) or {"lang": None, "package": None})
        for entry in entries:
            if not entry.get("target") and entry.get("name"):
                _note(doc["degraded"], "entries:reachability",
                      f"入口 {entry['name']} 是复合命令，未指向单文件，不作为可达性起点")
        if graph["omitted_isolated"]:                  # R485：M 在截断前算一次，页面只读这一个数
            drawn = node_set(node_ids, edges)          # 截断前节点集：孤立口径不受截断影响
            graph["omitted_manifests"] = sum(
                1 for row in files if row["path"] not in drawn
                and row.get("lang") not in SYMBOL_LANGS)
            _note(doc["degraded"], "graph.isolated",
                  f"{graph['omitted_isolated']} 个文件没有进入关系图"
                  f"（其中 {graph['omitted_manifests']} 个是清单、文档等不产生 import 的文件）")
    if graph["nodes"] and not graph["reachable_from_entries"]:        # R431
        _note(doc["degraded"], "graph.reachability", "仓里没有可解析的入口，unreachable 不适用")
    if graph["truncated"]:
        _note(doc["degraded"], "graph.truncated",
              f"图已截断：共 {len(node_set(node_ids, edges))} 个节点，"
              f"只画了 {MAX_GRAPH_NODES} 个（按连接数与 id 选）")
    return graph
