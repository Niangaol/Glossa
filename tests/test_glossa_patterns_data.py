"""A9 / R512：bars / cards 的数据数组放行（patterns.py）。

口径（派发书 §R512）：bars 是 [{label, value}]，最多 12 条，value 必须是数字；cards 是
[{label, text}]，最多 8 条，两项都必须是非空字符串。不合规的那一条丢掉并记 note，
不是整张图报错；超限截断也要记 note。没有 bars/cards 键的图仍然只有五个契约键。
"""
import pytest

from glossa.explain import patterns


def _doc(facts=None):
    return {"files": [], "facts": dict(facts or {})}


def test_bars_rows_survive_with_label_and_value():
    fig = {"pattern": "bars", "caption": "三个数字",
           "bars": [{"label": "文件", "value": 120}, {"label": "符号", "value": 40},
                    {"label": "比例", "value": 0.25}]}
    clean, dropped, notes = patterns.validate_figure(_doc(), fig)
    assert clean["bars"] == [{"label": "文件", "value": 120}, {"label": "符号", "value": 40},
                             {"label": "比例", "value": 0.25}]
    assert dropped == 0 and notes == []


def test_a_non_numeric_value_is_dropped_and_disclosed():
    fig = {"pattern": "bars", "caption": "c",
           "bars": [{"label": "文件", "value": 12}, {"label": "坏的", "value": "十二"},
                    {"label": "布尔", "value": True}]}
    clean, dropped, notes = patterns.validate_figure(_doc(), fig)
    assert [row["label"] for row in clean["bars"]] == ["文件"]
    assert any("坏的" in note and "数字" in note for note in notes), notes
    assert any("布尔" in note for note in notes), notes


def test_a_bar_without_a_readable_label_is_dropped_and_disclosed():
    fig = {"pattern": "bars", "caption": "c",
           "bars": [{"value": 3}, {"label": "  ", "value": 4}, "不是对象",
                    {"label": "留下", "value": 5}]}
    clean, dropped, notes = patterns.validate_figure(_doc(), fig)
    assert clean["bars"] == [{"label": "留下", "value": 5}]
    assert len(notes) >= 3, notes


def test_more_than_twelve_bars_are_truncated_and_disclosed():
    fig = {"pattern": "bars", "caption": "c",
           "bars": [{"label": "第%d条" % i, "value": i} for i in range(15)]}
    clean, dropped, notes = patterns.validate_figure(_doc(), fig)
    assert len(clean["bars"]) == patterns.MAX_BARS == 12
    assert [row["value"] for row in clean["bars"]] == list(range(12))
    assert any("另有 3 条未画" in note for note in notes), notes


def test_cards_keep_label_and_text():
    fig = {"pattern": "cards", "caption": "图鉴",
           "cards": [{"label": "a.py", "text": "入口"}, {"label": "b.py", "text": "工具"}]}
    clean, dropped, notes = patterns.validate_figure(_doc(), fig)
    assert clean["cards"] == [{"label": "a.py", "text": "入口"}, {"label": "b.py", "text": "工具"}]
    assert dropped == 0 and notes == []


def test_a_card_missing_its_text_is_dropped_and_disclosed():
    fig = {"pattern": "cards", "caption": "c",
           "cards": [{"label": "a.py", "text": "入口"}, {"label": "b.py", "text": "   "},
                     {"text": "没名字"}, 7]}
    clean, dropped, notes = patterns.validate_figure(_doc(), fig)
    assert clean["cards"] == [{"label": "a.py", "text": "入口"}]
    assert len(notes) >= 3, notes


def test_more_than_eight_cards_are_truncated_and_disclosed():
    fig = {"pattern": "cards", "caption": "c",
           "cards": [{"label": "f%d.py" % i, "text": "第 %d 个" % i} for i in range(11)]}
    clean, dropped, notes = patterns.validate_figure(_doc(), fig)
    assert len(clean["cards"]) == patterns.MAX_CARDS == 8
    assert any("另有 3 张未画" in note for note in notes), notes


def test_a_figure_without_data_keeps_only_the_five_contract_keys():
    fig = {"pattern": "cards", "caption": "c", "nodes": [{"id": "n0"}], "edges": []}
    clean, _dropped, _notes = patterns.validate_figure(_doc(), fig)
    assert set(clean) == {"pattern", "caption", "nodes", "edges", "groups"}


def test_bars_that_are_not_a_list_is_a_loud_error():
    with pytest.raises(Exception):
        patterns.validate_figure(_doc(), {"pattern": "bars", "caption": "c", "bars": {"label": "x"}})
