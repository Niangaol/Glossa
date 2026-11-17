"""A6：离线桩（fake_llm.py）——不联网的假模型，只为把整条流水线跑通。

设计 §12 的口径：桩只从提示词里**已经给出**的素材取材——分节只从 plan 提示的「可用事实」
清单里挑 id，正文只搬「数字齐全」的 facts[].text 原样进卡片，图的节点与边全部取自
facts[].edges。所以桩跑出来的页面天然 0 处未溯源：四道闸在桩上的通过不是「放宽」，而是
桩没有东西可编——它连「数字没记全的那条事实」都不肯搬（见 _safe）。

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


def _figure(facts: list) -> dict:
    """一张图：有事实边就画分层图（每条边都来自 facts[].edges），没边就画事实卡片。"""
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
        return {"pattern": "layered", "caption": "每条连线都来自事实台账",
                "nodes": [{"id": end, "label": end} for end in ends], "edges": edges}
    picked = [str(row.get("id")) for row in facts if row.get("id")][:MAX_EDGE]
    return {"pattern": "cards", "caption": "这一节用到的事实",
            "nodes": [{"id": fact_id, "label": fact_id} for fact_id in picked]}


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
            if self.bad_json and self.sections == 1:
                return '{"title": "坏掉的一节", "html": "<p class=\\"lead\\">这不是 JSON'
            pack = _load(text)
            figures = _figure(_safe(pack))
            return json.dumps({
                "title": str((pack.get("section") or {}).get("title") or ""),
                "html": _body(pack, self.sections, self.untraced),
                "figures": [figures] if figures.get("nodes") else [],
                "notes": [],
            }, ensure_ascii=False)
        raise BuildError("离线桩只认两种提示词（分节 / 写一节）；收到开头：%r" % text[:80])
