"""T9 修复轮（R437–R450）：页面不许编原因、不许读 cwd、不许把两个数相加。"""
import hashlib
import shutil
from pathlib import Path

import pytest

from glossa import facts
from glossa.explain import components, render
from papertrace.exceptions import BuildError
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"


def _doc(name="ts-monorepo", **kw):
    dst = scratch_dir("glossa-t9g-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return facts.build_repo_doc(dst, **kw)


def _one(component, params):
    return components.render_block(_doc(), {"component": component, "params": params})


# ---- R449-T2：超限时不毁旧页（先查后写） ----

def test_write_explain_keeps_old_page_when_rendered_page_is_too_big():
    doc = _doc()
    out = scratch_dir("glossa-t9g-write")
    page, index = out / "explain.html", out / "index.html"
    page.write_text("<p>旧页</p>", encoding="utf-8")
    index.write_text("<p>旧 index</p>", encoding="utf-8")
    before = [hashlib.sha256(item.read_bytes()).hexdigest() for item in (page, index)]
    real = render.HTML_MAX_BYTES
    try:
        render.HTML_MAX_BYTES = 10
        with pytest.raises(BuildError):
            render.write_explain(doc, [{"component": "metrics", "params": {"keys": ["files"]}}], out)
    finally:
        render.HTML_MAX_BYTES = real
    after = [hashlib.sha256(item.read_bytes()).hexdigest() for item in (page, index)]
    assert after == before, "渲染失败不许动旧页（先写后查会把旧页换成半成品）"


# ---- R439：entry_list 按 note 分派，不写死「复合命令」 ----

def test_entry_list_dispatches_on_note_instead_of_guessing():
    doc = _doc()
    doc["entries"] = [{"kind": "npm_script", "name": "start", "command": "node index.js",
                       "target": None, "package": "a", "note": "命令不含文件路径"}]
    html = components.render_block(doc, {"component": "entry_list", "params": {}})
    assert "命令不含文件路径" in html                 # note 就是事实，必须可见
    assert "未解析到单文件目标" in html                # 中性主文案
    assert "复合命令" not in html                     # 不许无条件扣「复合命令」的帽子
    mixed = _one("entry_list", {})
    assert "复合命令未指向单文件" in mixed            # 真复合命令的 note 也要照抄


# ---- R440：没有入口就不许引用 unreachable ----

def test_no_entries_never_claims_unreachable():
    doc = _doc()
    doc["entries"] = []
    doc["graph"]["unreachable"] = ["packages/a/src/circuit.ts"]
    html = components.render_block(doc, {"component": "import_graph", "params": {}})
    assert "没有找到可解析的入口，可达性未计算" in html
    assert "从入口到不了" not in html


# ---- R441：兜底只说「不在清单里」，并给可回查的原因 ----

def test_file_card_fallback_does_not_invent_weak_symbols():
    html = _one("file_card", {"path": "package.json"})
    assert "不在 keyfiles 的可讲解清单里" in html
    assert "语言 json 不参与符号抽取" in html
    assert "符号与依赖都少" not in html and "都少" not in html


# ---- R443：degraded 逐条显示并注明程序事实 ----

def test_file_card_shows_degraded_reasons_as_program_facts():
    doc = _doc("py-broken")
    html = components.render_block(doc, {"component": "file_card", "params": {"path": "bad.py"}})
    assert "程序事实" in html
    assert "SyntaxError: invalid syntax (line 1)" in html


# ---- R444/R445：简介不否定仓库有 README；空值给显式 fallback ----

def test_overview_does_not_deny_readme_and_fills_fallbacks():
    doc = _doc("py-mini")
    html = components.render_block(doc, {"component": "overview", "params": {}})
    assert "事实层没有提供 README 正文；简介取的是模块 docstring（pkg/__init__.py 第 1 行）" in html
    assert "仓里没有" not in html and "既没有 README" not in html
    empty = components.render_block({}, {"component": "overview", "params": {}})
    for want in ("仓库：未登记", "路径：未登记", "commit：未登记", "主语言：未识别",
                 "生成于：未知", "工具：未登记"):
        assert want in empty, want
    assert "没有可用的项目简介" in empty


# ---- R446：code 不读 cwd，换 cwd 字节相同 ----

def test_code_block_is_identical_after_changing_cwd(monkeypatch):
    doc = _doc()
    blocks = [{"component": "code",
               "params": {"path": "packages/a/src/circuit.ts", "start": 1, "end": 3}}]
    before, _ = render.render_explain(doc, blocks)
    monkeypatch.chdir(scratch_dir("glossa-t9g-cwd"))
    after, _ = render.render_explain(doc, blocks)
    assert before == after, "换 cwd 后页面必须字节相同（code 只许用 doc 内的 fact:source）"
    assert "本页只给事实层摘录" in before


# ---- R447：project 级 hint 说 ProjectReference ----

def test_project_graph_hint_talks_about_project_reference():
    html = components.render_block(_doc("cs-solution"),
                                   {"component": "import_graph", "params": {}})
    assert "依赖图（project 级）" in html
    assert "箭头=谁引用谁（ProjectReference）" in html
    assert "谁 import 谁" not in html


# ---- R437：M 个清单文件由页面按 lang 现算 ----

def test_isolated_sentence_counts_manifests_by_language():
    doc = _doc()
    html = components.render_block(doc, {"component": "import_graph", "params": {}})
    assert doc["graph"]["omitted_isolated"] == 5
    assert "5 个文件没有进入关系图，其中 3 个是清单、文档等不产生 import 的文件" in html


# ---- R449-T3：孤立数与截断数分两句，禁止相加 ----

def _c5_repo():
    root = scratch_dir("glossa-t9g-c5")
    (root / "chain").mkdir()
    (root / "iso").mkdir()
    for i in range(1, 131):
        text = "export const x%d = %d;\n" % (i, i)
        if i < 130:
            text = 'import { x } from "./f%03d";\n' % (i + 1) + text
        (root / "chain" / ("f%03d.ts" % i)).write_text(text, encoding="utf-8")
    for i in range(1, 6):
        (root / "iso" / ("i%03d.ts" % i)).write_text("export const i%d = %d;\n" % (i, i), encoding="utf-8")
    (root / "package.json").write_text('{"name": "c5", "version": "1.0.0"}\n', encoding="utf-8")
    return facts.build_repo_doc(root)


def test_isolated_and_truncated_counts_are_two_sentences():
    doc = _c5_repo()
    graph = doc["graph"]
    assert (len(doc["files"]), graph["omitted_isolated"], graph["truncated_nodes"]) == (136, 6, 10)
    html = components.render_block(doc, {"component": "import_graph", "params": {}})
    assert ("6 个文件没有进入关系图，其中 1 个是清单、文档等不产生 import 的文件"
            "（未画进图是计数，不是丢了）。") in html
    # R458：断言绑完整句 + 反例数字。裸子串 "6 个…" 会被 "16 个…" 包含，M11 抓不住
    assert "16 个文件没有进入关系图" not in html, "孤立数 + 截断数的合并句不许出现"
    assert "图已截断，只画了前 120 个节点；另有 10 个节点没有画" in html
    assert html.count("没有进入关系图") == 1 and html.count("图已截断") == 1
    assert "126 个文件" not in html, "6 个孤立 + 120 个画出的合并数不许出现"
    assert "没有找到可解析的入口，可达性未计算" in html


# ---- R449-T4：数字断言绑到它的键上，不用裸子串 ----

def test_metrics_values_are_bound_to_their_key():
    doc = _doc()
    html = components.render_block(doc, {"component": "metrics",
                                         "params": {"keys": ["files", "packages"]}})
    assert '<span class="k">files</span><span class="v">13</span>' in html
    assert '<span class="k">packages</span><span class="v">3</span>' in html
    assert '<span class="k">packages</span><span class="v">13</span>' not in html
