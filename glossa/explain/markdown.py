r"""受限 markdown（R306/R410/R421）：只支持 ##/### 标题、空行分段、- 与 1. 列表、
**粗体**、单反引号行内代码；块与块之间用 "\n" 连接。

链接、图片、裸 HTML、表格、脚注、引用、分隔线、单个 # 或四级以上标题一律不支持：
整段当纯文本（先 HTML 转义）保留，并**每种构造记一条 note**（按首次出现顺序）。
顺序铁律：先整体转义，再插标签——反了就会把用户写的 <b> 变成真标签。
R421：标题不再要求独占一块——块首行是标题就出 <h2>/<h3>，余下行照常按段落/列表渲染；
列表按连续前缀切成 <ul>/<ol>（列表后的剩余行同理进段落），不让字面 "-" 漏到页面上。
CRLF/裸 CR 先归一成 LF（M1：否则回车会被写进 <h2>/<li>）。
"""
from __future__ import annotations

import html
import re

_HEADING = re.compile(r"^(#{2,3})\s+(.*)$")
_UL = re.compile(r"^- (.*)$")
_OL = re.compile(r"^\d+\. (.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")

# 不支持的构造：(人话标签, 首次命中位置用正则)。notes 按首次出现位置排序（R410）。
_UNSUPPORTED = (
    ("链接 [文字](地址)", re.compile(r"(?<!!)\[[^\]]*\]\([^)]*\)")),
    ("图片 ![文字](地址)", re.compile(r"!\[[^\]]*\]\([^)]*\)")),
    ("脚注 [^n]", re.compile(r"\[\^[^\]]*\]")),
    ("表格 |", re.compile(r"^\s*\|", re.M)),
    ("引用 >", re.compile(r"^\s*>", re.M)),
    ("分隔线 ---", re.compile(r"^\s*---\s*$", re.M)),
    ("标题层级（只支持 ##/###）", re.compile(r"^(?:#|#{4,})\s+\S", re.M)),
    ("裸 HTML", re.compile(r"</?[a-zA-Z][^>]*>")),
)


def _inline(text: str) -> str:
    """先对整段文字做 HTML 转义，再在已转义的文本上插 <strong>/<code>。"""
    escaped = html.escape(text, quote=False)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    return _CODE.sub(r"<code>\1</code>", escaped)


def _notes(src: str) -> list[str]:
    hits = []
    for label, pattern in _UNSUPPORTED:
        match = pattern.search(src)
        if match:
            hits.append((match.start(), label))
    hits.sort(key=lambda item: item[0])
    return ["不支持的构造「%s」已按纯文本保留" % label for _, label in hits]


def _render_list(lines: list[str], pattern: re.Pattern, tag: str) -> str:
    items = "".join("<li>%s</li>" % _inline(m.group(1)) for m in (pattern.match(ln) for ln in lines))
    return "<%s>%s</%s>" % (tag, items, tag)


def _render_lines(lines: list[str]) -> list[str]:
    """R421：连续列表项成 <ul>/<ol>，其余连续行合成段落。"""
    out: list[str] = []
    start = 0
    while start < len(lines):
        if _UL.match(lines[start]):
            pattern, tag = _UL, "ul"
        elif _OL.match(lines[start]):
            pattern, tag = _OL, "ol"
        else:
            pattern, tag = None, ""
        end = start
        if pattern is not None:
            while end < len(lines) and pattern.match(lines[end]):
                end += 1
            out.append(_render_list(lines[start:end], pattern, tag))
        else:
            while end < len(lines) and not (_UL.match(lines[end]) or _OL.match(lines[end])):
                end += 1
            out.append("<p>%s</p>" % _inline(" ".join(ln.strip() for ln in lines[start:end])))
        start = end
    return out


def render_markdown(text: str) -> tuple[str, list[str]]:
    """把模型写的 markdown 子集渲染成 HTML；不支持的构造保留原文并进 notes。"""
    if not text or not text.strip():
        return "", []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    notes = _notes(text)
    rendered: list[str] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        head = _HEADING.match(lines[0])          # R421：标题与正文可同块
        if head:
            level = len(head.group(1))
            rendered.append("<h%d>%s</h%d>" % (level, _inline(head.group(2)), level))
            lines = lines[1:]
        rendered.extend(_render_lines(lines))
    return "\n".join(rendered), notes
