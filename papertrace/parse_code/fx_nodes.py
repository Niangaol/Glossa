"""算子/输入/权重节点：`torch.export` 图 → trace.json 的 nodes（模块树在 fx_modules）。"""

from __future__ import annotations

from typing import Any

from papertrace.exceptions import BuildError
from papertrace.parse_code.fx_graph import (
    RUNTIME,
    all_val_shapes,
    fmt_shape,
    fused_items,
    node_kind,
    op_name,
    stack_paths,
    val_dtype,
)
from papertrace.parse_code.fx_inputs import (
    CONSTANT_LIKE_OPS,
    constant_names,
    data_shapes,
    param_derived,
)
from papertrace.parse_code.fx_contract import check_plan_table, require_real_export
from papertrace.parse_code.fx_shapes import tree_shapes
from papertrace.parse_code.fx_signature import classify, input_plan


def build_op_nodes(
    graph,
    module_id: str,
    module_ids: dict[str, str],
    root_loc: str,
    observed: dict[str, dict[str, Any]] | None = None,
    plan: dict | None = None,
    exported=None,
) -> tuple[list[dict], dict[str, str], dict[str, list[list[int]]]]:
    """算子/输入/权重节点。id 用 `模块id/@序号`，与模块 id（`/` 路径）互不撞车。

    形状只取真实执行观察到的值（`observed`）；观察失败时上层已 exit 5，不会走到这里。
    只有 interpreter 不经过的节点（get_attr/权重）才用 `node.meta["val"]`，那是它们的值本身。

    kind 只认 `torch.export` 的 `input_specs`（见 fx_signature）：没有它就无法区分
    权重/常量/数据输入，按名字猜会把整类标反（第七轮 C1）。缺 spec 时**拒绝出图**，
    不再保留 mangled 名兜底。

    **内部 API**：本函数只按 plan 分表，自己判断不了 kind 对不对（它拿不到 module）。
    外部调用请给 `exported`，入口会把 plan 与导出器自己的 input_specs 逐项核对；
    不给 exported 就等于声明「这份 plan 已经核过契约」——只有已经跑过
    `placeholder_args` 的调用方才该这么用。`fx_trace` 自己是传 exported 的。
    """
    plan = plan or {}
    if exported is not None:
        require_real_export(exported)
        check_plan_table(plan, classify(input_plan(exported)))
    spec_inputs = set(plan.get("inputs") or ())
    spec_consts = set(plan.get("consts") or ())
    spec_owner: dict[str, str] = dict(plan.get("owner") or ())
    param_names: set[str] = set(plan.get("params") or ()) | set(plan.get("consts") or ())
    observed = observed or {}
    nodes: list[dict] = []
    by_name: dict[str, str] = {}
    all_shapes: dict[str, list[list[int]]] = {}
    # 权重/缓冲/常量在 export 图里也是 placeholder，得先认出它们，才能从「入参」里
    # 挑出真正的数据输入。input_specs 是权威（sub.x 与根上的 sub_x 不会互相覆盖）；
    # 老 torch 没有它时 fail-closed：猜错的代价是整份 trace 的 kind 全反，比不出图更糟。
    # 守卫看的是「每个 placeholder 都被 spec 覆盖」，不是 plan 真假：classify([]) 是
    # 非空 dict，只判 not plan 会被它绕过去（第八轮 I-2）。
    covered = param_names | spec_inputs
    placeholders = [
        n.name for n in graph.nodes if getattr(n, "op", None) == "placeholder"
    ]
    uncovered = [name for name in placeholders if name not in covered]
    overlap = sorted(param_names & spec_inputs)
    ghost = sorted(covered - set(placeholders))
    problems: list[str] = []
    if uncovered:
        problems.append("没有 input_specs 覆盖：" + "、".join(uncovered))
    if overlap:
        problems.append("同时被标成权重和数据输入：" + "、".join(overlap))
    if ghost:
        problems.append("spec 里有图里不存在的 placeholder：" + "、".join(ghost))
    if problems:
        raise BuildError(
            "input_specs 与图对不上（" + "；".join(problems) + "）；"
            "无法区分权重/输入/常量，按约定拒绝出图（不再按 mangled 名猜，"
            "猜错会把参数和输入整类标反）"
        )
    # 只由权重/常量算出来的中间量（self.w[0]、torch.ones(...)、ones_like(x)）同样不是数据输入
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
        if op in CONSTANT_LIKE_OPS:
            # ones_like(x) 只借 x 的形状/类型，产出的是常量：它不是数据入参，
            # 也不把 x 算成自己的数据入参（否则 cat([ones_like(x), y]) 的 shape_in 会取 x）
            inputs = []
            data_input = None

        paths = stack_paths(node)
        parent_key = paths[-1] if paths else ""
        # torch.export 把权重抬成图输入（placeholder）；kind 以 input_specs 为准，
        # 父模块也用它给的 target（参数全名），不再拿会被压平的名字猜。
        if node.name in param_names:
            # 常量（self.const 这类被导出器抬成 CONSTANT_TENSOR 的属性；字面量
            # torch.ones(...) 是 ones **算子**，kind=op，不在这里）不是训练权重：分开标，摘要才不会把
            # 「常量 1 / 权重 0」写成「权重 1」，让人以为模型有可训练参数。
            kind = "const" if node.name in spec_consts else "param"
            parent_key = spec_owner.get(node.name, parent_key)
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

