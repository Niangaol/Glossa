"""三套风格预设的唯一真源（A2）：class 词汇表、CSS 文件、版式参数。

设计口径（docs/superpowers/specs/2026-11-17-glossa-styles.md §0）：三套风格共用同一套
内容区 class 词汇表，换风格只换 CSS 与版式参数，**内容 HTML 与图数据逐字不变**。
CSS 只由程序产出，永远不经模型之手，所以这里只认磁盘上的三份 .css。

normalize_classes 是「词汇表以外一律改名」的兑现处：AI 写了预设没定义的 class，
页面不能悄悄少一层样式，也不能假装它存在——统一改成 x- 前缀保留痕迹并记 note。
已经是 x- 前缀的 token 视为已改名（幂等），不再二次加前缀。
"""

from __future__ import annotations

import pathlib
import re

CLASSES: tuple[str, ...] = ("lead", "grid", "card", "steps", "note", "cols", "scope", "kbd", "toc")

_CSS_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates" / "styles"

STYLES: dict[str, dict] = {
    "magazine": {
        "title": "技术刊物",
        "summary": "纸色底、宋体标题、右侧旁注栏；章节以朱色序号起头，适合长文通读。",
        "css": "magazine.css",
        "layout": {"max_width": 680, "columns": 1, "note_side": True},
    },
    "report": {
        "title": "工程报告",
        "summary": "白底蓝规线、960px 栅格、左侧粘性目录；指标条与表格最清楚。",
        "css": "report.css",
        "layout": {"max_width": 960, "columns": 2, "note_side": False},
    },
    "cards": {
        "title": "文件图鉴",
        "summary": "暖白底、双列卡片、顶部色条；每个关键文件一张卡，扫读最快。",
        "css": "cards.css",
        "layout": {"max_width": 1000, "columns": 2, "note_side": False},
    },
}

_ORDER: tuple[str, ...] = ("magazine", "report", "cards")
_CLASS_ATTR = re.compile(r'class\s*=\s*(["\'])(.*?)\1', re.S)
_PREFIX = "x-"


def style_names() -> tuple[str, ...]:
    """三套风格的固定顺序（默认 magazine 排第一）。"""
    return _ORDER


def _spec(name: str) -> dict:
    try:
        return STYLES[name]
    except (KeyError, TypeError):
        raise ValueError("不认识的风格 %r；可用：%s" % (name, "、".join(_ORDER))) from None


def load_css(name: str) -> str:
    """读 <name>.css 全文；未知风格 ValueError 并列出三套名字。"""
    path = _CSS_DIR / _spec(name)["css"]
    return path.read_text(encoding="utf-8")


def layout(name: str) -> dict:
    """版式参数：正文列宽（px）、列数、旁注是否浮到侧栏。返回副本，改它不影响预设。"""
    return dict(_spec(name)["layout"])


def normalize_classes(html: str) -> tuple[str, int, list[str]]:
    """把 class 值里词汇表外的 token 改成 x- 前缀，返回 (新 html, 改名个数, notes)。

    改名个数按 token 计（同一个未知 class 出现三次就算三次）；notes 每个未知名字只记一条，
    因为读者要知道的是「模型编了哪几个 class」，重复次数没有信息量。
    """
    renamed = 0
    notes: list[str] = []
    seen: set[str] = set()

    def _fix(match: re.Match) -> str:
        nonlocal renamed
        quote, value = match.group(1), match.group(2)
        tokens = []
        for token in value.split():
            if token in CLASSES or token.startswith(_PREFIX):
                tokens.append(token)
                continue
            renamed += 1
            tokens.append(_PREFIX + token)
            if token not in seen:
                seen.add(token)
                notes.append("class %s 不在九个预设 class 里，已改名为 %s%s（%s）"
                             % (token, _PREFIX, token, "、".join(CLASSES)))
        return "class=%s%s%s" % (quote, " ".join(tokens), quote)

    return _CLASS_ATTR.sub(_fix, html), renamed, notes
