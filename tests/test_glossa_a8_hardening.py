"""A8：把 AIF 评审的 1 Critical + 5 Important 钉死在测试里（R505-R510）。

每条盯一个变异：外链 img 丢弃并披露、AI 剥内联 style、空集不放行、图节点 label 人话且可溯源、
页头恒写未溯源/失败计数、--llm 与 MCP mode 取值校验、sanitizer 禁标签与 R307 披露、连线闸在跑。
"""

import json
import pathlib
import re
import shutil

import pytest

from glossa import cli
from glossa.explain import ai_pipeline, fake_llm, gates, guard
from glossa.mcp import handlers
from tests._tmp import scratch_dir

FIX = pathlib.Path(__file__).parent / "fixtures" / "repos"
HTTP = re.compile(r'https?://[^"\' >]+')
SVG_TEXT = re.compile(r"<text[^>]*>([^<]*)</text>")


@pytest.fixture()
def repo():
    dst = scratch_dir("a8-hard")
    shutil.copytree(FIX / "ts-monorepo", dst, dirs_exist_ok=True)
    return dst


@pytest.fixture()
def doc(repo):
    from glossa import facts as facts_mod
    return facts_mod.build_repo_doc(repo)


class PlanLLM(fake_llm.FakeLLM):
    """真实协议形状的坏模型：第一节吐指定的 html/figures，其余节只写一句正文。"""
    def __init__(self, html="<p>正文</p>", figures=(), **kwargs):
        super().__init__(**kwargs)
        self.html, self.figures = html, list(figures)
    def complete(self, prompt, system=""):
        if "这一节的素材包" in str(prompt):
            self.sections += 1
            pack = fake_llm._load(prompt)
            return json.dumps({"title": str((pack.get("section") or {}).get("title") or ""),
                               "html": self.html if self.sections == 1 else "<p>正文</p>",
                               "figures": self.figures if self.sections == 1 else [],
                               "notes": []}, ensure_ascii=False)
        return super().complete(prompt, system)


def _run(doc, repo, llm=None):
    return ai_pipeline.run_ai(doc, llm or fake_llm.FakeLLM(), "magazine", root=repo)


def _main(html):
    at = html.index("<main")
    return html[html.index(">", at) + 1:html.index("</main>")]


def _pack(**extra):
    return {"repo": {"root_name": "r"},
            "section": {"title": "从哪儿读起", "goal": "只讲素材里查得到的事"},
            "facts": [{"id": "fact:file:a.py", "text": "a.py 是入口文件", "numbers": []}],
            "sources": [{"path": "a.py", "text": "print(1)"}], **extra}

# R505：外链图片一个都不许上页，丢了必须有话说
def test_external_img_is_dropped_and_disclosed(doc, repo):
    llm = PlanLLM('<p>看图 <img src="https://evil.example/x.png" alt="x">。</p>')
    result = _run(doc, repo, llm)
    assert "evil.example" not in result["html"]
    assert " src=" not in _main(result["html"])
    assert any("img" in note for note in result["notes"]), result["notes"]
    assert set(HTTP.findall(result["html"])) <= {"http://www.w3.org/2000/svg"}


def test_only_data_image_sources_survive():
    clean, removed, notes = guard.sanitize_html(
        '<img src="x.png"><img src="data:text/html;base64,AA"><img src="data:image/png;base64,AA">')
    assert "x.png" not in clean and "data:text" not in clean
    assert 'src="data:image/png;base64,AA"' in clean
    assert removed == 2 and all("img" in note for note in notes), notes


# R506：AI 模式剥内联 style，程序版（R420 冻结约定）保留
def test_ai_mode_strips_inline_style_but_program_mode_keeps_it():
    html = '<div style="position:fixed;inset:0;background:#fff">遮罩</div>'
    clean, notes = gates.gate_html(html, strip_style=True)
    assert "style=" not in clean and "遮罩" in clean
    assert any("style" in note for note in notes), notes
    kept, _dropped = gates.gate_html(html)
    assert 'style="position:fixed;inset:0;background:#fff"' in kept


def test_pipeline_strips_the_full_screen_overlay(doc, repo):
    result = _run(doc, repo, PlanLLM('<div style="position:fixed;inset:0">正文</div>'))
    main = _main(result["html"])
    assert "position:fixed" not in main and "正文" in main


# R507：空集在 AI 版意味着「一个数字都不可溯源」，不是放行
def test_empty_allowed_set_marks_every_number_in_ai_mode():
    marked, count = gates.gate_numbers("<p>共 8675309 个。</p>", set())
    assert count == 1 and '<mark class="untraced">8675309</mark>' in marked
    kept, zero = gates.gate_numbers("<p>共 8675309 个。</p>", set(), program=True)
    assert (kept, zero) == ("<p>共 8675309 个。</p>", 0)


def test_empty_pack_no_longer_lets_a_number_slip_through(repo):
    empty = {"meta": {"repo": {"root_name": "空仓"}}, "totals": {}, "files": [],
             "facts": {}, "graph": {}}
    result = ai_pipeline.run_ai(empty, PlanLLM("<p>共 8675309 个。</p>"), "magazine", root=repo)
    assert result["untraced"] == 1
    assert '<mark class="untraced">8675309</mark>' in result["html"]


# R508：节点 label 必须是人话，且在这一节素材里查得到；查不到整张图丢弃
def test_figure_node_label_must_be_findable_in_the_pack():
    bad = {"pattern": "cards", "caption": "编的图",
           "nodes": [{"id": "fact:invented:node", "label": "编出来的节点"}]}
    clean, notes = gates.gate_labels(bad, _pack())
    assert clean is None and any("丢" in note for note in notes), notes
    ok = {"pattern": "cards", "caption": "文件图鉴",
          "nodes": [{"id": "fact:file:a.py", "label": "a.py"}]}
    clean2, notes2 = gates.gate_labels(ok, _pack())
    assert clean2 is not None and notes2 == []
    cards = fake_llm._figure([{"id": "fact:file:a.py", "text": "a.py 是入口文件",
                               "numbers": [], "edges": []}])
    assert cards["nodes"] == [{"id": "fact:file:a.py", "label": "a.py 是入口文件"}]


def test_pipeline_drops_the_whole_figure_when_a_node_is_invented(doc, repo):
    fig = {"pattern": "cards", "caption": "编的图",
           "nodes": [{"id": "fact:invented:node", "label": "编出来的节点"}]}
    result = _run(doc, repo, PlanLLM("<p>正文</p>", [fig]))
    assert "编出来的节点" not in result["html"]
    assert any("整张图已丢弃" in note for note in result["notes"]), result["notes"]


def test_offline_stub_labels_are_readable_names(doc, repo):
    labels = SVG_TEXT.findall(_run(doc, repo)["html"])
    assert labels and not any("fact:" in label for label in labels), labels


# R509：页头恒写「未溯源 N 处 · 失败 M 节」，0 也写
def test_page_header_always_shows_untraced_and_failed_counts(doc, repo):
    assert "未溯源 0 处 · 失败 0 节" in _run(doc, repo)["html"]
    marked = _run(doc, repo, fake_llm.FakeLLM(untraced=True))["html"]
    assert "未溯源 1 处 · 失败 0 节" in marked
    broken = _run(doc, repo, fake_llm.FakeLLM(bad_json=True))["html"]
    assert "失败 1 节" in broken

# R510：取值必须校验，不许静默降级
def test_unknown_llm_value_is_rejected_by_argparse(repo):
    with pytest.raises(SystemExit) as caught:
        cli.main(["explain", "--repo", str(repo), "--out", str(repo / "o"),
                  "--llm", "bogus"])
    assert caught.value.code == 2


def test_ai_with_a_bare_or_offline_llm_flag_is_a_loud_error(repo, capsys):
    assert cli.main(["explain", "--repo", str(repo), "--out", str(repo / "o2"),
                     "--ai", "--llm"]) == 2
    assert "--ai" in capsys.readouterr().out
    assert cli.main(["explain", "--repo", str(repo), "--out", str(repo / "o3"),
                     "--ai", "--llm", "offline"]) == 2
    text = capsys.readouterr().out
    assert "offline" in text
    # D7：原来这句把 offline 同时说成「不接受」和「可接受」，还让人猜该用哪个
    assert "--llm fake" in text and "offline 不是它" in text


def test_ollama_is_recognised_but_reported_unimplemented(repo, capsys):
    assert cli.main(["explain", "--repo", str(repo), "--out", str(repo / "o4"),
                     "--llm", "ollama"]) == 4
    assert "ollama" in capsys.readouterr().out


def test_mcp_mode_is_whitelisted(repo):
    for mode in ("AI", "bogus"):
        result = handlers.call_tool("render_explain",
                                    {"repo": str(repo), "mode": mode}, {})
        assert result["isError"] is True
        text = result["content"][0]["text"]
        assert "program" in text and '"ai"' in text and mode in text, text


# 评审 Q8 的 M10/M11/M6：sanitizer 的禁标签与披露、连线闸
def test_forbidden_tags_are_removed_with_an_r307_disclosure():
    clean, notes = gates.gate_html('<p>ok</p><script>alert(1)</script><style>x{}</style>')
    assert "<script" not in clean and "<style" not in clean and "alert(1)" not in clean
    assert any("R307" in note for note in notes), notes


def test_edge_without_a_source_is_dropped_in_the_pipeline(doc, repo):
    label = doc["meta"]["repo"]["root_name"]
    fig = {"pattern": "layered", "caption": "编的连线",
           "nodes": [{"id": "a", "label": label}, {"id": "b", "label": label}],
           "edges": [{"from": "a", "to": "b", "fact": "fact:invented:edge"}]}
    result = _run(doc, repo, PlanLLM("<p>正文</p>", [fig]))
    assert result["sections"][0]["figures"][0]["edges"] == []
    assert any("已丢弃" in note for note in result["notes"]), result["notes"]
