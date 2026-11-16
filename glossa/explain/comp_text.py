"""模型文字类组件（3 个）：text / custom / table。

R314：text 与 custom 的未溯源标记由 components.render_block 统一施加，这里只出干净 HTML。
R307：custom 走 guard.sanitize_html；removed>0 时块顶插「本块已移除 N 处不允许的构造」，
并把 N 同时写进 data-removed——页面写多少、render 的报告就是多少（同一份事实，不另算一遍）。
R412：table 的列名按事实家族挑；列名不存在抛 BuildError 并列出可用列，绝不静默空列。
D10：字典一律 sorted(items()) 再拼。D15：全仓只有这一份单元格格式化 cell()，comp_file 引用它。
"""
from __future__ import annotations

import html

from glossa.explain import guard, markdown
from papertrace.exceptions import BuildError

_COLUMNS: dict[str, tuple[str, ...]] = {
    "files": ("path", "lang", "lines", "bytes", "symbols", "parse"),
    "pkg": ("name", "path", "manifest", "deps", "dev_deps", "scripts", "workspace"),
    "project": ("name", "csproj", "target_framework", "output_type",
                "project_refs", "package_refs"),
    "entry": ("name", "kind", "target", "command", "package"),
    "import": ("from", "line", "specifier", "kind", "target"),
    "degraded": ("scope", "reason", "count"),
    "excluded": ("files", "bytes", "rules", "oversize", "pruned_files",
                 "pruned_files_partial", "truncated"),
    "graph": ("id", "kind", "label", "lang", "package"),
}


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _plain(value) -> str:
    """列表/字典单元格的人话：["Demo.Core"] → Demo.Core；{"a": 1} → a=1。"""
    if isinstance(value, dict):
        if value.get("name"):
            version = value.get("version")
            return str(value["name"]) + (" " + str(version) if version else "")
        return "、".join("%s=%s" % (key, val) for key, val in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return "、".join(_plain(item) for item in value)
    return str(value)


def cell(value) -> str:
    """唯一一份单元格格式化（D15）：空值给破折号、bool 给是否、int 千分位、其余转义。"""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, (list, tuple)):
        return _esc(_plain(value)) if value else "无"
    return _esc(_plain(value) if isinstance(value, dict) else value)


def render_text(doc, params):
    """模型写的 markdown 子集 → HTML（不支持的构造按纯文本保留，先转义再插标签）。"""
    body, _notes = markdown.render_markdown(str(params.get("text") or ""))
    return '<div class="prose">%s</div>' % body if body else ""


def render_custom(doc, params):
    """模型写的任意 HTML → 只留安全构造；移除了多少落在包裹层的 data-removed 上（R307）。

    可见的「本块已移除 N 处不允许的构造」由 render 在未溯源标记**之后**补上：那句话里的 N
    是程序自己数的，不能让 mark_untraced 把它当成模型没出处的数字包起来（R314 同尺）。
    """
    clean, removed, _notes = guard.sanitize_html(str(params.get("html") or ""))
    if not clean.strip() and not removed:
        return ""
    attr = ' data-removed="%d"' % removed if removed else ""
    return '<div class="custom"%s>%s</div>' % (attr, clean)


def _file_row(row: dict) -> dict:
    out = dict(row)
    out["symbols"] = len(row.get("symbols") or [])
    return out


def _rows_for(doc, fact_id: str):
    """(rows, columns)：按 fact id 家族给出可列的行与列；不支持的家族响亮拒绝。"""
    files = doc.get("files") or []
    if fact_id == "fact:files":
        return [_file_row(row) for row in files], _COLUMNS["files"]
    kind, _, rest = fact_id[5:].partition(":") if fact_id.startswith("fact:") else ("", "", "")
    if kind == "file":
        row = next((item for item in files if item["path"] == rest), None)
        if row is None:
            raise BuildError("组件 table 的 fact %s 指向的文件不在 doc.files 里" % fact_id)
        return [_file_row(row)], _COLUMNS["files"]
    if kind in ("pkg", "project"):
        pool = doc.get("packages" if kind == "pkg" else "projects") or []
        rows = [row for row in pool if not rest or str(row.get("name")) == rest]
        return rows, _COLUMNS[kind]
    if kind == "entry":
        pool = doc.get("entries") or []
        return [row for row in pool if not rest or str(row.get("name")) == rest], _COLUMNS["entry"]
    if kind == "import":
        pool = doc.get("imports") or []
        if not rest.isdigit():
            return pool, _COLUMNS["import"]
        index = int(rest) - 1
        if not 0 <= index < len(pool):
            raise BuildError("组件 table 的 %s 越界：共 %d 条 import" % (fact_id, len(pool)))
        return [pool[index]], _COLUMNS["import"]
    if kind == "degraded":
        return list(doc.get("degraded") or []), _COLUMNS["degraded"]
    if kind == "excluded":
        return [dict(doc.get("excluded") or {})], _COLUMNS["excluded"]
    if kind == "graph":
        return list((doc.get("graph") or {}).get("nodes") or []), _COLUMNS["graph"]
    raise BuildError("组件 table 不支持事实家族 %s（支持：%s）"
                     % (fact_id, "、".join(sorted(_COLUMNS))))


def check_table(doc, params):
    """列名/列空校验（供 validate_blocks 复用），返回 (rows, 选中的列)。"""
    fact_id = str(params.get("fact") or "")
    rows, columns = _rows_for(doc, fact_id)
    picked = [str(name) for name in params.get("columns") or []]
    if not picked:
        raise BuildError("组件 table 必须给 columns；%s 的可用列是：%s"
                         % (fact_id, "、".join(columns)))
    unknown = [name for name in picked if name not in columns]
    if unknown:
        raise BuildError("组件 table 在 %s 上没有这些列：%s（可用列：%s）"
                         % (fact_id, "、".join(unknown), "、".join(columns)))
    return rows, picked


def render_table(doc, params):
    """事实表：一律 <details> 折叠（R320），表头就是 columns 的顺序。"""
    rows, picked = check_table(doc, params)
    total = len(rows)
    limit = params.get("limit")
    if limit is not None:
        rows = rows[:max(0, int(limit))]
    if not rows:
        return '<p class="muted">%s 目前没有可列的行。</p>' % _esc(params.get("fact"))
    head = "".join("<th>%s</th>" % _esc(name) for name in picked)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % cell(row.get(name))
                                          for name in picked) for row in rows)
    more = "，只列前 %d 行" % len(rows) if len(rows) < total else ""
    return ('<details class="facts"><summary>%s（共 %d 行%s）</summary>'
            '<table class="grid"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></details>'
            % (_esc(params.get("fact")), total, more, head, body))
