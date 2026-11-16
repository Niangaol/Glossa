"""T5：C# 符号级近似解析。行号是实测冻结事实。"""
from pathlib import Path

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
