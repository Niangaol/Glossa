"""把 stack_trace 变成人读的 file:line，供右栏代码视图定位。"""

from __future__ import annotations


def loc_from_stack_trace(stack_trace: str) -> str:
    raise NotImplementedError("parse_code.loc.loc_from_stack_trace 尚未实现")
