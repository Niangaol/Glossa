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


# ---- R433 M-3：密钥行只登记名与字节数 --------------------------------------

def test_schema_rejects_content_inside_a_secret_row():
    root = _copy("ts-monorepo")
    (root / ".env").write_text("TOKEN=zzz\n", encoding="utf-8")
    doc = facts.build_repo_doc(root)
    seen = doc["excluded"]["secrets_seen"]
    assert seen, "夹具里得真有一个密钥文件，否则这条断言是空转"
    assert all(set(row) == {"path", "bytes"} for row in seen), "GC30：内容一个字节都不读"
    seen[0]["content"] = "zzz"
    with pytest.raises(TraceSchemaError):
        schema_repo.validate_repo(doc)


# ---- R433 L-4：非法 UTF-8 的两种形态 --------------------------------------

def test_invalid_utf8_forms_are_skipped_with_the_exact_byte_offset():
    """L-4：UTF-16 BOM 与「首行合法 + 尾部坏字节」都要 skipped，字节号要指得准。"""
    root = _copy("ts-monorepo")
    (root / "u16.ts").write_bytes(b"\xff\xfe" + "const a = 1;".encode("utf-16-le"))
    (root / "tail.ts").write_bytes(b"const a = 1;\n" + b"x" * 7 + b"\xff")
    doc = facts.build_repo_doc(root)
    rows = {row["path"]: row for row in doc["files"]}
    assert rows["u16.ts"]["parse"] == "skipped", "BOM 不是 UTF-8 却当合法，解码会把文件读成乱码"
    assert rows["tail.ts"]["parse"] == "skipped", "只看首行就会放过尾部坏字节"
    reasons = {row["scope"]: row["reason"] for row in doc["degraded"]}
    assert "第 1 字节" in reasons["file:u16.ts"], reasons.get("file:u16.ts")
    assert "第 21 字节" in reasons["file:tail.ts"], reasons.get("file:tail.ts")


# ---- R433 L-1：非 file URL 不是本机路径 ------------------------------------

def test_urls_are_neither_rewritten_nor_reported_as_leaks():
    """L-1：http(s) 不是本机路径——即使串里出现了 base，也不许改写、不许报泄漏。"""
    root = _copy("ts-monorepo")
    base = str(root)
    plain, noisy = "https://example.com/x", f"https://example.com/view/{base}/x.ts"
    doc = {"facts": {"fact:plain": {"numbers": [], "text": f"见 {plain} 与 ./ok.ts"},
                     "fact:noisy": {"numbers": [], "text": f"见 {noisy}"}},
           "meta": {"repo": {"url": plain}}}
    assert repo_paths.portable_doc(doc, base=root) == 0, "URL 不是路径，改写它等于撒谎"
    assert doc["meta"]["repo"]["url"] == plain
    assert doc["facts"]["fact:plain"]["text"] == f"见 {plain} 与 ./ok.ts"
    assert doc["facts"]["fact:noisy"]["text"] == f"见 {noisy}", "URL 里的 base 不是路径"
    assert repo_paths.leaked(doc, base=root) == [], "URL 报泄漏会让整仓永远洗不干净"

# ---- R405：scratch_dir 并行安全 --------------------------------------------

def test_scratch_dir_names_are_unique_per_call():
    a = scratch_dir("glossa-probe")
    b = scratch_dir("glossa-probe")
    assert a != b and a.parent == b.parent
    assert len(a.name.rsplit("-", 1)[1]) == 8, "uuid4().hex[:8]，不是进程内计数器 -1/-2"
