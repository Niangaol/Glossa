"""A6：AI 讲解编排（ai_pipeline.py）——两次调用、五道内容闸、一次组装。

顺序固定（派发书 §2）：pack_for_plan → build_plan_prompt → complete → parse_plan →
每节 build_pack → build_section_prompt → complete → parse_section → gate_html（strip_style=True，
R506）→ gate_numbers（这一节素材包里的 numbers，空集不放行，R507）→ gate_edges（这一节素材包
里的边）→ gate_labels（节点/柱状/卡片 label 必须查得到，R508/R515）→ gate_values（柱状值必须
核得上素材 numbers，R516）→ assemble.build_page（页头恒写未溯源/
失败计数，R509）。

两条不许商量的口径：
- 一节失败不整页崩：解析或校验抛 BuildError 的那一节渲染成「这一段生成失败：<原因>」，
  其余照常，失败原因同时进 notes——页面上不假装成功；
- 体积只有一个真源 gates.MAX_PAGE_BYTES：超限由 assemble.build_page 在写盘之前抛
  BuildError，这里绝不截断（R317/R499）。
untraced 数的是页面上的黄标个数（与 render.py 同口径），不是「页面上所有数字」。
"""

from __future__ import annotations

import html as _html
import pathlib

from glossa.explain import assemble, fake_llm, gates, pack as pack_mod, prompt
from glossa.explain.llm_bridge import (ChatAdapter, DEV_FAKE, STUB_MODE,   # R517：真后端适配层
                                      as_completer, backend, deviation,
                                      build_llm as _build_llm, mode_text)
from papertrace.exceptions import BuildError

MODE = "ai"
MAX_SECTIONS = 8
PAGE = "explain.html"
_MARK = '<mark class="untraced">'
_FAILED = '<p class="note">这一段生成失败：%s</p>'

def build_llm(kind="openai"):
    """编排侧入口：真后端工厂走本模块的 backend()，测试注入才不会打偏（R517）。"""
    return _build_llm(kind, backend)


def _plain_texts(data, item, figures, notes) -> list:
    """R518：图注、连线/卡片标签、标题、说明——这些位置由程序画，数字也必须能追溯。"""
    texts = [data.get("title") or item.get("title") or ""]
    for fig in figures:
        texts.append(fig.get("caption") or "")
        for edge in fig.get("edges") or ():
            texts.append(edge.get("label") or "")
        for row in list(fig.get("bars") or ()) + list(fig.get("cards") or ()):
            texts.append(row.get("label") or "")
            texts.append(row.get("text") or "")
    texts.extend(notes)
    return texts


def _numbers(pack: dict) -> set:
    """这一节允许出现的数字 = 它素材包里所有事实的 numbers 并集。"""
    out = set()
    for row in pack.get("facts") or ():
        out.update((row or {}).get("numbers") or ())
    return out


def _pairs(pack: dict) -> set:
    """这一节允许画的边 = 它素材包里 facts[].edges 的 (from, to) 对。"""
    out = set()
    for row in pack.get("facts") or ():
        for edge in (row or {}).get("edges") or ():
            if isinstance(edge, dict) and edge.get("from") and edge.get("to"):
                out.add((str(edge["from"]), str(edge["to"])))
    return out


def _section(doc, item, pos, llm, root):
    """写一节并过三道内容闸，返回 {title, html, figures, notes}。"""
    pack = pack_mod.build_pack(doc, dict(item, index=pos), root)
    system, user = prompt.build_section_prompt(pack)
    data = prompt.parse_section(llm.complete(user, system), pos)
    body, notes = gates.gate_html(data["html"], strip_style=True)   # R506：AI 版不留内联样式
    body, _marked = gates.gate_numbers(body, _numbers(pack), program=False)  # R507：空集不放行
    figures, allowed = [], _pairs(pack)
    for fig in data["figures"]:
        clean, dropped = gates.gate_edges(fig, allowed)
        clean, kept = gates.gate_labels(clean, pack)        # R508/R515：label 查不到就整张丢弃
        if clean is not None:                                # R516：编出来的条形值一条都不印
            clean, valued = gates.gate_values(clean, _numbers(pack))
            kept = kept + valued
        notes += dropped + kept
        if clean is not None:
            figures.append(clean)
    section_notes = list(pack.get("notes") or ()) + list(data.get("notes") or ()) + notes
    unmarked = gates.count_plain_numbers(                       # R518：程序画的地方也要查数字
        _plain_texts(data, item, figures, data.get("notes") or ()), _numbers(pack))   # 只查模型写的，程序自己的说明不算
    if unmarked:
        section_notes.append("图注/卡片/连线标签/标题/说明里另有 %d 处数字在本节素材里查不到出处"
                             "（这些位置由程序绘制，加不了黄标，已计入页头的未溯源总数）" % unmarked)
    return {"title": data.get("title") or item["title"], "html": body, "figures": figures,
            "notes": section_notes, "unmarked": unmarked}


def run_ai(doc: dict, llm, style: str, *, root=None, max_sections: int = MAX_SECTIONS) -> dict:
    """跑一整页：分节 → 逐节写 + 过闸 → 组装。返回 html/sections/untraced/notes/mode/deviation。"""
    if not isinstance(doc, dict):
        raise BuildError("run_ai 的 doc 必须是事实台账对象，收到 %r" % (type(doc).__name__,))
    base = pathlib.Path(root).resolve() if root else pathlib.Path.cwd()
    notes, sections, failed = [], [], 0
    system, user = prompt.build_plan_prompt(doc)
    plan = prompt.parse_plan(llm.complete(user, system), doc)
    if not plan:
        raise BuildError("模型一节都没分出来（parse_plan 之后是空的），没有可组装的页面")
    limit = int(max_sections)
    if len(plan) > limit:
        notes.append("模型分了 %d 节，本页只组装前 %d 节（max_sections）" % (len(plan), limit))
        plan = plan[:limit]
    for pos, item in enumerate(plan, 1):
        try:
            row = _section(doc, item, pos, llm, base)
        except BuildError as exc:               # 一节失败不整页崩，但绝不假装成功
            sections.append({"title": item["title"], "figures": [], "notes": [],
                             "html": _FAILED % _html.escape(str(exc))})
            notes.append("第 %d 节「%s」生成失败，已按原文披露：%s" % (pos, item["title"], exc))
            failed += 1
            continue
        sections.append(row)
        notes += row["notes"]
    marks = sum(str(row.get("html") or "").count(_MARK) for row in sections)
    unmarked = sum(int(row.get("unmarked") or 0) for row in sections)
    page = assemble.build_page(doc, sections, style, mode=MODE, note=deviation(llm),
                               untraced=marks + unmarked, failed=failed,   # R509/R518：两处都算
                               mode_text=mode_text(llm))
    return {"html": page, "sections": sections, "untraced": marks + unmarked, "unmarked": unmarked,
            "notes": notes, "mode": MODE, "deviation": deviation(llm), "failed": failed}


def write_page(html: str, out_dir) -> pathlib.Path:
    """写 <out_dir>/explain.html（每次覆盖，R74 同尺），返回落地路径。"""
    target = pathlib.Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / PAGE
    path.write_text(html, encoding="utf-8", newline="\n")
    return path