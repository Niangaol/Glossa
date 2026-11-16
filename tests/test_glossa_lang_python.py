"""T3：Python 精确解析。夹具行号是冻结事实。"""
import sys
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
        "def marker_func():\n"
        "    return 1\n"
        "pathlib.Path('" + target + "').write_text('x')\n"
        "raise RuntimeError('BOOM')\n", encoding="utf-8")
    r = pylang.parse_source(victim.read_text(encoding="utf-8"), "victim.py")
    assert r["parse"] == "exact"          # 语法合法，只是运行时才炸
    assert not (d / "PWNED").exists()     # GC29：绝不执行
    # R370：只钉「没执行」会放过「解析了但零产出」——实现把 return 换成常量空
    # exact dict 时上面两条照样绿。同一份文本必须真的给出事实。
    assert [s["name"] for s in r["symbols"]] == ["marker_func"]
    assert r["symbols"][0]["kind"] == "function"
    assert r["symbols"][0]["line"] == 2
    assert [i["module"] for i in r["imports"]] == ["pathlib"]
    assert r["degraded"] == []


def test_deep_expression_does_not_raise_and_degrades():
    # R369：合法长表达式让 _collect 自己的递归炸掉 —— parse_source 不许抛。
    # 阈值不钉 1000（各机递归上限不同）：按本机上限抬到「必然溢出」的深度。
    n = max(1000, sys.getrecursionlimit() + 200)
    d = scratch_dir("glossa-t3-deep")
    p = d / "deep.py"
    p.write_text("x = " + "+".join(["1"] * n) + "\n", encoding="utf-8")
    try:
        r = pylang.parse_source(p.read_text(encoding="utf-8"), "deep.py")
    except RecursionError:                # 这一行本身就是断言：不许穿透
        raise AssertionError("packed: parse_source 因递归深度抛出")
    assert r["parse"] == "exact"          # 语法解析成功，不许谎报 skipped
    assert isinstance(r["symbols"], list)  # 已收集的保留（可为空或部分）
    assert any("嵌套过深" in note for note in r["degraded"]), r["degraded"]


def test_ast_parse_recursion_is_skipped_not_raised():
    # R374：R369 只堵了 _collect 的递归；ast.parse 自己在 ~6 KB 的长表达式上
    # 仍会抛 RecursionError（"during ast construction"）。那一步 parser 真没成功，
    # 所以必须如实返回 skipped，且 degraded 要点名「不代表语法有错」。
    # 断言不钉项数（各机递归上限不同），只钉「不抛 + skipped + degraded 有记」。
    n = max(4000, sys.getrecursionlimit() * 4)
    d = scratch_dir("glossa-t3-parse-deep")
    p = d / "parse_deep.py"
    p.write_text("x = " + "+".join(["1"] * n) + "\n", encoding="utf-8")
    try:
        r = pylang.parse_source(p.read_text(encoding="utf-8"), "parse_deep.py")
    except RecursionError:                # 这一行本身就是断言：不许穿透
        raise AssertionError("packed: ast.parse 的 RecursionError 穿透了 parse_source")
    assert r["parse"] == "skipped"        # parser 真的没完成，skipped 是事实（不违反 R369）
    assert r["symbols"] == []
    assert r["imports"] == []
    assert any("ast.parse" in note and "不代表语法有错" in note
               for note in r["degraded"]), r["degraded"]
