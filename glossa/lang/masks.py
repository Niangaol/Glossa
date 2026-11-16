"""源码掩码：单遍状态机把注释与字符串内部替换成空格（T4）。

R281：只把字符换成空格，绝不删除任何字符——masked 与原文**等长**、换行位置逐一相同。
这是硬不变量：少一个字符，之后所有行号都会静默漂移（S2 切片踩过这个坑）。
为什么是单遍状态机而不是两遍正则：
- 先掩注释再掩字符串，会把 "http://x" 里的 // 当成注释开头；
- 先掩字符串再掩注释，会把注释里的引号当成字符串开头。
两种两遍做法都会错，所以按扫描顺序一次判定当前状态。

引号字符本身保留在 masked 里：后续正则靠它定位，再用 string_at 回原文取内容。

已知边界（如实声明，不假装支持）：
- 模板字符串（反引号）整体按一个字符串处理，`${...}` 里的表达式不解析；若那里
  再嵌一个反引号，状态机会提前结束（R285 的非目标：不解析模板内部）。
- 反斜杠转义按「吃掉下一个字符」处理；未闭合的字符串/块注释一直算到文件末尾。
"""

from __future__ import annotations

_QUOTES = {"'": "squote", '"': "dquote", "`": "backquote"}
_CLOSING = {"squote": "'", "dquote": '"', "backquote": "`"}


def mask_source(text: str) -> tuple[str, list[tuple[int, int]]]:
    """返回 (masked, spans)；spans 是每个字符串字面量**内部**的 (start, end) 原文区间。"""
    out = list(text)
    spans: list[tuple[int, int]] = []
    i, n, state, start = 0, len(text), "code", 0
    while i < n:
        ch = text[i]
        if ch == "\n":                       # 换行一律原样保留（等长的硬不变量）
            if state == "line_comment":
                state = "code"
            i += 1
            continue
        if state == "code":
            if text.startswith("//", i):
                out[i] = out[i + 1] = " "
                i, state = i + 2, "line_comment"
                continue
            if text.startswith("/*", i):
                out[i] = out[i + 1] = " "
                i, state = i + 2, "block_comment"
                continue
            if ch in _QUOTES:
                state, start = _QUOTES[ch], i + 1     # 引号本身保留
                i += 1
                continue
            i += 1
            continue
        if state == "line_comment":
            out[i] = " "
            i += 1
            continue
        if state == "block_comment":
            if text.startswith("*/", i):
                out[i] = out[i + 1] = " "
                i, state = i + 2, "code"
                continue
            out[i] = " "
            i += 1
            continue
        if ch == "\\":                       # 字符串里的转义：吃掉下一个字符
            out[i] = " "
            if i + 1 < n and text[i + 1] != "\n":
                out[i + 1] = " "
            i += 2
            continue
        if ch == _CLOSING[state]:
            spans.append((start, i))
            state = "code"
            i += 1
            continue
        out[i] = " "
        i += 1
    if state in _CLOSING:
        spans.append((start, n))              # 未闭合：区间到文末，不丢这段依赖
    return "".join(out), spans


def string_at(text: str, spans: list[tuple[int, int]], quote_pos: int) -> str | None:
    """quote_pos 处引号紧跟的那个字符串的**原文**内容；不是字符串开头则 None。"""
    for begin, end in spans:
        if begin == quote_pos + 1:
            return text[begin:end]
    return None
