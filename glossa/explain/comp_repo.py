"""仓储级组件（3 个）+ 通用格式化：overview / metrics / dir_tree / fmt / _table。

R450：四个图/入口组件（package_map / project_map / entry_list / import_graph）与 _svg 搬到
comp_graph.py，这里只留总览、指标、目录树与两个模块共用的格式化出口（comp_graph 单向依赖本模块）。
R315：package_map 无 packages 时返回空串，整层不出现；R320：事实表一律 <details> 折叠。
R444：事实层没有 README 正文时只说事实层没有，不断言仓库里没有 README。
R445：overview 的每个字段取不到时写显式 fallback（未登记 / 未识别 / 未知），不留空串。
D10：字典一律 sorted(items()) 再拼；D12：0 文件时 dir_tree 不产出空 <ul>。
"""
from __future__ import annotations

import html

from papertrace.api import BuildError

def fmt(value) -> str:
    """统一出口：None → 空、bool → 是否、int → 千分位、其余转义。"""
    if value is None or value == "":
        return ""
    if isinstance(value, (bool, int)):
        return ("是" if value else "否") if isinstance(value, bool) else f"{value:,}"
    return html.escape(str(value), quote=True)

def _shown(value, fallback: str) -> str:
    """R445：取不到就写显式 fallback，绝不让「主语言：」后面空着。"""
    return fmt(value) or fmt(fallback)

def _table(summary: str, headers, rows) -> str:
    """折叠事实表（R320）：表头顺序就是 headers，rows 是渲染好的 <tr> 串。"""
    return ('<details class="facts"><summary>%s</summary><table class="grid"><thead><tr>%s</tr></thead>'
            '<tbody>%s</tbody></table></details>'
            % (summary, "".join("<th>%s</th>" % fmt(name) for name in headers), rows))

def _root_readme(path: str) -> bool:
    """R484：只有**根目录的 README**代表整仓；别的文件（连根目录脚本）都只代表它自己。"""
    return "/" not in path and path.lower().startswith("readme")

def _intro(doc):
    """(人话简介, 来源)：R444 只说事实层没给 README 正文；R484 兜底句必须自带限定。"""
    rows = [row for row in doc.get("files") or []
            if str(row.get("doc_first_line") or "").strip()]
    rows.sort(key=lambda row: not _root_readme(str(row.get("path") or "")))
    if not rows:
        return None, "事实层没有提供 README 正文，也没抓到任何模块 docstring"
    path, line = str(rows[0].get("path") or ""), str(rows[0]["doc_first_line"]).strip()
    if _root_readme(path):
        return line, "简介取的是仓库根 README 的首段（%s 第 1 行）" % path
    return ("（以下一句来自 %s 的模块注释，只代表这个文件）：%s" % (path, line),
            "事实层没有提供 README 正文；简介取的是模块 docstring（%s 第 1 行）" % path)

def overview(doc, params):
    """meta + 一句项目简介（R320：人话在前，明细在后；R444/R445）。"""
    meta = doc.get("meta") or {}
    repo, tool = meta.get("repo") or {}, meta.get("tool") or {}
    intro, source = _intro(doc)
    lead = '<p class="intro">%s</p>' % fmt(intro) if intro else '<p class="intro muted">没有可用的项目简介</p>'
    tool_text = " ".join(part for part in (str(tool.get("name") or "").strip(),
                                          str(tool.get("version") or "").strip()) if part)
    items = (("仓库", _shown(repo.get("root_name"), "未登记")), ("路径", _shown(repo.get("url"), "未登记")),
             ("commit", _shown(repo.get("commit"), "未登记")),
             ("主语言", _shown(repo.get("language"), "未识别")),
             ("生成于", _shown(meta.get("created_at"), "未知")),
             ("工具", _shown(tool_text, "未登记")))
    rows = "".join("<li>%s：%s</li>" % (fmt(key), value) for key, value in items)
    return '%s<p class="src">来源：%s</p><ul class="plain">%s</ul>' % (lead, fmt(source), rows)

def metrics(doc, params):
    """指标条：整数一律千分位（R320）；键不认识就响亮拒绝；字典按 key 升序（D10）。"""
    totals = doc.get("totals") or {}
    rows = []
    for key in params.get("keys") or []:
        if key not in totals:
            raise BuildError("组件 metrics 不认识 totals 键 %r（可用：%s）" % (key, "、".join(sorted(totals))))
        value = totals[key]
        if isinstance(value, dict):
            value = "、".join("%s %s" % (k, v) for k, v in sorted(value.items())) or "无"
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
    """按 files 路径造目录树，默认 3 层，整棵树折叠（R320）；0 文件不产出空 <ul>（D12）。"""
    depth = int(params.get("max_depth") or 3)
    if depth < 1:
        raise BuildError("组件 dir_tree 的 max_depth 必须 ≥ 1，收到 %r" % (params.get("max_depth"),))
    paths = [row["path"] for row in doc.get("files") or []]
    if not paths:
        return '<p class="muted">这个仓库里没有可展开的目录（%d 个文件）。</p>' % len(paths)
    tree = _tree(paths, depth)
    return ('<p class="hint">按文件路径造的目录树，最多 %d 层；摘要里的数字是该目录下的文件数（含更深层）。'
            '</p><details class="facts"><summary>展开目录树（%d 个文件）</summary><ul class="tree">%s</ul>'
            '</details>' % (depth, tree["_n"], _tree_html(tree)))

def package_finder(doc):
    """path → 所属包名（最长目录前缀）；path='.' 的根包只管根目录文件。comp_graph / comp_file 复用。"""
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
