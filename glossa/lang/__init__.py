"""语言解析器注册表与分派（T3：第一版只有 python）。

R354：LANG_PARSERS 第一版只注册 python；未注册语言返回与 parse_source 同形状的
dict（symbols=[]、imports=[]、doc_first_line=None、main_guard=False、
parse='skipped'、degraded=['尚无 <lang> 解析器']），不抛。如实披露「这个语言还没
解析」比崩溃或假装解析过都好（GC32）。
禁止在顶层 import 尚不存在的 tsjs / vue / csharp：T4/T5 才创建它们，提前 import
会让本包一引入就 ModuleNotFoundError。T4 追加 tsjs+vue，T5 追加 csharp。
"""

from __future__ import annotations

from collections.abc import Callable

from glossa.lang import python as _python

LANG_PARSERS: dict[str, Callable[[str, str], dict]] = {"python": _python.parse_source}


def parse_file(lang: str, text: str, relpath: str) -> dict:
    """按 lang 分派到解析器；未注册语言如实 skipped + degraded，不抛（R354）。"""
    parser = LANG_PARSERS.get(lang)
    if parser is None:
        return {"symbols": [], "imports": [], "doc_first_line": None, "main_guard": False,
                "parse": "skipped", "degraded": [f"尚无 {lang} 解析器"]}
    return parser(text, relpath)
