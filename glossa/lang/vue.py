"""Vue 单文件组件：只切第一个 <script> 块交给 tsjs（T4，parse='approx'）。

R282：只取**第一个** <script…> 块；出现第二个时 degraded 明说「只解析了第一个」。
template/style 一律不解析。行号偏移 = 开标签之前那一行：切出的内容从开标签行的
换行之后开始，所以内层第 N 行 = 绝对第 N + 开标签行 - 1（App.vue 开标签在第 4 行、
内层 import 在第 2 行 → 第 5 行）。
R298：Vue 与 TS 同口径，只抓带 export 的符号；<script setup> 的顶层绑定没有 export
关键字，所以不抓，并记 degraded 说清楚（只抓 import）——页面说某 Vue 文件有 N 个
符号时，用户必须能在源码里找到那 N 个 export。
已知局限：没有 <script> 块的文件记 parse='file_only'（只登记，不解析）；<script
src="…"> 不追外部文件；模板表达式与样式不解析。
"""

from __future__ import annotations

import re

from glossa.lang import tsjs

_OPEN = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
_CLOSE = re.compile(r"</script\s*>", re.IGNORECASE)


def parse_source(text: str, relpath: str) -> dict:
    """切第一个 <script> 块，交 tsjs 近似解析，再把行号偏移回绝对行。"""
    empty = {"symbols": [], "imports": [], "doc_first_line": None,
             "main_guard": False, "parse": "approx", "degraded": []}
    open_tag = _OPEN.search(text)
    if open_tag is None:
        return {**empty, "parse": "file_only",
                "degraded": ["没有 <script> 块：只登记文件，未解析符号与 import"]}
    close_tag = _CLOSE.search(text, open_tag.end())
    body = text[open_tag.end():close_tag.start() if close_tag else len(text)]
    offset = text.count("\n", 0, open_tag.start())     # 开标签之前有几行
    inner = tsjs.parse_source(body, relpath)
    degraded = list(inner["degraded"])
    if close_tag is None:
        degraded.append("<script> 开标签没有配对的 </script>：按到文末处理")
    elif _OPEN.search(text, close_tag.end()):
        degraded.append("多 script 块只解析了第一个")
    if re.search(r"\bsetup\b", open_tag.group(0)):
        degraded.append("script setup 顶层绑定未导出，符号未抓（只抓 import）")
    return {"symbols": [{**row, "line": row["line"] + offset} for row in inner["symbols"]],
            "imports": [{**row, "line": row["line"] + offset} for row in inner["imports"]],
            "doc_first_line": None, "main_guard": False, "parse": "approx",
            "degraded": degraded}
