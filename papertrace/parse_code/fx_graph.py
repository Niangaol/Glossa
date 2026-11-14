"""把 torch.export 的图翻译成 trace.json 的节点与边。

本文件**不 import torch**：只吃 fx 图对象，方便离线单测翻译规则。

三条底线：
1. 形状只取自 `node.meta["val"]`，不猜；0 维张量记 `[]`（标量），拿不到形状记 `None`。
2. 多输出算子（split）逐项记进 `outputs`，getitem 按索引取**这一项**的形状。
3. 容器参数（`cat([a, b])`）递归展开，别静默丢边。
"""

from __future__ import annotations

from typing import Any

#: 模块节点：结构来自代码，不是来自执行。
STATIC = "static"
#: 算子节点：形状来自真实执行。
RUNTIME = "runtime"

#: 融合算子：一个 aten 算子内部吞掉了论文里好几个公式项。
FUSED_OPS: dict[str, tuple[str, ...]] = {
    "scaled_dot_product_attention": ("matmul", "scale", "mask", "softmax"),
    "_scaled_dot_product_attention_math": ("matmul", "scale", "mask", "softmax"),
    "scaled_dot_product_flash_attention": ("matmul", "scale", "mask", "softmax"),
    "scaled_dot_product_efficient_attention": ("matmul", "scale", "mask", "softmax"),
    "_native_multi_head_attention": ("linear", "matmul", "softmax", "linear"),
    "multi_head_attention_forward": ("linear", "matmul", "softmax", "linear"),
}

FUSION_WARNING = (
    "图里有 {count} 个融合算子（{names}）：论文里对应的 {items} 已被吞进单个 aten 算子，"
    "算子级对账会漏检。要么在仓库里拆开（如 nanoGPT 夹具把 flash 写死 False），"
    "要么把这些节点标成 degraded 交给人工。"
)


def simple_type(type_str: Any) -> str:
    text = str(type_str)
    return text.rsplit(".", 1)[-1] if "." in text else text


def val_shape(value: Any) -> list[int] | None:
    """张量形状。0 维张量是 []（标量），不是「未知」；未知返回 None。"""
    shape = getattr(value, "shape", None)
    if shape is None:
        return None
    return [int(d) for d in shape]


def all_val_shapes(value: Any) -> list[list[int]]:
    """一个节点所有输出张量的形状（元组/列表输出逐项递归）。"""
    if isinstance(value, (list, tuple)):
        out: list[list[int]] = []
        for item in value:
            out.extend(all_val_shapes(item))
        return out
    shape = val_shape(value)
    return [shape] if shape is not None else []


def val_dtype(value: Any) -> str | None:
    if isinstance(value, (list, tuple)):
        for item in value:
            dtype = val_dtype(item)
            if dtype:
                return dtype
        return None
    dtype = getattr(value, "dtype", None)
    return str(dtype).replace("torch.", "") if dtype is not None else None


def op_name(node) -> str:
    """placeholder/get_attr 用自己的 op 名，别拿属性名（wte.weight）冒充算子名。"""
    if getattr(node, "op", None) in ("placeholder", "get_attr"):
        return node.op
    target = getattr(node, "target", None)
    schema = getattr(target, "_schema", None)
    if schema is not None:
        return str(schema.name).split("::")[-1]
    name = getattr(target, "__name__", None)
    return str(name) if name else str(target)


def node_kind(node) -> str:
    """input（形参）/ param（权重）/ op（算子）。"""
    if getattr(node, "op", None) == "placeholder":
        return "input"
    if getattr(node, "op", None) == "get_attr":
        return "param"
    return "op"


def stack_paths(node) -> list[str]:
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


def collect_module_types(graph) -> dict[str, str]:
    """从所有节点的 `nn_module_stack` 收集「模块路径 → 类型名」。"""
    types: dict[str, str] = {}
    for node in graph.nodes:
        stack = node.meta.get("nn_module_stack") or {}
        for entry in stack.values():
            if not isinstance(entry, (tuple, list)) or len(entry) < 2:
                continue
            path, type_str = str(entry[0]), entry[1]
            types.setdefault(path, simple_type(type_str))
    return types


def owned_paths(module) -> dict[str, str]:
    """参数/缓冲区名 → 拥有它的模块路径。

    同时登记 torch.export 的 mangled 名（`wte.weight` → `p_wte_weight`）：
    export 把权重抬成图输入，光看节点名分不清它是权重还是用户输入。
    """
    owner: dict[str, str] = {}
    # 直接遍历模块树，不走 named_parameters：tied weight（lm_head.weight 与 wte.weight
    # 同一个 Parameter）会被 named_parameters 去重掉，只看它就漏了。
    for mod_name, mod in module.named_modules():
        prefix = f"{mod_name}." if mod_name else ""
        for attr in list(getattr(mod, "_parameters", {}) or {}) + list(getattr(mod, "_buffers", {}) or {}):
            full = f"{prefix}{attr}"
            owner[full] = mod_name
            mangled = full.replace(".", "_")
            owner["p_" + mangled] = mod_name
            owner["b_" + mangled] = mod_name
    return owner



def fmt_shape(shape) -> str:
    """() 表示 0 维标量；(?) 表示形状未知。"""
    if shape is None:
        return "(?)"
    if not shape:
        return "()"
    return "(" + ", ".join(str(d) for d in shape) + ")"


