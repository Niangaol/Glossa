"""T10：程序版讲解。每个数字都必须有出处。"""
from tests.common import FIXTURES
import shutil
from pathlib import Path

from glossa import facts
from glossa.explain import components, narrate, render
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"


def _doc(name='ts-monorepo', **kw):
    dst = scratch_dir("glossa-t10n-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return facts.build_repo_doc(dst, **kw)


def test_program_blocks_are_valid_and_cite_real_facts():
    doc = _doc()
    blocks = narrate.program(doc)
    components.validate_blocks(doc, blocks)      # 不抛即合格
    for b in blocks:
        assert b["cites"], b["component"]
        for fid in b["cites"]:
            assert fid in doc["facts"], fid
    assert len([b for b in blocks if b["component"] == "file_card"]) <= 12


def test_program_page_has_zero_untraced_numbers():
    doc = _doc()
    html, report = render.render_explain(doc, narrate.program(doc))
    assert report["untraced"] == 0
    assert "本页有 0 处数字未溯源" in html
    assert "本页由程序生成，未使用模型" in html


def test_program_is_deterministic_and_bonus_is_optional():
    doc = _doc()
    assert narrate.program(doc) == narrate.program(doc)
    # 一「块」是七块骨架的一节：组件块的数量随文件数增长，所以这里数 section
    assert {b["section"] for b in narrate.program(doc)} == set(range(1, 7))   # 无 bonus → 第七块不出现
    with_bonus = _doc("ts-monorepo", bonus={"nodes": [1, 2], "edges": [],
                                            "anchors": []})
    assert {b["section"] for b in narrate.program(with_bonus)} == set(range(1, 8))


def test_build_prompt_contains_real_ids_and_component_contract():
    doc = _doc()
    prompt = narrate.build_prompt(doc)
    assert "fact:totals" in prompt
    assert "fact:graph" in prompt
    for name in components.COMPONENTS:
        assert name in prompt
    assert "fact:ghost" not in prompt
    assert "不许编" in prompt or "禁止编造" in prompt
