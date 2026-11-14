"""用真实张量把导出的图再跑一遍，逐节点截获「消费者到底拿到了什么形状」。

`torch.export` 的 `node.meta["val"]` 是 fake tensor 的元数据：它说明导出器**认为**形状
是什么，不是消费者真的收到了什么。所以要判断形状链断没断，必须看运行时的那个值。
这里用 `torch.fx.Interpreter` 拿真实输入跑一遍，只记形状树（不留张量，省内存）。

真实执行可能失败（自定义算子、设备不支持、数据依赖分支），这时如实返回原因；
上层会直接 `TraceUnsupported` / exit 5 且不写 trace——绝不拿推断形状冒充核实过的形状。
"""

from __future__ import annotations

from typing import Any

from papertrace.parse_code.fx_shapes import shape_tree


class _ShapeRecorder:
    """记录每个节点看到的参数形状与输出形状。"""

    def __init__(self) -> None:
        self.seen: dict[str, dict[str, Any]] = {}

    def record(self, name: str, args, kwargs, out) -> None:
        self.seen[name] = {
            "args": [shape_tree(arg) for arg in args],
            "kwargs": {str(k): shape_tree(v) for k, v in kwargs.items()},
            "out": shape_tree(out),
        }


def observe(gm, example_inputs) -> tuple[dict[str, dict[str, Any]], str | None]:
    """跑一遍导出图。返回 (每个节点的形状树, 失败原因)；失败时 seen 为空。"""
    import torch

    recorder = _ShapeRecorder()

    class _Tracer(torch.fx.Interpreter):
        def run_node(self, node):  # noqa: D102 - torch 内部接口
            args, kwargs = self.fetch_args_kwargs_from_env(node)
            out = super().run_node(node)
            recorder.record(node.name, args, kwargs, out)
            return out

    try:
        _Tracer(gm).run(*example_inputs)
    except Exception as exc:  # noqa: BLE001 - 真实执行失败是合法结果，要如实上报
        return {}, f"{type(exc).__name__}: {exc}"[:400]
    return recorder.seen, None
