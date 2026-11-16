r"""custom HTML 守卫（R307）与未溯源数字标记（R308）。

R307：用 html.parser 逐标签重建，禁用正则剥标签。FORBIDDEN_TAGS 整标签连内容丢弃；
丢一切 on* 事件属性；<a href> 命中 http/https///javascript:/data: 只去 href、保留标签与文字；
<img src=data:…> 丢整个 img；其它标签、内联 style、data-* 放行。
removed 计数：每个被丢标签算 1、每个被丢属性算 1；被丢标签内的文本不另计，配对结束标签不另计。

R407：禁标签是 void 元素（embed / param）时，丢弃时绝不进入抑制态——否则它后面整篇
HTML 会被静默吞掉（不抛不报）。R411：未闭合的禁标签 → 其后内容一并丢弃（fail-closed）。

R308：re.split(r'(<[^>]*>)') 切标签/文本，只处理文本段；<code> 深度 >0 整段跳过；
数字正则 r'\d[\d,]*(?:\.\d+)?%?'，比对前去掉逗号与百分号（29,856→29856、50%→50）；
命中 numbers 原样不动，未命中原样包 <mark class="untraced">（不改写、不四舍五入）。
日期 2026-11-16 会被拆成 2026、11、16 三个数——这是预期行为，不是缺陷。
幂等：自己产出的 <mark class="untraced"> 子树不再重复包裹；其它 <mark> 照常处理，
避免模型用普通 <mark> 把未溯源数字藏起来。
"""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser

FORBIDDEN_TAGS = frozenset({"script", "iframe", "object", "embed"})
_VOID = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})
_DANGEROUS = ("http://", "https://", "//", "javascript:", "data:")


def _dangerous(value: str | None, prefixes: tuple[str, ...] = _DANGEROUS) -> bool:
    return bool(value) and value.strip().lower().startswith(prefixes)


def _emit(tag: str, attrs) -> str:
    """按输入顺序重建标签；属性值重新转义，防止 &quot; 从值里逃逸成新属性。"""
    parts = ["<", tag]
    for name, value in attrs:
        parts.append(" %s" % name if value is None
                     else ' %s="%s"' % (name, _html.escape(value, quote=True)))
    parts.append(">")
    return "".join(parts)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.removed = 0
        self.notes: list[str] = []
        self._suppressed: list[str] = []

    def _note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def handle_starttag(self, tag, attrs) -> None:
        tag = tag.lower()
        if self._suppressed:
            if tag in FORBIDDEN_TAGS:
                self._suppressed.append(tag)     # 嵌套禁标签一起吞，不重复计数
            return
        if tag in FORBIDDEN_TAGS:
            self.removed += 1
            self._note("丢弃 <%s> 标签及其中内容" % tag)
            if tag not in _VOID:                 # R407：void 禁标签不进抑制态
                self._suppressed.append(tag)
            return
        if tag == "img" and any(low == "src" and _dangerous(value, ("data:",))
                                for low, value in ((n.lower(), v) for n, v in attrs)):
            self.removed += 1                    # 整个 img 算 1；属性不再另计
            self._note("丢弃 data: 内联图片")
            return
        kept = []
        for name, value in attrs:
            low = name.lower()
            if low.startswith("on"):
                self.removed += 1
                self._note("丢弃事件属性 %s" % low)
                continue
            if low == "href" and tag == "a" and _dangerous(value):
                self.removed += 1
                self._note("去掉外链 href，保留标签与文字")
                continue
            kept.append((name, value))
        self.out.append(_emit(tag, kept))

    def handle_startendtag(self, tag, attrs) -> None:
        before = len(self._suppressed)
        self.handle_starttag(tag, attrs)
        if len(self._suppressed) > before:
            self._suppressed.pop()

    def handle_endtag(self, tag) -> None:
        tag = tag.lower()
        if self._suppressed:
            if tag == self._suppressed[-1]:
                self._suppressed.pop()
            return
        if tag in _VOID:
            return
        if tag in FORBIDDEN_TAGS:
            self.removed += 1
            self._note("丢弃孤立的 </%s>" % tag)
            return
        self.out.append("</%s>" % tag)

    def handle_data(self, data) -> None:
        if self._suppressed:
            return
        self.out.append(_html.escape(data, quote=False))


def sanitize_html(text: str) -> tuple[str, int, list[str]]:
    """返回 (clean, removed, notes)；removed 口径见 R307。"""
    parser = _Sanitizer()
    parser.feed(text)
    parser.close()
    if parser._suppressed:                        # R411：fail-closed
        parser._note("未闭合的禁标签 <%s>：其后内容一并丢弃" % parser._suppressed[0])
    return "".join(parser.out), parser.removed, list(parser.notes)


_TAG = re.compile(r"(<[^>]*>)")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_MARK_OPEN = re.compile(r'^<mark\s+class="untraced"\s*>$', re.I)
_MARK_CLOSE = re.compile(r"^</mark\s*>$", re.I)


def _as_number(token: str):
    raw = token.replace(",", "").rstrip("%")
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return None


def mark_untraced(text: str, numbers: set) -> tuple[str, int]:
    """把未出现在 numbers 里的数字包 <mark class="untraced">，数字本身原样保留。"""
    out: list[str] = []
    count = 0
    code_depth = 0
    mark_depth = 0
    for piece in _TAG.split(text):
        if piece.startswith("<") and piece.endswith(">"):
            low = piece.lower()
            if low.startswith("<code"):
                code_depth += 1
            elif low.startswith("</code"):
                code_depth = max(0, code_depth - 1)
            elif _MARK_OPEN.match(piece):
                mark_depth += 1
            elif _MARK_CLOSE.match(piece) and mark_depth:
                mark_depth -= 1
            out.append(piece)
            continue
        if not piece or code_depth > 0 or mark_depth > 0:
            out.append(piece)
            continue
        buf = []
        last = 0
        for match in _NUM.finditer(piece):
            value = _as_number(match.group(0))
            if value is not None and value in numbers:
                continue
            buf.append(piece[last:match.start()])
            buf.append('<mark class="untraced">%s</mark>' % match.group(0))
            last = match.end()
            count += 1
        buf.append(piece[last:])
        out.append("".join(buf))
    return "".join(out), count
