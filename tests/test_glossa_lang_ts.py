"""T4：TS/JS/Vue 近似解析。行号是实测冻结事实，不许改夹具凑数。"""
from pathlib import Path

from glossa.lang import masks, tsjs, vue
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos" / "ts-monorepo"


def _read(rel):
    return (FIX / rel).read_text(encoding="utf-8")


def test_comment_and_string_imports_are_masked():
    r = tsjs.parse_source(_read("packages/a/src/comments.ts"), "comments.ts")
    assert r["imports"] == []          # 三条假 import 全被掩码杀掉
    assert r["parse"] == "approx"


def test_static_imports_have_specifier_and_line():
    r = tsjs.parse_source(_read("packages/a/src/server.ts"), "server.ts")
    static = [i for i in r['imports'] if not i['dynamic']]
    assert [(i['line'], i['specifier']) for i in static] == [
        (1, "./circuit.js"), (2, "@x/b"), (3, "node:fs/promises"),
        (4, "./types.js"), (5, "left-pad")]


def test_type_only_import_is_flagged():
    r = tsjs.parse_source(_read("packages/a/src/server.ts"), "server.ts")
    hit = next(i for i in r["imports"] if i["specifier"] == "./types.js")
    assert hit["type_only"] is True
    assert hit["names"] == ["Shape"]
    plain = next(i for i in r["imports"] if i["specifier"] == "./circuit.js")
    assert plain["type_only"] is False


def test_dynamic_import_is_captured():
    r = tsjs.parse_source(_read("packages/a/src/server.ts"), "server.ts")
    dyn = [i for i in r['imports'] if i['dynamic']]
    assert len(dyn) == 1
    assert dyn[0]["line"] == 8
    assert dyn[0]["specifier"] == "./lazy.js"


def test_multiline_import_records_statement_start_line():
    r = tsjs.parse_source(_read("packages/a/src/multiline.ts"), "multiline.ts")
    assert len(r["imports"]) == 1
    assert r["imports"][0]["line"] == 1        # R278：不是 from 所在的第 4 行
    assert r["imports"][0]["specifier"] == "./circuit.js"
    assert r["imports"][0]["names"] == ["one", "two"]


def test_export_symbols_are_captured():
    circuit = tsjs.parse_source(_read("packages/a/src/circuit.ts"), "circuit.ts")
    assert [(s["name"], s["kind"], s["line"]) for s in circuit["symbols"]] == [
        ("Circuit", "class", 1)]
    types = tsjs.parse_source(_read("packages/a/src/types.ts"), "types.ts")
    assert [(s["name"], s["kind"], s["line"]) for s in types["symbols"]] == [
        ("Shape", "interface", 1), ("Kind", "type", 4)]
    server = tsjs.parse_source(_read("packages/a/src/server.ts"), "server.ts")
    fn = next(s for s in server["symbols"] if s["name"] == "serve")
    assert fn["kind"] == "async_function"
    assert fn["line"] == 7


def test_vue_script_offset_restores_line_numbers():
    r = vue.parse_source(_read("apps/web/App.vue"), "App.vue")
    assert len(r["imports"]) == 1
    assert r["imports"][0]["line"] == 5        # 实测：script 开标签在第 4 行
    assert r["imports"][0]["specifier"] == "@x/b"
    assert r["parse"] == "approx"
    assert r["symbols"] == []                  # R298：script setup 顶层绑定不抓
    assert any("script setup" in d for d in r["degraded"])


def test_mask_keeps_length_and_newlines():
    text = _read("packages/a/src/comments.ts")
    masked, spans = masks.mask_source(text)
    assert len(masked) == len(text)            # R281 硬不变量
    assert [i for i, c in enumerate(masked) if c == '\n'] == [
        i for i, c in enumerate(text) if c == '\n']
    assert spans                              # 字符串区间被记下来了
    q = masked.index(chr(34))                 # 第一个双引号
    got = masks.string_at(text, spans, q)
    assert got == "import { alsoFake } from './nope2.js'"
