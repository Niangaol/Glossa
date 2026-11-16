"""T5：C# 符号级近似解析。行号是实测冻结事实。"""
from pathlib import Path

from glossa import resolve_cs
from glossa.lang import csharp
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos" / "cs-solution"
POKEMON = "src/Demo.Core/Models/Pokemon.cs"
VM = "src/Demo.App/ViewModels/MainViewModel.cs"


def _read(rel):
    return (FIX / rel).read_text(encoding="utf-8")


def test_file_scoped_namespace_is_detected():
    r = csharp.parse_source(_read(POKEMON), POKEMON)
    assert r["namespaces"] == [
        {"name": "Demo.Core.Models", "line": 3, "style": "file_scoped"}]
    assert r["parse"] == "approx"


def test_block_namespace_and_partial_class_with_base():
    r = csharp.parse_source(_read(VM), VM)
    assert r["namespaces"] == [
        {"name": "Demo.App.ViewModels", "line": 5, "style": "block"}]
    cls = next(s for s in r["symbols"] if s["name"] == "MainViewModel")
    assert cls["kind"] == "class"
    assert cls["line"] == 8
    assert cls["partial"] is True
    assert cls["bases"] == ["ObservableObject"]
    assert cls["namespace"] == "Demo.App.ViewModels"


def test_symbol_kinds_and_lines_match_measured_truth():
    r = csharp.parse_source(_read(POKEMON), POKEMON)
    got = [(s['name'], s['kind'], s['line']) for s in r['symbols']]
    assert got == [
        ("Kind", "enum", 5),
        ("Pokemon", "record", 7),
        ("Repository", "class", 9),
        ("Items", "property", 11),
        ("FindAsync", "method", 13)]
    find = next(s for s in r["symbols"] if s["name"] == "FindAsync")
    assert find["async"] is True
    assert find["parent"] == "Repository"
    v = csharp.parse_source(_read(VM), VM)
    got_v = [(s['name'], s['kind'], s['line']) for s in v['symbols']
             if s['name'] != 'MainViewModel']
    assert got_v == [
        ("_host", "field", 10),
        ("StatusText", "property", 12),
        ("Navigate", "method", 14)]


def test_attribute_attaches_to_the_next_symbol():
    r = csharp.parse_source(_read(VM), VM)
    cls = next(s for s in r["symbols"] if s["name"] == "MainViewModel")
    assert cls["attributes"] == ["ObservableProperty"]


def test_usings_are_extracted_with_line_and_modifiers():
    r = csharp.parse_source(_read(POKEMON), POKEMON)
    assert r["imports"] == [
        {"specifier": "System.Linq", "line": 1, "static": False, "alias": None}]
    v = csharp.parse_source(_read(VM), VM)
    assert [(i['specifier'], i['line']) for i in v['imports']] == [
        ("CommunityToolkit.Mvvm.ComponentModel", 1),
        ("Demo.Core.Models", 2),
        ("System.Windows.Input", 3)]


def test_comments_and_strings_are_masked_in_csharp():
    d = scratch_dir("glossa-t5-mask")
    f = d / "Mask.cs"
    f.write_text(
        "// using Fake.One;\n"
        "/* using Fake.Two; */\n"
        'var s = "using Fake.Three;";\n'
        "using Real.Four;\n"
        "namespace Demo;\n", encoding="utf-8")
    r = csharp.parse_source(f.read_text(encoding="utf-8"), "Mask.cs")
    assert [i['specifier'] for i in r['imports']] == ['Real.Four']
    assert r['imports'][0]['line'] == 4


# --- R381–R386 冻结测试（T5 修复轮 1） ---


def _parse(src):
    return csharp.parse_source(src, "X.cs")


_SHAPE = {"symbols", "imports", "namespaces", "doc_first_line", "main_guard",
          "parse", "degraded"}


def test_generic_constraint_is_not_a_base_class():
    r = _parse("namespace N;\n"
               "public class A<T> where T : class\n{\n}\n"
               "public class B<T> : Base where T : new()\n{\n}\n"
               "public class C<T>\n{\n}\n")
    bases = {s["name"]: s["bases"] for s in r["symbols"]}
    assert bases == {"A": [], "B": ["Base"], "C": []}
    assert not any(b in ("class", "struct", "new()", "notnull")
                   for got in bases.values() for b in got)


def test_assembly_and_body_attributes_do_not_leak_to_symbols():
    r = _parse('[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]\n'
               "namespace N;\n"
               "public class A\n{\n"
               "    public void M()\n    {\n"
               "        [MyAttr] int local = 1;\n"
               "    }\n"
               "    public int P { get; }\n"
               "}\n"
               "[Serializable]\n"
               "public class B { }\n")
    by = {s["name"]: s for s in r["symbols"]}
    assert by["A"]["attributes"] == []
    assert by["M"]["attributes"] == []
    assert by["P"]["attributes"] == []
    assert by["B"]["attributes"] == ["Serializable"]      # 正例：紧邻的仍要贴


def test_generic_methods_are_captured():
    r = _parse("namespace N;\npublic class C\n{\n"
               "    public T Get<T>(string id)\n    {\n        return default;\n    }\n"
               "    public async Task<List<T>> LoadAsync<T>(int id) => null;\n}\n")
    got = {s["name"]: s for s in r["symbols"]}
    assert got["Get"]["kind"] == "method"
    assert got["LoadAsync"]["kind"] == "method"
    assert got["LoadAsync"]["async"] is True


def test_single_line_bodies_are_captured():
    r = _parse("namespace N;\npublic class C\n{\n"
               "    public void A() { }\n"
               "    public void B() { return; }\n"
               "    public int Count\n{\n        get { return 1; }\n    }\n}\n")
    got = {s["name"]: s["kind"] for s in r["symbols"]}
    assert got["A"] == got["B"] == "method"
    assert got["Count"] == "property"


def test_event_required_indexer_and_operator_are_captured():
    r = _parse("namespace N;\npublic class C\n{\n"
               "    public event System.EventHandler Changed;\n"
               "    public required string Name { get; init; }\n"
               "    public int this[int i] => 0;\n"
               '    public (int, string) Pair() => (1, "");\n'
               "    public static implicit operator int(C c) => 0;\n}\n")
    got = {s["name"]: s["kind"] for s in r["symbols"]}
    assert got["Changed"] == "field"
    assert got["Name"] == "property"
    assert got["this"] == "property"
    assert got["Pair"] == "method"
    assert got["operator"] == "method"


def test_using_modifiers_are_preserved():
    r = _parse("using static System.Math;\nusing IO = System.IO;\nnamespace N;\n")
    assert r["imports"] == [
        {"specifier": "System.Math", "line": 1, "static": True, "alias": None},
        {"specifier": "System.IO", "line": 2, "static": False, "alias": "IO"}]
    us = resolve_cs.resolve_usings([{"path": "U.cs", **r}], [])
    assert [u["kind"] for u in us] == ["builtin", "builtin"]
    assert all(u["target"] is None for u in us)


def test_namespace_prefix_must_be_exact_and_microsoft_is_not_builtin():
    files = [{"path": "src/Demo/Core.cs", "namespaces": [{"name": "Demo.Core"}]},
             {"path": "src/App/App.cs",
              "imports": [{"specifier": "Demo.CoreX.Models", "line": 1},
                          {"specifier": "Microsoft.Win32", "line": 2}]}]
    ghost, ms = resolve_cs.resolve_usings(files, [])
    assert ghost["kind"] == "unresolved"          # 禁裸 startswith：不许命中 Demo.Core
    assert ghost["files"] == [] and ghost["namespace"] is None
    assert ms["kind"] == "unresolved"             # 无 PackageReference 不许猜 builtin
    assert "框架" in ms["reason"]
    near = resolve_cs.resolve_usings(
        [{"path": "src/Demo/CoreX.cs", "namespaces": [{"name": "Demo.CoreX"}]},
         {"path": "src/App/Near.cs", "imports": [{"specifier": "Demo.Core"}]}], [])
    assert near[0]["kind"] == "unresolved"        # 声明 Demo.CoreX 不许被 using Demo.Core 命中


def test_unbalanced_brace_multinamespace_and_verbatim_are_reported():
    cases = [
        ("namespace A;\nnamespace B;\npublic class C { }\n", "多个 namespace"),
        ("namespace N;\npublic class C\n{\n    public void M()\n    {\n", "未闭合"),
        ('namespace N;\npublic class C\n{\n    public string S = @"C:\\tmp";\n}\n',
         "verbatim"),
    ]
    for src, needle in cases:
        r = _parse(src)                            # 不许抛异常
        assert set(r) == _SHAPE
        assert any(needle in d for d in r["degraded"]), (needle, r["degraded"])
