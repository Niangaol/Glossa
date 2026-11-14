"""判断题：只问「这两者是同一件事吗」，只接受 yes/no + 依据。

刻意不提供任何能一次吐出整张映射表的接口。
"""

from __future__ import annotations

from typing import NamedTuple


class JudgeResult(NamedTuple):
    yes: bool
    evidence: str


def judge(term, snippet: str) -> JudgeResult:
    raise NotImplementedError("align.judge.judge 尚未实现（M3）")
