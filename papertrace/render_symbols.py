"""C6 修复轮 R247：⑤ 符号表的说明句与取句函数（从 render_analysis.py 整体挪出）。

口径（要改先改这段 docstring，再改测试，GC19）：R225——meta.paper 缺失或
source == "none" → 一句含「没有论文」的说明，告诉读者这张表只有代码侧符号、
没有论文侧符号与映射可列；有论文 → ""（不刷废话）。

挪动的原因（R247）：symbols_note 只吃 doc 的 meta.paper，跟 ⑥ 代码体检的数字
行构造毫无关系；放在 render_analysis.py 里，连「只改符号表」的提交都被迫碰
渲染分析文件。挪出后 render_analysis.py 重新导出（# noqa: F401），render_html
与 tests/test_code_html.py 的 import 路径一个字不用改。

本文件零 torch 依赖：只读 trace 的 meta 字段。
"""

from __future__ import annotations

#: R225：无论文时 ⑤ 符号表里的说明句（代码侧符号可列，论文侧无可列）。
NO_PAPER_NOTE = (
    "本次 build 没有论文，所以这张表只有代码侧符号，没有论文侧符号与映射可列"
)


def symbols_note(doc: dict) -> str:
    """R225：meta.paper 缺失或 source == "none" → NO_PAPER_NOTE；有论文 → ""。"""
    paper = (doc.get("meta") or {}).get("paper") or {}
    if not paper or paper.get("source") == "none":
        return NO_PAPER_NOTE
    return ""
