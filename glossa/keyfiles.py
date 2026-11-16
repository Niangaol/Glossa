"""关键文件挑选（keyfiles，T7b，R334/R335）：用户拍板「只讲关键文件」。

R334：逐个讲解最多 KEY_FILE_LIMIT=12 个文件，其余留在折叠清单里（页面必须写明讲了多少／共多少）。
R335：候选 = files 里 lang in SYMBOL_LANGS（**从 glossa.exclude 导入唯一真身，禁止另抄一份集合**，
否则会与 T1 的扫描口径漂移）；json/md 等 file_only 文件没有符号可讲，不进候选。
排序键 = (is_entry 降序, indegree 降序, symbols 降序, path 升序)：四个键全部能从 doc 复算，
同分靠 path 升序打破（R319 逐字节可复现）。indegree 是 graph.edges 里 to==path 的**边数**，
不是 edge['count'] 累加。reasons 只写非零项，顺序固定 入口 → 被依赖 → 符号数，措辞逐字固定。
"""

from __future__ import annotations

import collections

from glossa.exclude import SYMBOL_LANGS

KEY_FILE_LIMIT = 12


def candidate_files(doc: dict) -> list[dict]:
    """可讲解的文件（lang in SYMBOL_LANGS），返回 files 里的原始字典、按 path 升序。"""
    rows = [row for row in doc.get("files") or [] if row.get("lang") in SYMBOL_LANGS]
    return sorted(rows, key=lambda row: row["path"])


def _entry_names(doc: dict) -> dict[str, list[str]]:
    """path → 指向它的入口名（升序）；没有 target 的复合命令不指向任何文件。"""
    found: dict[str, list[str]] = collections.defaultdict(list)
    for entry in doc.get("entries") or []:
        target = entry.get("target")
        if target:
            found[target.split(":", 1)[1] if ":" in target else target].append(str(entry.get("name")))
    return {path: sorted(names) for path, names in found.items()}


def key_files(doc: dict, limit: int = KEY_FILE_LIMIT) -> list[dict]:
    """按 R335 的四个键挑前 limit 个可讲解文件，每项带可复算的 reasons。"""
    names = _entry_names(doc)
    indegree: collections.Counter = collections.Counter()
    for edge in (doc.get("graph") or {}).get("edges") or []:
        indegree[edge.get("to")] += 1                    # 边数，不是 count 累加
    rows: list[dict] = []
    for row in candidate_files(doc):
        path = row["path"]
        reasons = [f"入口 {name} 的目标文件" for name in names.get(path) or []]
        if indegree[path]:
            reasons.append(f"被 {indegree[path]} 个文件依赖")
        symbols = len(row.get("symbols") or [])
        if symbols:
            reasons.append(f"{symbols} 个符号")
        rows.append({"path": path, "lang": row.get("lang"), "is_entry": bool(names.get(path)),
                     "indegree": indegree[path], "symbols": symbols, "reasons": reasons})
    rows.sort(key=lambda item: (not item["is_entry"], -item["indegree"],
                                -item["symbols"], item["path"]))
    return rows[:limit]
