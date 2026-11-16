"""T9：组件注册表与校验。数字来自真跑夹具。"""
import shutil
from pathlib import Path

import pytest

from glossa import facts
from glossa.explain import components
from papertrace.exceptions import BuildError
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"
NAMES = {"text", "custom", "overview", "metrics", "dir_tree", "package_map",
         "project_map", "entry_list", "import_graph", "file_card",
         "symbol_table", "code", "table", "bonus"}


def _doc(name='ts-monorepo', **kw):
    dst = scratch_dir("glossa-t9-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return facts.build_repo_doc(dst, **kw)


def test_registry_has_exactly_fourteen_components():
    assert set(components.COMPONENTS) == NAMES
    assert len(components.COMPONENTS) == 14
    for name, spec in components.COMPONENTS.items():
        assert spec["name"] == name
        assert callable(spec["render"])
        assert isinstance(spec["required"], list)


def test_unknown_component_is_rejected_loudly():
    doc = _doc()
    with pytest.raises(BuildError) as ei:
        components.validate_blocks(doc, [{"component": "nope", "params": {}}])
    assert "nope" in str(ei.value)


def test_missing_required_param_is_rejected():
    doc = _doc()
    with pytest.raises(BuildError) as ei:
        components.validate_blocks(doc, [{"component": "file_card",
                                          "params": {}}])
    assert "path" in str(ei.value)
    with pytest.raises(BuildError):
        components.validate_blocks(doc, [{"component": "code",
                                          "params": {"path": "packages/a/src/circuit.ts",
                                                     "start": 1}}])


def test_fake_fact_id_in_cites_is_rejected():
    doc = _doc()
    with pytest.raises(BuildError) as ei:
        components.validate_blocks(doc, [{"component": "text",
                                          "params": {"text": "共 13 个文件"},
                                          "cites": ["fact:totals", "fact:ghost"]}])
    assert "fact:ghost" in str(ei.value)


def test_code_range_out_of_bounds_is_rejected():
    doc = _doc()
    path = "packages/a/src/circuit.ts"
    n = [f for f in doc["files"] if f["path"] == path][0]["lines"]
    with pytest.raises(BuildError) as ei:
        components.validate_blocks(doc, [{"component": "code",
                                          "params": {"path": path, "start": 1,
                                                     "end": n + 5}}])
    assert path in str(ei.value)


def test_text_marks_untraced_but_keeps_the_number():
    doc = _doc()
    html = components.render_block(doc, {"component": "text",
                                         "params": {"text": "共 999 个文件"},
                                         "cites": ["fact:totals"]})
    assert '<mark class="untraced">999</mark>' in html
    assert "999" in html


def test_component_own_numbers_are_not_marked():
    doc = _doc()
    html = components.render_block(doc, {"component": "metrics",
                                         "params": {"keys": ["files", "packages"]}})
    assert "13" in html and "3" in html
    assert "untraced" not in html      # R314：程序自产数字不标记
