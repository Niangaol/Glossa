"""组件注册表（R312 唯一真源）+ 块校验 + 单块渲染。

R312：14 个组件的名字 / 必填参 / 选填参 / 事实模式只在这里声明一次，渲染逻辑在 comp_*.py，
注册表只放 callable 引用（将来 MCP 的 list_components 从这个表生成，不许手抄漂移）。
R313：cites 或 params.fact 里有 doc.facts 没有的 id → BuildError 点名组件与那个 id，整页拒绝。
R314：mark_untraced 只施加在 text / custom 的模型文字上；其余 12 个组件的数字是程序从 doc
复算出来的，一律不标记（全页黄标会让警示失效）。
R315：组件返回空串（bonus / package_map）就整层不出现，不生成空 section。
R316：code 必须 1 ≤ start ≤ end ≤ 该文件行数，越界 BuildError，不静默截到文件尾。
R412：块可选键 section(1–7) 只决定标题取七块骨架的哪一条，缺省用组件默认标题。
"""
from __future__ import annotations

from glossa import fact_ids
from glossa.explain import comp_file, comp_graph, comp_repo, comp_text, guard, outline
from papertrace.exceptions import BuildError

UNTRACED_MARK = '<mark class="untraced">'
_MARKED = frozenset({"text", "custom"})

def _spec(name, render, required=(), optional=(), facts=(), section=None, title=None):
    return {"name": name, "required": list(required), "optional": list(optional), "facts": list(facts),
            "section": section, "title": title, "render": render}

COMPONENTS = {spec["name"]: spec for spec in (
    _spec("text", comp_text.render_text, ("text",), ("title",), ("任意（由 cites 决定）",), title="讲解"),
    _spec("custom", comp_text.render_custom, ("html",), ("title",), ("任意（由 cites 决定）",), title="自定义内容"),
    _spec("overview", comp_repo.overview, facts=("fact:totals", "fact:files"), section=1),
    _spec("metrics", comp_repo.metrics, ("keys",), facts=("fact:totals",), section=1),
    _spec("dir_tree", comp_repo.dir_tree, optional=("max_depth",), facts=("fact:files",), section=3),
    _spec("package_map", comp_graph.package_map, facts=("fact:pkg:*",), section=3),
    _spec("project_map", comp_graph.project_map, facts=("fact:project:*",), section=3),
    _spec("entry_list", comp_graph.entry_list, optional=("limit",), facts=("fact:entry:*",), section=2),
    _spec("import_graph", comp_graph.import_graph, facts=("fact:graph",), section=4),
    _spec("file_card", comp_file.file_card, ("path",), facts=("fact:file:<path>",), section=5),
    _spec("symbol_table", comp_file.symbol_table, ("path",), ("kind",), ("fact:symbol:<path>#*",), section=5),
    _spec("code", comp_file.code, ("path", "start", "end"), facts=("fact:source:<path>:*",), section=5),
    _spec("table", comp_text.render_table, ("fact", "columns"), ("limit",), ("该 fact id",), section=6),
    _spec("bonus", comp_file.bonus, facts=("fact:bonus",), section=7),
)}

def _facts(doc):
    return doc.get("facts") or {}

def _require_fact(doc, component, fact_id):
    if fact_id not in _facts(doc):
        raise BuildError("组件 %s 引用的事实 id 在 doc.facts 里不存在：%s" % (component, fact_id))

def _require_file(doc, component, path):
    if path not in {row["path"] for row in doc.get("files") or []}:
        raise BuildError("组件 %s 的 path 不在 doc.files 里：%s" % (component, path))

def _check_code(doc, params):
    path = str(params.get("path"))
    row = next((item for item in doc.get("files") or [] if item["path"] == path), {})
    start, end, total = params.get("start"), params.get("end"), int(row.get("lines") or 0)
    plain = all(isinstance(value, int) and not isinstance(value, bool) for value in (start, end))
    if not plain or not 1 <= start <= end <= total:
        raise BuildError("组件 code 的行区间越界：%s 第 %s–%s 行不在 1–%d 之内（R316：不许静默截断）"
                         % (path, start, end, total))

def _check_params(doc, name, params):
    if name in ("file_card", "symbol_table", "code"):
        _require_file(doc, name, str(params.get("path")))
    if name == "code":
        _check_code(doc, params)
    if name == "table":
        comp_text.check_table(doc, params)
    if name == "metrics":
        unknown = [key for key in params.get("keys") or [] if key not in (doc.get("totals") or {})]
        if unknown:
            raise BuildError("组件 metrics 不认识这些 totals 键：%s" % "、".join(map(str, unknown)))

_BLOCK_KEYS = frozenset({"component", "params", "cites", "section", "title", "notes"})

def validate_blocks(doc, blocks):
    """逐块校验；任何一条不合契约都抛 BuildError（R313/R316），绝不静默跳过。

    合法顶层键只有 component / params / cites / section / title / notes（R448-D16）：
    多一个键就抛 BuildError，与「未知组件响亮报错」同口径（notes 是 narrate 的披露通道）。
    """
    for index, block in enumerate(blocks or [], 1):
        extra = [str(key) for key in block if key not in _BLOCK_KEYS] if isinstance(block, dict) else []
        if extra:
            raise BuildError("第 %d 块有不认识的顶层键：%s（合法键：%s）"
                             % (index, "、".join(sorted(extra)), "、".join(sorted(_BLOCK_KEYS))))
        name = block.get("component") if isinstance(block, dict) else None
        spec = COMPONENTS.get(name)
        if spec is None:
            raise BuildError("第 %d 块的组件名 %r 不在注册表里（共 14 个：%s）"
                             % (index, name, "、".join(sorted(COMPONENTS))))
        params = block.get("params")
        if not isinstance(params, dict):
            raise BuildError("第 %d 块（%s）的 params 必须是 dict，收到 %r" % (index, name, params))
        for key in spec["required"]:
            if params.get(key) in (None, ""):
                raise BuildError("第 %d 块（%s）缺少必填参 %s（必填：%s）"
                                 % (index, name, key, "、".join(spec["required"])))
        for fact_id in [str(item) for item in block.get("cites") or []]:
            _require_fact(doc, name, fact_id)
        if isinstance(params.get("fact"), str):
            _require_fact(doc, name, params["fact"])
        section = block.get("section")
        if section is not None and (isinstance(section, bool) or section not in range(1, 8)):
            raise BuildError("第 %d 块（%s）的 section 必须是 1–7 的整数，收到 %r" % (index, name, section))
        _check_params(doc, name, params)

def block_title(block, spec):
    """标题：block.title > params.title > 七块骨架（block.section 或组件默认）> 组件默认名。"""
    if block.get("title"):
        return str(block["title"])
    params = block.get("params") or {}
    if params.get("title"):
        return str(params["title"])
    section = block.get("section") or spec.get("section")
    return outline.BLOCK_TITLES[int(section) - 1] if section else str(spec.get("title") or spec["name"])

def render_block(doc, block):
    """渲染一块；空串表示整层不出现（R315）。未知组件同样响亮拒绝，不回退到纯文本。"""
    name = block.get("component")
    spec = COMPONENTS.get(name)
    if spec is None:
        raise BuildError("没有名为 %r 的组件；可用的 14 个：%s" % (name, "、".join(sorted(COMPONENTS))))
    html = spec["render"](doc, dict(block.get("params") or {}))
    if name in _MARKED and html.strip():
        numbers = fact_ids.numbers_for(_facts(doc), [str(item) for item in block.get("cites") or []])
        html = guard.mark_untraced(html, numbers)[0]
    return html
