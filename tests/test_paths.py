"""路径便携化：trace.json 不许带出本机目录结构。

背景：meta.repo.url / meta.paper.source / nodes[*].loc / symbols[*].defined_at
原本全是 D:\\... 这样的本机绝对路径，分享 trace.json 等于把发件人的
目录结构一起发出去。本测试钉死 papertrace.paths 的三个函数。

纪律：路径一律动态取（pathlib.Path.cwd() / scratch_dir），
不硬编码盘符——换一台机器这些测试必须照样绿。
"""

from __future__ import annotations

import pathlib

from _tmp import scratch_dir

from papertrace import paths as paths_module
from papertrace.paths import portable_loc, portable_path, relativize_doc


def test_portable_path_makes_paths_under_base_relative():
    """base 之下的绝对路径 → 相对路径，分隔符一律用 '/'，绝不带盘符。"""
    base = scratch_dir("portable-path-under")
    target = base / "sub" / "model.py"
    assert portable_path(str(target), base) == "sub/model.py"
    # base 自身 → '.'，也不算泄漏
    assert portable_path(str(base), base) == "."


def test_portable_path_keeps_paths_outside_base():
    """base 之外的绝对路径原样返回：不抛 ValueError，更不硬造 '..\\..' 跳出形态。"""
    drive = pathlib.Path.cwd().drive  # 形如 'D:'，换机器自动跟着变
    letter = "Z" if drive[:1].upper() != "Z" else "Y"
    other_drive = pathlib.Path(f"{letter}:\\elsewhere\\model.py")
    assert portable_path(str(other_drive)) == str(other_drive)
    # 同盘但不在 base 之下（base 的上级目录）：同样原样返回，不造 '..\\..'。
    # base 显式传 scratch_dir：原先那条 `cwd().parent != cwd()` 在盘根目录
    # （cwd 就是盘符根）会假失败，而那不是本测试要测的东西。
    above_base = scratch_dir("portable-path-above")
    above = above_base.parent / "elsewhere" / "model.py"
    assert portable_path(str(above), above_base) == str(above)


def test_portable_path_converts_separators_for_relative_input():
    """相对路径本来就是便携形态：只把 '\\' 换成 '/'，不解析、不拼 base。"""
    assert portable_path("src\\model.py") == "src/model.py"
    assert portable_path("src/model.py") == "src/model.py"


def test_portable_path_passes_empty_string_through():
    """空串是"没有路径"，原样返回。"""
    assert portable_path("") == ""


def test_portable_loc_rewrites_file_line_only():
    """只有 '<路径>:<纯数字行号>' 才动手；模块路径（冒号后不是数字）原样返回。"""
    base = scratch_dir("portable-loc-file")
    target = base / "sub" / "model.py"
    assert portable_loc(f"{target}:147", base) == "sub/model.py:147"
    # 模块路径不是文件：冒号后没有行号，原样
    assert portable_loc("model.GPT") == "model.GPT"
    # 空串原样
    assert portable_loc("") == ""


def test_relativize_doc_covers_all_four_fields():
    """四处字段各来一条绝对路径：四条都变相对，返回改动条数 4。"""
    base = scratch_dir("relativize-doc-four")
    abs_loc = str(base / "pkg" / "model.py")
    doc = {
        "meta": {
            "repo": {"url": str(base / "repo"), "commit": "abc123"},
            "paper": {"source": str(base / "p.md")},
            "runtime": {"cwd": str(base)},
        },
        "nodes": [{"id": "node_0", "loc": f"{abs_loc}:10"}],
        "symbols": {"code": [{"name": "GPT", "defined_at": f"{abs_loc}:20"}]},
    }
    assert relativize_doc(doc, base) == 4
    assert doc["meta"]["repo"]["url"] == "repo"
    assert doc["meta"]["paper"]["source"] == "p.md"
    assert doc["nodes"][0]["loc"] == "pkg/model.py:10"
    assert doc["symbols"]["code"][0]["defined_at"] == "pkg/model.py:20"
    # 白名单之外的字段一个字节都不许动
    assert doc["meta"]["repo"]["commit"] == "abc123"
    assert doc["meta"]["runtime"]["cwd"] == str(base)
    assert doc["nodes"][0]["id"] == "node_0"


def test_relativize_doc_tolerates_minimal_doc():
    """minimal / skeleton trace 缺键、None、非 str：一律跳过不抛，返回 0。"""
    assert relativize_doc({}) == 0
    doc = {"meta": {}, "nodes": [{"loc": None}, {}], "symbols": {"code": []}}
    assert relativize_doc(doc) == 0
    assert doc["nodes"][0]["loc"] is None


def test_relativize_doc_leaves_module_paths_alone():
    """nodes[*].loc 走 portable_loc：模块路径保持原样，只有真文件路径被改写。"""
    base = scratch_dir("relativize-doc-module")
    abs_loc = str(base / "pkg" / "model.py")
    doc = {
        "nodes": [
            {"id": "n0", "loc": f"{abs_loc}:10"},
            {"id": "n1", "loc": "model.GPT"},
        ]
    }
    assert relativize_doc(doc, base) == 1
    assert doc["nodes"][0]["loc"] == "pkg/model.py:10"
    assert doc["nodes"][1]["loc"] == "model.GPT"


def test_leaked_absolute_reports_only_real_local_paths():
    """R154：泄漏诊断只认「真的是本机绝对路径」的值，URL 与模块路径不算。

    三类算泄漏：盘符（D:\\ / D:/）、UNC（\\\\srv\\share）、POSIX 根（/tmp）。
    https:// 的 scheme 会被 Windows 的 PurePath 当成盘符（路径评审 M4 实测过），
    所以任何含 :// 的串一律不算——否则 GitHub URL 会被当成泄漏刷屏。
    """
    base = scratch_dir("leaked-abs")
    doc = {
        "meta": {
            "repo": {"url": "D:\\a\\b.py"},
            "paper": {"source": "\\\\srv\\share\\x"},
        },
        "nodes": [
            {"id": "n0", "loc": "/tmp/x"},
            {"id": "n1", "loc": "https://github.com/x/y"},
            {"id": "n2", "loc": "model.GPT"},
            {"id": "n3", "loc": "tests/fixtures/x"},
            {"id": "n4", "loc": "D:\\a\\b.py:12"},
            {"id": "n5", "loc": "{}:12"},
        ],
        "symbols": {"code": [{"name": "GPT", "defined_at": "D:\\a\\b.py:20"}]},
    }
    fn = getattr(paths_module, "leaked_absolute", None)
    assert callable(fn), "R154：papertrace/paths.py 还没有 leaked_absolute(doc, base) 诊断函数"
    # 原值返回（不改写、不去重、按字段顺序），loc 形态只判 head
    assert fn(doc, base) == [
        "D:\\a\\b.py",
        "\\\\srv\\share\\x",
        "/tmp/x",
        "D:\\a\\b.py:12",
        "D:\\a\\b.py:20",
    ], fn(doc, base)
    # base 之下的绝对路径会被相对化，不算泄漏（否则一切正常的构建也喊狼来了）
    inside = str(base / "pkg" / "model.py")
    assert fn({"nodes": [{"id": "n", "loc": f"{inside}:10"}]}, base) == [], "在 base 之下不算泄漏"
    # 空串 / None / 非 str / 缺键：一律跳过不抛
    empty = {
        "meta": {"repo": {"url": ""}, "paper": {"source": None}},
        "nodes": [{"loc": None}, {}],
    }
    assert fn(empty, base) == []
    assert fn({}, base) == []
