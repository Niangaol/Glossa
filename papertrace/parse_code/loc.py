"""把 stack_trace 变成人读的 file:line，供右栏代码视图定位。

只做纯字符串处理：meta 是普通 dict，不 import torch。
"""

from __future__ import annotations

import re

_FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
_LIBRARY_MARKS = ("site-packages", "pydeps", "\\torch\\", "/torch/")


def loc_from_stack_trace(stack_trace: str) -> str:
    """取 traceback 里第一个不属于库的帧，返回绝对路径的 `<path>:<N>`。

    `""` / `None` / 没有帧 / 全是库帧一律返回 `""`：拿不到证据就不给位置，
    绝不编行号，也绝不返回猜测值（调用方用 `or root_loc` 诚实降级）。

    两条已知局限（如实记下，别当成 bug 修歪）：
    1. 库帧判定是**路径子串**黑名单（site-packages / pydeps / \\torch\\ / /torch/），
       不是「仓库外」判定。用户自己的仓库路径里若含这些字样，会被整体误判成库帧 →
       全部帧被排除 → 返回 "" → 回落 root_loc（诚实降级，宁缺毋假）。
    2. 行号只定位到**行**，不区分行内算子：同一行可能挤着多个算子（真实夹具里 68 个
       算子都在 tests/fixtures/nanogpt/model.py:147），行内到底是哪一个只能靠 node id。
    """
    if not stack_trace:
        return ""
    for path, lineno, _func in _FRAME.findall(stack_trace):
        if any(mark in path.lower() for mark in _LIBRARY_MARKS):
            continue
        return f"{path}:{lineno}"
    return ""
