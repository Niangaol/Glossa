"""A3：AI 协议（prompt.py）——SYSTEM 的逐字约束与两次回包的严格解析。

契约来自派发书 §2：SYSTEM 必须逐字包含九 class、六范式、禁原生标签、数字来源、
连线出处、严格 JSON 六条；parse_section 顶层键只许四个且 html 非空、figures 是数组，
坏回包一律 BuildError 且带原文前 200 字；parse_plan 丢弃台账里没有的 fact id，
全空时返回空列表而不是抛。
"""
import json
import re

import pytest

from glossa.explain import pack as pack_mod
from glossa.explain import patterns, prompt, styles
from papertrace.exceptions import BuildError

GOOD = {"title": "入口", "html": '<p class="lead">入口在这里</p>',
        "figures": [], "notes": ["只讲查得到的事"]}


def _doc(facts=None):
    return {"meta": {"repo": {"url": "demo", "commit": "b" * 40, "root_name": "demo",
                              "language": "python"}},
            "totals": {"files": 2, "symbols": 3}, "graph": {"level": "file"},
            "facts": dict(facts or {})}


def test_system_names_all_nine_classes_from_the_vocabulary():
    assert len(styles.CLASSES) == 9
    for cls in styles.CLASSES:
        assert cls in prompt.SYSTEM, cls


def test_system_names_all_six_patterns_from_the_contract():
    assert len(patterns.PATTERNS) == 6
    for name in patterns.PATTERNS:
        assert name in prompt.SYSTEM, name


def test_system_forbids_raw_style_script_svg_figure_iframe():
    assert "不要输出 <style>/<script>/<svg>/<figure>/<iframe>" in prompt.SYSTEM


def test_system_states_number_edge_and_json_rules():
    assert "数字只能使用 facts[].numbers 里出现过的" in prompt.SYSTEM
    assert "每条连线必须带 fact，且必须是 facts 里给出的边" in prompt.SYSTEM
    assert "输出严格 JSON，不要 markdown 围栏外的解释" in prompt.SYSTEM


def test_parse_section_reads_plain_json():
    out = prompt.parse_section(json.dumps(GOOD, ensure_ascii=False), 2)
    assert out == GOOD
    assert out["figures"] == [] and out["notes"] == ["只讲查得到的事"]


def test_parse_section_unwraps_a_markdown_fence():
    text = "```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```\n"
    out = prompt.parse_section(text, 1)
    assert out["title"] == "入口" and out["html"] == GOOD["html"]


def test_parse_section_rejects_extra_top_level_keys():
    bad = dict(GOOD, style="magazine")
    with pytest.raises(BuildError) as info:
        prompt.parse_section(json.dumps(bad, ensure_ascii=False), 3)
    message = str(info.value)
    assert "style" in message and "第 3 节" in message


def test_parse_section_rejects_empty_html():
    bad = dict(GOOD, html="   ")
    with pytest.raises(BuildError) as info:
        prompt.parse_section(json.dumps(bad, ensure_ascii=False), 1)
    assert "html" in str(info.value)


def test_parse_section_rejects_non_list_figures():
    bad = dict(GOOD, figures={"pattern": "layered"})
    with pytest.raises(BuildError) as info:
        prompt.parse_section(json.dumps(bad, ensure_ascii=False), 5)
    message = str(info.value)
    assert "figures" in message and "第 5 节" in message


def test_parse_section_reports_bad_json_with_the_raw_excerpt():
    raw = "这不是 JSON，只是把 HTML 直接贴回来了：" + "<p>入口</p>" * 30
    with pytest.raises(BuildError) as info:
        prompt.parse_section(raw, 4)
    message = str(info.value)
    assert "这不是 JSON" in message and "第 4 节" in message
    assert len(message) < 200 + 120                       # 最多附原文前 200 字，不是整篇


def test_parse_plan_drops_fact_ids_missing_from_the_ledger():
    doc = _doc({"fact:file:a.py": {"text": "a.py 一行。", "numbers": [1]}})
    text = json.dumps({"sections": [
        {"title": "入口", "goal": "讲入口", "facts": ["fact:file:a.py", "fact:ghost"]},
        {"title": "  ", "goal": "没标题的节", "facts": ["fact:file:a.py"]},
        "不是对象",
    ]}, ensure_ascii=False)
    assert prompt.parse_plan(text, doc) == [
        {"title": "入口", "goal": "讲入口", "facts": ["fact:file:a.py"]}]


def test_parse_plan_without_usable_sections_returns_empty_list():
    doc = _doc()
    assert prompt.parse_plan('{"sections": []}', doc) == []
    assert prompt.parse_plan("[]", doc) == []
    assert prompt.parse_plan(json.dumps({"sections": [{"title": "", "facts": ["fact:ghost"]}]}),
                             doc) == []


def test_parse_plan_rejects_bad_json():
    with pytest.raises(BuildError) as info:
        prompt.parse_plan("分节如下：一、入口", _doc())
    assert "分节如下" in str(info.value)


def test_plan_prompt_offers_every_kind_and_the_graph_edges():
    facts = {"fact:file:f%02d.py" % i: {"text": "f%d.py 一行。" % i, "numbers": [1]}
             for i in range(70)}
    facts["fact:graph"] = {"text": "依赖图 2 个节点、1 条边。", "numbers": [1, 2]}
    facts["fact:totals"] = {"text": "全仓 2 个文件。", "numbers": [2]}
    doc = {"meta": {"repo": {"url": "demo", "commit": "b" * 40, "root_name": "demo",
                             "language": "python"}},
           "totals": {"files": 2}, "facts": facts,
           "graph": {"level": "file", "nodes": [], "edges": [{"from": "a.py", "to": "b.py"}],
                     "project_edges": [], "cycles": [], "layers": [], "unreachable": [],
                     "truncated": False}}
    system, user = prompt.build_plan_prompt(doc)
    assert system == prompt.SYSTEM
    assert "- fact:graph：" in user and "可画图的边：a.py→b.py" in user
    assert '"has_edges": true' in user, "带边的图事实必须在摘要里亮出来（R501）"
    offered = set(re.findall(r"^- (fact:\S+?)：", user, re.M))
    assert offered == {row["id"] for row in pack_mod.pack_for_plan(doc)["facts"]}
    assert "fact:file:f00.py" in offered


def test_both_prompt_builders_return_the_system_and_a_json_task():
    doc = _doc({"fact:file:a.py": {"text": "a.py 一行。", "numbers": [1]}})
    system, user = prompt.build_plan_prompt(doc)
    assert system == prompt.SYSTEM
    assert "fact:file:a.py" in user and "sections" in user
    assert '"totals"' in user and "demo" in user
    system, user = prompt.build_section_prompt(pack_mod.pack_for_plan(doc))
    assert system == prompt.SYSTEM
    assert '"files"' in user and "figures" in user and "html" in user
