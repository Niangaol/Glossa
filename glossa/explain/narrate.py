"""程序版讲解（T10）：七块骨架，每个数字都有出处，没有 key 也能读懂。

R322：每块过注册表校验，cites 非空且全在 doc["facts"]，文字里每个数字都要落在 cites 的 numbers 并集内
（渲染后 untraced==0），取不到出处的句子整句不写。R324：build_prompt 是纯函数，七块 outline、真 fact id
与组件契约全从 outline / components 生成。R338：第⑤块逐个讲 keyfiles，两个数字不在 numbers 里就改成
无数字措辞并留 notes。R323 的三态在 cli 落地，这里只问一次后端并解析，失败抛 LLMUnavailable / BuildError。
"""
from __future__ import annotations

import json
import re

from glossa import fact_ids, keyfiles
from glossa.explain import components, outline
from papertrace.exceptions import BuildError
from papertrace.llm.client import get_llm

ENV_GLOSSA_BACKEND = "GLOSSA_LLM_BACKEND"
ENV_PAPER_BACKEND = "PAPERTRACE_LLM_BACKEND"
_FACT_LIMIT = 60
_FENCE = "```"


def _block(component, params, cites, section, notes=None):
    """一个组件块；section 决定标题取七块骨架的哪一条（R322 ④）。"""
    block = {"component": component, "params": params, "cites": list(cites), "section": section}
    if notes:
        block["notes"] = list(notes)
    return block


def _nums(doc, cites):
    """(真存在的 cites, 它们的 numbers 并集)：cites 永远不会编（R322 ②③）。"""
    facts = doc.get("facts") or {}
    real = [fact_id for fact_id in cites if fact_id in facts]
    return real, fact_ids.numbers_for(facts, real)


def _sentence(numbers, template, **values):
    """模板里的每个数字都得在这组 cites 的 numbers 里，否则整句不写（R322 ③）。"""
    if all(value in numbers and not isinstance(value, bool) for value in values.values()):
        return template.format(**values)
    return None


def _join(parts):
    return "\n\n".join(part for part in parts if part)


def program(doc):
    """确定性的七块讲解：每个数字都取自 doc["totals"] / facts（R322）。"""
    totals, facts = doc.get("totals") or {}, doc.get("facts") or {}
    blocks = []
    # ① 这项目是什么
    cites, numbers = _nums(doc, ["fact:totals", "fact:files"])
    text = _join([
        _sentence(numbers, "全仓 {files} 个文件、{symbols} 个符号、{imports} 条 import"
                  "（其中 {unresolved} 条 unresolved）、{packages} 个包、{entries} 个入口。",
                  files=totals.get("files", 0), symbols=totals.get("symbols", 0),
                  imports=totals.get("imports", 0), unresolved=totals.get("unresolved", 0),
                  packages=totals.get("packages", 0), entries=totals.get("entries", 0)),
        "下面的指标条与目录树都是从事实台账复算的，没有一句是猜的。"])
    blocks += [_block("overview", {}, cites, 1), _block("text", {"text": text}, cites, 1),
               _block("metrics", {"keys": ["files", "symbols", "imports", "packages", "entries"]},
                      cites, 1)]
    # ② 从哪进来
    entries = doc.get("entries") or []
    cites, numbers = _nums(doc, ["fact:totals"] + ["fact:entry:%s" % r.get("name") for r in entries])
    composite = sum(1 for row in entries if row.get("note") == "复合命令未指向单文件")   # R454：只认它
    other = sum(1 for row in entries if not row.get("target")) - composite
    text = _join([
        _sentence(numbers, "共 {entries} 个入口。", entries=len(entries)),
        _sentence(numbers, "其中 {composite} 个是复合命令，没指向单个文件，所以不作为可达性起点。",
                  composite=composite) if composite else None,
        _sentence(numbers, "其中 {other} 个没解析到单文件目标，原因见入口表。", other=other) if other else None,
        "入口的名字、目标与可复制的命令逐条列在下面。"])
    blocks += [_block("text", {"text": text}, cites, 2), _block("entry_list", {}, cites, 2)]
    # ③ 分几块
    packages, projects = doc.get("packages") or [], doc.get("projects") or []
    cites, numbers = _nums(doc, ["fact:totals"]
                           + ["fact:pkg:%s" % row.get("name") for row in packages]
                           + ["fact:project:%s" % row.get("name") for row in projects])
    text = _join([
        _sentence(numbers, "分 {packages} 个包、{projects} 个项目。",
                  packages=len(packages), projects=len(projects)),
        "包依赖图与项目引用图只画仓内互相引用的边；目录树按文件路径造出来，都折叠在下面。"])
    blocks.append(_block("text", {"text": text}, cites, 3))
    for kind, rows in (("package", packages), ("project", projects)):
        if rows:
            blocks.append(_block(kind + "_map", {}, _nums(doc, ["fact:totals"] + [
                "fact:%s:%s" % (kind, row.get("name")) for row in rows])[0], 3))
    blocks.append(_block("dir_tree", {"max_depth": 3}, _nums(doc, ["fact:files"])[0], 3))
    # ④ 谁依赖谁（R459：unreachable 为空不许写 0；R456：页面不列折叠清单，截断只给计数口径）
    graph = doc.get("graph") or {}
    cites, numbers = _nums(doc, ["fact:graph", "fact:totals"])
    unreachable, cut = len(graph.get("unreachable") or []), int(graph.get("truncated_nodes") or 0)
    text = _join([
        _sentence(numbers, "依赖图有 {nodes} 个节点、{edges} 条边、{cycles} 个环，分 {layers} 层。",
                  nodes=len(graph.get("nodes") or []), edges=len(graph.get("edges") or []),
                  cycles=len(graph.get("cycles") or []), layers=len(graph.get("layers") or [])),
        "没有找到可解析的入口，可达性未计算。" if not entries else
        _sentence(numbers, "从入口到不了 {unreachable} 个文件。", unreachable=unreachable)
        if unreachable else None,
        _sentence(numbers, "另有 {cut} 个节点没有画（截断是计数，本页不列这份清单）。", cut=cut)
        or "图装不下的节点没画进这张图（截断是计数，本页不列这份清单）。" if cut else None,
        "箭头的方向是「谁 import 谁」。"])
    blocks += [_block("text", {"text": text}, cites, 4),
               _block("import_graph", {}, _nums(doc, ["fact:graph"])[0], 4)]
    # ⑤ 关键文件逐个讲（R338）
    picked = keyfiles.key_files(doc, keyfiles.KEY_FILE_LIMIT)
    cites, numbers = _nums(doc, ["fact:files", "fact:totals"])
    candidates, notes = len(keyfiles.candidate_files(doc)), []
    head = _sentence(numbers, "共 {candidates} 个可讲解文件，本页逐个讲了 {shown} 个。",
                     candidates=candidates, shown=len(picked))
    if head is None:
        head = "本页只逐个讲事实台账挑得出的关键文件。"
        notes.append("可讲解文件数 %d / 本页讲了 %d 个都不在 fact:files 或 fact:totals 的 numbers 里，"
                     "这句话改成不含数字的措辞（R338）" % (candidates, len(picked)))
    blocks.append(_block("text", {"text": head + "\n\n挑选规则：入口目标优先 → 被依赖边数 → 符号数"
                                          " → path 升序；其余文件的清单在折叠表里。"}, cites, 5, notes=notes))
    for row in picked:
        path = row["path"]
        file_id = "fact:file:" + path
        symbol_ids = [fid for fid in sorted(facts) if fid.startswith("fact:symbol:" + path + "#")]
        blocks.append(_block("file_card", {"path": path}, _nums(doc, [file_id])[0], 5))
        blocks.append(_block("symbol_table", {"path": path}, _nums(doc, [file_id] + symbol_ids)[0], 5))
    # ⑥ 我没看清的地方
    excluded = doc.get("excluded") or {}
    cites, numbers = _nums(doc, ["fact:excluded", "fact:degraded", "fact:totals"])
    text = _join([
        _sentence(numbers, "排除 {files} 个文件 / {bytes} 字节，其中 {oversize} 个是超限文件。",
                  files=int(excluded.get("files") or 0), bytes=int(excluded.get("bytes") or 0),
                  oversize=len(excluded.get("oversize") or [])),
        _sentence(numbers, "被剪目录只按 listing 计数，另有 {pruned} 个文件没进 files 列表。",
                  pruned=int(excluded.get("pruned_files") or 0)),
        _sentence(numbers, "还有 {unresolved} 条 import 没解析出来，理由都在台账里。",
                  unresolved=int(totals.get("unresolved") or 0)),
        _sentence(numbers, "{degraded} 条降级说明逐条列在下面的表里——没看清的地方就这些，不粉饰。",
                  degraded=len(doc.get("degraded") or [])),
        "本页不执行被分析的代码，也不读任何密钥文件的内容。"])
    blocks += [_block("text", {"text": text}, cites, 6),
               _block("table", {"fact": "fact:degraded", "columns": ["scope", "reason", "count"]},
                      _nums(doc, ["fact:degraded"])[0], 6)]
    # ⑦ 甜头（可选）
    if "fact:bonus" in facts:
        blocks.append(_block("bonus", {}, ["fact:bonus"], 7))
    return blocks


def build_prompt(doc):
    """给模型的唯一约束（R324）：七块骨架 + 真 fact id + 组件契约 + 输出格式 + 三条禁令。"""
    lines = ["你在给一台机器扫出来的代码仓库写中文讲解。事实只有下面这份台账，台账里没有的，你不知道。", "", "## 七块骨架（顺序不许改）"]
    for row in outline.build_outline(doc):
        shown, rest = row["facts"], max(0, len(row["facts"]) - _FACT_LIMIT)
        lines.append("%d. %s · 可用组件：%s" % (row["index"], row["title"], "、".join(row["components"])))
        lines.append("   可用 fact id：%s%s" % (
            "、".join(shown[:_FACT_LIMIT]) if shown else "（这一块没有事实）",
            "（另有 %d 条同族事实未列出）" % rest if rest else ""))
    lines += ["", "## 组件参数契约（从注册表生成，别手抄）"]
    for name, spec in components.COMPONENTS.items():
        lines.append("- %s：必填 %s；选填 %s；可用事实 %s"
                     % (name, "、".join(spec["required"]) or "无", "、".join(spec["optional"]) or "无",
                        "、".join(spec["facts"])))
    lines += ["", "## 输出格式", "只输出一个 JSON 数组，不要代码围栏、不要解释。每项：",
              '{"component": 组件名, "params": {...}, "cites": ["真实 fact id"], "section": 1-7}',
              "", "## 三条禁令",
              "1. 不许编 fact id：cites 里每个 id 都必须逐字出现在上面的清单里。",
              "2. 不许写 <script>、<style>、外链或任何脚本；正文用 ## 标题、- 列表、**粗体**、`行内代码`。",
              "3. 数字必须有出处：正文里每个数字都要能在 cites 那些 fact 的 numbers 里找到，找不到就别写。"]
    return "\n".join(lines)


def _parse(text):
    """模型回什么就解析什么；不是非空 JSON 数组就抛 BuildError 并附原文前 200 字。"""
    raw = str(text or "").strip()
    if raw.startswith(_FENCE):
        raw = re.sub(r"```[a-zA-Z]*\s*", "", raw, count=1)
        raw = re.sub(r"\s*```$", "", raw, count=1)
    try:
        blocks = json.loads(raw)
    except ValueError as exc:
        raise BuildError("模型返回的不是合法 JSON（%s）；原文前 200 字：%s" % (exc, raw[:200])) from exc
    if not isinstance(blocks, list) or not blocks:
        raise BuildError("模型必须返回「非空的 JSON 数组」，收到 %r" % (blocks,))
    return blocks


def ask(doc, *, backend=None):
    """问一次模型，返回 (blocks, 模型名)；解析失败 BuildError，后端不可用 LLMUnavailable。"""
    llm = backend or get_llm()
    result = llm.chat(build_prompt(doc))
    blocks = _parse(result.text)
    components.validate_blocks(doc, blocks)
    return blocks, str(getattr(result, "model", "") or getattr(llm, "name", "") or "未指明")


def model(doc, *, backend=None):
    """Interfaces 里的形态：只要 blocks（模型名走 ask）。"""
    return ask(doc, backend=backend)[0]
