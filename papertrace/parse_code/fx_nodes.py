"""模块树与算子节点：`torch.export` 图 → trace.json 的 nodes。"""

from __future__ import annotations

from typing import Any

from papertrace.parse_code.fx_graph import (
    FUSED_OPS,
    RUNTIME,
    STATIC,
    all_val_shapes,
    fmt_shape,
    node_kind,
    op_name,
    owned_paths,
    simple_type,
    stack_paths,
    val_dtype,
)

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


def build_op_nodes(module, graph, module_id: str, module_ids: dict[str, str], root_loc: str) -> tuple[list[dict], dict[str, str], dict[str, list[list[int]]]]:
    """算子/输入/权重节点。id 用 `模块id/@序号`，与模块 id（`/` 路径）互不撞车。"""
    owner = owned_paths(module)
    nodes: list[dict] = []
    by_name: dict[str, str] = {}
    all_shapes: dict[str, list[list[int]]] = {}

    for index, node in enumerate(graph.nodes):
        if node.op == "output":
            continue
        node_id = f"{module_id}/@{index:03d}"
        by_name[node.name] = node_id
        value = node.meta.get("val")
        shapes = all_val_shapes(value)
        kind = node_kind(node)
        op = op_name(node)

        paths = stack_paths(node)
        parent_key = paths[-1] if paths else ""
        # torch.export 把权重抬成图输入（placeholder），名字就是参数全名 wte.weight
        if kind == "param" or (kind == "input" and node.name in owner):
            kind = "param"
            parent_key = owner.get(node.name, parent_key)
        parent_id = module_ids.get(parent_key, module_id)

        reason = None
        if len(shapes) > 1:
            reason = (
                f"多输出算子，shape_out 记的是第 1 项（共 {len(shapes)} 项："
                + "、".join(fmt_shape(sh) for sh in shapes)
                + "），逐项形状见 outputs"
            )
        elif op in FUSED_OPS:
            reason = (
                "融合算子：内部已把 " + "/".join(FUSED_OPS[op])
                + " 吞成一个 aten 算子，算子级对账会漏检；需拆开或人工核对"
            )

        nodes.append(
            {
                "id": node_id,
                "parent_id": parent_id,
                "level": "op",
                "op": op,
                "label": f"{module_id}.{node.name}",
                "loc": root_loc,
                "kind": kind,
                "shape_in": [],
                "shape_out": shapes[0] if shapes else [],
                "outputs": shapes,
                "dtype": val_dtype(value),
                "inplace": op.endswith("_"),
                "source": RUNTIME,
                "degraded": len(shapes) > 1 or op in FUSED_OPS,
                "degraded_reason": reason,
                "repeat": 1,
                "stale": False,
            }
        )
        all_shapes[node_id] = shapes

    return nodes, by_name, all_shapes


