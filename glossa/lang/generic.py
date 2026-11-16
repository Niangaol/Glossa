"""非符号语言的 file_only 兜底（T6，设计 §9）。

json / yaml / md / sh / css / html / xaml / sln / csproj 这类「只统计」的语言没有解析器，
parse 记 'file_only'，符号与 import 一律为空。本模块**不读文件内容**：scan 已经把字节数
与行数记好了，再读一遍只是白花 IO（大仓库里是成倍的读取）。
也不记 degraded ——「这门语言第一版不解析」是设计口径，不是解析失败；GC32 的降级只用于
真的没看清的东西，滥用会让「我没看清的地方」变成噪音。
"""

from __future__ import annotations


def parse_source(text: str, relpath: str) -> dict:
    """与语言解析器同形状：空符号、空 import、parse='file_only'、零 degraded。"""
    return {"symbols": [], "imports": [], "doc_first_line": None, "main_guard": False,
            "parse": "file_only", "degraded": []}
