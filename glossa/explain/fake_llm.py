"""A6：离线桩（fake_llm.py）——不联网的假模型，只为把整条流水线跑通。

设计 §12 的口径：桩只从提示词里**已经给出**的素材取材——分节只从 plan 提示的「可用事实」
清单里挑 id，正文只搬「数字齐全」的 facts[].text 原样进卡片，图的节点与边全部取自
facts[].edges。所以桩跑出来的页面天然 0 处未溯源：四道闸在桩上的通过不是「放宽」，而是
桩没有东西可编——它连「数字没记全的那条事实」都不肯搬（见 _safe）。

R508：图节点的 label 必须是读者看得懂的人话（成员名 / 文件名），且必须是这一节素材里
真能查到的原文子串——桩绝不把 fact:… 印到图上，A4 的标签闸会整张图丢弃。
R513：页面的第一张图（桩从第 1 节的图开始算）在那节素材凑够三组「人话标签 + 真数字」时
改画条形图：数字取自 facts[].numbers，标签是语言名/量词这类人话，一个 fact: 都不印；
凑不够三组就原样退回 layered / cards。

桩永不进生产默认路径：只有 --llm fake（或测试显式注入）才会用到，页头因此必须标注
「本页由离线桩生成，未调用真实模型」——那句 note 由 ai_pipeline.deviation 给出。
两种故意失败形态（供测试用）：FakeLLM(bad_json=True) 让第一次写节的回包是坏 JSON，证明
「单节失败不整页崩」；FakeLLM(untraced=True) 多写一个没出处的数字 8675309。
"""

from __future__ import annotations

import html as _html
import json
import re

from papertrace.exceptions import BuildError

NAME, BOGUS = "fake", 8675309   # BOGUS 是溯源闸探针：任何台账里都不会有这个数
MAX_CARD, MAX_EDGE = 3, 4       # 一节最多搬几条事实 / 一张图最多画几条边
MIN_SECTIONS, MAX_SECTIONS = 3, 5  # 分节计划只出 3–5 节
_GOAL = "只讲素材里查得到的事"      # 桩给每节的目标：不承诺素材之外的东西
_PLAN_TASK = "任务：把这次讲解分成"
_SECTION_TASK = "这一节的素材包"
_FACT_LINE = re.compile(r"^- (fact:[^\s：]+)：", re.M)
_DIGITS = re.compile(r"[0-9]+")
_GROUPS = (   # (id 匹配, 节标题)：同类归一节，绝不凭空造 id
    (("fact:totals", "fact:files"), "这项目是什么"),
    (("fact:graph",), "谁依赖谁"),
    (("fact:project:", "fact:pkg:"), "包与项目怎么分"),
    (("fact:entry:", "fact:import:", "fact:symbol:", "fact:namespace:"), "从哪儿读起"),
    (("fact:file:",), "关键文件"),
    (("fact:excluded", "fact:degraded", "fact:bonus"), "没看清的地方"),
)
_EXTRA = ("还有什么", "再补一点", "剩下的素材")
_BAR_MIN, MAX_BAR = 3, 6        # R513：凑够三组数字才画条形；一张图最多六条
_LANG = re.compile(r"个文件（([^）]*)）")          # totals 里的语言明细：json 3、typescript 9
_LANG_ROW = re.compile(r"([A-Za-z][\w+#.-]*)\s+([0-9]+)")
_UNIT = re.compile(r"([0-9]+)\s*(?:个|条|张|名)?\s*(开发依赖|不可达文件|超限文件|字节|文件|符号|"
                   r"依赖|脚本|项目|入口|节点|包|边|环|层|行|import)")


def _esc(text) -> str:
    return _html.escape(str(text), quote=True)


def _safe(pack: dict, cap: int = MAX_CARD) -> list:
    """只留「文字里每个数字都在台账 numbers 里」的事实：搬其余的就是替它编数字。"""
    rows = [row for row in (pack.get("facts") or ()) if isinstance(row, dict)]
    return [row for row in rows
            if all(tok in {str(num) for num in (row.get("numbers") or ())}
                   for tok in _DIGITS.findall(str(row.get("text") or "")))][:cap]


def _plan(prompt: str) -> list:
    """分节：只从提示里那份事实清单挑 id，同类归一节，凑不满三节就拿剩下的补。"""
    ids = _FACT_LINE.findall(str(prompt or ""))
    rows, used = [], set()
    for heads, title in _GROUPS:
        cited = [fid for fid in ids if fid not in used and any(
            fid == head or (head[-1:] == ":" and fid.startswith(head)) for head in heads)]
        if cited:
            used.update(cited[:MAX_CARD])
            rows.append({"title": title, "goal": _GOAL, "facts": cited[:MAX_CARD]})
    left = [fid for fid in ids if fid not in used]
    while len(rows) < MIN_SECTIONS:              # 素材不足也要有节可写，页面才能自解释
        rows.append({"title": _EXTRA[len(rows) % len(_EXTRA)], "goal": _GOAL,
                     "facts": left[:MAX_CARD]})
        left = left[MAX_CARD:]
    return rows[:MAX_SECTIONS]


def _load(prompt: str) -> dict:
    """从写节提示里取出素材包 JSON；取不出来是提示词不对，不是「模型胡说」。"""
    text = str(prompt or "")
    head = text.find(_SECTION_TASK)
    at = text.find("{", head + len(_SECTION_TASK)) if head >= 0 else -1
    if at < 0:
        raise BuildError("离线桩没在提示词里找到素材包 JSON")
    try:
        data, _end = json.JSONDecoder().raw_decode(text[at:])
    except ValueError as exc:
        raise BuildError("离线桩读不出素材包 JSON（%s）" % exc) from None
    return data if isinstance(data, dict) else {}


def _short(text, cap: int = 18) -> str:
    """人话标签：取原文第一段、截到 cap 字；必须是素材子串，否则 R508 的闸认不出来。"""
    body = re.split(r"[，。；：、,;]", str(text or ""), maxsplit=1)[0].strip()
    return body[:cap]


_RETRY = "上一轮的返回不是合法 JSON"   # ai_pipeline 重试时追加的那句（R522）


def _label(raw) -> str:
    """fact id / 路径 → 人话：成员名 > 文件名；桩图上绝不印 fact:（R508）。"""
    text = re.sub(r"^fact:[^:]*:", "", str(raw or "").strip())
    text = text.split("#", 1)[1] if "#" in text else text
    return text.rstrip("/").rsplit("/", 1)[-1] or str(raw or "").strip()


def _bar_rows(facts: list) -> list:
    """R513：语言文件数优先，其次通用计数；同一档凑够三组才作数，最多六条。"""
    tiers = [[], []]
    for row in facts:                     # 值只许是这条事实 numbers 里的数，台账没记的不画
        nums, text = row.get("numbers") or (), str(row.get("text") or "")
        detail = "".join(_LANG.findall(text))          # totals 里的「json 3、typescript 9」
        tiers[0] += [{"label": name + " 文件", "value": int(num)}
                     for name, num in _LANG_ROW.findall(detail) if int(num) in nums]
        tiers[1] += [{"label": unit, "value": int(num)}
                     for num, unit in _UNIT.findall(text) if int(num) in nums]
    for rows in tiers:                    # 先出现的档先试；标签去重、0 与负数不占一行
        kept = list({row["label"]: row for row in rows if row["value"] > 0}.values())
        kept.sort(key=lambda row: -row["value"])   # 大的在前：要砍也只砍最小的那几条
        if len(kept) >= _BAR_MIN:
            return kept[:MAX_BAR]
    return []


def _figure(facts: list, bars=None) -> dict:
    """一张图：给条形数据就画 bars（R513）；否则有事实边画分层图、没边画事实卡片。"""
    if bars:
        return {"pattern": "bars", "nodes": [], "bars": list(bars), "caption": "这一节的数字并排比大小"}
    found = [(str(e.get("from") or ""), str(e.get("to") or ""), row.get("id"))
             for row in facts for e in (row.get("edges") or ()) if isinstance(e, dict)]
    edges, seen = [], set()
    for src, dst, fact in found:
        if src and dst and (src, dst) not in seen:
            seen.add((src, dst))
            edges.append({"from": src, "to": dst, "fact": fact})
    edges = edges[:MAX_EDGE]
    if edges:
        ends = list(dict.fromkeys([e["from"] for e in edges] + [e["to"] for e in edges]))
        return {"pattern": "layered",
                "caption": "每条连线都来自事实台账（节点名取自素材原文）",
                "nodes": [{"id": end, "label": _label(end)} for end in ends], "edges": edges}
    picked = [row for row in facts if row.get("id")][:MAX_EDGE]
    return {"pattern": "cards", "caption": "这一节用到的事实（标签取自素材原文）",
            "nodes": [{"id": str(row.get("id")),
                       "label": _short(row.get("text")) or _label(row.get("id"))}
                      for row in picked]}


def _body(pack: dict, index: int, untraced: bool) -> str:
    """一节正文：六个词汇表 class；自己一句带数字的话都不写，数字全在事实原文里。"""
    section = pack.get("section") or {}
    cards = "".join('<div class="card"><p>%s</p></div>'
                    % _esc(str(row.get("text") or "").strip()) for row in _safe(pack))
    paths = "".join("<li><code>%s</code></li>" % _esc(str(row.get("path") or ""))
                    for row in (pack.get("sources") or ())
                    if isinstance(row, dict) and row.get("path"))
    parts = ['<p class="lead">这一节讲「%s」：%s</p>'
             % (_esc(section.get("title") or "这一节"), _esc(section.get("goal") or _GOAL)),
             '<p class="scope">素材包是这一节的全部依据，包外的内容一个都没写。</p>',
             '<div class="grid">%s</div>' % (cards or '<div class="card"><p>这一节的事实，台账'
             '里把数字记全的一条都没有，所以一条都没搬。</p></div>'),
             '<ol class="steps">%s</ol>' % (paths or "<li><code>（本节没有原文片段）</code></li>"),
             # D10：清单不全就必须说清楚只列了包里这几段，不许让人以为这就是全部
             '<p class="note">上面这段清单只列本节素材包里真有的原文片段，台账里其它文件没有搬进来。</p>',
             '<p class="kbd">离线桩只搬运素材，不加新说法。</p>']
    if untraced and index == 1:
        parts.append('<p class="kbd">溯源闸探针：%d 这个数字在素材里没有出处。</p>' % BOGUS)
    return "".join(parts)


class FakeLLM:
    """按真实协议形状说话的离线模型：两次调用的入参就是它的全部信息来源。"""

    name = NAME

    def __init__(self, *, bad_json: bool = False, untraced: bool = False) -> None:
        self.bad_json, self.untraced, self.plans, self.sections = bool(bad_json), bool(untraced), 0, 0

    def complete(self, prompt: str, system: str = "") -> str:
        """认出这两次调用：分节 → sections；写一节 → {title, html, figures, notes}。"""
        text = str(prompt or "")
        if _PLAN_TASK in text:
            self.plans += 1
            return json.dumps({"sections": _plan(text)}, ensure_ascii=False)
        if _SECTION_TASK in text:
            self.sections += 1
            if self.bad_json and (self.sections == 1 or _RETRY in text):   # R522：重试也坏
                return '{"title": "坏掉的一节", "html": "<p class=\\"lead\\">这不是 JSON'
            pack = _load(text)
            facts = _safe(pack)
            figures = _figure(facts, _bar_rows(facts) if self.sections == 1 else [])
            return json.dumps({
                "title": str((pack.get("section") or {}).get("title") or ""),
                "html": _body(pack, self.sections, self.untraced),
                "figures": [figures] if figures.get("nodes") or figures.get("bars") else [],
                "notes": [],
            }, ensure_ascii=False)
        raise BuildError("离线桩只认两种提示词（分节 / 写一节）；收到开头：%r" % text[:80])
