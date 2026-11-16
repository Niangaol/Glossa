"""图与入口类组件（4 个）：package_map / project_map / entry_list / import_graph。

R450：comp_repo.py 已顶到 200 行硬上限，四个图/入口组件连同 _svg / _panel 搬到这里；通用格式化
（fmt / _table）仍在 comp_repo 头部，两个模块共用同一口径（comp_graph → comp_repo 单向依赖）。
R437：孤立数与截断数分两句写；「其中 M 个是清单、文档等不产生 import 的文件」的 M 与 degraded 句
共用同一个数，截断数直接读 doc["graph"]["truncated_nodes"]，两句互不相加、也不互相掩盖。
R485：M 只读 doc["graph"]["omitted_manifests"]（facts 层在截断前算一次），本页不再按截断后的节点集现算
——那样截断恰好吃掉几个清单文件时，页面与 degraded 会给出两个不同的数。
R439：target 为 None 时按 entry["note"] 分派文案，note 单独成列可见，不写死「复合命令」。
R440：doc["entries"] 为空时只写「没有找到可解析的入口，可达性未计算」，绝不引用 unreachable。
R447：hint 按 doc.graph.level 分派：project 级的边是 ProjectReference，不是 import。
D11：cycles 只列前 3 个时补「等 N 个」。D13：SVG 节点优先 label，id 放 <title>。
D14：layers 漏掉节点时补网格位置（与「无 layers」同一条回退），不许 KeyError。
R479：混合仓的 level 仍是 file，但 graph.project_edges 非空时要补一句「另有 N 条项目引用…」；
N 与项目名都从 doc 读（project_edges + projects 的 csproj→name），最多列 5 条，project 级整句不写。
"""
from __future__ import annotations

import math

from glossa.explain.comp_repo import _table, fmt, package_finder
from glossa.graph import MAX_GRAPH_NODES

def _rows(names, layers):
    """层 → 行；层漏掉的节点补进网格行（D14），保证每个节点都有坐标。"""
    known, rows, seen = set(names), [], set()
    for layer in layers or []:
        row = [name for name in (str(item) for item in layer) if name in known and name not in seen]
        seen.update(row)
        if row:
            rows.append(row)
    missing = [name for name in names if name not in seen]
    if missing:
        cols = max(1, math.ceil(math.sqrt(len(missing))))
        rows += [missing[index:index + cols] for index in range(0, len(missing), cols)]
    if not rows:
        cols = max(1, math.ceil(math.sqrt(len(names)))) if names else 1
        rows = [names[index:index + cols] for index in range(0, len(names), cols)] or [[]]
    return rows

def _svg(nodes, edges, *, key, title, layers=None, labels=None):
    """节点=名单，边=(from,to)；label 优先显示、id 放 <title>（D13）；0 节点也出合法 SVG。"""
    names = [str(node) for node in nodes]
    labels = labels or {}
    rows = _rows(names, layers)
    width = max(320, max(len(row) for row in rows) * 200 + 40)
    height = max(120, len(rows) * 90 + 40)
    pos = {name: (30 + col * 200, 40 + row * 90)
           for row, line in enumerate(rows) for col, name in enumerate(line)}
    out = ['<svg class="graph" xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
           'role="img"><title>%s</title>' % (width, height, width, height, fmt(title)),
           '<defs><marker id="%s-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
           'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#8b93a1"/></marker></defs>' % key]
    for src, dst in edges:
        if src in pos and dst in pos and src != dst:
            (x1, y1), (x2, y2) = pos[src], pos[dst]
            out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#8b93a1" stroke-width="1.2" '
                       'marker-end="url(#%s-a)"/>' % (x1 + 80, y1 + 34, x2 + 80, y2, key))
    for name in names:
        x, y = pos[name]
        label = str(labels.get(name) or name)
        shown = fmt(label if len(label) <= 24 else label[:23] + "…")
        ident = "<title>%s</title>" % fmt(name) if label != name else ""
        out.append('<g>%s<rect x="%d" y="%d" width="160" height="34" rx="6" fill="#eef2f7" stroke="#c6cedb"/>'
                   '<text x="%d" y="%d" font-size="11">%s</text></g>'
                   % (ident, x, y, x + 8, y + 21, shown))
    return "".join(out) + "</svg>"

def _panel(nodes, edges, *, key, hint, title, summary, headers, rows, layers=None, labels=None):
    """图 + 提示 + 折叠清单，四个图组件共用。"""
    return ('<p class="hint">%s</p>' % hint + _svg(nodes, edges, key=key, title=title,
                                                   layers=layers, labels=labels)
            + _table(summary, headers, rows))

def package_map(doc, params):
    """节点=npm 包，边=workspace 依赖（C# 仓库无 packages → 空串，R315）。"""
    packages = [row for row in doc.get("packages") or [] if row.get("name")]
    if not packages:
        return ""
    names, find = {row["name"] for row in packages}, package_finder(doc)
    pairs = {(find(str(imp.get("from") or "")), str(imp.get("package")))
             for imp in doc.get("imports") or [] if imp.get("kind") == "workspace"}
    pairs |= {(row["name"], str(dep)) for row in packages for dep in row.get("deps") or {}}
    edges = sorted(pair for pair in pairs if pair[0] in names and pair[1] in names and pair[0] != pair[1])
    rows = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % fmt(row.get(key)) for key in ("name", "path", "manifest"))
                   for row in sorted(packages, key=lambda item: item["name"]))
    return _panel([row["name"] for row in packages], edges, key="pkg", title="包依赖图",
                  hint="节点是 npm 包，箭头从「文件所属的包」指向它 import 的 workspace 包。",
                  summary="包清单（%d 个）" % len(packages), headers=("包", "目录", "manifest"), rows=rows)

def project_map(doc, params):
    """节点=.NET 项目（SVG 显示项目名 label，id 放 title），边=ProjectReference（无则空串）。"""
    projects = [row for row in doc.get("projects") or [] if row.get("csproj")]
    if not projects:
        return ""
    by_name = {str(row.get("name")): str(row["csproj"]) for row in projects}
    edges = sorted({(str(row["csproj"]), by_name[str(ref)]) for row in projects
                    for ref in row.get("project_refs") or [] if str(ref) in by_name})
    labels = {str(row["csproj"]): str(row.get("name")) for row in projects}
    rows = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % fmt(row.get(key))
                                           for key in ("name", "csproj", "target_framework")) for row in projects)
    return _panel(sorted(by_name.values()), edges, key="proj", title="项目引用图",
                  hint="节点是 .NET 项目，箭头从项目指向它 ProjectReference 的项目。",
                  summary="项目清单（%d 个）" % len(projects), headers=("项目", "csproj", "目标框架"),
                  rows=rows, labels=labels)

def _target(row) -> str:
    """「目标」单元格：有 target 就照抄，没有就中性说「未解析到单文件目标」（R439）。"""
    return fmt(row.get("target")) if row.get("target") else "未解析到单文件目标"

def entry_list(doc, params):
    """入口逐条：name / kind / target / command / note（note 单独成列，R439 不隐藏事实）。"""
    entries = list(doc.get("entries") or [])
    if not entries:
        return '<p class="muted">没有找到入口（package scripts / main guard / dotnet 项目都没命中）。</p>'
    limit = params.get("limit")
    shown = entries[:max(0, int(limit))] if limit is not None else entries
    rows = "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td><code>%s</code></td><td>%s</td></tr>'
                   % (fmt(row.get("name")), fmt(row.get("kind")), _target(row),
                      fmt(row.get("command") or ""), fmt(row.get("note") or "") or "—") for row in shown)
    return ('<p class="hint">共 %d 个入口%s；target 为空的行没解析到单文件目标，原因在「说明」列'
            '（事实层记的原话，不替它编）。</p>'
            % (len(entries), "，这里只列前 %d 个" % len(shown) if len(shown) < len(entries) else "")
            + _table("入口清单（%d 条）" % len(shown), ("名字", "类型", "目标", "命令", "说明"), rows))

def _manifests(doc) -> int:
    """R485：只读 facts 层算好的 graph.omitted_manifests（页面不许拿截断后的节点集另算一套）。"""
    return int((doc.get("graph") or {}).get("omitted_manifests") or 0)

def _project_note(doc, rows) -> str:
    """R479：文件级图只画 import，项目引用边的条数与去向必须说出来（数与名字都取自 doc）。"""
    names = {str(row.get("csproj")): str(row.get("name")) for row in doc.get("projects") or []}
    pairs = ["%s → %s" % (fmt(names.get(str(row["from"]), str(row["from"]))),
                          fmt(names.get(str(row["to"]), str(row["to"])))) for row in rows[:5]]
    tail = " 等 %d 条" % len(rows) if len(rows) > 5 else ""
    return ("另有 %d 条项目引用（ProjectReference），本图只画文件级 import：%s%s"
            % (len(rows), "、".join(pairs), tail))

def import_graph(doc, params):
    """依赖图 SVG + 环 + 不可达清单 + R437 的孤立/截断两句披露。"""
    graph = doc.get("graph") or {}
    nodes = [str(row["id"]) for row in graph.get("nodes") or []]
    labels = {str(row.get("id")): str(row.get("label") or row.get("id")) for row in graph.get("nodes") or []}
    rows = graph.get("edges") or []       # R471：边数恒取 len(graph.edges)（facts 已按 (from,to,kind) 合并）
    edges = sorted((str(row["from"]), str(row["to"])) for row in rows)
    level = str(graph.get("level") or "file")
    arrow = "箭头=谁引用谁（ProjectReference）" if level == "project" else "箭头=谁 import 谁"
    out = ['<p class="hint">依赖图（%s 级）：%d 个节点、%d 条边，按依赖层次摆放，%s。</p>'
           % (fmt(level), len(nodes), len(rows), arrow),
           _svg(nodes, edges, key="dep", title="依赖图",
                layers=[[str(item) for item in row] for row in graph.get("layers") or []], labels=labels)]
    hidden = graph.get("project_edges") or []
    if level == "file" and hidden:      # R479：混合仓只画文件级图，项目引用边必须如实披露
        out.append('<p class="note">%s。</p>' % _project_note(doc, hidden))
    rings = [" → ".join([str(item) for item in ring] + [str(ring[0])]) for ring in (graph.get("cycles") or [])[:3]]
    total = len(graph.get("cycles") or [])
    tail = " 等 %d 个" % total if total > 3 else ""
    out.append('<p class="note">环：%s。</p>' % ("；".join(rings) + tail if rings else "没有发现环"))
    entries = doc.get("entries") or []
    if not entries:                    # R440：没有入口就没有「从入口到不了」这个前提
        out.append('<p class="note">没有找到可解析的入口，可达性未计算。</p>')
    else:
        unreachable = [str(item) for item in graph.get("unreachable") or []]
        if unreachable:
            out.append('<p class="note">从入口到不了 %d 个文件：%s%s。</p>'
                       % (len(unreachable), "、".join(fmt(item) for item in unreachable[:12]),
                          " 等 %d 个" % len(unreachable) if len(unreachable) > 12 else ""))
    if level != "project":             # R455：project 级的 N 与 M 口径不同，整句省略，不许混写
        out.append('<p class="note">%d 个文件没有进入关系图，其中 %d 个是清单、文档等不产生 import 的文件'
                   '（未画进图是计数，不是丢了）。</p>'
                   % (int(graph.get("omitted_isolated") or 0), _manifests(doc)))
    if graph.get("truncated"):
        out.append('<p class="note">图已截断，只画了前 %d 个节点；另有 %d 个节点没有画'
                   '（截断是计数，不是丢了）。</p>'
                   % (MAX_GRAPH_NODES, int(graph.get("truncated_nodes") or 0)))
    return "".join(out)
