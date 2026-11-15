"""S2：本地 .tex → 稳定方程单元（RF1：坏 LaTeX / 缺 marker / 空 tex / 非 UTF-8）。

契约（派发裁决，唯一正确读法）：
- 只认 \\begin{equation} / \\begin{equation*}；align 等环境不碰——多行公式没有
  「一个环境一个公式」的语义，硬切就是猜（RF1）。
- unit_id 优先取 % papertrace-id: <id> 注释；没有 marker 才按 eq-<序号> 派生，
  序号是本文件全部方程里的 1 基位置（有 marker 的也占号）——改 marker 不会
  让别的方程改 ID。
- latex 是剔除全部 \\label{...} 之后的公式体，内部换行保留。
- 注释与逐字环境不产出单元（C1/R14 修复）：未转义 % 到行尾是注释，verbatim /
  lstlisting 里印出来的 \\begin{equation} 不是公式；marker 只认方程前的注释区。
- 读不了的论文抛 IngestError（不是 NotImplementedError），原因写在消息里：
  S9 靠这句话填 trace.json 的 unresolved，CLI 不该因为论文读不了就吐 traceback。
"""

import pathlib

import pytest

from papertrace.exceptions import IngestError
from papertrace.ingest.paper import PaperBundle, ingest_paper
from papertrace.parse_paper.units import PaperUnit, extract_units
from tests._tmp import scratch_dir

FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "papers"
    / "vaswani2017"
    / "attention.tex"
)


def test_fixture_tex_yields_one_unit():
    bundle = ingest_paper(FIXTURE)
    assert isinstance(bundle, PaperBundle)
    assert bundle.ingest_mode == "tex"
    assert bundle.unit_count == 1
    assert len(bundle.units) == 1
    unit = bundle.units[0]
    assert isinstance(unit, PaperUnit)
    # marker 优先：fixture 第 4 行的 % papertrace-id: S3.2-eq-attn
    assert unit.unit_id == "S3.2-eq-attn"
    # \label{eq:attention} 被抽进 label，并从 latex 里剔除
    assert unit.label == "eq:attention"
    assert "\\mathrm{softmax}" in unit.latex
    assert "\\label" not in unit.latex
    # R-a：标题 = 第一个 \begin{equation} 之前的第一行注释（去掉 % 与首尾空白）
    assert (
        bundle.title
        == 'Vaswani et al. 2017, "Attention Is All You Need", §3.2.1 Scaled Dot-Product Attention'
    )


def test_missing_marker_derives_stable_id():
    tex = "\\begin{equation}\na = b\n\\end{equation}\n"
    first = extract_units(tex)
    second = extract_units(tex)
    assert [u.unit_id for u in first] == [u.unit_id for u in second]
    assert [u.unit_id for u in first] == ["eq-1"]
    assert first[0].label is None
    assert first[0].latex == "a = b"


def test_derived_id_counts_all_equations():
    """R-c：序号是全部方程里的 1 基位置，带 marker 的方程也占号。"""
    tex = (
        "% papertrace-id: first-eq\n"
        "\\begin{equation}\na = b\n\\end{equation}\n"
        "\\begin{equation*}\nc = d\n\\end{equation*}\n"
    )
    units = extract_units(tex)
    assert [u.unit_id for u in units] == ["first-eq", "eq-2"]
    assert units[1].label is None


def test_equation_star_is_recognized():
    units = extract_units("\\begin{equation*}\nx = y\n\\end{equation*}\n")
    assert len(units) == 1
    assert units[0].latex == "x = y"


def test_align_environment_is_not_a_unit():
    """只认 equation：align 里可能是多行公式，切了就是猜。"""
    tex = "\\begin{align}\na &= b \\\\\nc &= d\n\\end{align}\n"
    assert extract_units(tex) == []


def test_empty_tex_yields_zero_units():
    d = scratch_dir("s2-ingest")
    path = d / "empty.tex"
    path.write_text("", encoding="utf-8")
    bundle = ingest_paper(path)
    assert bundle.units == []
    assert bundle.unit_count == 0
    assert bundle.ingest_mode == "tex"
    assert bundle.title is None


def test_comment_only_tex_yields_zero_units():
    d = scratch_dir("s2-ingest")
    path = d / "comments.tex"
    path.write_text("% 只有注释，没有公式\n% 第二行\n", encoding="utf-8")
    bundle = ingest_paper(path)
    assert bundle.units == []
    assert bundle.unit_count == 0
    assert bundle.ingest_mode == "tex"


def test_non_utf8_tex_raises_ingest_error():
    d = scratch_dir("s2-ingest")
    path = d / "latin1.tex"
    # 0xe9 单独出现不是合法 UTF-8（latin-1 里的 "café"）
    path.write_bytes(b"% caf\xe9\n\\begin{equation}\na = b\n\\end{equation}\n")
    with pytest.raises(IngestError) as excinfo:
        ingest_paper(path)
    assert "UTF-8" in str(excinfo.value)


def test_pdf_source_raises_ingest_error_with_reason():
    with pytest.raises(IngestError) as excinfo:
        ingest_paper("some/where/paper.pdf")
    message = str(excinfo.value)
    assert "pdf" in message.lower()
    assert "PDF" in message


def test_arxiv_source_raises_ingest_error():
    with pytest.raises(IngestError) as excinfo:
        ingest_paper("arxiv:1706.03762")
    assert "arxiv" in str(excinfo.value).lower()


def test_missing_path_raises_ingest_error():
    with pytest.raises(IngestError) as excinfo:
        ingest_paper("no/such/paper.tex")
    assert "找不到" in str(excinfo.value)


def test_tex_without_leading_comment_has_title_none():
    """R-a：第一个 \begin{equation} 之前没有注释行 → title=None。"""
    d = scratch_dir("s2-ingest")
    path = d / "nocomment.tex"
    path.write_text("\\begin{equation}\na = b\n\\end{equation}\n", encoding="utf-8")
    bundle = ingest_paper(path)
    assert bundle.title is None
    assert bundle.unit_count == 1


def test_unit_count_equals_len_units():
    bundle = ingest_paper(FIXTURE)
    assert bundle.unit_count == len(bundle.units)


def test_paper_bundle_units_defaults_empty():
    """既有四字段构造点不受影响：第五字段 units 带默认值。"""
    bundle = PaperBundle("src", "tex", 0, None)
    assert bundle.units == []


def test_commented_out_equation_is_not_a_unit():
    """C1 触发器 1/2：注释里的 equation 不是单元，也不许吞掉后面的真公式。"""
    commented = (
        "% \\begin{equation}\n"
        "% a = b\n"
        "% \\end{equation}\n"
        "\\begin{equation}\nc = d\n\\end{equation}\n"
    )
    units = extract_units(commented)
    assert [u.unit_id for u in units] == ["eq-1"]
    assert [u.latex for u in units] == ["c = d"]

    mention = (
        "% TODO: rewrite \\begin{equation} below\n"
        "\\begin{equation}\na = b\n\\end{equation}\n"
    )
    mentioned = extract_units(mention)
    assert len(mentioned) == 1
    assert mentioned[0].unit_id == "eq-1"
    assert mentioned[0].latex == "a = b"


def test_trailing_comment_inside_body_is_dropped():
    """C1 触发器 3：公式体内的行尾 % 注释不许活进 latex（内部换行仍保留）。"""
    tex = "\\begin{equation}\na = b % 行尾注释\nc = d\n\\end{equation}\n"
    units = extract_units(tex)
    assert len(units) == 1
    assert units[0].latex.startswith("a = b")
    assert units[0].latex.endswith("c = d")
    assert "\\n" in repr(units[0].latex)
    assert "%" not in units[0].latex
    assert "行尾注释" not in units[0].latex


def test_verbatim_equation_is_not_a_unit():
    """C1 触发器 4：verbatim 里印出来的 \\begin{equation} 不是公式。"""
    tex = (
        "\\begin{verbatim}\n"
        "\\begin{equation}\n"
        "a = b\n"
        "\\end{equation}\n"
        "\\end{verbatim}\n"
        "\\begin{equation}\n"
        "c = d\n"
        "\\end{equation}\n"
    )
    units = extract_units(tex)
    assert [u.unit_id for u in units] == ["eq-1"]
    assert [u.latex for u in units] == ["c = d"]


def test_marker_inside_body_is_ignored():
    """R14：marker 只认上一个 \\end 之后、本 \\begin 之前的注释区。

    写在公式体里的 marker 一律忽略，该公式回落 eq-<序号>——宁可退回位置编号，
    也不要把 A 公式的 ID 静默安到 B 公式头上。
    """
    tex = (
        "\\begin{equation}\n"
        "a = b\n"
        "% papertrace-id: second\n"
        "\\end{equation}\n"
        "\\begin{equation}\n"
        "c = d\n"
        "\\end{equation}\n"
    )
    assert [u.unit_id for u in extract_units(tex)] == ["eq-1", "eq-2"]


def test_escaped_percent_is_not_a_comment():
    """\\% 是转义百分号：它自己是 latex 的一部分，它后面才是真注释。"""
    tex = "\\begin{equation}\na = b \\% c % 真注释\n\\end{equation}\n"
    units = extract_units(tex)
    assert len(units) == 1
    assert "\\%" in units[0].latex
    assert "真注释" not in units[0].latex
    assert "%" not in units[0].latex.replace("\\%", "")


def test_inline_verbatim_and_url_percent_do_not_eat_equation_end():
    """Important-1 (FIX-1): 行内 \\verb 与 \\url 里的 % 不能把同行的 \\end{equation} 当注释吃掉。

    ① \\begin{equation} a = b \\verb|%| c \\end{equation} → 1 个单元且 latex 完整含 \\verb|%|
    ② \\url{http://x/%20y} 在 equation 内 → 1 个单元
    ③ \\verb|%| 后跟另一条 equation → 2 个单元，第二条 latex 是 z = w（不许缝合）
    ④ 对照组：\\% 与真行尾注释行为不变
    """
    # ① \verb|%|
    tex1 = "\\begin{equation} a = b \\verb|%| c \\end{equation}"
    u1 = extract_units(tex1)
    assert len(u1) == 1
    assert "a = b \\verb|%| c" in u1[0].latex

    # ② \url{http://x/%20y}
    tex2 = "\\begin{equation} a = b \\url{http://x/%20y} c \\end{equation}"
    u2 = extract_units(tex2)
    assert len(u2) == 1
    assert "\\url{http://x/%20y}" in u2[0].latex

    # ③ \verb|%| 后跟另一条 equation（不能缝合成一条）
    tex3 = (
        "\\begin{equation} a = b \\verb|%| \\end{equation}\n"
        "\\begin{equation} z = w \\end{equation}"
    )
    u3 = extract_units(tex3)
    assert len(u3) == 2
    assert u3[0].latex.endswith("\\verb|%|")
    assert u3[1].latex == "z = w"

    # ④ 对照组
    tex4 = "\\begin{equation} a = b \\% c % 行尾真注释\n\\end{equation}"
    u4 = extract_units(tex4)
    assert len(u4) == 1
    assert u4[0].latex == "a = b \\% c"

