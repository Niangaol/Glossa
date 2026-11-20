"""整页渲染（T9）：14 个组件自由组合 → 单文件离线 HTML（人话优先）。

R317：零外链、零 <script>、样式全内联；SVG 的 xmlns 是唯一允许出现的 http 串；超
HTML_MAX_BYTES（模块级常量，可被 monkeypatch）抛 BuildError，且在写盘之前就抛，不删旧页。
R318：页顶三件事——标题「笺疏 · <root_name>」、模式徽章、「本页有 N 处数字未溯源」（N=0 也显示）。
R319：同一 doc + 同一 blocks 渲染两次逐字节相同：时间只取 doc.meta.created_at，渲染过程不取
当前时间，组件内部按 id / path 排序，不遍历无序集合。
R412：每块一个 <section>（空串块不生成）；第一个 file_card 的 section 顶部写「共 N 个可讲解
文件，本页逐个讲了 M 个」+ 挑选规则；页脚两句固定披露在模板里。
A1：fallback=True 时页头多渲染一条红条「本页未使用 AI（仅事实底稿）…」；model 模式
的页面永远不带这条红条（模型页声称「没用 AI」是自相矛盾），条件写在模板里，不做
渲染后拼接。

report 的两个数字与页面同源：untraced 数页面上的黄标，removed 读自定义块顶部的 data-removed。
"""
from __future__ import annotations

import pathlib
import re

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from glossa import keyfiles
from glossa.explain import components
from papertrace.api import HTML_MAX_BYTES
from papertrace.api import BuildError

_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates"
_TEMPLATE = "glossa.html.j2"
_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)),
                   autoescape=select_autoescape(enabled_extensions=("html", "htm", "j2")),
                   undefined=StrictUndefined)
_REMOVED = re.compile(r'^<div class="custom" data-removed="(\d+)"')

def _sections(doc, blocks):
    """渲染每一块，空串块整层不出现（R315）；标题由注册表 + block.section 决定。"""
    out = []
    for block in blocks:
        spec = components.COMPONENTS[block.get("component")]
        html = components.render_block(doc, block)
        if not html.strip():
            continue
        found = _REMOVED.match(html)
        removed = int(found.group(1)) if found else 0
        if removed:      # 补在标记之后：这句话里的 N 是程序数的，不该被当成未溯源数字
            html = '<p class="removed">本块已移除 %d 处不允许的构造</p>%s' % (removed, html)
        out.append({"component": spec["name"], "title": components.block_title(block, spec),
                    "html": html, "removed": removed})
    return out

def _file_card_header(doc, sections):
    """R412-3/R442：第一个 file_card 的 section 顶部写清「共 N 个，讲了 M 个」+ 挑选规则。

    N 恒等于 len(keyfiles.candidate_files(doc))（不是 len(doc["files"])）；候选为 0 而调用方
    显式指定了 file_card 时改写成「清单为空；只按你指定的路径讲了 M 个」，不写 0 讲了 1 的矛盾。
    """
    cards = [item for item in sections if item["component"] == "file_card"]
    if not cards:
        return
    candidates = len(keyfiles.candidate_files(doc))
    if candidates:
        scope = ('<p class="scope">共 %d 个可讲解文件，本页逐个讲了 %d 个。'
                 '挑选规则：入口目标优先 → 被依赖边数 → 符号数 → path 升序。</p>' % (candidates, len(cards)))
    else:
        scope = ('<p class="scope">可讲解文件清单为空；本页只按你指定的路径讲了 %d 个。</p>' % len(cards))
    cards[0]["html"] = scope + cards[0]["html"]

def _badge(mode, model_name):
    if mode == "model":
        return "模型：%s" % (model_name or "未指明")
    if mode == "program":
        return "本页由程序生成，未使用模型"
    raise BuildError("mode 只能是 program 或 model，收到 %r" % (mode,))

def _fallback(mode, fallback):
    """A1：红条只属于程序版页面——模型写的页面说「未使用 AI」是自相矛盾，开关一律无效。"""
    return bool(fallback) and mode != "model"


def render_explain(doc, blocks, *, mode="program", model_name=None, rescanned=False,
                   fallback=False):
    """渲染整页，返回 (html, report)；report 键：untraced / removed / notes / bytes / blocks。

    R487/R496：rescanned=True 时模板在页脚多渲染一句「本页数据来自本次重扫」（条件在模板里，
    不做渲染后拼接）；只这一句随参数变，其余字节不受影响。
    A1：fallback=True 给程序版事实页加页头红条；model 模式一律不认这个开关（见 _fallback）。
    """
    blocks = list(blocks or [])
    components.validate_blocks(doc, blocks)
    sections = _sections(doc, blocks)
    _file_card_header(doc, sections)
    untraced = sum(section["html"].count(components.UNTRACED_MARK) for section in sections)
    removed = sum(section["removed"] for section in sections)
    meta = doc.get("meta") or {}
    repo, tool = meta.get("repo") or {}, meta.get("tool") or {}
    html = _ENV.get_template(_TEMPLATE).render(
        title="笺疏 · %s" % (repo.get("root_name") or "未命名仓库"), badge=_badge(mode, model_name),
        mode=mode, untraced=untraced, sections=sections, repo_url=repo.get("url") or "未登记",
        commit=repo.get("commit") or "unknown", language=repo.get("language") or "未识别",
        created_at=meta.get("created_at") or "未登记", tool_name=tool.get("name") or "glossa",
        tool_version=tool.get("version") or "", rescanned=bool(rescanned),
        fallback=_fallback(mode, fallback))
    size = len(html.encode("utf-8"))
    if size > HTML_MAX_BYTES:      # 运行时读模块全局：rmod.HTML_MAX_BYTES 的 monkeypatch 才生效
        raise BuildError("解释页 %d 字节，超过单文件上限 %d 字节（R317：不截断，也不删旧页）"
                         % (size, HTML_MAX_BYTES))
    notes = []
    if untraced:
        notes.append("有 %d 处数字没有出处，已用 mark.untraced 标出（宽松但可见）" % untraced)
    if removed:
        notes.append("自定义块里移除了 %d 处不允许的构造（R307：剥掉并明示）" % removed)
    report = {"untraced": untraced, "removed": removed, "notes": notes, "bytes": size,
              "blocks": len(sections)}
    return html, report

def write_explain(doc, blocks, out_dir, *, mode="program", model_name=None, rescanned=False,
                  fallback=False):
    """写 <out_dir>/explain.html，每次覆盖（R74 同尺，不受 --force 约束）。"""
    html, _report = render_explain(doc, blocks, mode=mode, model_name=model_name,
                                   rescanned=rescanned, fallback=fallback)
    target = pathlib.Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / "explain.html"
    path.write_text(html, encoding="utf-8", newline="\n")
    return path
