"""A3：AI 协议（prompt.py）——两次调用各自的 system/user，以及严格回包的解析。

协议的口径是「模型只有两种输出，且都必须过闸」：
- 第一次只分节（title/goal/facts），第二次只写一节的 JSON（title/html/figures/notes）；
- SYSTEM 里的约束逐字可测：九个 class、六种范式、禁原生标签、数字只能来自 facts[].numbers、
  连线必须带 fact 且必须是 facts 里给出的边、输出严格 JSON；
- 回包不合规一律 BuildError，消息带原文前 200 字——让人能看见模型到底写了什么，
  而不是只看到「解析失败」四个字。
九个 class 与六种范式名都从 styles.CLASSES / patterns.PATTERNS 现取，绝不手抄：
抄一份，改一处，就变成两份真源。
"""

from __future__ import annotations

import json

from glossa.explain import pack as pack_mod
from glossa.explain import patterns, styles
from papertrace.exceptions import BuildError

MAX_FACT_CHARS = 120        # 每条事实在提示里只留这么长（全文在段包里）
PEEK = 200                  # 报错时附的原文长度

_RULES = (
    "1. 正文 HTML 只能用这九个 class：" + "、".join(styles.CLASSES) + "。",
    "2. 图只能用这六种范式：" + "、".join(patterns.PATTERNS) + "。",
    "3. 不要输出 <style>/<script>/<svg>/<figure>/<iframe>。",
    "4. 数字只能使用 facts[].numbers 里出现过的。",
    "5. 每条连线必须带 fact，且必须是 facts 里给出的边。",
    "6. 输出严格 JSON，不要 markdown 围栏外的解释。",
)
SYSTEM = "你是给代码仓库写讲解页的作者：只讲查得到的事，讲清楚。\n约束：\n" + "\n".join(_RULES)

_ALLOWED = ("title", "html", "figures", "notes")


def _strip(text: str) -> str:
    """剥 ```json 围栏（模型偶尔会加）；围栏外的文字不剥，交给 json.loads 判死。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        end = raw.rfind("```")
        if end >= 0:
            raw = raw[:end]
    return raw.strip()


def _peek(text: str) -> str:
    return (text or "").strip()[:PEEK]


def _loads(text: str, what: str):
    try:
        return json.loads(_strip(text))
    except ValueError as exc:
        raise BuildError("%s 不是合法 JSON（%s）：%s" % (what, exc, _peek(text))) from None


def _fact_line(row: dict) -> str:
    """一条事实行："- id：text"（桩按这个形状取 id）；带边的图事实把边一起写出来给模型看。"""
    text = str(row.get("text") or "")[:MAX_FACT_CHARS]
    edges = [edge for edge in row.get("edges") or () if isinstance(edge, dict)]
    if not edges:
        return "- %s：%s" % (row.get("id"), text)
    pairs = "、".join("%s→%s" % (edge.get("from"), edge.get("to")) for edge in edges)
    return "- %s：%s（可画图的边：%s）" % (row.get("id"), text, pairs)


def build_plan_prompt(doc: dict) -> tuple[str, str]:
    """分节那次：repo/totals/graph 摘要 + 按种类抽样的事实行（R501），分 3–6 节。"""
    plan = pack_mod.pack_for_plan(doc)
    facts, total = plan.get("facts") or [], len(doc.get("facts") or {})
    summary = {key: plan[key] for key in ("repo", "totals", "graph") if key in plan}
    if plan.get("has_edges"):
        summary["has_edges"] = True
    rows = [_fact_line(row) for row in facts]
    user = "\n".join([
        "仓库摘要（JSON）：",
        json.dumps(summary, ensure_ascii=False, indent=2),
        "",
        "可用事实 %d 条（台账共 %d 条，按种类抽样、每组至少 1 条）；facts 只能从这里选："
        % (len(facts), total),
        "\n".join(rows) or "（无）",
        "",
        "任务：把这次讲解分成 3–6 节，每节一句标题与一句目标，并点名这节要用的事实 id。",
        '只输出：{"sections":[{"title":"...","goal":"...","facts":["fact:..."]}]}',
    ])
    return SYSTEM, user


def build_section_prompt(pack: dict) -> tuple[str, str]:
    """写一节那次：整包素材 + 回包的四个键；包外的内容不许写。"""
    user = "\n".join([
        "这一节的素材包（JSON；包外的内容一律不许写）：",
        json.dumps(pack, ensure_ascii=False, indent=2),
        "",
        "任务：写这一节的 HTML 正文；需要图时从六种范式里选一种并填内容。",
        '只输出：{"title":"...","html":"...","figures":[...],"notes":[...]}',
    ])
    return SYSTEM, user


def parse_plan(text: str, doc: dict) -> list[dict]:
    """分节回包：只留 title 非空的行，facts 里台账没有的 id 静默丢弃（宁缺不编）。"""
    data = _loads(text, "分节结果")
    if isinstance(data, dict):
        data = data.get("sections") or data.get("plan") or []
    if not isinstance(data, list):
        raise BuildError("分节结果必须是数组或 {\"sections\": [...]}：%s" % _peek(text))
    known = doc.get("facts") or {}
    plan = []
    for row in data:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:                                   # 没标题的节没法放，也不算内容
            continue
        cites = row.get("facts") or []
        kept = [item for item in cites if isinstance(item, str) and item in known] \
            if isinstance(cites, list) else []
        plan.append({"title": title, "goal": str(row.get("goal") or "").strip(), "facts": kept})
    return plan


def parse_section(text: str, index: int) -> dict:
    """写节回包：顶层键只许四个、html 非空、figures 是数组，任一不合规就 BuildError。"""
    raw = _peek(text)
    data = _loads(text, "第 %d 节的返回" % index)
    if not isinstance(data, dict):
        raise BuildError("第 %d 节的返回必须是 JSON 对象：%s" % (index, raw))
    extra = [key for key in data if key not in _ALLOWED]
    if extra:
        raise BuildError("第 %d 节的返回多了顶层键 %s（只允许 %s）：%s"
                         % (index, "、".join(map(str, extra)), "、".join(_ALLOWED), raw))
    html = data.get("html")
    if not isinstance(html, str) or not html.strip():
        raise BuildError("第 %d 节的 html 必须是非空字符串：%s" % (index, raw))
    figures = data.get("figures", [])
    if not isinstance(figures, list):
        raise BuildError("第 %d 节的 figures 必须是数组，收到 %r：%s"
                         % (index, type(figures).__name__, raw))
    notes = data.get("notes") or []
    if not isinstance(notes, list):
        raise BuildError("第 %d 节的 notes 必须是数组：%s" % (index, raw))
    return {"title": str(data.get("title") or ""), "html": html,
            "figures": figures, "notes": [str(item) for item in notes]}
