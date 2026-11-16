"""文件级组件（4 个）：file_card / symbol_table / code / bonus。

R412-3：每张 file_card 都写出该文件在 keyfiles 里的 reasons；不在清单里就明说，不装。
R316：code 的行区间已由 validate_blocks 卡在 1..行数（越界 BuildError），这里不再静默截断。
R315：bonus 没有 fact:bonus 时返回空串，整层不出现。

code 的原文从磁盘读：doc.meta.repo.url 是相对 cwd 的路径，只读 doc.files 里登记过的相对路径
（.env 这类文件在 scan 阶段就没进 files，天然读不到）。解析不到根目录或读不出来，就退到事实台账
里的 fact:source 摘录，并把「没有原文」写在页面上——绝不假装给了全文。
"""
from __future__ import annotations

import html
import pathlib
import re

from glossa import keyfiles
from glossa.explain.comp_repo import fmt, package_finder
from papertrace.exceptions import BuildError

_CODE_LIMIT = 200
_DRIVE = re.compile(r"^[A-Za-z]:")

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

def _cell(value) -> str:
    return fmt(value) or "—"

def file_card(doc, params):
    """一张卡片：路径 + 明细 + 一句人话（注明来源）+ 为什么讲它（R412-3）。"""
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
        why = "不在 keyfiles 的关键文件清单里（符号与依赖都少），这里只按你指定的路径讲。"
    elif reasons:
        why = "为什么讲它：" + "、".join(fmt(item) for item in reasons) + "。"
    else:
        why = "它进了可讲解清单，但 entry / 被依赖 / 符号三条理由都没命中。"
    return ('<div class="card"><p class="card-path"><code>%s</code></p>%s%s<p class="note">%s</p>'
            '<ul class="plain">%s</ul></div>' % (fmt(path), quote, human, why, cells))

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
                       % (fmt(item.get("name")), _cell(item.get("line")), _cell(item.get("end_line")),
                          _cell(item.get("parent"))) for item in items)
        blocks.append('<h3>%s（%d 个）</h3><table class="grid"><thead><tr><th>名字</th><th>声明行</th>'
                      '<th>结束行</th><th>父符号</th></tr></thead><tbody>%s</tbody></table>'
                      % (fmt(name), len(items), rows))
    return ('<p class="hint">%s 的符号按 kind 分组，共 %d 个%s。</p>'
            % (fmt(path), len(symbols), "（只看了 %s 这一类）" % fmt(kind) if kind else "")
            + '<details class="facts"><summary>展开符号表</summary>%s</details>' % "".join(blocks))

def _repo_root(doc):
    """doc.meta.repo.url 是相对 cwd 的路径；裸目录名 / 绝对路径 / 不存在 → None。"""
    url = str(((doc.get("meta") or {}).get("repo") or {}).get("url") or "").replace("\\", "/")
    if url.startswith(("/", "//")) or _DRIVE.match(url):
        return None
    root = pathlib.Path.cwd() if url in ("", ".", "./") else (pathlib.Path.cwd() / url).resolve()
    return root if root.is_dir() else None

def _source_lines(doc, path):
    """只读 doc.files 里登记过的相对路径；读不到返回 None，由 code 如实说明。"""
    root = _repo_root(doc)
    if root is None or path.startswith("/") or ".." in path.split("/"):
        return None
    try:
        return (root / path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

def code(doc, params):
    """带行号的等宽摘录；单块最多 _CODE_LIMIT 行，超出部分明写「只摘了前 N 行」。"""
    path = str(params.get("path") or "")
    start, end = int(params.get("start") or 0), int(params.get("end") or 0)
    row = _row(doc, path)
    head = ('<p class="hint">%s 第 %d–%d 行（文件共 %s 行，解析精度 %s）。</p>'
            % (fmt(path), start, end, _cell(row.get("lines")), fmt(row.get("parse"))))
    lines = _source_lines(doc, path)
    if lines is None:
        spanned = sorted(fact for fact in doc.get("facts") or {} if fact.startswith("fact:source:%s:" % path))
        return (head + '<p class="note">读不到 %s 的原文（仓库根解析不到，或文件不是合法 UTF-8）；'
                       '这里不假装给了全文。</p>' % fmt(path)
                + ('<p class="note">事实台账里只有这些行区间的摘录：%s。</p>'
                   % "、".join(spanned[:6]) if spanned else ""))
    note = ""
    if len(lines) < end:
        note = ('<p class="note">磁盘上现在只有 %d 行（事实层记的是 %s 行），只摘到能读的部分。</p>'
                % (len(lines), _cell(row.get("lines"))))
        end = len(lines)
    stop = min(end, start - 1 + _CODE_LIMIT)
    picked = lines[start - 1:stop]
    body = "".join('<span class="ln">%5d</span> %s\n' % (start + offset, html.escape(text))
                   for offset, text in enumerate(picked))
    cut = ""
    if stop < end:
        cut = ('<p class="note">这一块只摘了从第 %d 行起的前 %d 行（单块上限 %d 行）；要看更多就再开一块。</p>'
               % (start, len(picked), _CODE_LIMIT))
    return head + '<pre class="code">%s</pre>' % body + note + cut

def bonus(doc, params):
    """甜头：旧 trace 对账 + 相对链接回 index.html（R315：没有 fact:bonus 就整层不出现）。"""
    fact = (doc.get("facts") or {}).get("fact:bonus")
    if not fact:
        return ""
    counts = [int(value) for value in (fact.get("numbers") or [])][:3] + [0, 0, 0]
    return ('<p class="hint">旧 trace 对账：%d 个模型算子节点、%d 条边、%d 个锚点。</p>'
            '<p><a href="index.html">回旧的 trace 页面（index.html，相对链接，离线可开）</a></p>'
            % (counts[0], counts[1], counts[2]))
