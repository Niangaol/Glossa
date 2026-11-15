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
    # 同盘但不在 base 之下（仓库的上级目录）：同样原样返回，不造 '..\\..'
    assert pathlib.Path.cwd().parent != pathlib.Path.cwd(), "仓库目录不该是盘符根目录"
    above = pathlib.Path.cwd().parent / "elsewhere" / "model.py"
    assert portable_path(str(above)) == str(above)


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
