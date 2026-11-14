"""判断题：只问「这两者是同一件事吗」，只接受 yes/no + 依据。

刻意不提供任何能一次吐出整张映射表的接口。
"""

from __future__ import annotations

from typing import NamedTuple

from papertrace.constants import EVIDENCE_MAX_CHARS
from papertrace.exceptions import LLMUnavailable
from papertrace.llm.client import get_llm
from papertrace.llm.prompts import judge_prompt


class JudgeResult(NamedTuple):
    yes: bool
    evidence: str


#: R51：逐行找以这两个键开头的行。全角冒号也必须认——模型经常顺手打成全角。
_VERDICT_KEYS = ("verdict:", "verdict：")
_EVIDENCE_KEYS = ("evidence:", "evidence：")

#: 首 token 后面常跟着的标点，取 token 时一并剥掉（R51）。
_TRIM = " \t\r\n,，.。;；!！?？:：、)}]）】>》\"'“”‘’…"


def _line_value(text: str, keys: tuple[str, ...]) -> str:
    """R51：逐行扫，返回第一个以 keys 之一开头的行的「其余文本」。

    键大小写不敏感；找不到返回空串。刻意**不**对整个响应取首 token——
    那是 `Verdict:` 自己，会让真实后端全判失败（已批修订 S19）。
    """
    for line in text.splitlines():
        stripped = line.strip()
        for key in keys:
            if stripped.lower().startswith(key):
                return stripped[len(key):]
    return ""


def _first_token(value: str) -> str:
    """取赋值的首 token，剥掉尾随标点后转小写（R51）。"""
    words = value.split()
    if not words:
        return ""
    return words[0].strip(_TRIM).lower()


def _is_yes(value: str) -> bool:
    """R51：只有首 token 恰好是 yes 才算 yes，其余一律 False。"""
    return _first_token(value) == "yes"


def _evidence(text: str) -> str:
    """R50：strip 外侧空白 → 按**字符数**（`len(str)`，不是字节）截断到 40。

    中文 1 字 3 字节，按字节截断只剩 13 个汉字，会无谓丢掉证据。
    """
    return _line_value(text, _EVIDENCE_KEYS).strip()[:EVIDENCE_MAX_CHARS]


def judge(term: str, snippet: str) -> JudgeResult:
    """问一个是/否问题；答不成 yes/no 或后端不可用，一律 `JudgeResult(False, "")`。

    R47：`term` 是公式项的文本字符串，不是 Term 对象也不是 dict；本模块
    刻意不提供任何能一次吐出整张映射表的接口。
    R53：`chat` 返回的是 `ChatResult` 不是 str，必须取 `.text` 再解析两行格式。
    R49：`JudgeResult` 没有 reason 字段——那句给用户看的 reason 由 S9 写进
    unresolved / anchor，不是这里的职责。
    """
    try:
        reply = get_llm().chat(judge_prompt(term, snippet))
    except LLMUnavailable:
        return JudgeResult(False, "")
    text = reply.text
    return JudgeResult(_is_yes(_line_value(text, _VERDICT_KEYS)), _evidence(text))


def judge_score(result: JudgeResult) -> float:
    """R57：yes 且依据非空且非纯空白 → 1.0；否则 0.0。

    `no` 一律 0.0，不管有没有 evidence——没有依据的 yes 不算数（RF2）。
    """
    if result.yes and result.evidence.strip():
        return 1.0
    return 0.0
