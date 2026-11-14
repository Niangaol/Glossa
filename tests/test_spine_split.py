"""S3：公式拆项 + 安全 LaTeX（RF1：坏 LaTeX 不许猜出项，也不许抛裸 traceback）。

契约（派发裁决，唯一正确读法）：
- split_formula 先丢掉第一个顶层 `=` 及其左边的 LHS（R16）：LHS 上的
  \\mathrm{Attention} 一个项都不产出，拆的只有等号右边。
- 每一项的 latex 必须是原公式串的**真子串**（R15）：拆项器从不重写公式。
  「1/\\sqrt{d_k} 是缩放」这类语义由编排层（S9）写 reason 字符串，不许塞进
  latex 字段——所以 t1.latex 是 \\sqrt{d_k}，不是 1/\\sqrt{d_k}。
- safe parse 先行：白名单外的宏（\\unknownmacro、\\mathrm{Attention}…）一律
  ok=False，整条公式不拆、返回 []，由编排层整条进 unresolved（不猜项）。
- 单字母符号必须躲开 sympy 全局命名空间：裸 parse_expr('I*V') 不抛错，但 I 会
  静默变成虚数单位、free_symbols 里直接消失（实测只剩 {V}），所以必须传显式
  local_dict，且要断言符号本身还在 free_symbols 里，不是只断言不抛。
- Term 只有 index / latex / kind 三个字段（R17）：term_id 由编排层拼
  f"{unit_id}-t{term.index}"，split_formula 永远看不到 unit_id。
"""

import pathlib

import pytest
import sympy

from papertrace.parse_paper.latex_safe import latex_to_sympy_safe
from papertrace.parse_paper.split_terms import Term, split_formula
from papertrace.parse_paper.units import extract_units

REPO = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = (
    REPO / "tests" / "fixtures" / "papers" / "vaswani2017" / "attention.tex"
)
SOURCE_DIR = REPO / "papertrace" / "parse_paper"


def _fixture_formula() -> str:
    """公式正文从 S2 的 extract_units 拿，不在这里抄第二份。"""
    units = extract_units(FIXTURE.read_text(encoding="utf-8"))
    assert len(units) == 1
    return units[0].latex


def test_vaswani_splits_into_exactly_four_terms():
    terms = split_formula(_fixture_formula())
    assert len(terms) == 4
    assert [(t.index, t.kind) for t in terms] == [
        (0, "matmul"),
        (1, "scale"),
        (2, "norm"),
        (3, "matmul"),
    ]
    assert [t.index for t in terms] == [0, 1, 2, 3]


def test_term_latex_preserves_original_substring():
    """R15：每一项 latex 都是原串的真子串，证明拆项器没有重写公式。"""
    formula = _fixture_formula()
    terms = split_formula(formula)
    for term in terms:
        assert term.latex in formula
    assert [t.latex for t in terms] == [
        "QK^{T}",
        "\\sqrt{d_k}",
        "\\mathrm{softmax}",
        "V",
    ]


def test_term_namedtuple_has_exactly_three_fields():
    """R17：Term 只有 index / latex / kind；term_id 是编排层拼的。"""
    assert Term._fields == ("index", "latex", "kind")
    term = Term(index=0, latex="QK^{T}", kind="matmul")
    assert (term.index, term.latex, term.kind) == (0, "QK^{T}", "matmul")


def test_equals_sign_lhs_produces_no_terms():
    """R16：第一个顶层 `=` 及其左边整段丢弃，右边才拆。"""
    formula = _fixture_formula()
    rhs = formula.split("=", 1)[1]
    assert split_formula(formula) == split_formula(rhs)
    # 显式构造：LHS 带宏和三个参数，一个项都不许从它出来
    terms = split_formula("\\mathrm{Attention}(Q, K, V) = QK")
    assert [(t.latex, t.kind) for t in terms] == [("QK", "matmul")]


@pytest.mark.parametrize("expr", ["Q*K", "I*V", "E*x", "N*x", "S*x"])
def test_single_letter_symbols_do_not_collide_with_sympy_globals(expr):
    parsed = latex_to_sympy_safe(expr)
    assert parsed["ok"] is True
    letter = expr[0]
    # 不是只断言「不抛」：I*V 裸解析就不抛，但 I 静默变成虚数单位
    assert letter in {str(s) for s in parsed["expr"].free_symbols}


def test_fixture_formula_parses_with_every_symbol():
    parsed = latex_to_sympy_safe(_fixture_formula().split("=", 1)[1])
    assert parsed["ok"] is True
    assert {str(s) for s in parsed["expr"].free_symbols} == {
        "Q",
        "K",
        "V",
        "T",
        "d_k",
    }


def test_fixture_formula_translates_to_sympy():
    softmax = sympy.Function("softmax")
    Q, K, V, T, d_k = (sympy.Symbol(n) for n in ("Q", "K", "V", "T", "d_k"))
    expected = V * softmax((Q * K**T) / sympy.sqrt(d_k))
    parsed = latex_to_sympy_safe(_fixture_formula().split("=", 1)[1])
    assert parsed["ok"] is True
    assert parsed["expr"] == expected


def test_frac_and_cdot_translate_to_sympy_operators():
    a, b = sympy.Symbol("a"), sympy.Symbol("b")
    parsed = latex_to_sympy_safe("\\frac{a}{b}")
    assert parsed["ok"] is True
    assert parsed["expr"] == a / b
    parsed = latex_to_sympy_safe("a \\cdot b")
    assert parsed["ok"] is True
    assert parsed["expr"] == a * b


def test_transpose_superscript_becomes_power():
    Q, T = sympy.Symbol("Q"), sympy.Symbol("T")
    parsed = latex_to_sympy_safe("Q^{T}")
    assert parsed["ok"] is True
    assert parsed["expr"] == Q**T


def test_unknown_macro_is_not_split():
    bad = "\\unknownmacro{Q K}"
    parsed = latex_to_sympy_safe(bad)
    assert parsed["ok"] is False
    assert parsed["expr"] is None
    assert parsed["raw"] == bad
    assert split_formula(bad) == []
    assert split_formula(f"y = {bad}") == []


def test_attention_macro_is_not_whitelisted():
    """R16：\\mathrm{Attention} 不在白名单——它是等号左边，不是表达式。"""
    lhs = "\\mathrm{Attention}(Q, K, V)"
    parsed = latex_to_sympy_safe(lhs)
    assert parsed["ok"] is False
    assert parsed["expr"] is None
    assert parsed["raw"] == lhs


BAD_LATEX = [
    "",
    "   ",
    "\\frac{1}{2",
    "\\unknownmacro{x}",
    "\\mathrm{Attention}(Q, K, V)",
    "a = b",
    "\\frac{}{}",
    "\\sqrt{}",
    "\\begin{equation}",
    "Q & K",
    "\\sum_{i=1}^{n} x_i",
    "((",
]


@pytest.mark.parametrize("bad", BAD_LATEX)
def test_safe_parse_never_raises(bad):
    parsed = latex_to_sympy_safe(bad)
    assert parsed["ok"] is False
    assert parsed["expr"] is None
    assert parsed["raw"] == bad


def test_empty_latex_yields_no_terms():
    assert split_formula("") == []
    assert split_formula("   \n\t ") == []
    assert split_formula("=") == []
    assert split_formula("x =") == []


def test_no_latex_frontend_is_used():
    """Constraint 13：antlr4/lark 都没装，parse_latex 一调用就 ImportError。"""
    for name in ("latex_safe.py", "split_terms.py"):
        text = (SOURCE_DIR / name).read_text(encoding="utf-8")
        assert "parse_latex" not in text
        assert "sympy.parsing.latex" not in text


def test_out_of_grammar_formula_yields_no_terms():
    """超出已知文法不猜：求和、对齐符都不是项，整条交给编排层。"""
    assert split_formula("\\sum_{i} x_i") == []
    assert split_formula("a & b") == []
    assert split_formula("\\left\\{a, b\\right\\}") == []


def test_formula_without_any_term_yields_empty_list():
    """a+b 里没有已知结构：两个叶子符号都不是项，不硬凑。"""
    assert split_formula("y = a + b") == []
