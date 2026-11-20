"""M1b：算子必须落到真实 file:line；拿不到证据就诚实回落，绝不编造。"""

from __future__ import annotations
from tests.common import ROOT

import ast
import pathlib

import pytest

from papertrace.parse_code.loc import loc_from_stack_trace

FIXTURE = str(ROOT / "tests" / "fixtures" / "nanogpt")
LOC_MODULE = ROOT / "papertrace" / "parse_code" / "loc.py"

USER = r"D:\work\proj\train.py"
HELPERS = r"D:\work\proj\helpers.py"
TORCH = r"C:\py\pydeps\torch\nn\modules\linear.py"
SITE = r"C:\py\Lib\site-packages\torch\nn\functional.py"


def _trace(*frames):
    """拼一段像 CPython traceback 的文本：每帧一行 File "…", line N, in fn。"""
    out = []
    for path, lineno, func in frames:
        out.append(f'  File "{path}", line {lineno}, in {func}')
        out.append("    return _forward(x)")
    return "\n".join(out)


def test_returns_first_user_frame_with_line():
    text = _trace((USER, 42, "forward"), (HELPERS, 7, "run"))
    assert loc_from_stack_trace(text) == f"{USER}:42"


def test_skips_torch_internal_frames():
    text = _trace((TORCH, 142, "forward"), (USER, 42, "forward"))
    assert loc_from_stack_trace(text) == f"{USER}:42"


def test_skips_site_packages_and_pydeps():
    text = _trace((SITE, 5, "relu"), (TORCH, 9, "forward"), (USER, 42, "forward"))
    assert loc_from_stack_trace(text) == f"{USER}:42"


def test_empty_string_returns_empty():
    assert loc_from_stack_trace("") == ""


def test_none_returns_empty():
    assert loc_from_stack_trace(None) == ""


def test_no_frames_return_empty():
    assert loc_from_stack_trace("Traceback (most recent call last):\n  boom") == ""


def test_all_library_frames_return_empty():
    text = _trace((SITE, 5, "relu"), (TORCH, 9, "forward"))
    assert loc_from_stack_trace(text) == ""


def test_real_trace_gives_real_locations():
    pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")
    from papertrace.build.trace import build_trace
    from papertrace.parse_code.fx_trace import _ensure_export_cache

    _ensure_export_cache()
    doc = build_trace(FIXTURE, entry="model:build_model")
    ops = [n for n in doc["nodes"] if n.get("kind") == "op"]
    assert len(ops) == 75, f"kind==op 的节点数变了：{len(ops)}"
    for node in ops:
        loc = node["loc"]
        assert loc != "model.GPT", f"{node['label']} 仍停在模块路径，没落到行"
        assert ".py:" in loc, f"{node['label']} 的 loc 不是 file:line：{loc!r}"
        path, _, lineno = loc.rpartition(":")
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
        row = int(lineno)
        assert pathlib.Path(path).is_file(), f"{node['label']} 指向不存在的文件：{path}"
        assert 1 <= row <= len(lines), f"{node['label']} 行号越界：{row}/{len(lines)}"
        assert lines[row - 1].strip(), f"{node['label']} 落在空行：{loc}"


def test_placeholder_nodes_fall_back_to_root_loc():
    pytest.importorskip("torch", reason="真实追踪需要 torch（CPU 版即可）")
    from papertrace.build.trace import build_trace
    from papertrace.parse_code.fx_trace import _ensure_export_cache

    _ensure_export_cache()
    doc = build_trace(FIXTURE, entry="model:build_model")
    placeholders = [
        n for n in doc["nodes"] if n.get("kind") in ("param", "input")
    ]
    assert placeholders, "没有 placeholder 节点，测试前提不成立"
    for node in placeholders:
        assert node["loc"] == "model.GPT", f"{node['label']} 没回落 root_loc：{node['loc']!r}"


def test_loc_module_does_not_import_torch():
    tree = ast.parse(LOC_MODULE.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    assert not [name for name in names if name == "torch" or name.startswith("torch.")], (
        f"loc.py 不许 import torch，实际 import 了：{names}"
    )
