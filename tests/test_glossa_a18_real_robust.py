"""R521/R522：真模型第一轮实测暴露的两件事（StepPlan step-5-preview）。

一轮真实运行 exit 0、页头写「失败 5 节」，5 节全是「这一段生成失败：未知的图范式 None」——
模型给了 figures 却没写 pattern，而一张图不合规把整节正文一起判死了。另一节返回的 JSON 被截断，
parse_section 直接判死，没有第二次机会。
"""

import json
import pathlib
import shutil

import pytest

from glossa import facts as facts_mod
from glossa.explain import ai_pipeline, fake_llm
from tests._tmp import scratch_dir

FIX = pathlib.Path(__file__).parent / "fixtures" / "repos"


@pytest.fixture()
def repo():
    dst = scratch_dir("a18-robust")
    shutil.copytree(FIX / "ts-monorepo", dst, dirs_exist_ok=True)
    return dst


@pytest.fixture()
def doc(repo):
    return facts_mod.build_repo_doc(repo)


class Scripted(fake_llm.FakeLLM):
    """分节走离线桩，写节按脚本回包（脚本用完退回桩）。"""

    def __init__(self, responses=()):
        super().__init__()
        self.responses = list(responses)
        self.section_calls = 0

    def complete(self, prompt, system=""):
        if "这一节的素材包" in str(prompt):
            self.section_calls += 1
            if self.responses:
                return self.responses.pop(0)
        return super().complete(prompt, system)


def _section(figures=(), html="<p>正文</p>"):
    return json.dumps({"title": "规模", "html": html, "figures": list(figures), "notes": []},
                      ensure_ascii=False)


def test_a_figure_without_a_pattern_does_not_kill_the_prose(doc, repo):
    llm = Scripted([_section([{"caption": "没有范式的图", "nodes": []}])])
    result = ai_pipeline.run_ai(doc, llm, "magazine", root=repo)
    first = result["sections"][0]
    assert "正文" in first["html"] and "生成失败" not in first["html"]
    assert first["figures"] == []
    assert any("一张图被丢弃" in note for note in result["notes"]), result["notes"]
    assert result["failed"] == 0


def test_a_broken_json_answer_gets_one_retry(doc, repo):
    llm = Scripted(['{"title": "被截断的返回', _section()])
    result = ai_pipeline.run_ai(doc, llm, "magazine", root=repo)
    assert llm.section_calls >= 2
    assert "正文" in result["sections"][0]["html"]
    assert result["failed"] == 0


def test_a_second_broken_json_answer_fails_that_section_only(doc, repo):
    llm = Scripted(['{"title": "还是坏的', '{"title": "又坏了'])
    result = ai_pipeline.run_ai(doc, llm, "magazine", root=repo)
    first = result["sections"][0]["html"]
    assert "这一段生成失败" in first and "正文" not in first
    assert result["failed"] >= 1
    assert llm.section_calls >= 2


def test_all_sections_failing_raises_instead_of_writing_a_useless_page(doc, repo):
    from papertrace.exceptions import BuildError
    llm = Scripted(["{"] * 12)
    with pytest.raises(BuildError, match="全部失败"):
        ai_pipeline.run_ai(doc, llm, "magazine", root=repo)


def test_the_prompt_states_the_figure_shape(doc, repo):
    from glossa.explain import prompt
    assert "pattern" in prompt.SYSTEM and "figures: []" in prompt.SYSTEM
