"""T5：using 四态 + 项目级边。namespace 态 target 必须 None（GC34）。"""
from tests.common import FIXTURES
import shutil
from pathlib import Path

from glossa import manifests_cs, resolve_cs, scan
from glossa.lang import csharp
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos" / "cs-solution"


def _analyze():
    dst = scratch_dir("glossa-t5-cs")
    shutil.copytree(FIX, dst, dirs_exist_ok=True)
    sc = scan.scan_repo(dst)
    cs = manifests_cs.read_cs_projects(dst, sc["files"])
    files = []
    for f in sc["files"]:
        if f["lang"] != "csharp":
            continue
        text = (dst / f["path"]).read_text(encoding="utf-8")
        files.append({**f, **csharp.parse_source(text, f["path"])})
    return dst, cs, files


def test_system_usings_are_builtin():
    _, cs, files = _analyze()
    us = resolve_cs.resolve_usings(files, cs["projects"])
    by = {(u['from'], u['specifier']): u for u in us}
    a = by[('src/Demo.Core/Models/Pokemon.cs', 'System.Linq')]
    b = by[('src/Demo.App/ViewModels/MainViewModel.cs', 'System.Windows.Input')]
    assert a['kind'] == b['kind'] == 'builtin'
    assert a['target'] is None and b['target'] is None


def test_package_reference_using_is_external():
    _, cs, files = _analyze()
    us = resolve_cs.resolve_usings(files, cs["projects"])
    hit = next(u for u in us
               if u['specifier'] == 'CommunityToolkit.Mvvm.ComponentModel')
    assert hit['kind'] == 'external'
    assert hit['package'] == 'CommunityToolkit.Mvvm'
    assert hit['target'] is None


def test_repo_namespace_using_has_null_target_and_file_hits():
    _, cs, files = _analyze()
    us = resolve_cs.resolve_usings(files, cs["projects"])
    hit = next(u for u in us if u['specifier'] == 'Demo.Core.Models')
    assert hit['kind'] == 'namespace'
    assert hit['target'] is None                 # GC34 硬约束
    assert hit['namespace'] == 'Demo.Core.Models'
    assert hit['files'] == ['src/Demo.Core/Models/Pokemon.cs']


def test_unknown_using_is_unresolved_and_project_reference_is_an_edge():
    dst, cs, files = _analyze()
    extra = dst / "src" / "Demo.App" / "Extra.cs"
    extra.write_text("using Foo.Bar;\nnamespace Demo.App;\n", encoding="utf-8")
    files.append({"path": "src/Demo.App/Extra.cs", "lang": "csharp",
                  **csharp.parse_source(extra.read_text(encoding="utf-8"),
                                        "src/Demo.App/Extra.cs")})
    us = resolve_cs.resolve_usings(files, cs["projects"])
    hit = next(u for u in us if u['specifier'] == 'Foo.Bar')
    assert hit['kind'] == 'unresolved'
    assert hit['target'] is None
    edges = resolve_cs.project_edges(cs["projects"])
    assert edges == [{'from': 'project:Demo.App',
                      'to': 'project:Demo.Core',
                      'kind': 'internal_project'}]
