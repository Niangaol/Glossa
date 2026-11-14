"""LaTeX → sympy 的容错转换。失败必须保留 raw，不论解析成不成功。

不装也不调任何 LaTeX 前端（Constraint 13：antlr4 / lark 都没装、也不许装），只做
白名单宏翻译 + sympy.parsing.sympy_parser.parse_expr(local_dict=...)。不猜、不抛
（R16/R18）：白名单/文法之外一律 ok=False 并原样带回 raw。必须传 local_dict：
parse_expr('I*V') 不报错，但 I 会静默变成虚数单位、free_symbols 里直接消失（实测只剩
{V}）；函数名则故意不进 local_dict，让 parse_expr 自己建。
"""

from __future__ import annotations

import re
import string

import sympy
from sympy.parsing.sympy_parser import parse_expr

# 已知函数名 → kind；split_terms import 它当唯一事实源。\mathrm{Attention} 故意不在
# 里面（R16：它在等号左边，不是可解析表达式）。
KNOWN_FUNCTIONS = {"softmax": "norm", "log_softmax": "norm", "layernorm": "norm",
                   "relu": "act", "sigmoid": "act", "tanh": "act", "gelu": "act"}
_NAMED_MACROS = ("mathrm", "mathit", "operatorname")
_FUNC_NAMES = frozenset(KNOWN_FUNCTIONS) | {"sqrt"}
_ALLOWED = frozenset(string.ascii_letters + string.digits + "()[]{}+-*/_,")
_IDENT = re.compile(r"[A-Za-z_](?:[A-Za-z0-9]|_[A-Za-z0-9]+)*")
_SYM = re.compile(r"[A-Za-z_](?:_[A-Za-z0-9]+)?")
_NUM = re.compile(r"[0-9]+")
_CALL = re.compile(r"[A-Za-z_](?:[A-Za-z0-9]|_[A-Za-z0-9]+)*[ \t]*\(")
_PLAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TAIL = frozenset(")]" + string.ascii_letters + string.digits + "_")
_HEAD = frozenset("([" + string.ascii_letters + string.digits)


class _Reject(Exception):
    """输入超出白名单/文法：转成 ok=False，绝不上浮。"""


def latex_to_sympy_safe(latex: str) -> dict:
    """把一条 LaTeX **表达式** 翻成 sympy；失败返回 {ok: False, expr: None, raw}。

    是表达式不是方程（R16）：带 = 直接 ok=False——拆等号是 split_formula 的活。
    """
    raw, ok, expr = latex, False, None
    try:
        if "=" not in latex:
            pieces: list[tuple[bool, str]] = []
            _emit(latex, 0, len(latex), pieces)
            text = "".join(t for _, t in pieces)
            parsed = parse_expr(text, local_dict=_local_dict(text))
            ok = isinstance(parsed, sympy.Expr)  # () / (a,b) / [a+b] 返回 tuple/list
            expr = parsed if ok else None
    except Exception:  # R18：只捕 Exception，KeyboardInterrupt/SystemExit 照旧上浮
        pass
    return {"ok": ok, "expr": expr, "raw": raw}


def _emit(s: str, start: int, end: int, pieces: list[tuple[bool, str]]) -> None:
    """扫 s[start:end]；相邻的两个「值」之间补乘号（LaTeX 并列即相乘）。"""
    i = start
    while i < end:
        ch = s[i]
        if ch in " \t\r\n":
            i += 1
        elif ch == "\\":
            i = _macro(s, i, end, pieces)
        elif ch == "{":
            close = match_delim(s, i, end, "{", "}")
            _push(pieces, "(")
            _emit(s, i + 1, close, pieces)
            _push(pieces, ")")
            i = close + 1
        elif ch in "^_":
            i = _power(s, i, end, pieces, ch)
        elif ch in string.ascii_letters or ch == "_":
            m = _IDENT.match(s, i, end)
            run, j = m.group(0), m.end()
            if _CALL.match(s, i, end):
                if run not in _FUNC_NAMES:
                    raise _Reject(f"unknown function call: {run}")
                _push(pieces, run)
            else:
                for sym in _SYM.findall(run):  # 相邻字母即相乘：QK -> Q*K
                    _push(pieces, sym)
            i = j
        elif ch in string.digits:
            m = _NUM.match(s, i, end)
            _push(pieces, m.group(0))
            i = m.end()
        elif ch in _ALLOWED:
            _push(pieces, ch, value=ch not in "+-*/,")
            i += 1
        else:
            raise _Reject(f"character not in grammar: {ch!r}")


def _macro(s: str, i: int, end: int, pieces: list[tuple[bool, str]]) -> int:
    """处理 \宏；返回消耗到的位置。"""
    j = i + 1
    k = j
    while k < end and s[k] in string.ascii_letters:
        k += 1
    name, j = s[j:k] or (s[j:j + 1] if j < end else ""), max(k, j + 1)
    if name in _NAMED_MACROS:
        a, b = group_span(s, skip_ws(s, j, end), end)
        inner = s[a:b].strip()
        if inner not in KNOWN_FUNCTIONS:
            raise _Reject(f"\\{name}{{{inner}}} is not a whitelisted function")
        _push(pieces, inner)
        return b + 1
    if name == "frac":
        a0, a1 = group_span(s, skip_ws(s, j, end), end)
        b0, b1 = group_span(s, skip_ws(s, a1 + 1, end), end)
        _push(pieces, "(")
        _emit(s, a0, a1, pieces)
        _push(pieces, ")/(")
        _emit(s, b0, b1, pieces)
        _push(pieces, ")")
        return b1 + 1
    if name == "sqrt":
        a, b = group_span(s, skip_ws(s, j, end), end)
        _push(pieces, "sqrt(")
        _emit(s, a, b, pieces)
        _push(pieces, ")")
        return b + 1
    if name == "cdot":
        _push(pieces, "*", value=False)
        return j
    if name in ("left", "right"):
        k = skip_ws(s, j, end)
        if s[k:k + 1] not in ("(", ")", "[", "]"):
            raise _Reject(f"delimiter not in whitelist: {s[k:k + 1]!r}")
        _push(pieces, "(" if name == "left" else ")")
        return k + 1
    raise _Reject(f"macro not in whitelist: \\{name}")


def _power(s: str, i: int, end: int, pieces: list[tuple[bool, str]], ch: str) -> int:
    """^ / _ 的附着内容。复合下标（x_{i+1}）必须拒绝：翻出来会静默丢掉主符号。"""
    j = i + 1
    if j >= end:
        raise _Reject("dangling ^ or _")
    if s[j] == "{":
        close = match_delim(s, j, end, "{", "}")
        if close == j + 1:
            raise _Reject("empty subscript/superscript")
        a, b, after = j + 1, close, close + 1
    elif s[j] == "\\":
        raise _Reject("macro in subscript/superscript is not supported")
    else:
        a, b, after = j, j + 1, j + 1
    if ch == "^":
        _push(pieces, "**(", value=False)
        _emit(s, a, b, pieces)
        _push(pieces, ")")
    elif not _PLAIN.fullmatch(s[a:b]):
        raise _Reject(f"compound subscript: {s[i:b]!r}")
    else:
        _push(pieces, "_" + s[a:b])
    return after


def _push(pieces: list[tuple[bool, str]], text: str, value: bool = True) -> None:
    """追加片段；相邻的两个「值」补乘号，函数名后面的 ( 不补。"""
    if value and pieces:
        prev = pieces[-1][1]
        if prev[-1] in _TAIL and text[0] in _HEAD and not (text[0] == "(" and prev in _FUNC_NAMES):
            pieces.append((False, "*"))
    pieces.append((value, text))


def _local_dict(text: str) -> dict[str, sympy.Symbol]:
    """标识符 → Symbol；紧跟 ( 的（函数名）跳过，交给 parse_expr 自己建。"""
    calls = {m.group(0).split("(")[0].strip() for m in _CALL.finditer(text)}
    return {n: sympy.Symbol(n) for n in _IDENT.findall(text) if n not in calls}


def group_span(s: str, j: int, end: int) -> tuple[int, int]:
    """读 {...} 的内容区间；不接受裸参数（\\frac12 一律拒绝）。"""
    if j >= end or s[j] != "{":
        raise _Reject("expected { after macro")
    close = match_delim(s, j, end, "{", "}")
    return j + 1, close


def match_delim(s: str, i: int, end: int, open_ch: str, close_ch: str) -> int:
    """从 s[i]（必须是 open_ch）找到配对的 close_ch 下标。"""
    depth, p = 0, i
    while p < end:
        ch = s[p]
        p += 2 if ch == "\\" else 1
        depth += (ch == open_ch) - (ch == close_ch)
        if ch == close_ch and not depth:
            return p - 1
    raise _Reject(f"unbalanced {open_ch}{close_ch}")


def skip_ws(s: str, i: int, end: int) -> int:
    while i < end and s[i] in " \t\r\n":
        i += 1
    return i
