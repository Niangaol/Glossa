"""仓储级组件（7 个）：overview / metrics / dir_tree / package_map / project_map /
entry_list / import_graph。组件自己从 doc 取数，模型只决定用哪个、什么顺序。

R315：package_map 无 packages 时返回空串，整层不出现；R320：事实表一律 <details> 折叠。
R412-4：import_graph 恒写「N 个文件没有 import 关系，未画进图」，truncated 另起截断说明。
SVG 在「0 节点 / 1 节点 / 120 节点截断」下都合法：xmlns 在、宽高都是正数。
"""
from __future__ import annotations

import html
import math

from glossa.graph import MAX_GRAPH_NODES
from papertrace.exceptions import BuildError

def fmt(value) -> str:
    """统一出口：None → 空、bool → 是否、int → 千分位、其余转义。"""
    if value is None or value == "":
        return ""
    if isinstance(value, (bool, int)):
        return ("是" if value else "否") if isinstance(value, bool) else f"{value:,}"
    return html.escape(str(value), quote=True)

def _table(summary: str, headers, rows) -> str:
    """折叠事实表（R320）：表头顺序就是 headers，rows 是渲染好的 <tr> 串。"""
    return ('<details class="facts"><summary>%s</summary><table class="grid"><thead><tr>%s</tr></thead>'
            '<tbody>%s</tbody></table></details>'
            % (summary, "".join("<th>%s</th>" % fmt(name) for name in headers), rows))

def _intro(doc):
    """(人话简介, 来源)：有 docstring 用 docstring，取不到就明说没有，绝不编。"""
    for row in doc.get("files") or []:
        if line := str(row.get("doc_first_line") or "").strip():
            return line, "模块 docstring（%s 第 1 行）" % row["path"]
    return None, "事实层里既没有 README 正文，也没有模块 docstring"

def overview(doc, params):
    """meta + 一句项目简介（R320：人话在前，明细在后）。"""
    meta = doc.get("meta") or {}
    repo, tool = meta.get("repo") or {}, meta.get("tool") or {}
    intro, source = _intro(doc)
    lead = '<p class="intro">%s</p>' % fmt(intro) if intro else '<p class="intro muted">没有可用的项目简介</p>'
    items = (("仓库", repo.get("root_name")), ("路径", repo.get("url")), ("commit", repo.get("commit")),
             ("主语言", repo.get("language")), ("生成于", meta.get("created_at")),
             ("工具", "%s %s" % (tool.get("name") or "glossa", tool.get("version") or "")))
    rows = "".join("<li>%s：%s</li>" % (fmt(key), fmt(value)) for key, value in items)
    return '%s<p class="src">来源：%s</p><ul class="plain">%s</ul>' % (lead, fmt(source), rows)

def metrics(doc, params):
    """指标条：整数一律千分位（R320）；键不认识就响亮拒绝。"""
    totals = doc.get("totals") or {}
    rows = []
    for key in params.get("keys") or []:
        if key not in totals:
            raise BuildError("组件 metrics 不认识 totals 键 %r（可用：%s）" % (key, "、".join(sorted(totals))))
        value = totals[key]
        if isinstance(value, dict):
            value = "、".join("%s %s" % (k, v) for k, v in value.items()) or "无"
        rows.append('<li><span class="k">%s</span><span class="v">%s</span></li>' % (fmt(key), fmt(value)))
    return '<ul class="metrics">%s</ul>' % "".join(rows)

def _tree(paths, depth):
    root = {"_n": 0, "_d": {}}
    for path in paths:
        node = root
        node["_n"] += 1
        for part in path.split("/")[:-1][:depth]:
            node = node["_d"].setdefault(part, {"_n": 0, "_d": {}})
            node["_n"] += 1
    return root

def _tree_html(node):
    items = []
    for name in sorted(node["_d"]):
        child = node["_d"][name]
        inner = "<ul>%s</ul>" % _tree_html(child) if child["_d"] else ""
        items.append('<li><details><summary>%s/ · %d 个文件</summary>%s</details></li>'
                     % (fmt(name), child["_n"], inner))
    return "".join(items)

def dir_tree(doc, params):
    """按 files 路径造目录树，默认 3 层，整棵树折叠（R320）。"""
    depth = int(params.get("max_depth") or 3)
    if depth < 1:
        raise BuildError("组件 dir_tree 的 max_depth 必须 ≥ 1，收到 %r" % (params.get("max_depth"),))
    tree = _tree([row["path"] for row in doc.get("files") or []], depth)
    return ('<p class="hint">按文件路径造的目录树，最多 %d 层；摘要里的数字是该目录下的文件数（含更深层）。'
            '</p><details class="facts"><summary>展开目录树（%d 个文件）</summary><ul class="tree">%s</ul>'
            '</details>' % (depth, tree["_n"], _tree_html(tree)))

def _svg(nodes, edges, *, key, title, layers=None):
    """节点=名单，边=(from,to)；0 节点也给正数宽高，绝不产出非法 SVG。"""
    names = [str(node) for node in nodes]
    rows = [row for row in (sorted(set(layer) & set(names)) for layer in layers or []) if row] or [[]]
    if not rows[0]:
        cols = max(1, math.ceil(math.sqrt(len(names)))) if names else 1
        rows = [names[index:index + cols] for index in range(0, len(names), cols)] or [[]]
    width, height = max(320, max(len(row) for row in rows) * 200 + 40), max(120, len(rows) * 90 + 40)
    pos = {name: (30 + col * 200, 40 + row * 90) for row, line in enumerate(rows) for col, name in enumerate(line)}
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
        out.append('<g><rect x="%d" y="%d" width="160" height="34" rx="6" fill="#eef2f7" stroke="#c6cedb"/>'
                   '<text x="%d" y="%d" font-size="11">%s</text></g>'
                   % (x, y, x + 8, y + 21, fmt(name if len(name) <= 24 else name[:23] + "…")))
    return "".join(out) + "</svg>"

def package_finder(doc):
    """path → 所属包名（最长目录前缀）；path='.' 的根包只管根目录文件。comp_file 复用。"""
    pairs = sorted(((str(row.get("path") or "").strip("/"), str(row.get("name")))
                    for row in doc.get("packages") or [] if row.get("name")), key=lambda item: -len(item[0]))

    def find(path):
        for base, name in pairs:
            if base in ("", ".", "./") and "/" not in path:
                return name
            if base not in ("", ".", "./") and path.startswith(base + "/"):
                return name
        return None
    return find

def _panel(nodes, edges, *, key, hint, title, summary, headers, rows, layers=None):
    """图 + 提示 + 折叠清单，三个图组件共用。"""
    return ('<p class="hint">%s</p>' % hint + _svg(nodes, edges, key=key, title=title, layers=layers)
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
    """节点=C# 项目，边=ProjectReference（无 projects → 空串）。"""
    projects = [row for row in doc.get("projects") or [] if row.get("csproj")]
    if not projects:
        return ""
    by_name = {str(row.get("name")): str(row["csproj"]) for row in projects}
    edges = sorted({(str(row["csproj"]), by_name[str(ref)]) for row in projects for ref in row.get("project_refs") or []
                    if str(ref) in by_name})
    rows = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % fmt(row.get(key))
                                           for key in ("name", "csproj", "target_framework")) for row in projects)
    return _panel(sorted(by_name.values()), edges, key="proj", title="项目引用图",
                  hint="节点是 .NET 项目，箭头从项目指向它 ProjectReference 的项目。",
                  summary="项目清单（%d 个）" % len(projects), headers=("项目", "csproj", "目标框架"), rows=rows)

def entry_list(doc, params):
    """入口逐条：name / kind / target（None 明写「未指向单文件」）/ command。"""
    entries = list(doc.get("entries") or [])
    if not entries:
        return '<p class="muted">没有找到入口（package scripts / main guard / dotnet 项目都没命中）。</p>'
    limit = params.get("limit")
    shown = entries[:max(0, int(limit))] if limit is not None else entries
    rows = "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td><code>%s</code></td></tr>'
                   % (fmt(row.get("name")), fmt(row.get("kind")),
                      fmt(row.get("target")) if row.get("target") else "未指向单文件",
                      fmt(row.get("command") or "")) for row in shown)
    return ('<p class="hint">共 %d 个入口%s；target 写「未指向单文件」的是复合命令。</p>'
            % (len(entries), "，这里只列前 %d 个" % len(shown) if len(shown) < len(entries) else "")
            + _table("入口清单（%d 条）" % len(shown), ("名字", "类型", "目标", "命令"), rows))

def import_graph(doc, params):
    """依赖图 SVG + 环 + 不可达清单 + R412-4 的两句固定披露。"""
    graph = doc.get("graph") or {}
    nodes = [str(row["id"]) for row in graph.get("nodes") or []]
    edges = sorted({(str(row["from"]), str(row["to"])) for row in graph.get("edges") or []})
    out = ['<p class="hint">依赖图（%s 级）：%d 个节点、%d 条边，按依赖层次摆放，箭头=谁 import 谁。</p>'
           % (fmt(graph.get("level") or "file"), len(nodes), len(edges)),
           _svg(nodes, edges, key="dep", title="依赖图",
                layers=[[str(item) for item in row] for row in graph.get("layers") or []])]
    rings = [" → ".join([str(item) for item in ring] + [str(ring[0])]) for ring in (graph.get("cycles") or [])[:3]]
    out.append('<p class="note">环：%s。</p>' % ("；".join(rings) if rings else "没有发现环"))
    unreachable = [str(item) for item in graph.get("unreachable") or []]
    if unreachable:
        out.append('<p class="note">从入口到不了 %d 个文件：%s%s。</p>'
                   % (len(unreachable), "、".join(fmt(item) for item in unreachable[:12]),
                      " 等 %d 个" % len(unreachable) if len(unreachable) > 12 else ""))
    out.append('<p class="note">%d 个文件没有 import 关系，未画进图（隔离是计数，不是丢了）。</p>'
               % int(graph.get("omitted_isolated") or 0))
    if graph.get("truncated"):
        out.append('<p class="note">图已截断，只画了前 %d 个节点。</p>' % MAX_GRAPH_NODES)
    return "".join(out)
