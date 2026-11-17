"""A9 / R511：三个真仓的份额预算与页面披露（活体验证）。

真仓不是夹具：中文仓每段 3–4KB 才是「每节都喊超限」的病根。这里用真台账造节：
每节点名 6 条抽样事实 + 最长的 6 段源码，断言份额预算、包上限、truncated 的口径；
再用离线桩把整页跑出来，数页面里「超过 8000 字节」出现几次（必须是 0）。
仓不在本机就跳过——没有真仓就没有这条证据，而不是把断言放宽。
"""
import json
import pathlib

import pytest

from glossa import facts
from glossa.explain import ai_pipeline, pack as pack_mod, pack_trim
from glossa.explain.fake_llm import FakeLLM

REPOS = (("safetrace", pathlib.Path(r"D:\AgentPrograms\safetrace")),
         ("pokemondata", pathlib.Path(r"D:\AgentPrograms\PokemonData")),
         ("papertrace", pathlib.Path(r"D:\AgentPrograms\PaperTrace")))
OVERFLOW = "超过 8000 字节"
SHARE = "3200 字节预算"
SECTION = '<section class="sec"'


@pytest.fixture(scope="session")
def real_docs():
    """三个真仓各建一次台账（约 21 秒，全组共用）。"""
    found = {name: facts.build_repo_doc(path) for name, path in REPOS if path.is_dir()}
    if not found:
        pytest.skip("本机没有三个真仓，跳过活体验证")
    return found


def _size(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _sections(doc):
    """三节：每节 6 条抽样事实 + 最长的 6 段源码（与 AI 分节的真实形状一致）。"""
    sampled = [row["id"] for row in pack_mod.pack_for_plan(doc)["facts"]]
    files = [row for row in doc.get("files") or [] if row.get("path")]
    files.sort(key=lambda row: (-int(row.get("lines") or 0), str(row["path"])))
    sources = [str(row["path"]) for row in files[:pack_mod.MAX_SOURCES]]
    return [{"index": pos, "title": "第 %d 节" % pos, "goal": "",
             "facts": sampled[(pos - 1) * 6:pos * 6], "sources": sources}
            for pos in (1, 2, 3)]


def test_every_real_section_stays_inside_the_share_and_the_pack(real_docs):
    roots = dict(REPOS)
    for name, doc in real_docs.items():
        for section in _sections(doc):
            out = pack_mod.build_pack(doc, section, roots[name])
            assert _size(out) <= pack_mod.MAX_PACK_BYTES, name
            assert _size(out["sources"]) <= pack_trim.SHARE_BYTES, name
            assert _size(out["sources"]) > 0, name
            assert out["truncated"] is False, (name, out["notes"])
            assert sum(SHARE in note for note in out["notes"]) == 1, (name, out["notes"])


def test_the_real_page_never_shouts_about_the_pack(real_docs):
    roots = dict(REPOS)
    for name, doc in real_docs.items():
        result = ai_pipeline.run_ai(doc, FakeLLM(), "magazine", root=roots[name])
        page = result["html"]
        assert page.count(OVERFLOW) == 0, name
        assert result["untraced"] == 0, name
        assert page.count(SHARE) == len(result["sections"]), (name, page.count(SHARE))
        assert page.count(SECTION) == len(result["sections"]) >= 3, name
