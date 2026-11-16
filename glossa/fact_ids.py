"""事实台账：14 种 fact id + numbers 归一（T6，设计 §13）。

FACT_KINDS 是 14 种 id 的**唯一清单**：schema 的 patternProperties 只放宽到 '^fact:'，
种类的契约钉在这里（一个不多一个不少）。
numbers 一律走 numbers_of：只收 int、排除 bool（True 是 int 的子类，不排除会把「一个真」
写成数字 1）、float 整数转 int、升序去重。
text 是一句人话且**不许空串**：讲解层引用了 id 却拿不到话说，就是空引用。
引用不存在的 id → require 抛 BuildError 并点名（GC33：不猜、不静默跳过）。
"""

from __future__ import annotations

import pathlib

from papertrace.exceptions import BuildError

FACT_KINDS: tuple[str, ...] = (
    "totals", "files", "file", "pkg", "project", "entry", "import", "symbol",
    "namespace", "graph", "excluded", "degraded", "source", "bonus")


def numbers_of(values) -> list[int]:
    """只收 int（排除 bool）、float 整数转 int、升序去重。"""
    out: set[int] = set()
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out.add(value)
        elif isinstance(value, float) and value.is_integer():
            out.add(int(value))
    return sorted(out)


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


def _put(facts: dict, fact_id: str, numbers, text: str) -> None:
    """登记一条事实；同 id 重复出现（如同名重载符号）时合并 numbers、保留首条 text。"""
    row = facts.get(fact_id)
    if row is None:
        facts[fact_id] = {"numbers": numbers_of(numbers), "text": text}
    else:
        row["numbers"] = numbers_of(list(row["numbers"]) + list(numbers))


def _totals_text(totals: dict) -> str:
    by_lang = "、".join(f"{name} {count}" for name, count in (totals.get("by_lang") or {}).items())
    return (f"全仓 {totals.get('files', 0)} 个文件（{by_lang or '无'}）、{totals.get('symbols', 0)} 个符号、"
            f"{totals.get('imports', 0)} 条 import（{totals.get('unresolved', 0)} 条 unresolved）、"
            f"{totals.get('packages', 0)} 个包、{totals.get('projects', 0)} 个项目、"
            f"{totals.get('entries', 0)} 个入口；排除 {totals.get('excluded_files', 0)} 个文件、"
            f"{totals.get('degraded', 0)} 条降级。")


def _file_facts(facts: dict, row: dict) -> None:
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
             f"{row['path']} 的 {sym.get('kind')} {sym.get('name')} 在{span}{note}。")
    for ns in row.get("namespaces") or []:
        _put(facts, "fact:namespace:" + ns["name"], [ns.get("line")],
             f"命名空间 {ns['name']} 由 {row['path']} 第 {ns.get('line')} 行声明（{ns.get('style')}）。")


def _source_facts(facts: dict, files: list[dict], repo_root) -> None:
    """R294：按每个符号的行区间摘原文；end_line 为 None 只摘声明行并注明。"""
    root, cache = pathlib.Path(repo_root), {}
    for row in files:
        if not row.get("symbols"):
            continue
        rel = row["path"]
        if rel not in cache:
            try:
                cache[rel] = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                cache[rel] = []
        lines = cache[rel]
        for sym in row["symbols"]:
            line, end = sym.get("line") or 1, sym.get("end_line")
            end = end if end is not None else line
            excerpt = " ".join(lines[line - 1:end]).strip() if 0 < line <= len(lines) else ""
            if excerpt:
                text = f"{rel} 第 {line}–{end} 行原文：{excerpt[:120]}"
            else:
                text = f"{rel} 第 {line}–{end} 行没有摘到原文（文件共 {len(lines)} 行）"
            if sym.get("end_line") is None:
                text += "（只摘录了声明行）"
            _put(facts, f"fact:source:{rel}:{line}-{end}", [line, end, len(lines)], text)


def build_facts(doc: dict, *, repo_root=None, bonus: dict | None = None) -> dict:
    """生成 14 种 fact id；顺序固定（字典插入序即输出序），可复现。"""
    facts: dict = {}
    totals = doc.get("totals") or {}
    _put(facts, "fact:totals", totals.values(), _totals_text(totals))
    files = doc.get("files") or []
    _put(facts, "fact:files",
         [len(files), sum(f.get("bytes") or 0 for f in files),
          sum(f.get("lines") or 0 for f in files),
          sum(len(f.get("symbols") or []) for f in files)],
         f"共保留 {len(files)} 个文件，合计 {sum(f.get('lines') or 0 for f in files)} 行、"
         f"{sum(f.get('bytes') or 0 for f in files)} 字节。")
    for row in files:
        _file_facts(facts, row)
    for pkg in doc.get("packages") or []:
        if not pkg.get("name"):
            continue
        _put(facts, "fact:pkg:" + pkg["name"],
             [len(pkg.get("deps") or {}), len(pkg.get("dev_deps") or {}), len(pkg.get("scripts") or {})],
             f"包 {pkg['name']}（manifest {pkg.get('manifest')}）：{len(pkg.get('deps') or {})} 个依赖、"
             f"{len(pkg.get('dev_deps') or {})} 个开发依赖、{len(pkg.get('scripts') or {})} 个脚本。")
    for proj in doc.get("projects") or []:
        _put(facts, "fact:project:" + str(proj.get("name")),
             [len(proj.get("package_refs") or []), len(proj.get("project_refs") or [])],
             f"项目 {proj.get('name')}（{proj.get('csproj')}，目标框架 {proj.get('target_framework')}，"
             f"输出类型 {proj.get('output_type')}）：{len(proj.get('package_refs') or [])} 个包引用、"
             f"{len(proj.get('project_refs') or [])} 个项目引用。")
    entries = doc.get("entries") or []
    for index, entry in enumerate(entries, 1):
        _put(facts, "fact:entry:" + str(entry.get("name")), [index, len(entries)],
             f"第 {index}/{len(entries)} 个入口：{entry.get('kind')} {entry.get('name')}，"
             f"命令 {entry.get('command')}，目标 {entry.get('target')}。")
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
         f"{len(graph.get('unreachable') or [])} 个不可达文件。")
    excluded = doc.get("excluded") or {}
    _put(facts, "fact:excluded",
         [excluded.get("files"), excluded.get("bytes"), len(excluded.get("rules") or []),
          len(excluded.get("oversize") or []), excluded.get("pruned_files")],
         f"排除 {excluded.get('files', 0)} 个文件 / {excluded.get('bytes', 0)} 字节，"
         f"命中 {len(excluded.get('rules') or [])} 条规则，{len(excluded.get('oversize') or [])} 个超限文件。")
    degraded = doc.get("degraded") or []
    _put(facts, "fact:degraded", [len(degraded)] + [d.get("count") for d in degraded],
         f"共 {len(degraded)} 条降级说明（没看清的地方都记在这里）。")
    if repo_root is not None:
        _source_facts(facts, files, repo_root)
    if bonus is not None:
        counts = [len(bonus.get(key) or []) for key in ("nodes", "edges", "anchors")]
        _put(facts, "fact:bonus", counts,
             f"旧 trace 对账：{counts[0]} 个模型算子节点、{counts[1]} 条边、{counts[2]} 个锚点。")
    return facts
