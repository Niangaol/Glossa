"""T9：组件注册表与校验。数字来自真跑夹具。"""
from tests.common import FIXTURES
import re
import shutil
from pathlib import Path

import pytest

from glossa import facts
from glossa.explain import components
from papertrace.exceptions import BuildError
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"
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


# ---- R449-T6：code 行区间 / section / 标题优先级 / 未知顶层键 ----

def test_code_and_section_params_are_validated():
    doc = _doc()
    path = "packages/a/src/circuit.ts"
    bad_ranges = [{"start": 0, "end": 1}, {"start": 3, "end": 2},
                  {"start": "1", "end": 2}, {"start": 1, "end": "2"},
                  {"start": 1, "end": True}]
    for extra in bad_ranges:
        params = {"path": path, "start": 1, "end": 1, **extra}
        with pytest.raises(BuildError) as ei:
            components.validate_blocks(doc, [{"component": "code", "params": params}])
        assert "code" in str(ei.value) and path in str(ei.value), extra
    for section in (0, 8, True, 1.5):
        with pytest.raises(BuildError) as ei:
            components.validate_blocks(doc, [{"component": "overview", "params": {}, "section": section}])
        assert "section" in str(ei.value), section


def test_block_title_priority_is_block_then_params_then_section():
    spec = components.COMPONENTS["overview"]
    assert components.block_title({"title": "甲", "params": {"title": "乙"}, "section": 3}, spec) == "甲"
    assert components.block_title({"params": {"title": "乙"}, "section": 3}, spec) == "乙"
    assert components.block_title({"section": 3}, spec) == "分几块"
    assert components.block_title({}, spec) == "这项目是什么"      # 组件默认 section=1
    assert components.block_title({}, components.COMPONENTS["text"]) == "讲解"


def test_unknown_top_level_block_key_is_rejected():
    doc = _doc()
    with pytest.raises(BuildError) as ei:
        components.validate_blocks(doc, [{"component": "overview", "params": {}, "foo": 1}])
    assert "foo" in str(ei.value) and "notes" in str(ei.value)     # 合法键里必须点名 notes
    components.validate_blocks(doc, [{"component": "overview", "params": {}, "notes": ["x"]}])


# ---- R448-D10：字典一律 sorted(items()) ----

def test_dict_cells_are_sorted():
    doc = {"totals": {"by_lang": {"typescript": 9, "json": 3}},
           "packages": [{"name": "p", "path": "", "manifest": "x", "deps": {"z": "1.0", "a": "2.0"},
                         "dev_deps": {}, "scripts": {}, "workspace": False}],
           "facts": {"fact:pkg:p": {"numbers": [], "text": "包 p"}}}
    html = components.render_block(doc, {"component": "metrics", "params": {"keys": ["by_lang"]}})
    assert '<span class="v">json 3、typescript 9</span>' in html
    table = components.render_block(doc, {"component": "table",
                                          "params": {"fact": "fact:pkg:p", "columns": ["deps"]}})
    assert "a=2.0、z=1.0" in table and "z=1.0、a=2.0" not in table


# ---- R448-D11：cycles 前 3 补「等 N 个」 ----

def test_cycles_beyond_three_end_with_a_count():
    names = ["a1", "a2", "b1", "b2", "c1", "c2", "d1", "d2"]
    nodes = [{"id": name, "kind": "file", "label": name, "lang": "typescript", "package": None}
             for name in names]
    edges = [{"from": names[i], "to": names[i + 1], "kind": "internal", "count": 1}
             for i in (0, 2, 4, 6)]
    doc = {"graph": {"nodes": nodes, "edges": edges, "cycles": [[names[i], names[i + 1]]
                                                               for i in (0, 2, 4, 6)],
                     "layers": [], "level": "file", "unreachable": [], "truncated": False,
                     "truncated_nodes": 0, "omitted_isolated": 0}, "files": [], "entries": []}
    html = components.render_block(doc, {"component": "import_graph", "params": {}})
    assert "a1 → a2 → a1；b1 → b2 → b1；c1 → c2 → c1 等 4 个" in html
    assert "d1 → d2" not in html           # 只列前 3 个，第 4 个只按总数披露


# ---- R448-D12：0 文件不产出空 <ul> ----

def test_empty_dir_tree_has_no_empty_ul():
    html = components.render_block({"files": []}, {"component": "dir_tree", "params": {}})
    assert "没有可展开的目录（0 个文件）" in html
    assert "<ul" not in html


# ---- R448-D13/D14：SVG 优先 label、漏层不 KeyError ----

def test_project_svg_prefers_labels():
    doc = _doc("cs-solution")
    html = components.render_block(doc, {"component": "project_map", "params": {}})
    assert "<title>src/Demo.App/Demo.App.csproj</title>" in html
    assert "<title>src/Demo.Core/Demo.Core.csproj</title>" in html
    texts = re.findall(r"<text[^>]*>([^<]*)</text>", html)
    assert "Demo.App" in texts and "Demo.Core" in texts
    assert not any(item.startswith("src/") for item in texts)


def test_svg_missing_layer_nodes_fall_back_to_grid():
    nodes = [{"id": name, "kind": "file", "label": name, "lang": "typescript", "package": None}
             for name in ("a", "b", "c")]
    doc = {"graph": {"nodes": nodes, "edges": [], "cycles": [], "layers": [["a"]], "level": "file",
                     "unreachable": [], "truncated": False, "truncated_nodes": 0, "omitted_isolated": 0},
           "files": [], "entries": []}
    html = components.render_block(doc, {"component": "import_graph", "params": {}})
    for name in ("a", "b", "c"):
        assert ">%s</text>" % name in html
    assert html.count("<rect") == 3


# ---- R448-D15：单元格格式化只有一份 ----

def test_only_one_cell_formatter_exists():
    from glossa.explain import comp_file, comp_text
    assert not hasattr(comp_file, "_cell") and not hasattr(comp_text, "_cell")
    assert comp_text.cell(None) == "—" and comp_text.cell(0) == "0"

