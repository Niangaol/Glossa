"""T6 修复轮 2：R395/R397/R398/R405 的严格解码、便携化、摘录与 schema 盲区。

每条都钉「能区分实现」的不变量：按裁决把实现改回去必须红（R400）。
"""
import copy
import json
import pathlib
import shutil

import pytest

from glossa import fact_ids, facts, lang, repo_paths, schema_repo
from papertrace.exceptions import TraceSchemaError
from tests._tmp import scratch_dir

FIX = pathlib.Path(__file__).parent / "fixtures" / "repos"


def _copy(name):
    dst = scratch_dir("glossa-t6-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst


def _file(path, symbols=(), lines=0, namespaces=()):
    """合成一条 files[i]：不跑 scan，专门给 build_facts 喂边界数据。"""
    return {"path": path, "lang": "typescript", "bytes": 1, "lines": lines,
            "parse": "approx", "symbols": list(symbols), "imports": [],
            "namespaces": list(namespaces)}


def _doc(files):
    return {"totals": {}, "files": files, "packages": [], "projects": [], "entries": [],
            "imports": [], "graph": {}, "excluded": {}, "degraded": []}


# ---- R395：解码必须真的会失败 -------------------------------------------------

def test_invalid_utf8_file_is_skipped_not_replaced():
    root = _copy("ts-monorepo")
    (root / "caf.ts").write_bytes(b"export function caf\xe9() {}\n")
    doc = facts.build_repo_doc(root)
    row = next(f for f in doc["files"] if f["path"] == "caf.ts")
    assert row["parse"] == "skipped", "非法 UTF-8 必须走 §9 的 skipped"
    assert row["symbols"] == [] and row["imports"] == []
    reasons = [d["reason"] for d in doc["degraded"]]
    assert any("不是合法 UTF-8" in r and "第 20 字节" in r for r in reasons), reasons
    assert "\ufffd" not in json.dumps(doc, ensure_ascii=False), "任何字段都不许出现 U+FFFD"
    assert not any(k.startswith("fact:source:caf.ts") for k in doc["facts"])
    schema_repo.validate_repo(doc)


def test_scan_line_count_fallback_does_not_feed_parser(monkeypatch):
    root = _copy("ts-monorepo")
    (root / "caf.ts").write_bytes(b"export function caf\xe9() {}\n")
    seen = []
    real = lang.parse_file

    def spy(language, text, relpath):
        seen.append((relpath, text))
        return real(language, text, relpath)

    monkeypatch.setattr(lang, "parse_file", spy)
    doc = facts.build_repo_doc(root)
    row = next(f for f in doc["files"] if f["path"] == "caf.ts")
    assert row["lines"] == 1, "scan 的 replace 解码只用于行数统计"
    assert "\ufffd" not in json.dumps(doc, ensure_ascii=False)
    assert all(rel != "caf.ts" for rel, _text in seen), "替换后的文本不许进解析器"
    assert seen, "其余文件仍要正常解析"


# ---- R397/R398 M5：便携化 ------------------------------------------------

def test_portable_doc_rewrites_absolute_paths_inside_text():
    root = _copy("ts-monorepo")
    doc = facts.build_repo_doc(root)
    base = str(root)
    doc["facts"]["fact:probe"] = {"numbers": [], "text": f"详见 {base}\\glossa\\facts.py 第 3 行"}
    assert repo_paths.portable_doc(doc, base=root) == 1
    assert "./glossa/facts.py" in doc["facts"]["fact:probe"]["text"], "句内也要 posix + './'"
    assert base not in json.dumps(doc, ensure_ascii=False)
    assert repo_paths.leaked(doc, base=root) == []
    rel = {"v": "src\\y.ts"}
    assert repo_paths.portable_doc(rel, base=root) == 1 and rel["v"] == "./src/y.ts"
    url = {"v": "file:///" + pathlib.PurePath(base).as_posix() + "/glossa/facts.py"}
    assert repo_paths.portable_doc(url, base=root) == 1 and url["v"] == "./glossa/facts.py"
    assert repo_paths.leaked({"v": "看 D:\\Elsewhere\\secret.ts 这个文件"}, base=root) == ["v"]


# ---- R397：R367 重建、摘录内容、schema 嵌套 --------------------------------

def test_python_entry_main_guard_comes_from_parse(monkeypatch):
    real = lang.parse_file

    def fake(language, text, relpath):
        parsed = real(language, text, relpath)
        return {**parsed, "main_guard": False} if language == "python" else parsed

    monkeypatch.setattr(lang, "parse_file", fake)
    doc = facts.build_repo_doc(_copy("py-mini"))
    assert not any(e["kind"] == "main_guard" for e in doc["entries"]), "R367：只信 parse"


def test_fact_source_text_is_really_the_original_line():
    root = _copy("ts-monorepo")
    doc = facts.build_repo_doc(root)
    first = (root / "packages/a/src/circuit.ts").read_text(encoding="utf-8").splitlines()[0]
    text = doc["facts"]["fact:source:packages/a/src/circuit.ts:1-1"]["text"]
    assert first.strip() in text, "摘录必须是原文，不许占位"
    assert "\ufffd" not in text


def test_schema_rejects_nested_extra_keys():
    doc = facts.build_repo_doc(_copy("cs-solution"))
    row = next(f for f in doc["files"] if f["symbols"])
    row["symbols"][0]["extra"] = 1
    with pytest.raises(TraceSchemaError):
        schema_repo.validate_repo(doc)
    doc = facts.build_repo_doc(_copy("ts-monorepo"))
    doc["graph"]["nodes"][0]["extra"] = 1
    with pytest.raises(TraceSchemaError):
        schema_repo.validate_repo(doc)


def test_schema_pins_graph_array_shapes():
    base = facts.build_repo_doc(_copy("ts-monorepo"))
    assert base["graph"]["nodes"] and base["graph"]["edges"]
    cases = [lambda d: d["graph"]["nodes"].append("not-an-object"),
             lambda d: d["graph"]["layers"].append("a.ts"),
             lambda d: d["graph"]["cycles"].append([1, 2]),
             lambda d: d["graph"]["reachable_from_entries"].append(3),
             lambda d: d["graph"]["unreachable"].append({"x": 1}),
             lambda d: d["graph"]["edges"][0].pop("count")]
    for mutate in cases:
        doc = copy.deepcopy(base)
        mutate(doc)
        with pytest.raises(TraceSchemaError):
            schema_repo.validate_repo(doc)


# ---- R398 M1/M2/M4：摘录像人话 -------------------------------------------

def test_long_source_excerpt_is_marked_truncated():
    root = scratch_dir("glossa-t6-m1")
    long_line = "export const LONG = '" + "A" * 300 + "';"
    (root / "a.ts").write_text(long_line + "\n", encoding="utf-8")
    doc = _doc([_file("a.ts", [{"name": "LONG", "kind": "const", "line": 1}], 1)])
    text = fact_ids.build_facts(doc, repo_root=root)["fact:source:a.ts:1-1"]["text"]
    assert "…（已截断，原文共 323 字符）" in text
    assert long_line not in text


def test_bad_line_range_is_clamped_or_dropped():
    root = scratch_dir("glossa-t6-m2")
    (root / "a.ts").write_text("l1\nl2\nl3\nl4\n", encoding="utf-8")
    doc = _doc([_file("a.ts", [{"name": "Weird", "kind": "class", "line": 9, "end_line": 2}], 4)])
    got = fact_ids.build_facts(doc, repo_root=root)
    sources = {k: v for k, v in got.items() if k.startswith("fact:source:")}
    assert "fact:source:a.ts:9-2" not in sources, "禁止反向 id"
    for fid in sources:
        lo, hi = (int(x) for x in fid.rsplit(":", 1)[1].split("-"))
        assert lo <= hi and 1 <= lo and hi <= 4, fid
    empty = scratch_dir("glossa-t6-m2e")
    (empty / "b.ts").write_text("", encoding="utf-8")
    doc = _doc([_file("b.ts", [{"name": "Ghost", "kind": "class", "line": 5, "end_line": 1}], 0)])
    got = fact_ids.build_facts(doc, repo_root=empty)
    assert not any(k.startswith("fact:source:b.ts") for k in got), "取不到原文不产 fact"
    reasons = [d["reason"] for d in doc["degraded"]]
    assert any("符号 Ghost 的行区间 5–1 与文件行数 0 不符，未摘原文" in r for r in reasons), reasons


def test_same_fact_id_lists_every_source():
    files = [_file(f"{name}.cs", namespaces=[{"name": "Demo.Core", "line": 1,
                                              "style": "file_scoped"}])
             for name in ("A", "B", "C", "D", "E")]
    text = fact_ids.build_facts(_doc(files))["fact:namespace:Demo.Core"]["text"]
    assert "A.cs" in text and "B.cs" in text and "C.cs" in text
    assert "等 5 处" in text, "超过 3 处要按总数披露"
    two = fact_ids.build_facts(_doc(files[:2]))["fact:namespace:Demo.Core"]["text"]
    assert "A.cs" in two and "B.cs" in two
    pkgs = [{"name": "@x/a", "path": d, "manifest": d + "/package.json", "deps": {},
             "dev_deps": {}, "scripts": {}, "workspace": True} for d in ("p1", "p2")]
    doc = _doc([])
    doc["packages"] = pkgs
    pkg_text = fact_ids.build_facts(doc)["fact:pkg:@x/a"]["text"]
    assert "p1/package.json" in pkg_text and "p2/package.json" in pkg_text


# ---- R405：scratch_dir 并行安全 --------------------------------------------

def test_scratch_dir_names_are_unique_per_call():
    a = scratch_dir("glossa-probe")
    b = scratch_dir("glossa-probe")
    assert a != b and a.parent == b.parent
    assert len(a.name.rsplit("-", 1)[1]) == 8, "uuid4().hex[:8]，不是进程内计数器 -1/-2"
