"""算子输入的判定：哪些张量算「数据输入」，哪些是权重及其派生量。

两条规则都是被评审打出来的：
  1. 权重/缓冲/常量由 `torch.export` 的 `input_specs` 说了算（见 fx_signature），
     不靠名字猜：`sub.x` 与根上的 `sub_x` 会被压成同一个 mangled 名。
  2. 权重派生量（`self.w[0]`、`self.w[:, :2]`）与常量派生量（`torch.ones(...)`）是算子
     节点而不是 param 叶子，只看叶子会把它们当成数据输入，`shape_in` 于是变成权重/常量形状。
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


# 不带张量实参的常量构造算子：它们的输出是常量，不是模型数据输入。
CONSTANT_OPS = frozenset({"ones", "zeros", "full", "empty", "arange", "linspace", "eye"})
# 带实参的常量派生：形状随输入走，但产出的是常量，不是数据流。第七轮评审
# （I1）用 cat([ones_like(x), y]) 抓到过：cat 的 shape_in 变成了 x 的形状。
# 反向对照：rand_like 不在表里——它产出随机数，不能当常量忽略。
CONSTANT_LIKE_OPS = frozenset(
    {"ones_like", "zeros_like", "full_like", "empty_like", "new_ones", "new_zeros", "new_full", "new_empty"}
)


def constant_names(graph, op_of) -> set[str]:
    """常量/常量派生节点的名字（`torch.ones(2, 4)`、`ones_like(x)`）。

    两类都算：无实参的常量构造（`CONSTANT_OPS`），以及带实参但只借用形状/类型的
    `*_like`（`CONSTANT_LIKE_OPS`）。它们的输出都不是模型的数据输入。
    `op_of` 由调用方传入（fx_graph.op_name），这里不 import torch 也不必知道 aten 命名。
    """
    names: set[str] = set()
    for node in graph.nodes:
        if getattr(node, "op", None) in ("placeholder", "get_attr", "output"):
            continue
        op = op_of(node)
        if op in CONSTANT_LIKE_OPS:
            names.add(node.name)
            continue
        if arg_nodes(node):
            continue
        if op in CONSTANT_OPS:
            names.add(node.name)
    return names


def param_derived(graph, seed: set[str]) -> set[str]:
    """只由权重/缓冲/常量算出来的节点（含 getitem/slice/转置等）——都不是数据输入。"""
    derived: set[str] = set(seed)
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