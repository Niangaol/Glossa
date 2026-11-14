"""CPU forward 探针。默认 CPU：GPU 留给生成模型，两者不抢显存。"""

from __future__ import annotations


def run_forward(mod, args, device: str = "cpu") -> object:
    raise NotImplementedError("trace_runtime.probe.run_forward 尚未实现")
