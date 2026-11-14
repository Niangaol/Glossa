"""真实算子级追踪：torch.export 抓一次前向，翻译成节点 + 边。

为什么不用 `torch.fx.symbolic_trace`：
nanoGPT 的 `forward` 里有 `B, T, C = x.size()` 和 `att.masked_fill(self.bias[:, :, :T, :T] == 0, ...)`，
符号追踪时 `T` 是 Proxy，切片直接 `TypeError: slice indices must be integers`。
换成 `torch.export` 后是真实（fake-tensor）执行，切片/断言都能过，而且每个节点自带
`nn_module_stack` 和 `val`（真实形状），一举解决「层级」和「形状」两件事。

翻译规则全在 `fx_graph.py`（不 import torch），本文件只管：拿到 torch、让缓存目录可写、
调 export、把结果拼起来。
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from papertrace.exceptions import RuntimeUnavailable, TraceUnsupported
from papertrace.parse_code.fx_edges import build_edges, finish_nodes
from papertrace.parse_code.fx_graph import (
    FUSED_OPS,
    FUSION_WARNING,
    RUNTIME,
    STATIC,
    all_val_shapes,
    collect_module_types,
    val_dtype,
    val_shape,
)
from papertrace.parse_code.fx_nodes import build_op_nodes, module_nodes
from papertrace.parse_code.fx_observe import observe

__all__ = [
    "FUSED_OPS",
    "FUSION_WARNING",
    "RUNTIME",
    "STATIC",
    "trace_module",
]


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


def _short_error(exc: BaseException) -> str:
    """torch.export 的报错常带整张诊断图；只留第一行，别把终端刷满。"""
    first = (str(exc).strip().splitlines() or [""])[0]
    if len(first) > 400:
        first = first[:400] + "…"
    return f"{type(exc).__name__}: {first}"


def _runtime_meta(module, torch_mod, example_inputs) -> dict:
    """把「这次追踪到底怎么跑的」记进 trace，不然结果无法复现也无法解释。"""
    inputs = []
    for item in example_inputs:
        if isinstance(item, (list, tuple)):
            inputs.extend(all_val_shapes(item))
        else:
            shape = val_shape(item)
            if shape is not None:
                inputs.append(shape)
    dtype = val_dtype(example_inputs[0]) if example_inputs else None
    return {
        "ok": True,
        "reason": None,
        "device": "cpu",
        "torch_version": str(getattr(torch_mod, "__version__", "")),
        "dtype": dtype,
        "batch": inputs[0][0] if inputs and inputs[0] else None,
        "seq_len": inputs[0][1] if inputs and len(inputs[0]) > 1 else None,
        "entry": f"{type(module).__module__}.{type(module).__name__}",
        "example_inputs": inputs,
    }


def trace_module(module, example_inputs, *, module_id: str = "root") -> dict:
    """追踪一个 nn.Module，返回 `{"nodes", "edges", "runtime"}`。"""
    torch_mod = _require_torch()
    _ensure_export_cache()
    module.eval()
    try:
        exported = torch_mod.export.export(module, tuple(example_inputs))
    except Exception as exc:  # noqa: BLE001 - 统一翻译成我们能解释的错
        raise TraceUnsupported(
            f"torch.export 追不动 {type(module).__name__}：{_short_error(exc)}"
        ) from exc

    graph = exported.graph
    module_types = collect_module_types(graph)
    tree, module_ids = module_nodes(module, module_id, module_types)
    root_loc = f"{type(module).__module__}.{type(module).__name__}"
    # 真实执行一遍导出图：边的两端形状从这里拿，不再靠 SSA 推断。
    try:
        observed, observe_error = observe(exported.module(), example_inputs)
    except Exception as exc:  # noqa: BLE001 - 观察失败不该拖垮追踪
        observed, observe_error = {}, _short_error(exc)
    op_nodes, by_name, all_shapes = build_op_nodes(
        module, graph, module_id, module_ids, root_loc, observed=observed
    )
    edges = build_edges(graph, by_name, op_nodes, all_shapes, observed=observed)
    nodes = list(tree) + op_nodes
    counts = finish_nodes(nodes, edges)
    runtime = _runtime_meta(module, torch_mod, example_inputs)
    runtime["counts"] = counts
    runtime["real_execution"] = {"ok": observe_error is None, "reason": observe_error}
    return {"nodes": nodes, "edges": edges, "runtime": runtime}
