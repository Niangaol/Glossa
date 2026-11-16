"""事实台账：14 种 fact id + numbers 归一（T6，设计 §13）。

FACT_KINDS 是 14 种 id 的**唯一清单**：schema 的 patternProperties 只放宽到 '^fact:'，
种类的契约钉在这里（一个不多一个不少）。
numbers 一律走 numbers_of（只在 facts_io 实现一次，这里原样再导出），且**每个数字都要在
text 里出现**（R398 M3：numbers 是正文引用值，不是死数据）。
text 是一句人话且**不许空串**：讲解层引用了 id 却拿不到话说，就是空引用。
同 id 多来源（namespace/entry/pkg/同名符号）时 text 要列出后续来源，最多 3 处，其余「等 N 处」（R398 M4）；
numbers 与 text 必须同步——只收 text 里真展示的来源行号，「等 N 处」的 N 不进 numbers（R426）。
摘录 120 字截断必须标「…（已截断，原文共 N 字符）」（M1）；行区间钳位与取不到原文的判断在
facts_io.source_span（M2）：取不到就**不产** fact:source，只记降级。
引用不存在的 id → require 抛 BuildError 并点名（GC33：不猜、不静默跳过）。
"""

from __future__ import annotations

from glossa import fact_text, facts_io
from glossa.facts_io import numbers_of
from papertrace.exceptions import BuildError

FACT_KINDS: tuple[str, ...] = (
    "totals", "files", "file", "pkg", "project", "entry", "import", "symbol",
    "namespace", "graph", "excluded", "degraded", "source", "bonus")


def numbers_for(facts: dict, cites: list[str]) -> set[int]:
    """把一组 fact id 的 numbers 并起来；缺 id 由 require 负责报。"""
    out: set[int] = set()
    for fact_id in cites:
        out.update((facts.get(fact_id) or {}).get("numbers") or [])
    return out


def require(facts: dict, cites: list[str]) -> None:
    """缺任何一个 id 就抛 BuildError，消息里点名全部缺失的 id。"""
    missing = [fact_id for fact_id in cites if fact_id not in facts]
    if missing:
        raise BuildError("事实台账里没有这些 fact id：" + "、".join(missing))


def _put(facts: dict, fact_id: str, numbers, text: str,
         srcs: dict | None = None, source: str | None = None) -> None:
    """登记一条事实；同 id 的后续来源由 fact_text.merge_into 同步 text 与 numbers（R426）。"""
    row = facts.get(fact_id)
    if row is None:
        facts[fact_id] = {"numbers": numbers_of(numbers), "text": text}
        if srcs is not None and source is not None:
            srcs[fact_id] = {"head": text, "head_numbers": numbers_of(numbers), "items": []}
        return
    if srcs is None or source is None:
        row["numbers"] = numbers_of(list(row["numbers"]) + list(numbers))
        return
    slot = srcs.setdefault(fact_id, {"head": row["text"], "head_numbers": list(row["numbers"]),
                                     "items": []})
    fact_text.merge_into(row, slot, numbers, source)


def _totals_text(totals: dict) -> str:
    """R398 M3：totals 的每个键都写进这一句（否则 numbers 里一半数字是死数据）。"""
    by_lang = "、".join(f"{name} {count}" for name, count in (totals.get("by_lang") or {}).items())
    return (f"全仓 {totals.get('files', 0)} 个文件（{by_lang or '无'}）、{totals.get('symbols', 0)} 个符号、"
            f"{totals.get('imports', 0)} 条 import（{totals.get('unresolved', 0)} 条 unresolved）、"
            f"{totals.get('packages', 0)} 个包、{totals.get('projects', 0)} 个项目、"
            f"{totals.get('entries', 0)} 个入口；依赖图 {totals.get('edges', 0)} 条边、"
            f"{totals.get('cycles', 0)} 个环、{totals.get('unreachable', 0)} 个不可达文件；"
            f"排除 {totals.get('excluded_files', 0)} 个文件 / {totals.get('excluded_bytes', 0)} 字节"
            f"（{totals.get('oversize', 0)} 个超限文件），{totals.get('degraded', 0)} 条降级。")


def totals_fact(totals: dict) -> dict:
    """fact:totals 与 totals 同源的唯一入口（build_repo_doc 追平 totals 时复用它）。"""
    return {"numbers": numbers_of(list(totals.values())), "text": _totals_text(totals)}


def _file_facts(facts: dict, srcs: dict, row: dict) -> None:
    symbols, imports = row.get("symbols") or [], row.get("imports") or []
    _put(facts, "fact:file:" + row["path"],
         [row.get("bytes"), row.get("lines"), len(symbols), len(imports)],
         f"{row['path']}（{row.get('lang')}）：{row.get('lines', 0)} 行 / {row.get('bytes', 0)} 字节，"
         f"{len(symbols)} 个符号、{len(imports)} 条 import，解析精度 {row.get('parse')}。")
    for sym in symbols:
        line, end = sym.get("line") or 1, sym.get("end_line")
        span = f"第 {line} 行" if end is None else f"第 {line}–{end} 行"
        note = "" if end is not None else "（只有声明行，end_line 未给出）"
        _put(facts, f"fact:symbol:{row['path']}#{sym.get('name')}", [line, end],
             f"{row['path']} 的 {sym.get('kind')} {sym.get('name')} 在{span}{note}。",
             srcs, f"{row['path']} 第 {line} 行")
    for ns in row.get("namespaces") or []:
        _put(facts, "fact:namespace:" + ns["name"], [ns.get("line")],
             f"命名空间 {ns['name']} 由 {row['path']} 第 {ns.get('line')} 行声明（{ns.get('style')}）。",
             srcs, f"{row['path']} 第 {ns.get('line')} 行（{ns.get('style')}）")


def build_facts(doc: dict, *, repo_root=None, bonus: dict | None = None) -> dict:
    """生成 14 种 fact id；顺序固定（字典插入序即输出序），可复现。"""
    facts, srcs = {}, {}
    facts["fact:totals"] = totals_fact(doc.get("totals") or {})
    files = doc.get("files") or []
    bytes_sum = sum(row.get("bytes") or 0 for row in files)
    lines_sum = sum(row.get("lines") or 0 for row in files)
    symbols_sum = sum(len(row.get("symbols") or []) for row in files)
    _put(facts, "fact:files", [len(files), bytes_sum, lines_sum, symbols_sum],
         f"共保留 {len(files)} 个文件，合计 {lines_sum} 行、{bytes_sum} 字节、{symbols_sum} 个符号。")
    for row in files:
        _file_facts(facts, srcs, row)
    for pkg in doc.get("packages") or []:
        if not pkg.get("name"):
            continue
        _put(facts, "fact:pkg:" + pkg["name"],
             [len(pkg.get("deps") or {}), len(pkg.get("dev_deps") or {}), len(pkg.get("scripts") or {})],
             f"包 {pkg['name']}（manifest {pkg.get('manifest')}）：{len(pkg.get('deps') or {})} 个依赖、"
             f"{len(pkg.get('dev_deps') or {})} 个开发依赖、{len(pkg.get('scripts') or {})} 个脚本。",
             srcs, f"manifest {pkg.get('manifest')}")
    for proj in doc.get("projects") or []:
        _put(facts, "fact:project:" + str(proj.get("name")),
             [len(proj.get("package_refs") or []), len(proj.get("project_refs") or [])],
             f"项目 {proj.get('name')}（{proj.get('csproj')}，目标框架 {proj.get('target_framework')}，"
             f"输出类型 {proj.get('output_type')}）：{len(proj.get('package_refs') or [])} 个包引用、"
             f"{len(proj.get('project_refs') or [])} 个项目引用。",
             srcs, str(proj.get("csproj")))
    entries = doc.get("entries") or []
    for index, entry in enumerate(entries, 1):
        _put(facts, "fact:entry:" + str(entry.get("name")), [index, len(entries)],
             f"第 {index}/{len(entries)} 个入口：{entry.get('kind')} {entry.get('name')}，"
             f"命令 {entry.get('command')}，目标 {entry.get('target')}。",
             srcs, f"{entry.get('kind')} {entry.get('name')}（第 {index}/{len(entries)} 个）")
    for index, imp in enumerate(doc.get("imports") or [], 1):
        line = imp.get("line")
        _put(facts, f"fact:import:{index}", [index, line],
             f"第 {index} 条 import：{imp.get('from')} 第 {line} 行 '{imp.get('specifier')}' → "
             f"{imp.get('kind')}，target={imp.get('target') or '无'}。")
    graph = doc.get("graph") or {}
    _put(facts, "fact:graph",
         [len(graph.get("nodes") or []), len(graph.get("edges") or []),
          len(graph.get("cycles") or []), len(graph.get("unreachable") or []),
          len(graph.get("layers") or [])],
         f"依赖图（{graph.get('level')} 级）：{len(graph.get('nodes') or [])} 个节点、"
         f"{len(graph.get('edges') or [])} 条边、{len(graph.get('cycles') or [])} 个环、"
         f"{len(graph.get('unreachable') or [])} 个不可达文件，分 {len(graph.get('layers') or [])} 层。")
    excluded = doc.get("excluded") or {}
    _put(facts, "fact:excluded",
         [excluded.get("files"), excluded.get("bytes"), len(excluded.get("rules") or []),
          len(excluded.get("oversize") or []), excluded.get("pruned_files")],
         f"排除 {excluded.get('files', 0)} 个文件 / {excluded.get('bytes', 0)} 字节，"
         f"命中 {len(excluded.get('rules') or [])} 条规则，{len(excluded.get('oversize') or [])} 个超限文件，"
         f"被剪目录 listing 计数 {excluded.get('pruned_files', 0)} 个文件。")
    degraded = doc.setdefault("degraded", [])
    counts = [int(row.get("count") or 1) for row in degraded]
    detail = f"（逐条计数 {'、'.join(str(c) for c in counts)}）" if counts else ""
    _put(facts, "fact:degraded", [len(degraded)] + counts,
         f"共 {len(degraded)} 条降级说明{detail}，没看清的地方都记在这里。")
    if repo_root is not None:
        for fact_id, numbers, text in fact_text.source_facts(files, repo_root, degraded):
            _put(facts, fact_id, numbers, text)
    if bonus is not None:
        counts = [len(bonus.get(key) or []) for key in ("nodes", "edges", "anchors")]
        _put(facts, "fact:bonus", counts,
             f"旧 trace 对账：{counts[0]} 个模型算子节点、{counts[1]} 条边、{counts[2]} 个锚点。")
    return facts
