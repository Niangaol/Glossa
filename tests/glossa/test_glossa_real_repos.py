"""A7：三个真仓（safetrace / PokemonData / 本仓）的活体验证（R501 + R502）。

真仓不是夹具：它们的事实顺序正是 R501 的病灶（前 60 条几乎全是 fact:file:*），只有真跑
才证明得了「图进得去、每类都看得见、文字里的数字都有出处」。仓不在本机就跳过——没有真仓
就没有这条证据，而不是把断言放宽。
"""
import json
import pathlib
import re

import pytest

from glossa import facts
from glossa.explain import pack as pack_mod

REPOS = (("safetrace", pathlib.Path(r"D:\AgentPrograms\safetrace")),
         ("pokemondata", pathlib.Path(r"D:\AgentPrograms\PokemonData")),
         ("papertrace", pathlib.Path(r"D:\AgentPrograms\PaperTrace")))
_DIGITS = re.compile(r"\d[\d,]*")


@pytest.fixture(scope="session")
def real_docs():
    """三个真仓各建一次台账：这是这组断言的唯一素材源（21 秒左右，全组共用）。"""
    found = {name: facts.build_repo_doc(path) for name, path in REPOS if path.is_dir()}
    if not found:
        pytest.skip("本机没有三个真仓，跳过活体验证")
    return found


def test_plan_pack_of_a_real_repo_keeps_the_graph(real_docs):
    for name, doc in real_docs.items():
        pack = pack_mod.pack_for_plan(doc)
        blob = json.dumps(pack, ensure_ascii=False).encode("utf-8")
        assert len(blob) <= pack_mod.MAX_PACK_BYTES, name
        prefixes = {row["id"].split(":")[1] for row in pack["facts"]}
        assert len(prefixes) >= 5, (name, sorted(prefixes))
        graph = next((row for row in pack["facts"] if row["id"] == "fact:graph"), None)
        assert graph is not None, "%s 的包里没有 fact:graph" % name
        assert graph["edges"], "%s 的图事实没有边，模型画不出关系图" % name
        assert graph["has_edges"] is True and pack["has_edges"] is True, name


def test_every_number_in_fact_text_is_sourced(real_docs):
    for name, doc in real_docs.items():
        for fact_id, row in doc["facts"].items():
            written = {int(tok.replace(",", "")) for tok in _DIGITS.findall(row["text"])
                       if tok.replace(",", "")}
            missing = written - set(row["numbers"])
            assert not missing, "%s %s 的文字写了 %s，numbers 里没有" % (name, fact_id, sorted(missing))
