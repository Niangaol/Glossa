"""T2：manifest 与入口（csproj / sln / 入口部分）。

R480：从 test_glossa_manifests.py 原样拆出（断言逐字保留，测试条数不变）；workspace 与包扫描
留在 test_glossa_manifests.py。
"""
from tests.common import FIXTURES
import shutil
from pathlib import Path

from glossa import entries, manifests, manifests_cs, scan
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"


def _scan(name):
    dst = scratch_dir("glossa-t2b-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst, scan.scan_repo(dst)


def test_npm_scripts_become_entries_with_target_files():
    root, sc = _scan("ts-monorepo")
    m = manifests.read_manifests(root, sc["files"])
    es = entries.find_entries(root, sc['files'], m)
    serve = next(e for e in es if e["name"] == "serve")
    assert serve["kind"] == "npm_script"
    assert serve["command"] == "tsx packages/a/src/server.ts"
    assert serve["target"] == "file:packages/a/src/server.ts"


def test_compound_shell_command_has_no_single_target():
    root, sc = _scan("ts-monorepo")
    m = manifests.read_manifests(root, sc["files"])
    es = entries.find_entries(root, sc['files'], m)
    check = next(e for e in es if e["name"] == "check")
    assert check["target"] is None
    assert "未指向单文件" in check["note"]


def test_pyproject_scripts_and_main_guard_are_entries():
    root, sc = _scan("py-mini")
    pyproj = root / "pyproject.toml"
    pyproj.write_text(pyproj.read_text(encoding="utf-8") + 'ghost = "nosuchmod:cli"\n',
                      encoding="utf-8")          # R345：模块找不到时必须 None + note
    sc = scan.scan_repo(root)
    m = manifests.read_manifests(root, sc["files"])
    es = entries.find_entries(root, sc['files'], m)
    kinds = {(e["kind"], e["name"]) for e in es}
    assert ("py_script", "py-mini") in kinds
    assert ("py_script", "ghost") in kinds
    assert ("main_guard", "main.py") in kinds
    script = next(e for e in es if e["kind"] == "py_script" and e["name"] == "py-mini")
    assert script["target"] == "file:main.py"
    ghost = next(e for e in es if e["name"] == "ghost")
    assert ghost["target"] is None
    assert "nosuchmod" in ghost["note"]
    # R361：函数体内的守卫不是入口（临时正则必须锚在第 0 列）
    (root / "nested.py").write_text("def f():\n    if __name__ == '__main__':\n        pass\n",
                                    encoding="utf-8")
    sc = scan.scan_repo(root)
    m = manifests.read_manifests(root, sc["files"])
    es = entries.find_entries(root, sc['files'], m)
    assert ("main_guard", "nested.py") not in {(e["kind"], e["name"]) for e in es}


def test_csproj_and_sln_are_read():
    root, sc = _scan("cs-solution")
    cs = manifests_cs.read_cs_projects(root, sc["files"])
    names = {p["name"] for p in cs["projects"]}
    assert names == {"Demo.Core", "Demo.App"}
    core = next(p for p in cs["projects"] if p["name"] == "Demo.Core")
    assert core["target_framework"] == "net8.0"
    assert core["implicit_usings"] is True
    assert core["root_namespace"] == "Demo.Core"
    assert core["output_type"] == "Library"      # R346：缺 OutputType 的默认值
    assert core["package_refs"] == [
        {"name": "Microsoft.Data.Sqlite", "version": "8.0.11"}]
    app = next(p for p in cs["projects"] if p["name"] == "Demo.App")
    assert app["project_refs"] == ["Demo.Core"]
    assert app["output_type"] == "WinExe"
    assert cs["sln"]["projects"] == ["Demo.App", "Demo.Core"]   # 升序
    assert cs["sln"]["folders_dropped"] == 1                  # R270


def test_csproj_implicit_usings_records_degraded():
    root, sc = _scan("cs-solution")
    cs = manifests_cs.read_cs_projects(root, sc["files"])
    hit = [d for d in cs["degraded"] if d["scope"] == "project:Demo.Core"]
    assert len(hit) == 1
    assert "隐式全局 using" in hit[0]["reason"]


def test_dotnet_exe_project_is_an_entry():
    root, sc = _scan("cs-solution")
    m = manifests.read_manifests(root, sc["files"])
    assert m["packages"] == []                                        # R347
    assert m["python"] == {"name": None, "scripts": {}, "deps": []}    # R347
    assert m["degraded"] == []                 # 没有 Python manifest 不是降级
    cs = manifests_cs.read_cs_projects(root, sc["files"])
    es = entries.find_entries(root, sc['files'], m, cs)
    hit = [e for e in es if e["kind"] == "dotnet_project"]
    assert [e["name"] for e in hit] == ["Demo.App"]
    assert hit[0]["target"] == "project:Demo.App"
