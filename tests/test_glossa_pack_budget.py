"""A9 / R511：sources 的份额预算（pack.py + pack_trim.py）与「不许每节都喊超限」。

派发书 §R511 的六条：
- sources 最多占包 40%（3200 字节），先按份额把切片从尾部减行；
- 份额截断**是正常取舍**：不置 truncated、不写「超过 8000 字节」那种 note；
- 只在 notes 里留一句「源码片段按 3200 字节预算截断，共保留 K 段」，**每节一条**；
- 只有真的连 facts 都要砍，才置 truncated=True 并写 note；
- 包本身仍 <= 8000 字节（份额预算不是放宽总上限）；
- 单行超过预算的怪物切片整段弃掉，不许把包撑爆。
"""
import json
import pathlib

import pytest

from glossa.explain import pack as pack_mod
from glossa.explain import pack_trim
from tests._tmp import scratch_dir

OVERFLOW = "超过 8000 字节"
SHARE = "3200 字节预算"


@pytest.fixture()
def work():
    """沙箱友好：不用 pytest 的 tmp_path / --basetemp，走 tests/_tmp。"""
    return scratch_dir("a9budget")


def _write(root, rel, lines):
    path = pathlib.Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _doc(paths, *, facts=None, edges=(), lines=40):
    files = [{"path": p, "lines": lines} for p in paths]
    return {
        "meta": {"repo": {"url": "demo", "commit": "a" * 40, "root_name": "demo",
                          "language": "python"}},
        "totals": {"files": len(files), "symbols": 2, "imports": 1, "degraded": 0},
        "files": files,
        "graph": {"level": "file", "nodes": [{"id": p} for p in paths],
                  "edges": [dict(edge) for edge in edges], "project_edges": [],
                  "cycles": [], "layers": [[p] for p in paths], "unreachable": [],
                  "truncated": False},
        "excluded": {"secrets_seen": []},
        "facts": dict(facts or {}),
    }


def _bytes(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _big_lines(count=40, width=20):
    return ["第 %03d 行：%s" % (i, "内容" * width) for i in range(1, count + 1)]


def _six_sources(work):
    paths = ["f%d.py" % i for i in range(6)]
    for path in paths:
        _write(work, path, _big_lines())
    return paths


def test_the_share_budget_is_forty_percent_of_the_pack():
    assert pack_trim.SHARE_BYTES == 3200 == int(pack_mod.MAX_PACK_BYTES * 0.40)


def test_sources_are_capped_at_their_share_but_stay_whole(work):
    paths = _six_sources(work)
    doc = _doc(paths, facts={"fact:files": {"text": "6 个文件。", "numbers": [6]}})
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": paths}, work)
    assert _bytes(out["sources"]) <= pack_trim.SHARE_BYTES
    assert [src["path"] for src in out["sources"]] == paths      # 段数不减，只减行
    assert _bytes(out) <= pack_mod.MAX_PACK_BYTES
    assert out["truncated"] is False                             # 正常取舍不算截断


def test_the_share_trim_is_disclosed_exactly_once_and_never_as_an_overflow(work):
    paths = _six_sources(work)
    doc = _doc(paths)
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": paths}, work)
    notes = out["notes"]
    assert sum(SHARE in note for note in notes) == 1, notes
    assert "共保留 6 段" in notes[0], notes
    assert all(OVERFLOW not in note for note in notes), notes


def test_the_share_trim_never_touches_the_facts(work):
    paths = _six_sources(work)
    facts = {"fact:n%02d" % i: {"text": "第 %d 条事实。" % i, "numbers": [i]}
             for i in range(10)}
    doc = _doc(paths, facts=facts)
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": paths}, work)
    assert [row["id"] for row in out["facts"]] == list(facts)
    assert out["truncated"] is False


def test_each_section_pays_the_share_budget_on_its_own(work):
    paths = _six_sources(work)
    doc = _doc(paths)
    for index in (1, 2, 3):
        out = pack_mod.build_pack(
            doc, {"index": index, "title": "第%d节" % index, "goal": "", "sources": paths}, work)
        assert sum(SHARE in note for note in out["notes"]) == 1, (index, out["notes"])
        assert _bytes(out["sources"]) <= pack_trim.SHARE_BYTES


def test_truncated_is_true_only_when_the_facts_have_to_go(work):
    paths = _six_sources(work)
    facts = {"fact:big%02d" % i: {"text": "第 %d 条：" % i + "长" * 900, "numbers": [i]}
             for i in range(12)}
    doc = _doc(paths, facts=facts)
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": paths}, work)
    assert out["truncated"] is True
    assert 0 < len(out["facts"]) < len(facts)
    assert _bytes(out) <= pack_mod.MAX_PACK_BYTES
    assert any("字节" in note for note in out["notes"])
    assert all(OVERFLOW not in note for note in out["notes"]), out["notes"]


def test_a_single_line_wider_than_the_share_is_dropped_whole(work):
    _write(work, "min.js", ["x" * 4000])
    doc = _doc(["min.js"], lines=1)
    out = pack_mod.build_pack(
        doc, {"index": 1, "title": "t", "goal": "", "sources": ["min.js"]}, work)
    assert out["sources"] == []
    assert _bytes(out) <= pack_mod.MAX_PACK_BYTES
    assert any("共保留 0 段" in note for note in out["notes"]), out["notes"]
    assert all(OVERFLOW not in note for note in out["notes"])


def test_source_slices_are_measured_on_the_same_bytes_as_the_pack():
    """3200 的口径必须和包的口径一样是 UTF-8 真字节，不是字符数。"""
    rows = [{"path": "a.py", "start": 1, "end": 20,
             "text": "\n".join(["中文" * 100] * 20)}]
    trimmed, cut = pack_trim.budget_sources(rows)
    assert cut is True and _bytes(trimmed) <= pack_trim.SHARE_BYTES
    assert trimmed[0]["text"] != rows[0]["text"]
