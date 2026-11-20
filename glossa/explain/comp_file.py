"""文件级组件（4 个）：file_card / symbol_table / code / bonus。

R412-3：每张 file_card 都写出该文件在 keyfiles 里的 reasons；不在清单里就明说「不在 keyfiles 的
可讲解清单里」，要解释原因就取 candidate_files / SYMBOL_LANGS 能回查的事实（R441），不编「符号少」。
R443：doc.files[].degraded 逐条列在卡片里并注明这是程序事实，让「我没看清的地方」拿到真原因。
R446：code 只用 doc.facts 里的 fact:source 摘录，绝不读盘、绝不读进程 cwd（R319 逐字节可复现）。
R316：code 的行区间已由 validate_blocks 卡在 1..行数（越界 BuildError），这里不再静默截断。
R315：bonus 没有 fact:bonus 时返回空串，整层不出现。D15：单元格格式化统一用 comp_text.cell。
"""
from __future__ import annotations

from glossa import keyfiles
from glossa.exclude import SYMBOL_LANGS
from glossa.explain.comp_repo import fmt, package_finder
from glossa.explain.comp_text import cell
from papertrace.api import BuildError

def _row(doc, path):
    """doc.files 里那一行；没有就抛 BuildError（path 已由 validate_blocks 挡过，这是二道闸）。"""
    for row in doc.get("files") or []:
        if row["path"] == path:
            return row
    raise BuildError("组件要讲的文件不在 doc.files 里：%s" % path)

def _reasons(doc, path):
    """keyfiles 的 reasons（R412-3）；None 表示这个文件不在关键文件清单里。"""
    for item in keyfiles.key_files(doc):
        if item["path"] == path:
            return list(item.get("reasons") or [])
    return None

def _why_not(doc, row, path):
    """不在 keyfiles 时的真实原因（R441）：只取 candidate_files / SYMBOL_LANGS 能回查的事实。"""
    if row.get("lang") not in SYMBOL_LANGS:
        return "（语言 %s 不参与符号抽取）" % fmt(row.get("lang") or "未知")
    ranked = [item["path"] for item in keyfiles.candidate_files(doc)]
    if path in ranked:
        return "（在可讲解清单里排第 %d，超出前 %d 个）" % (ranked.index(path) + 1, keyfiles.KEY_FILE_LIMIT)
    return ""

def file_card(doc, params):
    """一张卡片：路径 + 明细 + 一句人话（注明来源）+ 为什么讲它（R412-3）+ 降级原因（R443）。"""
    path = str(params.get("path") or "")
    row = _row(doc, path)
    facts = (("语言", row.get("lang")), ("行数", row.get("lines")), ("字节", row.get("bytes")),
             ("符号", len(row.get("symbols") or [])), ("import", len(row.get("imports") or [])),
             ("解析精度", row.get("parse")), ("所属包", package_finder(doc)(path) or "（根目录 / 未归包）"))
    cells = "".join("<li>%s：%s</li>" % (fmt(key), fmt(value)) for key, value in facts)
    line = str(row.get("doc_first_line") or "").strip()
    quote = '<p class="intro">%s</p>' % fmt(line) if line else ""
    human = ('<p class="src">来源：%s 的模块 docstring（第 1 行）</p>' % fmt(path) if line else
             '<p class="src">没抓到 docstring 或首行注释（解析精度 %s），这里不臆造一句。</p>'
             % fmt(row.get("parse")))
    reasons = _reasons(doc, path)
    if reasons is None:
        why = "不在 keyfiles 的可讲解清单里%s，这里只按你指定的路径讲。" % _why_not(doc, row, path)
    elif reasons:
        why = "为什么讲它：" + "、".join(fmt(item) for item in reasons) + "。"
    else:
        why = "它进了可讲解清单，但 entry / 被依赖 / 符号三条理由都没命中。"
    degraded = [str(item) for item in row.get("degraded") or []]
    if degraded:
        notes = ('<p class="note">程序事实 · 这个文件有 %d 条降级说明：%s</p>'
                 % (len(degraded), "；".join(fmt(item) for item in degraded)))
    elif row.get("parse") == "skipped":
        notes = '<p class="note">程序事实 · 解析精度 skipped：解析器没给出正文，这里不假装看过。</p>'
    else:
        notes = ""
    return ('<div class="card"><p class="card-path"><code>%s</code></p>%s%s<p class="note">%s</p>'
            '<ul class="plain">%s</ul>%s</div>' % (fmt(path), quote, human, why, cells, notes))

def symbol_table(doc, params):
    """按 kind 分组的符号表，整表折叠（R320）；kind 选填，只影响看哪一类。"""
    path = str(params.get("path") or "")
    row = _row(doc, path)
    kind = params.get("kind")
    symbols = [item for item in row.get("symbols") or [] if not kind or item.get("kind") == kind]
    if not symbols:
        return '<p class="muted">%s 没有%s符号。</p>' % (fmt(path), "「%s」类型的" % fmt(kind) if kind else "")
    groups = {}
    for item in symbols:
        groups.setdefault(str(item.get("kind")), []).append(item)
    blocks = []
    for name in sorted(groups):
        items = sorted(groups[name], key=lambda item: (int(item.get("line") or 0), str(item.get("name"))))
        rows = "".join("<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td></tr>"
                       % (fmt(item.get("name")), cell(item.get("line")), cell(item.get("end_line")),
                          cell(item.get("parent"))) for item in items)
        blocks.append('<h3>%s（%d 个）</h3><table class="grid"><thead><tr><th>名字</th><th>声明行</th>'
                      '<th>结束行</th><th>父符号</th></tr></thead><tbody>%s</tbody></table>'
                      % (fmt(name), len(items), rows))
    return ('<p class="hint">%s 的符号按 kind 分组，共 %d 个%s。</p>'
            % (fmt(path), len(symbols), "（只看了 %s 这一类）" % fmt(kind) if kind else "")
            + '<details class="facts"><summary>展开符号表</summary>%s</details>' % "".join(blocks))

def _spans(doc, path):
    """doc.facts 里该 path 的 fact:source 区间：(low, high, fact_id)，按行区间升序。"""
    prefix, out = "fact:source:%s:" % path, []
    for fact_id in sorted(doc.get("facts") or {}):
        if fact_id.startswith(prefix):
            try:
                low, high = (int(part) for part in fact_id[len(prefix):].split("-"))
            except ValueError:
                continue
            out.append((low, high, fact_id))
    return sorted(out)

def code(doc, params):
    """摘录块（R446）：只用 doc 内的 fact:source 摘录；没有摘录就明说，绝不读盘、不读 cwd。"""
    path = str(params.get("path") or "")
    start, end = int(params.get("start") or 0), int(params.get("end") or 0)
    row = _row(doc, path)
    head = ('<p class="hint">%s 第 %d–%d 行（文件共 %s 行，解析精度 %s）。</p>'
            % (fmt(path), start, end, cell(row.get("lines")), fmt(row.get("parse"))))
    facts = doc.get("facts") or {}
    spans = [item for item in _spans(doc, path) if item[1] >= start and item[0] <= end]
    if not spans:
        return (head + '<p class="note">事实层没有为 %s 的第 %d–%d 行留摘录；本页只给事实层摘录，'
                       '不读盘，也不假装有全文。</p>' % (fmt(path), start, end))
    low, high, fact_id = spans[0]
    return (head + '<p class="note">本页只给事实层摘录，不读盘：下面是 %s 第 %d–%d 行的原文'
                   '（与请求的 %d–%d 行重叠的第一条 fact:source）。</p><pre class="code">%s</pre>'
            % (fmt(path), low, high, start, end, fmt(facts[fact_id].get("text"))))

def bonus(doc, params):
    """甜头：旧 trace 对账 + 相对链接回 index.html（R315：没有 fact:bonus 就整层不出现）。"""
    fact = (doc.get("facts") or {}).get("fact:bonus")
    if not fact:
        return ""
    counts = [int(value) for value in (fact.get("numbers") or [])][:3] + [0, 0, 0]
    return ('<p class="hint">旧 trace 对账：%d 个模型算子节点、%d 条边、%d 个锚点。</p>'
            '<p><a href="index.html">回旧的 trace 页面（index.html，相对链接，离线可开）</a></p>'
            % (counts[0], counts[1], counts[2]))
