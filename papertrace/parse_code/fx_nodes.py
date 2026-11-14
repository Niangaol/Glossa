"""算子/输入/权重节点：`torch.export` 图 → trace.json 的 nodes（模块树在 fx_modules）。"""

from __future__ import annotations

from typing import Any

from papertrace.exceptions import BuildError
from papertrace.parse_code.fx_graph import (
    RUNTIME,
    all_val_shapes,
    fmt_shape,
    fused_items,
    mangled_collisions,
    node_kind,
    op_name,
    owned_paths,
    stack_paths,
    val_dtype,
)
from papertrace.parse_code.fx_inputs import constant_names, data_shapes, param_derived
from papertrace.parse_code.fx_shapes import tree_shapes


def build_op_nodes(
    module,
    graph,
    module_id: str,
    module_ids: dict[str, str],
    root_loc: str,
    observed: dict[str, dict[str, Any]] | None = None,
    plan: dict | None = None,
) -> tuple[list[dict], dict[str, str], dict[str, list[list[int]]]]:
    """算子/输入/权重节点。id 用 `模块id/@序号`，与模块 id（`/` 路径）互不撞车。

    形状只取真实执行观察到的值（`observed`）；观察失败时上层已 exit 5，不会走到这里。
    只有 interpreter 不经过的节点（get_attr/权重）才用 `node.meta["val"]`，那是它们的值本身。
    """
    owner, mangled_owner = owned_paths(module)
    plan = plan or {}
    spec_inputs = set(plan.get("inputs") or ())
    spec_consts = set(plan.get("consts") or ())
    spec_owner: dict[str, str] = dict(plan.get("owner") or ())
    observed = observed or {}
    nodes: list[dict] = []
    by_name: dict[str, str] = {}
    all_shapes: dict[str, list[list[int]]] = {}
    # 权重/缓冲/常量在 export 图里也是 placeholder，得先认出它们，才能从「入参」里
    # 挑出真正的数据输入。优先用 input_specs（权威：sub.x 与根上的 sub_x 不会互相覆盖）；
    # 拿不到 spec 时才退回 mangled 名（p_/b_）；那条路一旦发现压平撞名就报错，不静默取一个。
    if plan:
        param_names: set[str] = set(plan.get("params") or ()) | set(plan.get("consts") or ())
    else:
        clashes = mangled_collisions(module)
        if clashes:
            flat, first, second = clashes[0]
            raise BuildError(
                f"参数名压平后撞车：{first} 与 {second} 都会变成 {flat}；"
                "这个 torch 版本没有 graph_signature.input_specs，无法区分，拒绝出图"
            )
        param_names = {
            n.name for n in graph.nodes if node_kind(n) == "param"
        } | {n.name for n in graph.nodes if n.name in mangled_owner}
    # 只由权重/常量算出来的中间量（self.w[0]、torch.ones(...)）同样不是数据输入
    derived = param_derived(graph, param_names | constant_names(graph, op_name))

    for index, node in enumerate(graph.nodes):
        if node.op == "output":
            continue
        node_id = f"{module_id}/@{index:03d}"
        by_name[node.name] = node_id
        value = node.meta.get("val")
        seen = observed.get(node.name) or {}
        data_input: list[int] | None = None
        if seen:
            shapes = tree_shapes(seen.get("out"))
            inputs: list[list[int]] = []
            # inputs 只放**数据**输入：权重（param）位置整个跳过。
            # 否则 linear 的 shape_in 会变成权重形状，param-only 算子更会把
            # 权重冒充成数据输入（README 早就这么写，代码必须一致）。
            def is_param(value) -> bool:
                name = getattr(value, "name", None)
                return name in param_names or name in derived

            for position, arg in enumerate(seen.get("args") or []):
                source = node.args[position] if position < len(node.args) else None
                data_shapes(source, arg, is_param, inputs)
            for key, arg in (seen.get("kwargs") or {}).items():
                data_shapes(node.kwargs.get(key), arg, is_param, inputs)
            if inputs:
                data_input = inputs[0]
        else:
            shapes = all_val_shapes(value)
            inputs = []
        kind = node_kind(node)
        op = op_name(node)
        if op == "getitem" and shapes and node.name not in derived:
            # getitem 的入参是容器，它真正拿到手的只有被取出的那一项；
            # 取权重的那一项不算数据输入（否则 shape_in 变权重形状）
            inputs = [shapes[0]]
            data_input = shapes[0]

        paths = stack_paths(node)
        parent_key = paths[-1] if paths else ""
        # torch.export 把权重抬成图输入（placeholder）；kind 以 input_specs 为准，
        # 父模块也用它给的 target（参数全名），不再拿会被压平的名字猜。
        if kind == "param" or node.name in param_names:
            # 常量（torch.ones(...)、self.const）不是训练权重：分开标，摘要才不会把
            # 「常量 1 / 权重 0」写成「权重 1」，让人以为模型有可训练参数。
            kind = "const" if node.name in spec_consts else "param"
            if node.name in spec_owner:
                parent_key = spec_owner[node.name]
            else:
                parent_key = mangled_owner.get(node.name) or owner.get(node.name) or parent_key
        elif node.name in spec_inputs:
            kind = "input"
        parent_id = module_ids.get(parent_key, module_id)

        reasons: list[str] = []
        if len(shapes) > 1:
            reasons.append(
                f"多输出算子，shape_out 记的是第 1 项（共 {len(shapes)} 项："
                + "、".join(fmt_shape(sh) for sh in shapes)
                + "），逐项形状见 outputs"
            )
        fused = fused_items(op)
        if fused is not None:
            reasons.append(
                "融合算子：内部已把 " + "/".join(fused)
                + " 吞成一个 aten 算子，算子级对账会漏检；需拆开或人工核对"
            )
        reason = "；".join(reasons) or None

        nodes.append(
            {
                "id": node_id,
                "parent_id": parent_id,
                "level": "op",
                "op": op,
                "label": f"{module_id}.{node.name}",
                "loc": root_loc,
                "kind": kind,
                "shape_in": data_input if data_input is not None else [],
                "inputs": inputs,
                "shape_out": shapes[0] if shapes else [],
                "outputs": shapes,
                "dtype": val_dtype(value),
                "inplace": op.endswith("_"),
                "source": RUNTIME,
                "degraded": len(shapes) > 1 or fused is not None,
                "degraded_reason": reason,
                "repeat": 1,
                "stale": False,
            }
        )
        all_shapes[node_id] = shapes

    return nodes, by_name, all_shapes

