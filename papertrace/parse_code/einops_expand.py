"""把 einops 的 rearrange/reduce/repeat 展开成 reshape/transpose/expand。

不用手写正则：einops 自己的 parse 才是唯一正确的解析器。
"""

from __future__ import annotations


def expand_einops(bundle) -> object:
    raise NotImplementedError("parse_code.einops_expand.expand_einops 尚未实现")
