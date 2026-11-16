"""T4：TS/JS/Vue 近似解析。行号是实测冻结事实，不许改夹具凑数。"""
import re
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

def test_regex_literal_with_quotes_does_not_desync_masks():
    """R375：正则字面量里的引号不许把掩码带跑偏（否则字符串里的假 import 会复活）。"""
    src = '''const re = /['"]/;
import { a } from "./real.js";
const s = 'import { fake } from "./fake.js"';
'''
    r = tsjs.parse_source(src, "regex.ts")
    assert [(i["specifier"], i["dynamic"]) for i in r["imports"]] == [("./real.js", False)]
    assert r["degraded"] == []


def test_unterminated_string_is_reported_not_silently_swallowed():
    """R375：字符串未闭合到 EOF 必须记 degraded，不许静默把后半段掩成空格。"""
    r = tsjs.parse_source("export const a = 1;\nconst s = 'abc", "broken.ts")
    assert [s["name"] for s in r["symbols"]] == ["a"]
    assert any("未闭合" in note for note in r["degraded"]), r["degraded"]
    assert r["parse"] == "approx"


def test_export_list_and_multi_declarator_are_both_captured():
    """R376：列表式导出与多声明符都要抓全；名字取原名，列表式 kind='export_list'。"""
    listed = tsjs.parse_source("function f1() {}\nfunction f2() {}\nexport { f1, f2 as g };\n",
                               "list.ts")
    assert [(s["name"], s["kind"]) for s in listed["symbols"]] == [
        ("f1", "export_list"), ("f2", "export_list")]
    multi = tsjs.parse_source("export const x = 1, y = new Map([['k', 1]]), z = 3;\n",
                              "multi.ts")
    assert [(s["name"], s["kind"]) for s in multi["symbols"]] == [
        ("x", "const"), ("y", "const"), ("z", "const")]


def test_unhandled_export_forms_are_recorded():
    """R376：没被解析的 export 形态必须记 degraded（GC31），不许静默零产出。"""
    r = tsjs.parse_source('export default 42;\nexport * from "./other";\n', "odd.ts")
    assert r["symbols"] == []
    hits = [d for d in r["degraded"] if "export 形态第一版未解析" in d]
    assert len(hits) == 2, r["degraded"]
    assert all("行号" in d for d in hits)


def test_degraded_snippet_quotes_original_not_masked():
    """R483：降级片段取自原文——掩码把字符串内容换成空格，读者必须看得到真实 specifier。"""
    r = tsjs.parse_source('export * from "./m.js";\n', "m.ts")
    reasons = [d for d in r["degraded"] if "export 形态第一版未解析" in d]
    assert len(reasons) == 1, r["degraded"]
    assert "./m.js" in reasons[0], reasons[0]
    assert not re.search(r" {4,}", reasons[0]), reasons[0]


def test_degraded_snippet_keeps_spaces_the_source_itself_has():
    """R483 豁免：原文这行本来就含 4+ 连续空格，片段如实照抄，不许为了过断言去压空格。"""
    r = tsjs.parse_source('export *    from "./m.js";\n', "spaced.ts")
    reason = next(d for d in r["degraded"] if "export 形态第一版未解析" in d)
    assert reason.split("：", 1)[1].split("（行号")[0] == 'export *    from "./m.js";', reason
    assert "./m.js" in reason


def test_crossline_script_tag_offset_and_dotted_import_call():
    """R378/R379：跨行开标签按结束位置算偏移；foo.import() 不是动态 import。"""
    text = ('<template><div /></template>\n'
            '\n'
            '<script\n'
            '  lang="ts"\n'
            '  setup\n'
            '>\n'
            'import { a } from "./a.js";\n'
            'const b = 1;\n'
            'foo.import("./ghost.js");\n'
            '</script>\n')
    r = vue.parse_source(text, "Cross.vue")
    assert [(i["line"], i["specifier"]) for i in r["imports"]] == [(7, "./a.js")]
    assert [i for i in r["imports"] if i["dynamic"]] == []


def test_multi_declarator_with_call_arguments_is_split_at_depth_zero():
    """R380：多声明符按深度 0 切——裸 split(',') 会把 f(a, b) 的实参切成碎片名。"""
    d = scratch_dir("glossa-t4-r380-multi")
    f = d / "Pair.ts"
    f.write_text("export const pair = f(a, b), z = 3;\n", encoding="utf-8")
    r = tsjs.parse_source(f.read_text(encoding="utf-8"), "Pair.ts")
    assert {s["name"] for s in r["symbols"]} == {"pair", "z"}, r["symbols"]
    assert all(s["kind"] == "const" for s in r["symbols"]), r["symbols"]
    assert [x for x in r["degraded"] if "export 形态第一版未解析" in x] == [], r["degraded"]


def test_const_enum_symbol_is_named_after_enum():
    """R377/R380：export const enum 抓 Direction、kind='enum'，不许产出名为 enum 的符号。"""
    d = scratch_dir("glossa-t4-r380-enum")
    f = d / "Direction.ts"
    f.write_text("export const enum Direction { Up, Down }\n", encoding="utf-8")
    r = tsjs.parse_source(f.read_text(encoding="utf-8"), "Direction.ts")
    assert len(r["symbols"]) == 1, r["symbols"]
    assert r["symbols"][0]["name"] == "Direction", r["symbols"]
    assert r["symbols"][0]["kind"] == "enum", r["symbols"]
    assert [s for s in r["symbols"] if s["name"] == "enum"] == [], r["symbols"]

