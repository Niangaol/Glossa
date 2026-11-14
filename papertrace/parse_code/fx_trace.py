"""主路径：torch.fx 追踪出未融合的算子图。

注意：nanoGPT 默认走 scaled_dot_product_attention，会把 QKᵀ / scale / mask /
softmax 融成一个算子。夹具强制 flash=False，就是为了让这几步各自可见。
"""

from __future__ import annotations


def trace_module(mod, args: tuple) -> object:
    raise NotImplementedError("parse_code.fx_trace.trace_module 尚未实现（M1a）")


def count_ops(bundle) -> dict[str, int]:
    raise NotImplementedError("parse_code.fx_trace.count_ops 尚未实现")
