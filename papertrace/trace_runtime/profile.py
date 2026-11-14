"""可选的 profiler。不是默认路径，只在显式开启时跑。"""

from __future__ import annotations


def profile_forward(mod, args) -> object:
    raise NotImplementedError("trace_runtime.profile.profile_forward 尚未实现")
