"""七块骨架（R310/R336/R408）：标题逐字取自设计 §14，facts 只许是真 id。

R310：build_outline 每块的 facts 必须从 doc['facts'] 里筛真实存在的 id，绝不编造；
筛出空列表的块 required=False（渲染时整层不出现）。⑦ 的 required 由 fact:bonus 决定。
R336：第⑤块只讲关键文件——fact:file:* 取 glossa.keyfiles.key_files(doc)（≤12，按 R335 顺序），
并且必须带 fact:files（供折叠的全量清单），否则「其余文件去哪了」会被静默省略。
R408：除第⑤块外 available_facts 按 id 升序；第⑤块按 keyfiles 顺序、fact:files 放末尾
（字典序会把 App.vue 排最前、把入口文件埋中间）。
"""
from __future__ import annotations

from glossa import keyfiles

BLOCK_TITLES: tuple[str, ...] = (
    "这项目是什么",
    "从哪进来",
    "分几块",
    "谁依赖谁",
    "关键文件逐个讲",
    "我没看清的地方",
    "甜头（可选）",
)

_COMPONENTS: tuple[tuple[str, ...], ...] = (
    ("overview", "metrics", "text"),
    ("entry_list", "text"),
    ("package_map", "project_map", "dir_tree"),
    ("import_graph", "text"),
    ("file_card", "symbol_table", "code", "text"),
    ("table", "text"),
    ("bonus",),
)

# 每块可用事实的前缀；以 ":" 结尾的按前缀匹配，否则按整 id 匹配。
_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("fact:totals", "fact:files", "fact:pkg:", "fact:project:"),
    ("fact:entry:",),
    ("fact:pkg:", "fact:project:", "fact:files"),
    ("fact:graph", "fact:import:"),
    (),
    ("fact:excluded", "fact:degraded", "fact:import:"),
    ("fact:bonus",),
)


def _matches(fact_id: str, prefixes: tuple[str, ...]) -> bool:
    for prefix in prefixes:
        if fact_id.startswith(prefix) if prefix.endswith(":") else fact_id == prefix:
            return True
    return False


def available_facts(doc: dict, index: int) -> list[str]:
    """第 index 块可用的真实 fact id（第⑤块按 keyfiles 顺序，其余升序）。"""
    ids = doc.get("facts") or {}
    if index == 5:
        picked = ["fact:file:" + row["path"] for row in keyfiles.key_files(doc)]
        available = [fact_id for fact_id in picked if fact_id in ids]
        if "fact:files" in ids:
            available.append("fact:files")
        return available
    return sorted(fact_id for fact_id in ids if _matches(fact_id, _PREFIXES[index - 1]))


def build_outline(doc: dict) -> list[dict]:
    """七块骨架：[{'index', 'title', 'components', 'facts', 'required'}]。"""
    ids = doc.get("facts") or {}
    blocks: list[dict] = []
    for index in range(1, 8):
        facts = available_facts(doc, index)
        blocks.append({
            "index": index,
            "title": BLOCK_TITLES[index - 1],
            "components": list(_COMPONENTS[index - 1]),
            "facts": facts,
            "required": ("fact:bonus" in ids) if index == 7 else bool(facts),
        })
    return blocks
