"""schema 管不到的结构约束：id 唯一、端点存在、父子链、层级与来源一致。

JSON Schema 只能校验单对象形状；跨对象的约束（边指向空气、父子成环、id 撞车）
放这里。与 schema_validate 分开是为了让「形状校验」与「结构校验」各自可读。
"""

from __future__ import annotations


def check_key_types(
    items: list[dict],
    errors: list[str],
    where: str,
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> list[dict]:
    """把类型不对的 id/端点项剔除并记错。

    这些字段要做集合成员判断：值是 list/dict 时 `x in ids` 会抛
    TypeError: unhashable type，漏成 exit 1 + traceback，而不是 README 承诺的 exit 2。
    """
    kept: list[dict] = []
    for index, item in enumerate(items):
        bad = False
        for key in required:
            if not isinstance(item.get(key), str):
                errors.append(
                    f"{where}[{index}]: {key} 必须是字符串，实际是 {type(item.get(key)).__name__}"
                    "（该条已跳过，其余项照常校验）"
                )
                bad = True
        for key in optional:
            value = item.get(key)
            if value is not None and not isinstance(value, str):
                errors.append(
                    f"{where}[{index}]: {key} 必须是字符串或 null，实际是 {type(value).__name__}"
                    "（该条已跳过，其余项照常校验）"
                )
                bad = True
        if not bad:
            kept.append(item)
    return kept


def structural_errors(doc: dict) -> list[str]:
    """schema 管不到的整体约束：id 唯一、端点存在、父子存在、层级与来源一致。

    JSON Schema 没有 uniqueItems 之外的跨对象校验能力；这些错误若放过，UI 会静默
    用后一个节点覆盖前一个（id 撞车），或者画出一条指向空气的边。
    """
    errors: list[str] = []
    # 用户手改的 trace 可能连根都不是对象、nodes 是字符串。这类输入要报成
    # TraceSchemaError（CLI exit 2），不能让 .get() 抛 AttributeError 变 traceback。
    if not isinstance(doc, dict):
        return [f"(root): trace 根必须是 JSON 对象，实际是 {type(doc).__name__}"]
    nodes = doc.get("nodes")
    if not isinstance(nodes, list):
        errors.append(f"nodes: 必须是数组，实际是 {type(nodes).__name__}")
        nodes = []
    edges = doc.get("edges")
    if not isinstance(edges, list):
        errors.append(f"edges: 必须是数组，实际是 {type(edges).__name__}")
        edges = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{index}]: 必须是对象，实际是 {type(node).__name__}")
    nodes = [node for node in nodes if isinstance(node, dict)]
    edges = [edge for edge in edges if isinstance(edge, dict)]
    # id / parent_id / 边端点要拿去做集合运算：先确认是字符串，否则 TypeError 会漏成
    # exit 1 + traceback（README 承诺非法 trace 一律 exit 2）。
    nodes = check_key_types(nodes, errors, "nodes", required=("id",), optional=("parent_id",))
    edges = check_key_types(edges, errors, "edges", required=("id", "src", "dst"))
    ids: set[str] = set()
    for node in nodes:
        node_id = node.get("id")
        if node_id in ids:
            errors.append(f"nodes: 节点 id 重复：{node_id}")
        ids.add(node_id)
    for node in nodes:
        parent = node.get("parent_id")
        if parent is not None and parent not in ids:
            errors.append(f"nodes: {node.get('id')} 的 parent_id 不存在：{parent}")
        level, source = node.get("level"), node.get("source")
        if level == "module" and source not in (None, "static"):
            errors.append(f"nodes: {node.get('id')} 是模块节点，source 必须是 static，实际 {source}")
        if level == "op" and source not in (None, "runtime", "static", "model"):
            errors.append(f"nodes: {node.get('id')} 的 source 非法：{source}")
    by_id = {node.get("id"): node for node in nodes}
    for node in nodes:
        # 父子链必须能走到根：成环会让 UI 的展开/面包屑无限递归
        seen: set[str] = set()
        cur = node
        while cur is not None and cur.get("parent_id") is not None:
            if cur.get("id") in seen:
                errors.append(f"nodes: {node.get('id')} 的父子链成环")
                break
            seen.add(cur.get("id"))
            cur = by_id.get(cur.get("parent_id"))
        if node.get("level") == "op" and node.get("parent_id") is None:
            errors.append(f"nodes: {node.get('id')} 是算子节点，必须挂在某个模块下")
        parent = by_id.get(node.get("parent_id"))
        if parent is not None and parent.get("level") != "module":
            errors.append(
                f"nodes: {node.get('id')} 的 parent_id 必须指向模块节点，实际指向 "
                f"{parent.get('id')}（level={parent.get('level')}）"
            )
    edge_ids: set[str] = set()
    for edge in edges:
        edge_id = edge.get("id")
        if edge_id in edge_ids:
            errors.append(f"edges: 边 id 重复：{edge_id}")
        edge_ids.add(edge_id)
        for end in ("src", "dst"):
            endpoint = edge.get(end)
            if endpoint not in ids:
                errors.append(f"edges: {edge_id} 的 {end} 端点不存在：{endpoint}")
                continue
            # 边是**算子之间**的数据流；模块节点画边会让层级树和形状链互相污染
            if by_id[endpoint].get("level") != "op":
                errors.append(
                    f"edges: {edge_id} 的 {end} 端点必须是算子节点，实际是 "
                    f"{endpoint}（level={by_id[endpoint].get('level')}）"
                )
        if edge.get("src") == edge.get("dst"):
            errors.append(f"edges: {edge_id} 是自环（src == dst）：{edge.get('src')}")
    return errors


