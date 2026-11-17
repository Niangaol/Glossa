"""A6：AI 编排（ai_pipeline）与离线桩（fake_llm）的接线测试。

锁的是派发书 §2 的固定顺序与四道闸：分节 → 逐节写 + 过闸 → 组装；单节失败不整页崩；
体积超限抛 BuildError 而不截断；离线桩只搬素材（0 处未溯源），但故意犯坏 JSON 与编数字时
闸会说话。CLI / MCP 只做一次分派，错误的形状仍是 exit 4 / isError。
"""

import json
import pathlib
import re
import shutil

import pytest

from glossa import cli, cli_explain, facts as facts_mod
from glossa.explain import ai_pipeline, fake_llm, gates, llm_config, prompt
from glossa.mcp import handlers
from papertrace.exceptions import BuildError
from tests._tmp import scratch_dir

FIX = pathlib.Path(__file__).parent / "fixtures" / "repos"
DEVIATION = "本页由离线桩生成，未调用真实模型"
FIG = re.compile(r"<figure.*?</figure>", re.S)
HTTP = re.compile(r'https?://[^"\' >]+')


@pytest.fixture()
def repo():
    """沙箱友好：不用 tmp_path（见 tests/_tmp.py），每个测试一份干净 fixture。"""
    dst = scratch_dir("a6-ai")
    shutil.copytree(FIX / "ts-monorepo", dst, dirs_exist_ok=True)
    return dst


@pytest.fixture()
def doc(repo):
    return facts_mod.build_repo_doc(repo)


def _run(doc, repo, style="magazine", llm=None, **kwargs):
    return ai_pipeline.run_ai(doc, llm or fake_llm.FakeLLM(), style, root=repo, **kwargs)


def _main(html):
    at = html.index("<main")
    return html[html.index(">", at) + 1:html.index("</main>")]


def test_stub_page_has_three_to_five_sections(doc, repo):
    result = _run(doc, repo)
    assert result["mode"] == "ai"
    assert 3 <= len(result["sections"]) <= 5
    assert all(section["title"].strip() for section in result["sections"])


def test_toc_has_exactly_one_entry_per_section(doc, repo):
    result = _run(doc, repo)
    assert result["html"].count('<li><a href="#s-') == len(result["sections"])
    assert result["html"].count('<section class="sec"') == len(result["sections"])


def test_every_section_carries_an_svg_figure(doc, repo):
    html = _run(doc, repo)["html"]
    assert html.count("<svg") == html.count("<figure") > 0


def test_styles_change_css_but_not_the_main_body(doc, repo):
    pages = {style: _run(doc, repo, style)["html"] for style in ("magazine", "report", "cards")}
    bodies = {FIG.sub("", _main(html)) for html in pages.values()}
    assert len(bodies) == 1, "A5 的契约：<main> 里一个字都不许随风格变（图里的取色除外）"
    assert len({html.encode("utf-8") for html in pages.values()}) == 3, "三套 CSS 必须各不相同"


def test_offline_stub_is_declared_in_the_page_header(doc, repo):
    result = _run(doc, repo)
    assert result["deviation"] == DEVIATION
    assert DEVIATION in result["html"]


def test_bad_json_in_one_section_keeps_the_rest_of_the_page(doc, repo):
    result = _run(doc, repo, llm=fake_llm.FakeLLM(bad_json=True))
    assert "这一段生成失败：" in result["html"]
    assert result["sections"][0]["title"] == "这项目是什么"    # 标题留着，只说这一段没写成
    assert len(result["sections"]) >= 3
    assert sum("生成失败" in note for note in result["notes"]) == 1


def test_invented_number_is_marked_and_counted(doc, repo):
    result = _run(doc, repo, llm=fake_llm.FakeLLM(untraced=True))
    assert result["untraced"] >= 1
    assert '<mark class="untraced">8675309</mark>' in result["html"]


def test_well_behaved_stub_leaves_zero_untraced_numbers(doc, repo):
    assert _run(doc, repo)["untraced"] == 0


def test_page_has_no_script_and_no_external_links(doc, repo):
    html = _run(doc, repo, llm=fake_llm.FakeLLM(untraced=True))["html"]
    assert "<script" not in html and "<link" not in html and " src=" not in html
    assert set(HTTP.findall(html)) == {"http://www.w3.org/2000/svg"}


def test_oversize_page_raises_instead_of_truncating(doc, repo, monkeypatch):
    monkeypatch.setattr(gates, "MAX_PAGE_BYTES", 200)
    with pytest.raises(BuildError) as caught:
        _run(doc, repo)
    assert "不截断" in str(caught.value)


def test_empty_ledger_still_builds_a_page_that_explains_itself(repo):
    empty = {"meta": {"repo": {"root_name": "空仓"}}, "totals": {"files": 0},
             "files": [], "facts": {}, "graph": {"nodes": [], "edges": []}}
    result = _run(empty, repo)
    assert len(result["sections"]) == 3 and result["untraced"] == 0
    assert "一条都没搬" in result["html"]


def test_plan_only_cites_fact_ids_that_the_prompt_offered(doc):
    system, user = prompt.build_plan_prompt(doc)
    plan = prompt.parse_plan(fake_llm.FakeLLM().complete(user, system), doc)
    offered = set(re.findall(r"^- (fact:\S+?)：", user, re.M))
    assert plan and offered
    assert all(set(row["facts"]) <= offered for row in plan)


def test_bare_llm_flag_is_not_an_ai_run():
    class Args:
        ai = False
        llm = True

    assert cli_explain.wanted(Args()) is False
    Args.llm = "fake"
    assert cli_explain.wanted(Args()) is True


def test_cli_ai_fake_writes_the_page_and_exits_zero(repo, capsys):
    out = repo / "page"
    code = cli.main(["explain", "--repo", str(repo), "--out", str(out),
                     "--ai", "--llm", "fake", "--style", "report", "--force"])
    printed = capsys.readouterr().out
    assert code == 0
    assert (out / "explain.html").read_text(encoding="utf-8").count("<main") == 1
    assert "节 · 未溯源 0 处" in printed and DEVIATION in printed


def test_cli_ai_without_backend_exits_four(repo, capsys, monkeypatch):
    for pair in llm_config.ENV_PAIRS:
        for name in pair:
            monkeypatch.delenv(name, raising=False)
    code = cli.main(["explain", "--repo", str(repo), "--out", str(repo / "p2"), "--ai"])
    assert code == 4
    assert "模型后端" in capsys.readouterr().out


def test_mcp_mode_ai_returns_the_page(repo):
    result = handlers.call_tool("render_explain",
                                {"repo": str(repo), "mode": "ai", "llm": "fake",
                                 "out": str(repo / "mcp")}, {})
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] is False
    assert payload["mode"] == "ai" and payload["sections"] >= 3
    assert pathlib.Path(payload["out"]).read_text(encoding="utf-8").count("<main") == 1


def test_mcp_mode_ai_without_backend_is_error(repo, monkeypatch):
    for pair in llm_config.ENV_PAIRS:
        for name in pair:
            monkeypatch.delenv(name, raising=False)
    result = handlers.call_tool("render_explain", {"repo": str(repo), "mode": "ai"}, {})
    assert result["isError"] is True
    assert "离线桩" in result["content"][0]["text"]
