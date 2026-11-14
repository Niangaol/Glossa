"""模块节点树：把 nn.Module 的层级翻译成 trace.json 的 module 节点。

单独成文件是因为它不是「算子节点」的一部分：它只认模块树，不碰图里的张量。
"""

from __future__ import annotations

from papertrace.exceptions import BuildError
from papertrace.parse_code.fx_graph import STATIC, simple_type


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


def _all_module_types(module, from_graph: dict[str, str]) -> dict[str, str]:
    """整棵模块树的「路径 → 类型」，不只用图里出现过的那些。

    只含参数、没有任何算子的子模块不会出现在任何节点的 `nn_module_stack` 里，
    只看图就会把它的参数挂到 root 上——层级失真但 parent_id 不悬空，最难发现。
    """
    types: dict[str, str] = {"": type(module).__name__}
    for path, sub in module.named_modules():
        if path:
            types[path] = type(sub).__name__
    types.update(from_graph)  # 图里的类型名更准（可能被包装过）
    return types


def module_nodes(module, module_id: str, module_types: dict[str, str]) -> tuple[list[dict], dict[str, str]]:
    """建模块节点树：父在前、子在后，id 稳定可读（模块路径不含 @，与算子 id 不会撞）。"""
    root_loc = f"{type(module).__module__}.{type(module).__name__}"
    entries: dict[str, dict] = {
        "": _module_entry(
            module, entry_id=module_id, parent_id=None, op=type(module).__name__,
            label=module_id, loc=root_loc,
        )
    }
    types = _all_module_types(module, module_types)
    for path in sorted(types, key=lambda p: (p.count("."), p)):
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
            op=types[path],
            label=path,
            loc=root_loc,
        )
    ordered = [entries[""]] + [
        entries[p] for p in sorted(entries, key=lambda p: (p.count("."), p)) if p
    ]
    return ordered, {path: info["id"] for path, info in entries.items()}


