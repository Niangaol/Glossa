"""T6 修复轮 3（R426/R433 M-6、M-8）与 A7（R502）：numbers 与 text 的数字双向对齐。

R426 的不变量是 numbers ⊆ text 的数字集合（不是相等）；R502 补上反方向——text 里写出来的
每个数字都必须在 numbers 里（「等 N 处」的 N 也算），所以现在两个方向同时成立。
"""
import pathlib
import shutil

from glossa import fact_ids, facts
from tests._tmp import scratch_dir

FIX = pathlib.Path(__file__).parent / "fixtures" / "repos"


def _copy(name):
    dst = scratch_dir("glossa-t6n-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst


def _file(path, symbols=(), namespaces=(), lines=0, lang="typescript"):
    return {"path": path, "lang": lang, "bytes": 1, "lines": lines, "parse": "approx",
            "symbols": list(symbols), "imports": [], "namespaces": list(namespaces)}


def _doc(files):
    return {"totals": {}, "files": files, "packages": [], "projects": [], "entries": [],
            "imports": [], "graph": {}, "excluded": {}, "degraded": []}


# ---- R426：numbers 与 text 同步截断 ---------------------------------------

def test_numbers_only_cover_the_sources_shown_in_text():
    files = [_file(f"{name}.cs", namespaces=[{"name": "Demo.Core", "line": index,
                                              "style": "file_scoped"}])
             for index, name in enumerate(("A", "B", "C", "D", "E"), 1)]
    row = fact_ids.build_facts(_doc(files))["fact:namespace:Demo.Core"]
    assert "等 5 处" in row["text"]
    assert "第 4 行" not in row["text"] and "第 5 行" not in row["text"]
    assert row["numbers"] == [1, 2, 3, 5], "三条来源行号 + 「等 5 处」的 5（R502：文字里的都算）"
    assert all(str(number) in row["text"] for number in row["numbers"])


def test_entry_numbers_stay_on_the_sources_the_text_lists():
    doc = _doc([])
    doc["entries"] = [{"kind": "npm_script", "name": "build", "command": "tsc",
                       "target": None, "package": f"@x/p{index}", "note": ""}
                      for index in range(1, 6)]
    row = fact_ids.build_facts(doc)["fact:entry:build"]
    assert "等 5 处" in row["text"] and "第 4/5 个" not in row["text"]
    assert row["numbers"] == [1, 2, 3, 5]


def test_totals_fact_numbers_cover_every_number_in_its_text():
    doc = _doc([])
    doc["totals"] = {"files": 259, "symbols": 302, "imports": 4, "by_lang": {"python": 6,
                                                                             "csharp": 11}}
    row = fact_ids.build_facts(doc)["fact:totals"]
    for number in (6, 11, 259, 302):
        assert number in row["numbers"], row["numbers"]
    written = {int(token.replace(",", "")) for token in fact_ids._TEXT_DIGITS.findall(row["text"])}
    assert written <= set(row["numbers"]), "文字里写出来的数字缺 %s" % sorted(written - set(row["numbers"]))


def test_numbers_in_text_drops_thousands_separators():
    assert fact_ids.numbers_in_text("共 1,234 个文件、7 个包") == {1234, 7}
    assert fact_ids.numbers_in_text("没有数字") == set()


def test_every_number_appears_in_its_fact_text_for_every_fixture():
    for path in sorted(item for item in FIX.iterdir() if item.is_dir()):
        doc = facts.build_repo_doc(_copy(path.name))
        for fact_id, row in doc["facts"].items():
            missing = [number for number in row["numbers"] if str(number) not in row["text"]]
            assert not missing, f"{path.name} {fact_id} 的 numbers={missing} 不在 text 里"


# ---- M-6：摘录阈值 120 字 -------------------------------------------------

def test_excerpt_threshold_is_120_characters():
    root = scratch_dir("glossa-t6-m6")
    line = "x" * 150
    (root / "a.ts").write_text(line + "\n", encoding="utf-8")
    doc = _doc([_file("a.ts", [{"name": "long", "kind": "const", "line": 1}], lines=1)])
    row = fact_ids.build_facts(doc, repo_root=root)["fact:source:a.ts:1-1"]
    assert "…（已截断，原文共 150 字符）" in row["text"]
    assert line not in row["text"] and "x" * 121 not in row["text"]


# ---- M-8：反向区间必须抢救成 fact，不许静默丢弃 -------------------------

def test_reversed_span_is_rescued_into_a_fact():
    root = scratch_dir("glossa-t6-m8")
    (root / "x.ts").write_text("l1\nl2\nl3\nl4\n", encoding="utf-8")
    doc = _doc([_file("x.ts", [{"name": "Weird", "kind": "class", "line": 9,
                                "end_line": 2}], lines=4)])
    row = fact_ids.build_facts(doc, repo_root=root)["fact:source:x.ts:2-4"]
    assert "l2" in row["text"] and "l4" in row["text"] and "l1" not in row["text"]
    assert row["numbers"] == [2, 3, 4, 9], "摘录里的 2/3/4 与「行区间 9–2」的 9 一样都要有出处（R502）"


def test_bad_line_range_is_clamped_or_dropped():
    root = scratch_dir("glossa-t6-m2")
    (root / "a.ts").write_text("l1\nl2\nl3\nl4\n", encoding="utf-8")
    doc = _doc([_file("a.ts", [{"name": "Weird", "kind": "class", "line": 9, "end_line": 2}], lines=4)])
    got = fact_ids.build_facts(doc, repo_root=root)
    sources = {key: value for key, value in got.items() if key.startswith("fact:source:")}
    assert "fact:source:a.ts:9-2" not in sources, "禁止反向 id"
    for fact_id in sources:
        low, high = (int(part) for part in fact_id.rsplit(":", 1)[1].split("-"))
        assert low <= high and 1 <= low and high <= 4, fact_id
    empty = scratch_dir("glossa-t6-m2e")
    (empty / "b.ts").write_text("", encoding="utf-8")
    doc = _doc([_file("b.ts", [{"name": "Ghost", "kind": "class", "line": 5, "end_line": 1}], lines=0)])
    got = fact_ids.build_facts(doc, repo_root=empty)
    assert not any(key.startswith("fact:source:b.ts") for key in got), "取不到原文不产 fact"
    reasons = [row["reason"] for row in doc["degraded"]]
    assert any("符号 Ghost 的行区间 5–1 与文件行数 0 不符，未摘原文" in reason
               for reason in reasons), reasons
