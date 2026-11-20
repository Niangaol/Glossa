"""R484：兜底简介不许冒充整仓定义——非根 README 的来源必须自带限定。

README 首段进 facts 是 R444 记的「T11 之后」（schema 冻结，本轮不碰 facts 层），所以根
README 那一例按「doc 已给出根 README 首段」的形状断言 explain 侧口径，不假装事实层已支持。
"""
from glossa import facts
from glossa.explain import render
from tests._tmp import scratch_dir

BLOCKS = [{"component": "overview", "params": {}}]


def _page(doc):
    page, _report = render.render_explain(doc, BLOCKS)
    return page


def test_module_docstring_intro_carries_its_own_scope():
    """根目录没有 README、只有 scripts/tool.py 带 docstring：页面必须说「只代表这个文件」。"""
    root = scratch_dir("glossa-r484-script")
    (root / "scripts").mkdir()
    (root / "scripts" / "tool.py").write_text(
        '"""契约校验脚本：只做约定检查。"""\n\nVALUE = 1\n', encoding="utf-8")
    page = _page(facts.build_repo_doc(root))
    assert "只代表这个文件" in page
    assert "契约校验脚本：只做约定检查。" in page
    assert "scripts/tool.py" in page


def test_root_readme_intro_is_not_qualified():
    """根 README 首段代表整仓：页面含这段，且**不含**限定语（R484 反例）。"""
    root = scratch_dir("glossa-r484-readme")
    (root / "README.md").write_text("# 示例\n\n这是根 README 的第一段。\n", encoding="utf-8")
    doc = facts.build_repo_doc(root)
    next(row for row in doc["files"] if row["path"] == "README.md")["doc_first_line"] = \
        "这是根 README 的第一段。"
    page = _page(doc)
    assert "这是根 README 的第一段。" in page
    assert "只代表这个文件" not in page
