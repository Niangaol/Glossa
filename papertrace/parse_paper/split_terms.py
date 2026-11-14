r"""把一条论文公式按乘结构切成有序 Term。只认 fixture 级文法，不猜、不抛。

契约（派发裁决，唯一正确读法）：
- split_formula 先丢掉第一个顶层 `=` 及其左边的 LHS（R16），只拆等号右边；
- 每一项的 latex 是原公式串的**真子串**（R15）：本模块从不重写公式。「1/\sqrt{d_k}
  是缩放」这类语义由编排层（S9）写 reason 字符串，不许塞进 latex 字段——所以
  t1.latex 就是 \sqrt{d_k}，不是 1/\sqrt{d_k}；
- safe parse 先行：latex_to_sympy_safe 说 ok=False（白名单外的宏、串里带 `=`、
  文法外字符）就整条返回 []，由编排层整条进 unresolved，绝不猜项；
- Term 只有 index / latex / kind 三个字段（R17）：term_id 由编排层拼
  f"{unit_id}-t{term.index}"，本模块永远看不到 unit_id。

「项」指结构单元（乘因子、缩放、归一化、激活），不是代数加项：a + b 这种纯加减
没有已知结构，两个叶子符号都不硬凑成项，整条交给编排层。

R27（fix round 1）：不嵌套、不乱贴标签。自底向上——\frac 只在分子分母都没产出项时
才为自己产一项（\frac{a}{b} 是 1 个 scale 项），\sqrt 的 latex 永远盖住参数段；孤立
符号不是运算（y = a → []），和别的因子并列才是乘积（夹具的 V 跟在 \right) 后）。
"""

from __future__ import annotations

import string
from typing import NamedTuple

from papertrace.parse_paper.latex_safe import KNOWN_FUNCTIONS, group_span, latex_to_sympy_safe, match_delim, skip_ws

#: kind 的合法取值；term.kind 只从这里取（R17 的三个字段之一）。
KINDS = ("matmul", "scale", "norm", "act", "transpose", "concat")
_OPEN, _CLOSE = "{[(", "}])"
_PAIR = {"{": "}", "(": ")", "[": "]"}
_DELIMS = {"(": ")", "[": "]"}
_CALL_KINDS = {"sqrt": "scale", **KNOWN_FUNCTIONS}  # 裸调用 softmax(x)->norm，sqrt(x)->scale
_WORD = string.ascii_letters + string.digits + "_"


class Term(NamedTuple):
    """公式里的一个有序项。index 是 0 基序号；kind 取值见 KINDS。"""

    index: int
    latex: str
    kind: str


def split_formula(latex: str) -> list[Term]:
    """把公式等号右边按乘结构切成有序 Term；文法外 / 解析失败一律 []。"""
    out: list[Term] = []
    try:
        rhs = _right_hand_side(latex)
        if not rhs.strip() or not latex_to_sympy_safe(rhs)["ok"]:
            return []
        _scan(rhs, 0, len(rhs), True, out)
    except Exception:  # R18：只捕 Exception；扫描出 bug 也当作「不拆」，不吐裸 traceback
        return []
    return out


def _right_hand_side(latex: str) -> str:
    """R16：丢掉第一个顶层 `=` 及其左边整段；没有 `=` 就整条当右边。"""
    depth, i, n = 0, 0, len(latex)
    while i < n:
        ch = latex[i]
        if ch == "\\":
            i += 2
        elif ch in _OPEN or ch in _CLOSE:
            depth, i = depth + (1 if ch in _OPEN else -1), i + 1
        elif ch == "=" and not depth:
            return latex[i + 1:]
        else:
            i += 1
    return latex


def _scan(s: str, start: int, end: int, exposed: bool, out: list[Term]) -> None:
    """扫一段公式。exposed=False 表示这段被某个项的 latex 包住，不再产项。"""
    if exposed and _has_sum(s, start, end):
        return  # 顶层加减不是「项」：叶子符号不硬凑，整条交给编排层
    i = start
    while i < end:
        ch = s[i]
        if ch.isspace():
            i += 1
        elif ch in _PAIR:
            close = match_delim(s, i, end, ch, _PAIR[ch])
            _scan(s, i + 1, close, exposed, out)  # 括号组对拆项透明
            i = close + 1
        elif ch == "\\":
            i = _scan_macro(s, i, end, exposed, out)
        elif ch in _WORD:
            i = _scan_run(s, i, start, end, exposed, out)
        else:
            i += 1  # 运算符、逗号、孤立的 ^ _ 都不产项


def _scan_run(s: str, i: int, start: int, end: int, exposed: bool, out: list[Term]) -> int:
    """标识符串：裸调用吃掉参数，否则并列因子才产 matmul 项。"""
    j, names = _run(s, i, end)
    k = skip_ws(s, j, end)
    if k < end and s[k] == "(":  # 裸调用 softmax(x)：函数名自己是项，参数区并列
        close = match_delim(s, k, end, "(", ")")
        _scan(s, k + 1, close, exposed, out)
        if exposed:
            out.append(Term(len(out), s[i:j], _CALL_KINDS.get(s[i:j], "matmul")))
        return close + 1
    if exposed and (names > 1 or _is_factor(s, start, i, j, end)):
        out.append(Term(len(out), s[i:j], "matmul"))
    return j


def _run(s: str, i: int, end: int) -> tuple[int, int]:
    """标识符串的结尾下标与并列标识符个数：QK→2，d_k / K^{T}→1。"""
    j, names = i, 0
    while j < end:
        if s[j] in _WORD:
            if s[j].isalpha() and (j == i or s[j - 1] not in "_^{"):
                names += 1
            j += 1
        elif s[j] in "^_":  # ^{...} / _{...} / ^x / _x
            j += 1
            if j < end and s[j] == "{":
                j = match_delim(s, j, end, "{", "}") + 1
        else:
            break
    return j, names


def _scan_macro(s: str, i: int, end: int, exposed: bool, out: list[Term]) -> int:
    """处理 \宏；返回消耗到的位置。frac 自底向上，sqrt 产 scale 项。"""
    k = i + 1
    while k < end and s[k].isalpha():
        k += 1
    name, j = s[i + 1:k] or s[i + 1:i + 2], k if k > i + 1 else i + 2
    if name == "frac":
        a0, a1 = group_span(s, skip_ws(s, j, end), end)
        b0, b1 = group_span(s, skip_ws(s, a1 + 1, end), end)
        mark = len(out)
        _scan(s, a0, a1, exposed, out)  # 分子分母各自照常拆（自底向上：先子后父）
        _scan(s, b0, b1, exposed, out)
        if exposed and len(out) == mark:  # 后代没项 → 这个除法自己是唯一的一项
            out.append(Term(len(out), s[i:b1 + 1], "scale"))
        return b1 + 1
    if name == "sqrt":
        a, b = group_span(s, skip_ws(s, j, end), end)
        _scan(s, a, b, False, out)  # 根号里的内容被这一项的 latex 包住
        if exposed:
            out.append(Term(len(out), s[i:b + 1], "scale"))
        return b + 1
    if name == "cdot":
        return j
    if name in ("left", "right"):
        k = skip_ws(s, j, end)
        return k + 1 if k < end and s[k] in _DELIMS else j
    a, b = group_span(s, skip_ws(s, j, end), end)  # \mathrm{softmax} 等函数宏
    inner = s[a:b].strip()
    if inner not in KNOWN_FUNCTIONS:
        _scan(s, a, b, exposed, out)  # 未知宏的组照扫：门一撤就会产出项（变异探针靠这个）
        return b + 1
    k = _scan_args(s, b + 1, end, exposed, out)
    if exposed:
        out.append(Term(len(out), s[i:b + 1], KNOWN_FUNCTIONS[inner]))
    return k


def _scan_args(s: str, i: int, end: int, exposed: bool, out: list[Term]) -> int:
    """吃掉函数调用的参数（(...) 或带定界符的版本），参数内部照常拆项。"""
    k = skip_ws(s, i, end)
    if k < end and s[k] == "(":
        close = match_delim(s, k, end, "(", ")")
    elif s.startswith("\\left", k):
        k = skip_ws(s, k + 5, end)
        if k >= end or s[k] not in _DELIMS:
            return i
        close = match_delim(s, k, end, s[k], _DELIMS[s[k]])
    else:
        return i
    _scan(s, k + 1, close, exposed, out)
    return close + 1


def _is_factor(s: str, start: int, i: int, j: int, end: int) -> bool:
    """孤立单符号不是运算：同一个逗号分段里还有别的因子时，才是乘积。"""
    lo = max((p + 1 for p in range(start, i) if s[p] in ",;"), default=start)
    hi = min((p for p in range(j, end) if s[p] in ",;"), default=end)
    return bool(s[lo:i].strip()) or bool(s[j:hi].strip())


def _has_sum(s: str, start: int, end: int) -> bool:
    """这段里有没有顶层 + / -（括号花括号里的不算，宏名整体跳过）。"""
    depth, i = 0, start
    while i < end:
        ch = s[i]
        if ch == "\\":
            i += 2
        elif ch in "+-" and not depth:
            return True
        else:
            depth += (ch in _OPEN) - (ch in _CLOSE)
            i += 1
    return False
