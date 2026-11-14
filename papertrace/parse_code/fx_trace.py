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

from papertrace.exceptions import BuildError, RuntimeUnavailable, TraceUnsupported
from papertrace.parse_code.fx_edges import build_edges, finish_nodes, output_node_ids
from papertrace.parse_code.fx_graph import (
    FUSED_OPS,
    FUSION_WARNING,
    RUNTIME,
    STATIC,
    collect_module_types,
)
from papertrace.parse_code.fx_modules import module_nodes
from papertrace.parse_code.fx_nodes import build_op_nodes
from papertrace.parse_code.fx_observe import observe
from papertrace.parse_code.fx_runtime import runtime_meta
from papertrace.parse_code.fx_signature import classify, input_plan, placeholder_args

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


def trace_module(module, example_inputs, *, module_id: str = "root") -> dict:
    """追踪一个 nn.Module，返回 `{"nodes", "edges", "runtime"}`。"""
    torch_mod = _require_torch()
    _ensure_export_cache()
    try:
        module.eval()
    except Exception as exc:  # noqa: BLE001 - 用户重写的 eval 也可能炸
        raise TraceUnsupported(
            f"调用 {type(module).__name__}.eval() 失败：{_short_error(exc)}"
        ) from exc
    try:
        exported = torch_mod.export.export(module, tuple(example_inputs))
    except Exception as exc:  # noqa: BLE001 - 统一翻译成我们能解释的错
        raise TraceUnsupported(
            f"torch.export 追不动 {type(module).__name__}：{_short_error(exc)}"
        ) from exc

    graph = exported.graph
    # 能力边界：torch.export 会把 forward 里的 torch.no_grad() 这类区域包成子模块
    # （submod_N），图里留下 get_attr/call_module。它们不是张量：空根模块构造
    # GraphModule 会当场 AttributeError；就算把子模块挂回去跑通了，那个 get_attr
    # 也会被 node_kind 标成 param，让「权重 1」变成「权重 2」（实测）。宁可 exit 5
    # 说清楚，也不写一份权重数不对的 trace。纯张量图不受影响。
    artifacts = [n for n in graph.nodes if n.op in ("get_attr", "call_module")]
    if artifacts:
        raise TraceUnsupported(
            "torch.export 把部分区域包成了子模块（图里有 get_attr/call_module："
            + "、".join(n.name for n in artifacts)
            + "），常见于 forward 里的 torch.no_grad()；本切片只追纯张量图，"
            "不把非张量节点冒充成权重，按约定不写 trace（把 no_grad 移到 forward 外可绕过）"
        )
    module_types = collect_module_types(graph)
    tree, module_ids = module_nodes(module, module_id, module_types)
    root_loc = f"{type(module).__module__}.{type(module).__name__}"
    # 真实执行一遍导出图：边的两端形状从这里拿，不再靠 SSA 推断。
    # 跑不起来就**不能**冒充「真实追踪」：没有第二遍执行，形状只是 torch.export
    # 的推断，节点 source 也不再是 runtime。宁可 exit 5 不写 trace。
    plan = input_plan(exported)
    classified = classify(plan)
    try:
        # 用原图 + 真实张量跑：node.name 和 exported.graph 完全一致，
        # 参数/输入的内外名不会再错位（exported.module() 会换成 target 名）。
        # 老 torch 没有 input_specs 时 placeholder_args 会直接拒绝（fail-closed）。
        runnable = torch_mod.fx.GraphModule(torch_mod.nn.Module(), exported.graph)
        observed, observe_error = observe(
            runnable, placeholder_args(module, exported, plan, example_inputs)
        )
    except (TraceUnsupported, BuildError):
        # 契约错误（spec 对不上）与「追不动」都要原样上抛：包成 observe 失败会把
        # exit 2 变成 exit 5，两条路两个码（第八轮 I-1）。
        raise
    except Exception as exc:  # noqa: BLE001 - 统一翻译成可读原因
        observed, observe_error = {}, _short_error(exc)
    if observe_error is not None:
        raise TraceUnsupported(
            "导出图无法再真实执行一遍（自定义算子/数据依赖等），形状链只能靠推断；"
            "按约定不写 trace 冒充结果：" + observe_error
        )
    op_nodes, by_name, all_shapes = build_op_nodes(
        graph, module_id, module_ids, root_loc, observed=observed, plan=classified,
        exported=exported,
    )
    edges = build_edges(graph, by_name, op_nodes, all_shapes, observed=observed)
    nodes = list(tree) + op_nodes
    counts = finish_nodes(nodes, edges, outputs=output_node_ids(graph, by_name))
    runtime = runtime_meta(module, torch_mod, example_inputs)
    runtime["counts"] = counts
    # 走到这里说明第二遍真实执行成功了；失败已在上面转成 TraceUnsupported
    runtime["real_execution"] = {"ok": True, "reason": None}
    return {"nodes": nodes, "edges": edges, "runtime": runtime}