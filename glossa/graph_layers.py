"""依赖图的环与分层（T7；R425 重写分层、R435 从 graph.py 拆出）。
R302 环：DFS 三色；节点与邻接按 id 升序，环旋转归一化到环内最小 id，去重后按首 id 排序（可复现）。
R303/R425 分层：节点按**强连通分量（SCC）缩点**（自环是单元素分量），在凝聚图（DAG）上跑最长路径；
同一 SCC 的成员同层、层内按 id 升序，非环节点的层号等于其在凝聚图上的真实深度。旧的「所有 Kahn
未出队节点统一归 max(done)+1」会把环与环下游压成一层（下游深度整段丢失），已删。
"""

from __future__ import annotations

import collections

def node_set(node_ids: list[str], edges: list[dict]) -> set[str]:
    """节点击 = 显式 ids ∪ 边端点（参与边的文件一个都不许静默消失）。"""
    return set(node_ids) | {node for edge in edges for node in (edge["from"], edge["to"])}

def neighbours(edges: list[dict], keep: set[str]) -> dict[str, list[str]]:
    """只走两端都在 keep 里的边；邻接按 id 升序（R302 的可复现前提）。"""
    adj: dict[str, set[str]] = {node: set() for node in keep}
    for edge in edges:
        if edge["from"] in keep and edge["to"] in keep:
            adj[edge["from"]].add(edge["to"])
    return {node: sorted(nxt) for node, nxt in adj.items()}

def find_cycles(node_ids: list[str], edges: list[dict]) -> list[list[str]]:
    """DFS 三色找环；输出旋转归一化、去重、按首 id 升序（逐字节可复现）。"""
    order = sorted(node_set(node_ids, edges))
    adj = neighbours(edges, set(order))
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

def strongly_connected_components(node_ids: list[str], edges: list[dict]) -> list[list[str]]:
    """Kosaraju 缩点：分量内成员与分量之间都按 id 升序；两层叠代 DFS，不怕深链爆栈。

    与 find_cycles 的区别：a↔b 且 b↔c 是一个三分量（同层），find_cycles 会报两个环。
    """
    order = sorted(node_set(node_ids, edges))
    succ = neighbours(edges, set(order))
    pred: dict[str, list[str]] = {node: [] for node in order}
    for node in order:
        for nxt in succ[node]:
            pred[nxt].append(node)
    seen: set[str] = set()
    finished: list[str] = []
    for start in order:                               # 第一遍：正图 DFS 后序
        if start in seen:
            continue
        seen.add(start)
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            node, index = stack[-1]
            if index >= len(succ[node]):
                finished.append(node)
                stack.pop()
                continue
            stack[-1] = (node, index + 1)
            if succ[node][index] not in seen:
                seen.add(succ[node][index])
                stack.append((succ[node][index], 0))
    comps: list[list[str]] = []
    comp_of: dict[str, int] = {}
    for node in reversed(finished):                   # 第二遍：反图 DFS 取分量
        if node in comp_of:
            continue
        comp_of[node] = len(comps)
        members, stack = [], [node]
        while stack:
            cur = stack.pop()
            members.append(cur)
            for other in pred[cur]:
                if other not in comp_of:
                    comp_of[other] = len(comps)
                    stack.append(other)
        comps.append(sorted(members))
    return sorted(comps)

def longest_layers(node_ids: list[str], edges: list[dict]) -> list[list[str]]:
    """SCC 缩点后的最长路径分层：环成员同层，环下游按真实深度落层（R303/R425）。"""
    order = sorted(node_set(node_ids, edges))
    comps = strongly_connected_components(node_ids, edges)
    comp_of = {node: index for index, members in enumerate(comps) for node in members}
    succ = neighbours(edges, set(order))
    dag, indeg = [set() for _ in comps], [0] * len(comps)
    for node in order:                                # 凝聚图：只有跨分量的边留下
        for nxt in succ[node]:
            src, dst = comp_of[node], comp_of[nxt]
            if src != dst and dst not in dag[src]:
                dag[src].add(dst)
                indeg[dst] += 1
    depth = [0] * len(comps)
    queue = collections.deque(index for index in range(len(comps)) if not indeg[index])
    while queue:
        here = queue.popleft()
        for nxt in sorted(dag[here]):
            depth[nxt] = max(depth[nxt], depth[here] + 1)
            indeg[nxt] -= 1
            if not indeg[nxt]:
                queue.append(nxt)
    layers: dict[int, list[str]] = {}
    for node in order:                                # order 已升序 → 层内自然升序
        layers.setdefault(depth[comp_of[node]], []).append(node)
    return [layers[key] for key in sorted(layers)]
