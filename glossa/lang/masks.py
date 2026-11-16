"""源码掩码：单遍状态机把注释/字符串/正则字面量内部替换成空格（T4）。

R281：只把字符换成空格，绝不删除任何字符——masked 与原文**等长**、换行位置逐一相同。
这是硬不变量：少一个字符，之后所有行号都会静默漂移（S2 切片踩过这个坑）。
为什么是单遍状态机而不是两遍正则：
- 先掩注释再掩字符串，会把 "http://x" 里的 // 当成注释开头；
- 先掩字符串再掩注释，会把注释里的引号当成字符串开头。
两种两遍做法都会错，所以按扫描顺序一次判定当前状态。

R375：**正则字面量也要掩**（体换空格、两个斜杠保留）。不认它的话 `/['"]/` 里的引号会被
当成字符串开头：其后整段被掩掉（静默省略），字符串里的文本又会被当代码抓出幽灵 import
（静默造假边）。判据是「前一个有意义的字符/关键字」：`( , = : [ ! & | ? { } ; + - * % < > ~ ^`
与 return/typeof/case/do/else/in/of/new/delete/void/throw 之后算正则开头；标识符、数字、
`)`、`]` 之后按除号处理。启发式必然不完美，所以**未闭合的结构必须记 degraded**。

引号字符本身保留在 masked 里：后续正则靠它定位，再用 string_at 回原文取内容。

已知边界（如实声明，不假装支持）：
- 模板字符串（反引号）整体按一个字符串处理，`${...}` 里的表达式不解析；若那里再嵌一个
  反引号，状态机会提前结束（R285 的非目标：不解析模板内部）。
- 反斜杠转义按「吃掉下一个字符」处理；字符串/块注释一直到文件末尾都没闭合时，
  mask_source_notes 会返回一条 degraded（不再假装掩码完整）。
- 正则判据是启发式：比较运算里的 `/`（如 `a = b < c / d`）正常按除号处理，但
  「行首的 /」一律先按正则试，靠换行未闭合时整行回滚兜底。
"""

from __future__ import annotations

_QUOTES = {"'": "squote", '"': "dquote", "`": "backquote"}
_CLOSING = {"squote": "'", "dquote": '"', "backquote": "`"}
_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_WORDS = frozenset((
    "return", "typeof", "case", "do", "else", "in", "of", "new", "delete",
    "void", "throw"))


def _regex_allowed(text: str, i: int) -> bool:
    """R375：`/` 之前的有意义字符/关键字决定它是正则开头还是除号。"""
    j = i - 1
    while j >= 0 and text[j] in " \t\r\n":
        j -= 1
    if j < 0:
        return True                                   # 行首 / 文件首
    ch = text[j]
    if ch in _REGEX_AFTER:
        return True
    if ch.isalnum() or ch in "_$":
        k = j
        while k >= 0 and (text[k].isalnum() or text[k] in "_$"):
            k -= 1
        return text[k + 1:j + 1] in _REGEX_WORDS
    return False                                      # 标识符/数字/)/] → 除号


def _unclosed(text: str, pos: int) -> str:
    """R375：未闭合结构必须可见，行号指向开引号/开注释所在行。"""
    return "未闭合的字符串/块注释，掩码可能不完整（行号 %d）" % (
        text.count("\n", 0, pos) + 1)


def _scan(text: str) -> tuple[str, list[tuple[int, int]], list[str]]:
    out = list(text)
    spans: list[tuple[int, int]] = []
    notes: list[str] = []
    i, n, state, start = 0, len(text), "code", 0
    while i < n:
        ch = text[i]
        if ch == "\n":                        # 换行一律原样保留（等长的硬不变量）
            if state == "line_comment":
                state = "code"
            elif state in ("regex", "regex_class"):
                for k in range(start, i):     # 正则不能跨行：判定失误，恢复本行原文
                    out[k] = text[k]
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
                i, state, start = i + 2, "block_comment", i
                continue
            if ch == "/" and _regex_allowed(text, i):
                i, state, start = i + 1, "regex", i + 1
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
        if state == "regex":
            if ch == "\\":                     # 转义：吃掉下一个字符
                out[i] = " "
                if i + 1 < n and text[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if ch == "[":
                out[i] = " "
                i, state = i + 1, "regex_class"
                continue
            if ch == "/":                     # 结束斜杠保留
                i, state = i + 1, "code"
                continue
            out[i] = " "
            i += 1
            continue
        if state == "regex_class":            # [...] 里的 / 不结束正则
            if ch == "\\":
                out[i] = " "
                if i + 1 < n and text[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if ch == "]":
                out[i] = " "
                i, state = i + 1, "regex"
                continue
            out[i] = " "
            i += 1
            continue
        if ch == "\\":                         # 字符串里的转义：吃掉下一个字符
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
        notes.append(_unclosed(text, start - 1))
    elif state == "block_comment":
        notes.append(_unclosed(text, start))
    return "".join(out), spans, notes


def mask_source(text: str) -> tuple[str, list[tuple[int, int]]]:
    """返回 (masked, spans)；spans 是每个字符串字面量**内部**的 (start, end) 原文区间。"""
    masked, spans, _notes = _scan(text)
    return masked, spans


def mask_source_notes(text: str) -> tuple[str, list[tuple[int, int]], list[str]]:
    """同 mask_source，另返回「未闭合」degraded 说明（R375：掩码不完整必须可见）。"""
    return _scan(text)


def string_at(text: str, spans: list[tuple[int, int]], quote_pos: int) -> str | None:
    """quote_pos 处引号紧跟的那个字符串的**原文**内容；不是字符串开头则 None。"""
    for begin, end in spans:
        if begin == quote_pos + 1:
            return text[begin:end]
    return None
