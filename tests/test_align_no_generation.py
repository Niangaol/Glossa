"""守卫：对齐只能走「检索 → 判断题 → 结构加权」，禁止自由生成映射。

规格书里最容易被实现者偷懒掉的一条就是它：让模型一次吐出
「公式项 → 代码行」的对应表，看起来又快又准。那会把「可核验」变成「看起来对」，
整个产品的差异点就没了。
"""

from pathlib import Path

import pytest

ALIGN_DIR = Path(__file__).resolve().parents[1] / "papertrace" / "align"

FORBIDDEN_SNIPPETS = [
    "generate_alignment",
    "对应关系如下",
    "自由生成",
    "请列出对应关系",
]


def test_align_dir_exists():
    assert ALIGN_DIR.is_dir()


@pytest.mark.parametrize("snippet", FORBIDDEN_SNIPPETS)
def test_align_sources_have_no_free_generation(snippet):
    offenders = []
    for path in sorted(ALIGN_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if snippet in text:
            offenders.append(path.name)
    assert not offenders, f"{snippet!r} 出现在 {offenders}"


def test_judge_signature_takes_no_mapping_dict():
    """判断题的出口只能是 (yes, evidence)，不能整张映射表。"""
    import inspect

    from papertrace.align.judge import judge

    params = inspect.signature(judge).parameters
    assert "mapping" not in params
    assert len(params) >= 2
