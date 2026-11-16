"""语言解析器注册表与分派（T3 建，T4 追加 tsjs/vue，T5 追加 csharp）。

R354：LANG_PARSERS 按语言注册；未注册语言返回与 parse_source 同形状的 dict
（symbols=[]、imports=[]、doc_first_line=None、main_guard=False、
parse='skipped'、degraded=['尚无 <lang> 解析器']），不抛。如实披露「这个语言还没
解析」比崩溃或假装解析过都好（GC32）。
禁止在顶层 import 尚不存在的解析器：提前 import 会让本包一引入就 ModuleNotFoundError。
T4 已追加 tsjs（typescript/javascript）与 vue；T5 追加 csharp。
"""

from __future__ import annotations

from collections.abc import Callable

from glossa.lang import csharp as _csharp
from glossa.lang import python as _python
from glossa.lang import tsjs as _tsjs
from glossa.lang import vue as _vue

LANG_PARSERS: dict[str, Callable[[str, str], dict]] = {
    "python": _python.parse_source,
    "typescript": _tsjs.parse_source,
    "javascript": _tsjs.parse_source,
    "vue": _vue.parse_source,
    "csharp": _csharp.parse_source,
}


def parse_file(lang: str, text: str, relpath: str) -> dict:
    """按 lang 分派到解析器；未注册语言如实 skipped + degraded，不抛（R354）。"""
    parser = LANG_PARSERS.get(lang)
    if parser is None:
        return {"symbols": [], "imports": [], "doc_first_line": None, "main_guard": False,
                "parse": "skipped", "degraded": [f"尚无 {lang} 解析器"]}
    return parser(text, relpath)
