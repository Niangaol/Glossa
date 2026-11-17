"""A6：AI 讲解编排（ai_pipeline.py）——两次调用、四道闸、一次组装。

顺序固定（派发书 §2）：pack_for_plan → build_plan_prompt → complete → parse_plan →
每节 build_pack → build_section_prompt → complete → parse_section → gate_html →
gate_numbers（这一节素材包里的 numbers）→ gate_edges（这一节素材包里的边）→
assemble.build_page。

两条不许商量的口径：
- 一节失败不整页崩：解析或校验抛 BuildError 的那一节渲染成「这一段生成失败：<原因>」，
  其余照常，失败原因同时进 notes——页面上不假装成功；
- 体积只有一个真源 gates.MAX_PAGE_BYTES：超限由 assemble.build_page 在写盘之前抛
  BuildError，这里绝不截断（R317/R499）。
untraced 数的是页面上的黄标个数（与 render.py 同口径），不是「页面上所有数字」。
"""

from __future__ import annotations

import html as _html
import os
import pathlib

from glossa.explain import (assemble, fake_llm, gates, llm_config, narrate, pack as pack_mod,
                            prompt)
from papertrace.exceptions import BuildError

MODE = "ai"
MAX_SECTIONS = 8
DEV_FAKE = "本页由离线桩生成，未调用真实模型"
PAGE = "explain.html"
_MARK = '<mark class="untraced">'
_FAILED = '<p class="note">这一段生成失败：%s</p>'


def backend():
    """把 GLOSSA_* 四项临时映射成 papertrace 认的变量，问完立刻恢复原样。

    「读哪一层、配齐了没有」由 llm_config 决定；这里只保证真后端读到同一份值，否则
    GLOSSA_OPENAI_API_KEY 配齐了、后端却回头去点名 PAPERTRACE_OPENAI_API_KEY。
    """
    saved = {}
    for glossa_name, paper_name in llm_config.ENV_PAIRS:
        value = (os.environ.get(glossa_name) or "").strip()
        if value:
            saved[paper_name] = os.environ.get(paper_name)
            os.environ[paper_name] = value
    try:
        return narrate.get_llm()
    finally:
        for name, previous in saved.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


def build_llm(kind="openai"):
    """fake 走离线桩，其它走真后端（配不齐是 BuildError，连不上是 LLMUnavailable）。"""
    if str(kind or "").strip().lower() == fake_llm.NAME:
        return fake_llm.FakeLLM()
    cfg = llm_config.resolve()
    if not llm_config.ready(cfg):
        raise BuildError("AI 讲解需要一个可用的模型后端：%s；没有 key 时先用离线桩"
                         "（--llm fake / llm=\"fake\"）跑通。" % llm_config.describe(cfg))
    return backend()


def deviation(llm) -> str:
    """「无 AI / 离线桩」的说明串：桩跑出来就必须在页头承认（设计 §12）。"""
    return DEV_FAKE if str(getattr(llm, "name", "") or "") == fake_llm.NAME else ""


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
    body, notes = gates.gate_html(data["html"])
    body, _marked = gates.gate_numbers(body, _numbers(pack))
    figures, allowed = [], _pairs(pack)
    for fig in data["figures"]:
        clean, dropped = gates.gate_edges(fig, allowed)
        figures.append(clean)
        notes += dropped
    return {"title": data.get("title") or item["title"], "html": body, "figures": figures,
            "notes": list(pack.get("notes") or ()) + list(data.get("notes") or ()) + notes}


def run_ai(doc: dict, llm, style: str, *, root=None, max_sections: int = MAX_SECTIONS) -> dict:
    """跑一整页：分节 → 逐节写 + 过闸 → 组装。返回 html/sections/untraced/notes/mode/deviation。"""
    if not isinstance(doc, dict):
        raise BuildError("run_ai 的 doc 必须是事实台账对象，收到 %r" % (type(doc).__name__,))
    base = pathlib.Path(root).resolve() if root else pathlib.Path.cwd()
    notes, sections = [], []
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
            continue
        sections.append(row)
        notes += row["notes"]
    page = assemble.build_page(doc, sections, style, mode=MODE, note=deviation(llm))
    return {"html": page, "sections": sections, "untraced": page.count(_MARK),
            "notes": notes, "mode": MODE, "deviation": deviation(llm)}


def write_page(html: str, out_dir) -> pathlib.Path:
    """写 <out_dir>/explain.html（每次覆盖，R74 同尺），返回落地路径。"""
    target = pathlib.Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / PAGE
    path.write_text(html, encoding="utf-8", newline="\n")
    return path
