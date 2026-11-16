"""T8：七块骨架。标题逐字取自设计 §14。"""
import shutil
from pathlib import Path

from glossa import facts, keyfiles
from glossa.explain import outline
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"
TITLES = ["这项目是什么", "从哪进来", "分几块", "谁依赖谁",
          "关键文件逐个讲", "我没看清的地方", "甜头（可选）"]


def _doc(name, **kw):
    dst = scratch_dir("glossa-t8-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return facts.build_repo_doc(dst, **kw)


def test_outline_has_seven_blocks_in_order():
    blocks = outline.build_outline(_doc("ts-monorepo"))
    assert [b["index"] for b in blocks] == [1, 2, 3, 4, 5, 6, 7]
    assert [b["title"] for b in blocks] == TITLES
    assert blocks[0]["components"] == ["overview", "metrics", "text"]
    assert blocks[6]["components"] == ["bonus"]


def test_outline_facts_are_real_ids_from_doc():
    doc = _doc("ts-monorepo")
    blocks = outline.build_outline(doc)
    for b in blocks[:6]:
        assert b["required"] is True
        assert b["facts"], b["title"]
        for fid in b["facts"]:
            assert fid in doc["facts"], fid
    assert "fact:graph" in blocks[3]["facts"]
    assert any(f.startswith("fact:entry:") for f in blocks[1]["facts"])
    # R336：第⑤块只讲关键文件（≤12），且必须带全量清单供折叠
    b5 = blocks[4]
    ff = [f for f in b5["facts"] if f.startswith("fact:file:")]
    assert len(ff) == len(keyfiles.key_files(doc)) <= 12
    assert "fact:files" in b5["facts"]


def test_bonus_block_is_optional_without_trace():
    doc = _doc("ts-monorepo")
    b7 = outline.build_outline(doc)[6]
    assert b7["required"] is False
    assert b7["facts"] == []
    with_bonus = _doc("ts-monorepo", bonus={"nodes": [1], "edges": [],
                                            "anchors": []})
    b7b = outline.build_outline(with_bonus)[6]
    assert b7b["required"] is True
    assert b7b["facts"] == ["fact:bonus"]
