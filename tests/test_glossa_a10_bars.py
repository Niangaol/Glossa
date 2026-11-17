"""A10（R513）：离线桩在该节素材凑够三组「人话标签 + 真数字」时画真条形图。

盯四件事：第一张图变成 bars；<rect> 条数 == 数据条数；每个值都能在这一节素材包里查到
（且只取自 facts[].numbers）；素材不够三组就原样退回 layered / cards，不崩、不空图。
"""

import json
import pathlib
import re
import shutil

import pytest

from glossa import facts as facts_mod
from glossa.explain import ai_pipeline, fake_llm, pack as pack_mod, prompt
from tests._tmp import scratch_dir

FIX = pathlib.Path(__file__).parent / "fixtures" / "repos"
BARS = re.compile(r'<figure class="fig" data-pattern="bars".*?</figure>', re.S)
PATTERN = re.compile(r'data-pattern="([a-z]+)"')
RECT = re.compile(r"<rect ")
VAL_TEXT = re.compile(r"<text[^>]*>([^<>]*)</text>")

TS_MONO = [
    {"id": "fact:totals", "text": "全仓 13 个文件（json 3、typescript 9、vue 1）、10 个符号、"
     "9 条 import、3 个包、0 个项目、3 个入口；依赖图 6 条边、0 个环、2 个不可达文件。",
     "numbers": [0, 1, 2, 3, 6, 9, 10, 13], "edges": []},
    {"id": "fact:files", "text": "共保留 13 个文件，合计 54 行、1467 字节、10 个符号。",
     "numbers": [10, 13, 54, 1467], "edges": []},
]


@pytest.fixture()
def repo():
    dst = scratch_dir("a10-bars")
    shutil.copytree(FIX / "ts-monorepo", dst, dirs_exist_ok=True)
    return dst


@pytest.fixture()
def doc(repo):
    return facts_mod.build_repo_doc(repo)


def _first_pack(doc, repo):
    """跑一遍分节，把第 1 节的素材包原样拿到手（桩看到的就这一份）。"""
    system, user = prompt.build_plan_prompt(doc)
    plan = prompt.parse_plan(fake_llm.FakeLLM().complete(user, system), doc)
    return plan, pack_mod.build_pack(doc, dict(plan[0], index=1), repo)


# R513：三组以上「人话标签 + 真数字」→ 第一张图画 bars
def test_stub_draws_a_bar_chart_for_the_first_section(doc, repo):
    rows = fake_llm._bar_rows(fake_llm._safe(_first_pack(doc, repo)[1]))
    assert len(rows) >= 3, rows
    result = ai_pipeline.run_ai(doc, fake_llm.FakeLLM(), "magazine", root=repo)
    first = result["sections"][0]["figures"][0]
    assert first["pattern"] == "bars"
    assert first["bars"] == rows
    assert result["untraced"] == 0 and result["failed"] == 0


def test_bar_chart_carries_one_rect_per_row(doc, repo):
    rows = fake_llm._bar_rows(fake_llm._safe(_first_pack(doc, repo)[1]))
    page = ai_pipeline.run_ai(doc, fake_llm.FakeLLM(), "magazine", root=repo)["html"]
    figure = BARS.search(page)
    assert figure is not None, PATTERN.findall(page)
    assert len(RECT.findall(figure.group(0))) == len(rows)
    texts = VAL_TEXT.findall(figure.group(0))
    assert all(str(row["value"]) in texts for row in rows), texts


def test_every_bar_value_is_in_the_section_pack(doc, repo):
    rows = fake_llm._bar_rows(fake_llm._safe(_first_pack(doc, repo)[1]))
    text = json.dumps(_first_pack(doc, repo)[1], ensure_ascii=False)
    assert rows and all(str(row["value"]) in text for row in rows), rows


def test_bar_labels_are_human_words_never_fact_ids(doc, repo):
    rows = fake_llm._bar_rows(fake_llm._safe(_first_pack(doc, repo)[1]))
    assert all(row["label"] and not row["label"].startswith("fact:") for row in rows), rows
    assert all(isinstance(row["value"], int) and row["value"] > 0 for row in rows), rows


def test_bar_values_were_not_invented_by_the_stub():
    """文字里写 5、台账只记 7：这条不算「真数字」，条上不许出现 5。"""
    facts = [{"id": "fact:x", "text": "共 5 个文件、7 个符号、9 个包。",
              "numbers": [7, 9], "edges": []}]
    rows = fake_llm._bar_rows(facts)
    assert [row["value"] for row in rows] == []
    ok = [{"id": "fact:x", "text": "共 7 个文件、9 个符号、11 个包。",
           "numbers": [7, 9, 11], "edges": []}]
    assert [row["value"] for row in fake_llm._bar_rows(ok)] == [11, 9, 7]


def test_zero_counts_do_not_take_a_row():
    """「0 个项目」这种不算一条：条形图里 0 值条只是一条看不见的线，白占一行。"""
    facts = [{"id": "fact:x", "text": "0 个文件、3 个符号、4 个包、5 个入口。",
              "numbers": [0, 3, 4, 5], "edges": []}]
    assert [row["value"] for row in fake_llm._bar_rows(facts)] == [5, 4, 3]


def test_biggest_rows_survive_the_six_row_cap():
    """六行封顶时砍的是最小那几条：语言明细升序排列，最大的语言绝不能先掉。"""
    text = " 9 个文件（a 1、b 2、c 3、d 4、e 5、f 6、typescript 200）、" \
           "1 个符号、2 条 import、3 个包。"
    facts = [{"id": "fact:totals", "text": text,
              "numbers": [1, 2, 3, 4, 5, 6, 9, 200], "edges": []}]
    rows = fake_llm._bar_rows(facts)
    assert len(rows) == fake_llm.MAX_BAR and rows[0] == {"label": "typescript 文件", "value": 200}


# R513 的兜底：凑不够三组就退回旧形态，页面照旧出
def test_two_pairs_are_not_enough_for_a_bar_chart():
    thin = [{"id": "fact:x", "text": "3 个文件、4 个符号。", "numbers": [3, 4], "edges": []}]
    assert fake_llm._bar_rows(thin) == []
    assert fake_llm._figure(thin, [])["pattern"] == "cards"


def test_stub_falls_back_to_the_old_shapes_when_numbers_are_missing(doc, repo):
    result = ai_pipeline.run_ai(doc, fake_llm.FakeLLM(), "magazine", root=repo)
    patterns = PATTERN.findall(result["html"])
    assert patterns[0] == "bars" and "layered" in patterns
    assert patterns.count("bars") == 1, patterns


def test_layered_and_cards_still_come_back_for_thin_sections():
    edge = {"from": "a.py", "to": "b.py"}
    facts = [{"id": "fact:graph", "text": "依赖图 1 条边", "numbers": [1], "edges": [edge]}]
    assert fake_llm._figure(facts, [])["pattern"] == "layered"
    cards = fake_llm._figure([{"id": "fact:file:a.py", "text": "a.py 是入口文件",
                               "numbers": [], "edges": []}], [])
    assert cards["pattern"] == "cards" and cards["nodes"][0]["label"] == "a.py 是入口文件"
