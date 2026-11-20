"""T9：整页渲染。单文件离线、零外链、可复现。"""
from tests.common import FIXTURES
import re
import shutil
from pathlib import Path

import pytest

from glossa import facts
from glossa.explain import render
from papertrace.exceptions import BuildError
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"


def _doc(name='ts-monorepo', **kw):
    dst = scratch_dir("glossa-t9r-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return facts.build_repo_doc(dst, **kw)


def _blocks():
    return [{"component": "overview", "params": {}},
            {"component": "metrics", "params": {"keys": ["files", "packages"]}},
            {"component": "entry_list", "params": {}},
            {"component": "import_graph", "params": {}},
            {"component": "text", "params": {"text": "共 13 个文件。"},
             "cites": ["fact:totals"]},
            {"component": "file_card",
             "params": {"path": "packages/a/src/server.ts"}}]


def test_render_is_single_file_offline_with_no_absolute_paths():
    doc = _doc()
    html, report = render.render_explain(doc, _blocks())
    assert "<script" not in html.lower()
    # 唯一允许的 http 串是 SVG 命名空间（R317）
    stripped = html.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "http://" not in stripped and "https://" not in stripped
    assert 'src="//' not in stripped and 'href="//' not in stripped
    assert "D:\\" not in html and "/Users/" not in html
    assert report["bytes"] == len(html.encode("utf-8"))
    assert report["blocks"] == 6
    # R412：固定披露必须静态可见（R349 / R388 / C5）
    assert "符号链接内容未计入" in html
    assert "只按 listing 计数" in html
    assert "未画进图" in html


def test_empty_string_blocks_leave_no_section_layer():
    doc = _doc()
    blocks = _blocks() + [{"component": "bonus", "params": {}}]
    html, report = render.render_explain(doc, blocks)
    assert html.count("<section") == 6      # bonus 返回空串，整层不出现
    assert 'data-component="bonus"' not in html
    assert report["blocks"] == 6            # 只数真渲染出来的块
    # C# 仓库没有 packages → package_map 也必须整层不出现
    cs = _doc("cs-solution")
    html2, _ = render.render_explain(cs, [{"component": "package_map",
                                           "params": {}}])
    assert html2.count("<section") == 0


def test_page_header_shows_mode_and_untraced_count():
    doc = _doc()
    html, report = render.render_explain(doc, _blocks(), mode='program')
    assert "笺疏 · " + doc["meta"]["repo"]["root_name"] in html   # R387：root_name = 传入 root 的目录名
    assert "本页由程序生成，未使用模型" in html
    assert "本页有 0 处数字未溯源" in html
    html2, _ = render.render_explain(doc, _blocks(), mode='model',
                                     model_name='deepseek-chat')
    assert "模型：deepseek-chat" in html2


def test_program_blocks_have_zero_untraced():
    doc = _doc()
    _, report = render.render_explain(doc, _blocks())
    assert report["untraced"] == 0


def test_model_text_untraced_is_counted_and_shown():
    doc = _doc()
    blocks = _blocks() + [{"component": "text",
                           "params": {"text": "另有 999 个不明文件"},
                           "cites": ["fact:totals"]}]
    html, report = render.render_explain(doc, blocks, mode='model',
                                         model_name='m')
    assert report["untraced"] == 1
    assert "本页有 1 处数字未溯源" in html
    assert '<mark class="untraced">999</mark>' in html


def test_custom_block_removals_are_reported_and_shown():
    doc = _doc()
    blocks = [{"component": "custom",
               "params": {"html": '<div onclick="x()">你好<script>b()</script></div>'}}]
    html, report = render.render_explain(doc, blocks)
    assert report["removed"] == 2
    assert "本块已移除 2 处不允许的构造" in html
    assert "你好" in html and "<script" not in html.lower()


def test_render_is_deterministic_and_size_guard_raises():
    doc = _doc()
    a, _ = render.render_explain(doc, _blocks())
    b, _ = render.render_explain(doc, _blocks())
    assert a == b
    import glossa.explain.render as rmod
    real = rmod.HTML_MAX_BYTES
    try:
        rmod.HTML_MAX_BYTES = 10
        with pytest.raises(BuildError):
            render.render_explain(doc, _blocks())
    finally:
        rmod.HTML_MAX_BYTES = real


# ---- R449-T1：Jinja autoescape 不能关 ----

def test_autoescape_escapes_injected_markup_from_meta():
    doc = _doc()
    doc["meta"]["repo"]["root_name"] = '<script>alert("root")</script>'
    html, report = render.render_explain(doc, _blocks())
    assert "<script" not in html.lower()
    assert "&lt;script&gt;alert" in html
    assert report["blocks"] == 6


# ---- R449-T5 / R442：头行 N = keyfiles.candidate_files(doc) ----

def test_file_card_header_counts_candidates_not_all_files():
    from glossa import keyfiles
    doc = _doc()
    html, _ = render.render_explain(doc, _blocks())
    match = re.search(r"共 (\d+) 个可讲解文件，本页逐个讲了 (\d+) 个", html)
    assert match, html[:200]
    assert int(match.group(1)) == len(keyfiles.candidate_files(doc)) == 10
    assert int(match.group(2)) == 1
    assert "共 13 个可讲解文件" not in html          # 13 是 len(doc.files)，不许冒充候选数


def test_file_card_header_when_candidate_list_is_empty():
    from glossa import keyfiles
    root = scratch_dir("glossa-t9r-none")
    (root / "package.json").write_text('{"name": "n", "version": "1.0.0"}\n', encoding="utf-8")
    (root / "README.md").write_text("# n\n\n说明。\n", encoding="utf-8")
    doc = facts.build_repo_doc(root)
    assert keyfiles.candidate_files(doc) == []
    html, _ = render.render_explain(doc, [{"component": "file_card",
                                           "params": {"path": "package.json"}}])
    assert "可讲解文件清单为空；本页只按你指定的路径讲了 1 个。" in html
    assert "共 0 个可讲解文件" not in html


_TS = {"web/a.ts": 'import { b } from "./b";\n', "web/b.ts": "export const b = 2;\n"}


def _mixed(name, csproj):
    """R479 夹具：混合仓 = csproj 项目引用 + .ts 文件级 import（项目边条数随夹具变）。"""
    root = scratch_dir("glossa-r479-" + name)
    for rel, body in dict(_TS, **csproj).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return facts.build_repo_doc(root)


def _import_graph(doc):
    return render.render_explain(doc, [{"component": "import_graph", "params": {}}],
                                 mode="program")


def test_mixed_repo_page_discloses_the_project_edges_it_did_not_draw():
    """R479：文件级图不许对「谁引用谁」一字不提；句子里的数与名字都来自 doc。"""
    one = {"src/App/App.csproj": '<Project><ItemGroup>'
                                 '<ProjectReference Include="..\\Core\\Core.csproj" />'
                                 "</ItemGroup></Project>",
           "src/Core/Core.csproj": "<Project />"}
    html, report = _import_graph(_mixed("page-one", one))
    assert "另有 1 条项目引用（ProjectReference），本图只画文件级 import：App → Core" in html
    assert "没有项目引用" not in html
    assert report["untraced"] == 0
    # 句子里的数必须来自 doc：两条项目边的仓要写 2（写死 1 的话这里就红）
    two = {"src/A/A.csproj": '<Project><ItemGroup>'
                             '<ProjectReference Include="..\\B\\B.csproj" />'
                             '<ProjectReference Include="..\\C\\C.csproj" />'
                             "</ItemGroup></Project>",
           "src/B/B.csproj": "<Project />", "src/C/C.csproj": "<Project />"}
    html2, _ = _import_graph(_mixed("page-two", two))
    assert "另有 2 条项目引用（ProjectReference）" in html2
    assert "另有 1 条项目引用" not in html2
    # project 级（cs-solution）：图本身就是项目图，这句整句不写
    assert "另有" not in _import_graph(_doc("cs-solution"))[0]
