"""可选的 torch.export 回归。失败只写 meta.runtime，不阻断 build。"""

from __future__ import annotations


def try_export(mod, args: tuple) -> tuple[bool, str | None]:
    raise NotImplementedError("parse_code.export_try.try_export 尚未实现")
