"""narrate 的三类句子构造（T10，R478 从 narrate.py 拆出——那边已顶到 200 行硬上限）。

搬的是「入口 / 关系图 / 排除」三类句子：它们只依赖 doc 与 cites 的 numbers 并集，不参与七块编排，
所以整体搬走不改变任何一句文字。sentence / join_text 也住在这里：R322 ③「数字必须有出处，
取不到就整句不写」这条规则只留一份定义，narrate.py 从这里 import。
"""
from __future__ import annotations


def sentence(numbers, template, **values):
    """模板里的每个数字都得在这组 cites 的 numbers 里，否则整句不写（R322 ③）。"""
    if all(value in numbers and not isinstance(value, bool) for value in values.values()):
        return template.format(**values)
    return None


def join_text(parts):
    """按空行拼句子；取不到出处而被丢掉的句子（None）自动略过。"""
    return "\n\n".join(part for part in parts if part)


def entry_text(doc, numbers):
    """② 从哪进来：入口总数、复合命令、没解析到单文件目标（为 0 的那句不写）。"""
    entries = doc.get("entries") or []
    composite = sum(1 for row in entries if row.get("note") == "复合命令未指向单文件")   # R454：只认它
    other = sum(1 for row in entries if not row.get("target")) - composite
    return join_text([
        sentence(numbers, "共 {entries} 个入口。", entries=len(entries)),
        sentence(numbers, "其中 {composite} 个是复合命令，没指向单个文件，所以不作为可达性起点。",
                 composite=composite) if composite else None,
        sentence(numbers, "其中 {other} 个没解析到单文件目标，原因见入口表。", other=other) if other else None,
        "入口的名字、目标与可复制的命令逐条列在下面。"])


def graph_text(doc, numbers):
    """④ 谁依赖谁：节点/边/环/层、不可达、截断（R459：0 不写；R456：截断只给计数口径）。"""
    graph, entries = doc.get("graph") or {}, doc.get("entries") or []
    unreachable = len(graph.get("unreachable") or [])
    cut = int(graph.get("truncated_nodes") or 0)
    return join_text([
        sentence(numbers, "依赖图有 {nodes} 个节点、{edges} 条边、{cycles} 个环，分 {layers} 层。",
                 nodes=len(graph.get("nodes") or []), edges=len(graph.get("edges") or []),
                 cycles=len(graph.get("cycles") or []), layers=len(graph.get("layers") or [])),
        "没有找到可解析的入口，可达性未计算。" if not entries else
        sentence(numbers, "从入口到不了 {unreachable} 个文件。", unreachable=unreachable)
        if unreachable else None,
        sentence(numbers, "另有 {cut} 个节点没有画（截断是计数，本页不列这份清单）。", cut=cut)
        if cut else None,                       # R477：只留带数字的一种形态（缺口已在 fact:graph 里）

        "箭头的方向是「谁 import 谁」。"])


def _pruned_sentence(excluded) -> str:
    """R494：剪枝 listing 自己都不完整时，只能说「至少 N 个」，不许把下界报成确数。"""
    if excluded.get("pruned_files_partial"):
        return "被剪目录的 listing 不完整，至少 {pruned} 个文件没进 files 列表（listing 本身不完整）。"
    return "被剪目录只按 listing 计数，另有 {pruned} 个文件没进 files 列表。"


def gaps_text(doc, numbers):
    """⑥ 我没看清的地方：排除数、被剪目录 listing、未解析 import、降级条数（取不到出处就不写）。"""
    totals, excluded = doc.get("totals") or {}, doc.get("excluded") or {}
    return join_text([
        sentence(numbers, "排除 {files} 个文件 / {bytes} 字节，其中 {oversize} 个是超限文件。",
                 files=int(excluded.get("files") or 0), bytes=int(excluded.get("bytes") or 0),
                 oversize=len(excluded.get("oversize") or [])),
        sentence(numbers, _pruned_sentence(excluded),
                 pruned=int(excluded.get("pruned_files") or 0)),
        sentence(numbers, "还有 {unresolved} 条 import 没解析出来，理由都在台账里。",
                 unresolved=int(totals.get("unresolved") or 0)),
        sentence(numbers, "{degraded} 条降级说明逐条列在下面的表里——没看清的地方就这些，不粉饰。",
                 degraded=len(doc.get("degraded") or [])),
        "本页不执行被分析的代码，也不读任何密钥文件的内容。"])
