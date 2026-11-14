"""模块树与算子节点：`torch.export` 图 → trace.json 的 nodes。"""

from __future__ import annotations

from typing import Any

from papertrace.exceptions import BuildError
from papertrace.parse_code.fx_graph import (
    RUNTIME,
    STATIC,
    all_val_shapes,
    fmt_shape,
    fused_items,
    node_kind,
    op_name,
    owned_paths,
    simple_type,
    stack_paths,
    val_dtype,
)
from papertrace.parse_code.fx_shapes import tree_shapes

def _module_entry(module, *, entry_id, parent_id, op, label, loc) -> dict:
    return {
        "id": entry_id,
        "parent_id": parent_id,
        "level": "module",
        "op": op,
        "label": label,
        "loc": loc,
        "shape_in": [],
        "shape_out": [],
        "outputs": [],
        "dtype": None,
        "inplace": False,
        "source": STATIC,
        "degraded": False,
        "degraded_reason": None,
        "repeat": 1,
        "stale": False,
    }


def module_nodes(module, module_id: str, module_types: dict[str, str]) -> tuple[list[dict], dict[str, str]]:
    """建模块节点树：父在前、子在后，id 稳定可读（模块路径不含 @，与算子 id 不会撞）。"""
    root_loc = f"{type(module).__module__}.{type(module).__name__}"
    entries: dict[str, dict] = {
        "": _module_entry(
            module, entry_id=module_id, parent_id=None, op=type(module).__name__,
            label=module_id, loc=root_loc,
        )
    }
    for path in sorted(module_types, key=lambda p: (p.count("."), p)):
        if not path:
            continue
        if "@" in path:
            # 算子 id 形如 root/@007；模块路径里再出现 @ 就可能把两种 id 撞成一个
            raise BuildError(
                f"模块路径 {path!r} 含 '@'，会和算子 id（root/@序号）撞车；请重命名子模块。"
            )
        parent = path.rsplit(".", 1)[0] if "." in path else ""
        entries[path] = _module_entry(
            module,
            entry_id=f"{module_id}/{path}",
            parent_id=entries[parent]["id"] if parent in entries else module_id,
            op=module_types[path],
            label=path,
            loc=root_loc,
        )
    ordered = [entries[""]] + [
        entries[p] for p in sorted(entries, key=lambda p: (p.count("."), p)) if p
    ]
    return ordered, {path: info["id"] for path, info in entries.items()}


def build_op_nodes(
    module,
    graph,
    module_id: str,
    module_ids: dict[str, str],
    root_loc: str,
    observed: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict], dict[str, str], dict[str, list[list[int]]]]:
    """算子/输入/权重节点。id 用 `模块id/@序号`，与模块 id（`/` 路径）互不撞车。

    形状优先取真实执行观察到的值（`observed`）；没跑成的那部分退回 `node.meta["val"]`。
    """
    owner = owned_paths(module)
    observed = observed or {}
    nodes: list[dict] = []
    by_name: dict[str, str] = {}
    all_shapes: dict[str, list[list[int]]] = {}
    # 权重在 export 图里也是 placeholder，得先认出它们，才能从「入参」里挑出真正的数据输入
    param_names = {
        n.name for n in graph.nodes if node_kind(n) == "param" or n.name in owner
    }

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
            for position, arg in enumerate(seen.get("args") or []):
                source = node.args[position] if position < len(node.args) else None
                if getattr(source, "name", None) in param_names:
                    continue
                shapes_here = tree_shapes(arg)
                inputs.extend(shapes_here)
                if data_input is None and shapes_here:
                    data_input = shapes_here[0]
            for key, arg in (seen.get("kwargs") or {}).items():
                source = node.kwargs.get(key)
                if getattr(source, "name", None) in param_names:
                    continue
                shapes_here = tree_shapes(arg)
                inputs.extend(shapes_here)
                if data_input is None and shapes_here:
                    data_input = shapes_here[0]
        else:
            shapes = all_val_shapes(value)
            inputs = []
        kind = node_kind(node)
        op = op_name(node)
        if op == "getitem" and shapes:
            # getitem 的入参是容器，它真正拿到手的只有被取出的那一项
            inputs = [shapes[0]]
            data_input = shapes[0]

        paths = stack_paths(node)
        parent_key = paths[-1] if paths else ""
        # torch.export 把权重抬成图输入（placeholder），名字就是参数全名 wte.weight
        if kind == "param" or (kind == "input" and node.name in owner):
            kind = "param"
            parent_key = owner.get(node.name, parent_key)
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


