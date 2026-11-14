"""算子输入的判定：哪些张量算「数据输入」，哪些是权重及其派生量。

两条规则都是被评审打出来的：
  1. 参数全名可能和形参名相同（\`self.x\` + \`forward(self, x)\`），所以 placeholder
     只按 export 的 mangled 名（\`p_x\` / \`b_x\`）认权重，绝不能拿全名猜。
  2. 权重派生量（\`self.w[0]\`、\`self.w[:, :2]\`）是算子节点而不是 param 叶子，
     只看叶子会把它们当成数据输入，\`shape_in\` 于是变成权重形状。
"""

from papertrace.parse_code.fx_shapes import tree_leaf, tree_shapes


def arg_nodes(node, out: list | None = None) -> list:
    """递归收集一个节点实参里的所有 fx 节点（展开 list/tuple/dict）。"""
    found: list = [] if out is None else out
    for value in list(getattr(node, "args", ()) or ()) + list((getattr(node, "kwargs", {}) or {}).values()):
        _collect(value, found)
    return found


def _collect(value, found: list) -> None:
    if getattr(value, "name", None) is not None and hasattr(value, "op"):
        found.append(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect(item, found)
    elif isinstance(value, dict):
        for item in value.values():
            _collect(item, found)


def param_derived(graph, param_names: set[str]) -> set[str]:
    """只由权重/缓冲算出来的节点（含 getitem/slice/转置等）——也算权重，不是数据输入。"""
    derived: set[str] = set(param_names)
    for node in graph.nodes:
        if getattr(node, "op", None) in ("placeholder", "get_attr", "output"):
            continue
        sources = arg_nodes(node)
        if sources and all(source.name in derived for source in sources):
            derived.add(node.name)
    return derived


def data_shapes(raw, tree, is_param, out: list[list[int]]) -> None:
    """按「原始参数树」与「观察到的形状树」递归配对，跳过任意深度的权重。

    torch.cat([self.w, x]) 的权重藏在列表里：只看顶层参数名会把它当数据输入，
    shape_in 就变成权重形状（README 承诺过绝不这样）。
    """
    if raw is None or tree is None:
        return
    if getattr(raw, "name", None) is not None and is_param(raw):
        return
    leaf = tree_leaf(tree)
    if leaf is not None:
        out.append(leaf)
        return
    if isinstance(tree, dict) and isinstance(tree.get("l"), list):
        items = raw if isinstance(raw, (list, tuple)) else ()
        for sub_raw, sub_tree in zip(items, tree["l"]):
            data_shapes(sub_raw, sub_tree, is_param, out)
        return
    if isinstance(tree, dict) and isinstance(tree.get("d"), dict):
        mapping = raw if isinstance(raw, dict) else {}
        for key, sub_tree in tree["d"].items():
            data_shapes(mapping.get(key), sub_tree, is_param, out)