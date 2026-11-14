"""shape 传播：沿边推每一层张量形状。推不出就标 shape_consistent=False。"""

from __future__ import annotations


def propagate_shapes(bundle, symbols) -> object:
    raise NotImplementedError("symbols.shape_prop.propagate_shapes 尚未实现")
