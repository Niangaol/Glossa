"""T3：Python 精确解析。夹具行号是冻结事实。"""
from pathlib import Path

from glossa.lang import python as pylang
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"


def _read(name, rel):
    return (FIX / name / rel).read_text(encoding="utf-8")


def test_imports_capture_relative_level():
    r = pylang.parse_source(_read("py-mini", "pkg/sub/util.py"), "pkg/sub/util.py")
    imp = next(i for i in r["imports"] if i["module"] == "core")
    assert imp["level"] == 2
    assert imp["names"] == ["Thing"]
    assert imp["specifier"] == "..core"


def test_plain_import_has_level_zero_and_no_names():
    r = pylang.parse_source(_read("py-mini", "pkg/core.py"), "pkg/core.py")
    imp = next(i for i in r["imports"] if i["specifier"] == "os")
    assert imp["level"] == 0
    assert imp["names"] == []
    # R351/R352（控制器强化，条数不变）：多 alias 与 from . import x
    d = scratch_dir("glossa-t3-imports")
    p = d / "multi.py"
    p.write_text("import os, sys\nfrom . import helper\n", encoding="utf-8")
    r2 = pylang.parse_source(p.read_text(encoding="utf-8"), "multi.py")
    by = {i["specifier"]: i for i in r2["imports"]}
    assert set(by) == {"os", "sys", "."}
    assert by["sys"]["module"] == "sys" and by["sys"]["names"] == []
    assert by["."]["module"] is None and by["."]["names"] == ["helper"]
    assert by["."]["level"] == 1


def test_symbols_have_line_and_end_line():
    r = pylang.parse_source(_read("py-mini", "pkg/core.py"), "pkg/core.py")
    by = {s["name"]: s for s in r["symbols"]}
    assert by["Thing"]["line"] == 8
    assert by["Thing"]["end_line"] == 14
    assert by["Thing"]["kind"] == "class"
    assert by["fetch"]["line"] == 16
    assert by["fetch"]["kind"] == "async_function"
    assert by["fetch"]["end_line"] == 17


def test_nested_symbols_are_recorded_with_parent():
    r = pylang.parse_source(_read("py-mini", "pkg/core.py"), "pkg/core.py")
    by = {s["name"]: s for s in r["symbols"]}
    assert by["method"]["parent"] == "Thing"
    assert by["method"]["kind"] == "method"
    assert by["Inner"]["parent"] == "Thing"
    assert by["Thing"]["parent"] is None


def test_docstring_first_line_only():
    r = pylang.parse_source(_read("py-mini", "pkg/core.py"), "pkg/core.py")
    assert r["doc_first_line"] == "核心模块。"
    assert "第二行" not in repr(r)


def test_syntax_error_is_skipped_not_raised():
    r = pylang.parse_source(_read("py-broken", "bad.py"), "bad.py")
    assert r["parse"] == "skipped"
    assert r["symbols"] == []
    assert any("SyntaxError" in d for d in r["degraded"])


def test_main_guard_detected():
    assert pylang.parse_source(_read("py-mini", "main.py"), "main.py")["main_guard"] is True
    assert pylang.parse_source(_read("py-mini", "pkg/core.py"), "pkg/core.py")["main_guard"] is False
    # R353（控制器强化）：函数体内的守卫不算入口；反向比较也认
    d = scratch_dir("glossa-t3-guard")
    nested = d / "nested.py"
    nested.write_text("def f():\n    if __name__ == '__main__':\n        pass\n", encoding="utf-8")
    assert pylang.parse_source(nested.read_text(encoding="utf-8"), "nested.py")["main_guard"] is False
    rev = d / "rev.py"
    rev.write_text("if '__main__' == __name__:\n    pass\n", encoding="utf-8")
    assert pylang.parse_source(rev.read_text(encoding="utf-8"), "rev.py")["main_guard"] is True


def test_no_execution_of_target_code():
    d = scratch_dir("glossa-t3-noexec")
    victim = d / "victim.py"
    target = (d / "PWNED").as_posix()
    victim.write_text(
        "import pathlib\n"
        "pathlib.Path('" + target + "').write_text('x')\n"
        "raise RuntimeError('BOOM')\n", encoding="utf-8")
    r = pylang.parse_source(victim.read_text(encoding="utf-8"), "victim.py")
    assert r["parse"] == "exact"          # 语法合法，只是运行时才炸
    assert not (d / "PWNED").exists()     # GC29：绝不执行
