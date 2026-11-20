"""R515/R516：条形与卡片数据的 label 也要查出处，条形值必须能在素材里核上。

A10 报告 §8 的缺口：gate_labels 只看 fig["nodes"]，而 bars/cards 图的 nodes 是空的 →
R508 对它们完全失效；同一个洞还漏掉「模型给条形图编一个数值」——那个数值会直接印在 SVG 上，
成为页面上唯一一个没有任何出处的数字（数字溯源闸只扫 html，扫不到图数据）。
"""
from tests.common import FIXTURES

import json
import pathlib
import shutil

import pytest

from glossa import facts as facts_mod
from glossa.explain import ai_pipeline, fake_llm, gates, guard
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"


@pytest.fixture()
def repo():
    dst = scratch_dir("a15-datagates")
    shutil.copytree(FIX / "ts-monorepo", dst, dirs_exist_ok=True)
    return dst


@pytest.fixture()
def doc(repo):
    return facts_mod.build_repo_doc(repo)


def _pack(numbers=(3, 5)):
    return {"repo": {"root_name": "r"},
            "section": {"title": "规模", "goal": "只讲素材里查得到的事"},
            "facts": [{"id": "fact:languages", "text": "python 文件 3 个，markdown 文件 5 个",
                       "numbers": list(numbers)}],
            "sources": []}


class BarsLLM(fake_llm.FakeLLM):
    """真实协议形状的坏模型：第一节给指定 figures，其余节只写一句正文。"""

    def __init__(self, figures):
        super().__init__()
        self.figures, self.sections = list(figures), 0

    def complete(self, prompt, system=""):
        if "这一节的素材包" in str(prompt):
            self.sections += 1
            pack = fake_llm._load(prompt)
            head = str((pack.get("section") or {}).get("title") or "")
            return json.dumps({"title": head, "html": "<p>正文</p>",
                               "figures": self.figures if self.sections == 1 else [],
                               "notes": []}, ensure_ascii=False)
        return super().complete(prompt, system)


# R515：条形图的 label 同样必须是素材里查得到的人话
def test_bar_label_must_be_findable_in_the_pack():
    bad = {"pattern": "bars", "caption": "编的条形图",
           "bars": [{"label": "fact:languages", "value": 3}]}
    clean, notes = gates.gate_labels(bad, _pack())
    assert clean is None and any("丢" in note for note in notes), notes
    ok = {"pattern": "bars", "caption": "语言规模",
          "bars": [{"label": "python 文件", "value": 3}]}
    clean2, notes2 = gates.gate_labels(ok, _pack())
    assert clean2 is not None and notes2 == []


def test_card_label_is_checked_too():
    bad = {"pattern": "cards", "caption": "编的卡片",
           "cards": [{"label": "凭空捏造的卡片", "text": "编的摘要"}]}
    clean, notes = gates.gate_labels(bad, _pack())
    assert clean is None and any("丢" in note for note in notes), notes


# R516：条形值必须在这一节素材的 numbers 里，编的那一条丢掉、其余照画
def test_bar_value_without_a_source_is_dropped():
    fig = {"pattern": "bars", "caption": "语言规模",
           "bars": [{"label": "python 文件", "value": 3},
                    {"label": "markdown 文件", "value": 99999}]}
    kept, notes = gates.gate_values(fig, _pack()["facts"][0]["numbers"])
    assert kept is not None and [row["value"] for row in kept["bars"]] == [3]
    assert any("99999" not in note and "查不到出处" in note for note in notes), notes


def test_bar_with_every_value_invented_drops_the_figure():
    fig = {"pattern": "bars", "caption": "语言规模",
           "bars": [{"label": "python 文件", "value": 7}, {"label": "markdown 文件", "value": 9}]}
    kept, notes = gates.gate_values(fig, [3, 5])
    assert kept is None and any("整张图已丢弃" in note for note in notes), notes


def test_figures_without_bars_are_untouched():
    fig = {"pattern": "layered", "caption": "依赖", "nodes": [], "edges": []}
    kept, notes = gates.gate_values(fig, [3])
    assert kept == fig and notes == []


def test_pipeline_discloses_a_fabricated_bar_value(doc, repo):
    label = doc["meta"]["repo"]["root_name"]
    fig = {"pattern": "bars", "caption": "编的条形图",
           "bars": [{"label": label, "value": 99999}]}
    result = ai_pipeline.run_ai(doc, BarsLLM([fig]), "magazine", root=repo)
    assert "99999" not in result["html"]
    assert any("柱状图" in note for note in result["notes"]), result["notes"]

# R526：提交哈希不是数字——真跑 SafeTrace 时模型把 commit 写进正文，旧正则把
# 9ca2b4f9a17f3cf… 撕成 9/2/4/9/190/604/… 一串假黄标（误报 11 处）
def test_a_commit_hash_is_not_shredded_into_untraced_numbers():
    html = guard.mark_untraced(
        "<p>本节基于 commit 9ca2b4f9a17f3cf190f3b604c1dff779198c25a4 的扫描结果</p>", {"13"})
    assert "untraced" not in html
    assert gates.count_plain_numbers(["commit 9ca2b4f9a17f3cf190f3b6"], {"13"}) == 0


def test_a_plain_number_next_to_chinese_text_is_still_counted():
    assert gates.count_plain_numbers(["共 13 个文件"], set()) == 1
    assert gates.count_plain_numbers(["共 13 个文件"], {"13"}) == 0
