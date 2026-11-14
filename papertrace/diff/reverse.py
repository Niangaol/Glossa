"""反向对账：代码里做了但论文没提的实现细节（weight tying、pre-LN、bias=False…）。

v1 用写死的检测器，不交给模型——这条是产品卖点，不能靠概率。
"""

from __future__ import annotations


def diff_reverse(trace) -> list[object]:
    raise NotImplementedError("diff.reverse.diff_reverse 尚未实现")
