"""A5：把分好节的 AI 结果组装成单文件离线页（外壳 + 目录 + 风格注入）。

分工：AI 只交 {title, html, figures, notes}，四道闸已经在 A4 洗过；这里只做「摆位置」——
<section id="s-N">、h2 的两位序号、目录锚点、图交给 draw.draw_figure、notes 归到本节。
换风格时 <main> 里的标记（section/id/序号/class）逐字节不变：风格只进 <style> 与图配色
（图的墨/纸/主色来自 CSS :root 令牌，draw.palette 读它），所以三套风格共用一份
class 词汇表（styles.CLASSES）才成立。逐字节对比的分母是「无图的节」，有图的节只换颜色。
体积只有一个真源：gates.MAX_PAGE_BYTES（R499 统一到 constants.HTML_MAX_BYTES）；运行时
读模块属性，调用方 monkeypatch 有效。超限在写盘之前抛 BuildError，绝不截断（R317）。
"""

from __future__ import annotations

import html as _html
import pathlib

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from glossa.explain import draw, gates, styles
from papertrace.exceptions import BuildError

_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates"
_TEMPLATE = "ai_page.html.j2"
_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)),
                   autoescape=select_autoescape(enabled_extensions=("html", "htm", "j2")),
                   undefined=StrictUndefined)

MODES: dict[str, str] = {"ai": "本页由模型分节撰写", "program": "本页由程序组装，未使用模型"}
BADGE_KEYS: tuple = (("files", "文件"), ("symbols", "符号"), ("packages", "包"), ("entries", "入口"))
DISCLOSURES: tuple[str, ...] = ("统计口径为 listing 计数，符号链接内容未计入。",
                                "目录被剪枝时，其中的文件只按 listing 计数，不会进入 files 列表。")
EMPTY_TEXT = "本次没有可讲的章节。"
STATS = "未溯源 %d 处 · 失败 %d 节"   # R509：页头恒写，0 也写
_MARK = '<mark class="untraced">'


def _esc(text) -> str:
    return _html.escape(str(text), quote=True)


def _listed(sections) -> list[dict]:
    """节必须是对象数组；形状不对就响亮报错，不把 None 塞进页面。"""
    rows = list(sections or ())
    for pos, section in enumerate(rows, 1):
        if not isinstance(section, dict):
            raise BuildError("第 %d 节不是对象，收到 %r" % (pos, type(section).__name__))
    return rows


def _title(section: dict, pos: int) -> str:
    """节标题；没给标题就用位置兜底，页面上不留空 h2。"""
    return str(section.get("title") or "").strip() or "第 %d 节" % pos


def build_toc(sections: list) -> str:
    """目录：一条 <li><a href="#s-N">，条数恒等于节数（锚点与 section id 同源）。"""
    rows = _listed(sections)
    if not rows:
        return ""
    return "<ol>%s</ol>" % "".join(
        '<li><a href="#s-%d">%s</a></li>' % (pos, _esc(_title(section, pos)))
        for pos, section in enumerate(rows, 1))


def _section(pos: int, section: dict, style: str) -> str:
    """一节：h2（序号归内容，不归 CSS）+ 正文 + 逐张图 + 本节 notes。"""
    parts = ['<section class="sec" id="s-%d">' % pos,
             '<h2><span class="no">%02d</span>%s</h2>' % (pos, _esc(_title(section, pos)))]
    body = str(section.get("html") or "").strip()
    if body:
        parts.append(body)
    for fig in section.get("figures") or ():
        parts.append(draw.draw_figure(fig, style))
    for note in section.get("notes") or ():
        text = str(note).strip()
        if text:
            parts.append('<p class="note">%s</p>' % _esc(text))
    return "".join(parts) + "</section>"


def build_main(sections: list, style: str) -> str:
    """只出 <main> 里的内容；没有节也要给读者一句话，而不是一张空白页。"""
    rows = _listed(sections)
    if not rows:
        return '<p class="lead">%s</p>' % EMPTY_TEXT
    return "\n".join(_section(pos, section, style) for pos, section in enumerate(rows, 1))


def badge_of(doc: dict) -> str:
    """页头徽章行：数字全部取自 doc["totals"]（同一份口径，不另算）。"""
    totals = (doc or {}).get("totals") or {}
    shown = ["{:,} {}".format(int(totals[key]), label) for key, label in BADGE_KEYS
             if isinstance(totals.get(key), int) and not isinstance(totals.get(key), bool)]
    return " · ".join(shown) or "统计未登记"


def build_page(doc: dict, sections: list, style: str, *, mode: str, note: str = "",
               untraced=None, failed: int = 0, mode_text=None) -> str:
    """整页：注入 CSS、生成目录、组装 <main>，超限抛 BuildError（写盘之前）。

    mode 决定页头标记（ai / program）；R509：页头恒写「未溯源 N 处 · 失败 M 节」，
    N 默认数 <main> 里的黄标（与 render.py 同口径），调用方也可传自己数好的值；
    note 追加在统计行后面（A6 标注离线桩）；mode_text 可替换页头徽章文字（R519：桩跑出来
    不能同时写「模型分节撰写」和「未调用真实模型」，两句话直接冲突）。
    """
    css = styles.load_css(style)                 # 未知风格先响亮报错（ValueError）
    if mode not in MODES:
        raise BuildError("mode 只能是 ai 或 program，收到 %r" % (mode,))
    rows = _listed(sections)
    body = build_main(rows, style)
    marks = body.count(_MARK) if untraced is None else int(untraced)
    header = STATS % (marks, max(0, int(failed))) + (" · " + str(note) if note else "")
    meta = (doc or {}).get("meta") or {}
    title = "笺疏 · %s" % ((meta.get("repo") or {}).get("root_name") or "未命名仓库")
    page = _ENV.get_template(_TEMPLATE).render(
        title=title, css=css, mode=mode,
        mode_text=MODES[mode] if mode_text is None else str(mode_text), badge=badge_of(doc),
        note=header, toc=build_toc(rows), body=body, disclosures=DISCLOSURES)
    size, limit = len(page.encode("utf-8")), gates.MAX_PAGE_BYTES
    if size > limit:
        raise BuildError("AI 讲解页 %d 字节，超过单页上限 %d 字节（不截断，也不删旧页）"
                         % (size, limit))
    return page
