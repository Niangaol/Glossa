"""真实算子级追踪：torch.export 抓一次前向，产出算子节点 + 模块层级。

为什么不用 `torch.fx.symbolic_trace`：
nanoGPT 的 `forward` 里有 `B, T, C = x.size()` 和 `att.masked_fill(self.bias[:, :, :T, :T] == 0, ...)`，
符号追踪时 `T` 是 Proxy，切片直接 `TypeError: slice indices must be integers`。
换成 `torch.export` 后是真实（fake-tensor）执行，切片/断言都能过，而且每个节点自带
`nn_module_stack` 和 `val`（真实形状），一举解决「层级」和「形状」两件事。

三条底线：
1. 节点来自真实执行，形状取自 `node.meta["val"]`，不猜。
2. 多输出算子（`split`）在 schema 里表达不了 → 标 `degraded` 并写明原因。
3. 追不动就抛 `TraceUnsupported`，绝不写半张图冒充完整结果。
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from papertrace.exceptions import RuntimeUnavailable, TraceUnsupported

#: 模块节点：结构来自代码，不是来自执行。
STATIC = "static"
#: 算子节点：形状来自真实执行。
RUNTIME = "runtime"

#: 融合算子：一个 aten 算子内部吞掉了论文里好几个公式项。
#: 抓到它们不算失败，但**必须标出来**——否则算子级对账会安静地漏检。
FUSED_OPS: dict[str, tuple[str, ...]] = {
    "scaled_dot_product_attention": ("matmul", "scale", "mask", "softmax"),
    "_scaled_dot_product_attention_math": ("matmul", "scale", "mask", "softmax"),
    "scaled_dot_product_flash_attention": ("matmul", "scale", "mask", "softmax"),
    "scaled_dot_product_efficient_attention": ("matmul", "scale", "mask", "softmax"),
    "_native_multi_head_attention": ("linear", "matmul", "softmax", "linear"),
    "multi_head_attention_forward": ("linear", "matmul", "softmax", "linear"),
}

#: 融合算子的上游形状：置位后 build 会往 stderr 打一行警告。
FUSION_WARNING = "图里有 {count} 个融合算子（{names}）：论文里对应的 {items} 已被吞进单个 aten 算子，" \
    "算子级对账会漏检。要么在仓库里拆开（如 nanoGPT 夹具把 flash 写死 False），要么把这些节点标成 degraded 交给人工。"


def _require_torch():
    """拿到 torch，拿不到就给一个能读懂的错，而不是裸 ImportError。"""
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - 有 torch 的机器不会走到
        raise RuntimeUnavailable(
            "需要 torch 才能做真实算子追踪。装法见 docs/ENVIRONMENT.md"
            "（CPU 版即可：python tmpinstall\\fetch_deps.py pydeps wheels torch）。"
            "没有 torch 时不会写空 trace 冒充结果。"
        ) from exc
    return torch


def _ensure_export_cache() -> None:
    """torch.export 会拉起 inductor/dynamo，它们在 import 时就会去建缓存目录。

    机器上若已设了 `TORCHINDUCTOR_CACHE_DIR` 但目录不可写（沙箱、只读盘、别人的家目录），
    import 直接 PermissionError。这里只在「确实写不进去」时退到临时目录，别处不碰用户配置。
    """
    configured = os.environ.get("TORCHINDUCTOR_CACHE_DIR")
    if configured:
        try:
            os.makedirs(configured, exist_ok=True)
            probe = os.path.join(configured, ".papertrace-write-probe")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
            return
        except OSError:
            pass
    for base in (tempfile.gettempdir(), os.getcwd()):
        candidate = os.path.join(base, "papertrace-torch-cache")
        try:
            os.makedirs(candidate, exist_ok=True)
        except OSError:
            continue
        os.environ["TORCHINDUCTOR_CACHE_DIR"] = candidate
        return


def _simple_type(type_str: Any) -> str:
    text = str(type_str)
    return text.rsplit(".", 1)[-1] if "." in text else text


def _val_shape(value: Any) -> list[int]:
    shape = getattr(value, "shape", None)
    if shape is None:
        return []
    return [int(d) for d in shape]


def _all_val_shapes(value: Any) -> list[list[int]]:
    """一个节点所有输出张量的形状（`split` 这类元组输出逐项记录）。"""
    if isinstance(value, (list, tuple)):
        out: list[list[int]] = []
        for item in value:
            out.extend(_all_val_shapes(item))
        return out
    shape = _val_shape(value)
    return [shape] if shape else []


def _val_dtype(value: Any) -> str | None:
    if isinstance(value, (list, tuple)):
        for item in value:
            dtype = _val_dtype(item)
            if dtype:
                return dtype
        return None
    dtype = getattr(value, "dtype", None)
    return str(dtype).replace("torch.", "") if dtype is not None else None


def _op_name(node) -> str:
    schema = getattr(node.target, "_schema", None)
    if schema is not None:
        return str(schema.name).split("::")[-1]
    name = getattr(node.target, "__name__", None)
    if name:
        return str(name)
    return str(node.target)


def _stack_paths(node) -> list[str]:
    """`nn_module_stack` 里的模块路径，从最外层到最内层。"""
    stack = node.meta.get("nn_module_stack") or {}
    paths: list[str] = []
    for entry in stack.values():
        if isinstance(entry, (tuple, list)) and entry:
            path = str(entry[0])
        elif isinstance(entry, str):
            path = entry
        else:
            continue
        if path and path not in paths:
            paths.append(path)
    return paths


def _collect_module_types(graph) -> dict[str, str]:
    """从所有节点的 `nn_module_stack` 收集「模块路径 → 类型名」。"""
    types: dict[str, str] = {}
    for node in graph.nodes:
        stack = node.meta.get("nn_module_stack") or {}
        for entry in stack.values():
            if not isinstance(entry, (tuple, list)) or len(entry) < 2:
                continue
            path, type_str = str(entry[0]), entry[1]
            types.setdefault(path, _simple_type(type_str))
    return types


def _module_nodes(module, module_id: str, module_types: dict[str, str]) -> tuple[list[dict], dict[str, str]]:
    """建模块节点树：父在前、子在后，id 稳定可读。"""
    root_loc = f"{type(module).__module__}.{type(module).__name__}"
    entries: dict[str, dict] = {
        "": {
            "id": module_id,
            "parent_id": None,
            "level": "module",
            "op": type(module).__name__,
            "label": module_id,
            "loc": root_loc,
            "shape_in": [],
            "shape_out": [],
            "dtype": None,
            "inplace": False,
            "source": STATIC,
            "degraded": False,
            "degraded_reason": None,
            "repeat": 1,
            "stale": False,
        }
    }
    for path in sorted(module_types, key=lambda p: (p.count("."), p)):
        if not path:
            continue
        parent = path.rsplit(".", 1)[0] if "." in path else ""
        entries[path] = {
            "id": f"{module_id}/{path}",
            "parent_id": entries[parent]["id"] if parent in entries else module_id,
            "level": "module",
            "op": module_types[path],
            "label": path,
            "loc": root_loc,
            "shape_in": [],
            "shape_out": [],
            "dtype": None,
            "inplace": False,
            "source": STATIC,
            "degraded": False,
            "degraded_reason": None,
            "repeat": 1,
            "stale": False,
        }
    ordered = [entries[""]] + [entries[p] for p in sorted(entries, key=lambda p: (p.count("."), p)) if p]
    return ordered, {path: info["id"] for path, info in entries.items()}


def _fmt(shape: list[int]) -> str:
    return "(" + ", ".join(str(d) for d in shape) + ")" if shape else "(?)"


def _is_getitem(node) -> bool:
    """`torch.export` 的图里 node.op 是 `call_function`，真正的算子名在 target 上。"""
    if getattr(node, "op", None) == "getitem":
        return True
    try:
        return _op_name(node) == "getitem"
    except AttributeError:
        return False


def _resolve_arg_shape(node, producer_shapes: list[list[int]]) -> list[int] | None:
    """多输出生产者 + getitem 消费者：按索引取到**这一项**的形状。

    `split_with_sizes(x, [2, 3])` 的两项分别是 (2,2) 和 (2,3)；
    如果一律用第 1 项，第二条边就会把 (2,3) 记成 (2,2)，形状链在自家输出里就断了。
    """
    if len(producer_shapes) <= 1 or not _is_getitem(node) or len(node.args) < 2:
        return None
    index = node.args[1]
    if not isinstance(index, int):
        return None
    if index < 0:
        index += len(producer_shapes)
    if 0 <= index < len(producer_shapes):
        return producer_shapes[index]
    return None


def trace_module(module, example_inputs, *, module_id: str = "root") -> dict:
    """追踪一个 nn.Module，返回 schema 形状的 {"nodes": [...], "edges": [...]}。"""
    torch_mod = _require_torch()
    _ensure_export_cache()
    module.eval()
    try:
        exported = torch_mod.export.export(module, tuple(example_inputs))
    except Exception as exc:  # noqa: BLE001 - 统一翻译成我们能解释的错
        raise TraceUnsupported(
            f"torch.export 追不动 {type(module).__name__}：{type(exc).__name__}: {exc}"
        ) from exc

    graph = exported.graph
    module_types = _collect_module_types(graph)
    module_nodes, module_ids = _module_nodes(module, module_id, module_types)
    root_loc = f"{type(module).__module__}.{type(module).__name__}"

    nodes: list[dict] = list(module_nodes)
    by_name: dict[str, str] = {}
    edges: list[dict] = []
    #: 每个算子节点的**全部**输出形状（多输出时逐项），只用来解析边，不进 trace.json
    all_shapes: dict[str, list[list[int]]] = {}

    for index, node in enumerate(graph.nodes):
        if node.op == "output":
            continue
        node_id = f"{module_id}/op{index:03d}"
        by_name[node.name] = node_id
        value = node.meta.get("val")
        shapes = _all_val_shapes(value)
        multi_output = len(shapes) > 1
        paths = _stack_paths(node)
        parent_key = paths[-1] if paths else ""
        op = _op_name(node)
        node_inplace = op.endswith("_")
        reason = None
        if multi_output:
            reason = (
                f"多输出算子，shape_out 记的是第 1 项（共 {len(shapes)} 项："
                + "、".join(_fmt(sh) for sh in shapes)
                + "）"
            )
        elif op in FUSED_OPS:
            reason = (
                "融合算子：内部已把 "
                + "/".join(FUSED_OPS[op])
                + " 吞成一个 aten 算子，算子级对账会漏检；需拆开或人工核对"
            )
        nodes.append(
            {
                "id": node_id,
                "parent_id": module_ids.get(parent_key, module_id),
                "level": "op",
                "op": op,
                "label": f"{module_id}.{node.name}",
                "loc": root_loc,
                "shape_in": [],
                "shape_out": shapes[0] if shapes else [],
                "dtype": _val_dtype(value),
                "inplace": node_inplace,
                "source": RUNTIME,
                "degraded": multi_output or op in FUSED_OPS,
                "degraded_reason": reason,
                "repeat": 1,
                "stale": False,
            }
        )
        all_shapes[node_id] = shapes

    shapes_by_id = {n["id"]: n["shape_out"] for n in nodes if n["level"] == "op"}
    inplace_by_id = {n["id"]: n["inplace"] for n in nodes if n["level"] == "op"}

    for node in graph.nodes:
        if node.op == "output" or node.name not in by_name:
            continue
        dst = by_name[node.name]
        for position, arg in enumerate(list(node.args) + list(node.kwargs.values())):
            if not getattr(arg, "name", None) or arg.name not in by_name:
                continue
            src = by_name[arg.name]
            producer_shapes = all_shapes.get(src) or [shapes_by_id.get(src, [])]
            resolved = _resolve_arg_shape(node, producer_shapes)
            edge_shape = resolved if resolved is not None else (
                producer_shapes[0] if producer_shapes else []
            )
            # 形状链一致性：真的拿「生产者这一项输出的形状」去比「消费者自己记下的形状」。
            # 多输出算子只有索引解析失败、或 getitem 的形状与它取的那一项对不上，才算断链。
            consistent = bool(edge_shape)
            if consistent and resolved is not None and _is_getitem(node):
                consumed = shapes_by_id.get(dst) or []
                consistent = not consumed or consumed == resolved
            if consistent and inplace_by_id.get(src):
                consistent = bool(shapes_by_id.get(src)) and shapes_by_id.get(src) == shapes_by_id.get(
                    dst, shapes_by_id.get(src)
                )
            edges.append(
                {
                    "id": f"e:{src}->{dst}:{position}",
                    "src": src,
                    "dst": dst,
                    "shape": edge_shape,
                    "dtype": None,
                    "inplace": bool(inplace_by_id.get(src)),
                    "shape_consistent": consistent,
                }
            )

    node_index = {n["id"]: n for n in nodes if n["level"] == "op"}
    for node in nodes:
        if node["level"] != "op":
            continue
        produced = node["shape_out"]
        # shape_in：所有入边的形状（多入边时取第一条非空），供 UI 画「进→出」
        for edge in edges:
            if edge["dst"] == node["id"] and edge["shape"]:
                node["shape_in"] = list(edge["shape"])
                break
        if not produced and node["op"] not in ("placeholder", "get_attr"):
            node["degraded"] = True
            node["degraded_reason"] = node["degraded_reason"] or "该节点没有张量输出形状"

    return {"nodes": nodes, "edges": edges}
