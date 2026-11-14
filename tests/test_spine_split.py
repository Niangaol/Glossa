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
- R27（fix round 1）：拆项不嵌套、不乱贴标签。自底向上——\\frac 只有分子分母都
  没产出项时才为自己产一项（\\frac{a}{b} → 1 个 scale 项）；位置决定标签——孤立单
  字母不是运算（y = a → []），但和别的因子并列就是乘积（夹具末尾的 V 与 \\right)
  并列 → matmul）。任何两项的区间不重叠，index 严格递增。
- R29（fix round 2）：\\frac 透明（至少一侧产出了项）时两侧都必须留下代表项——没
  产出项的那一侧按它自己的原文补一个 scale 项，不许连同除法一起静默消失：
  \\frac{QK}{V} → QK 的 matmul 项 + V 的 scale 项，\\frac{h}{\\sqrt{d_k}} → h 的
  scale 项 + \\sqrt{d_k} 的 scale 项；两侧都没项时（\\frac{a}{b}）仍是整段一项。
"""

import itertools
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

# --- R27（fix round 1）：除法操作数不贴 matmul、项与项不嵌套 -------------------
INVARIANT_CASES = [
    "fixture",
    "\\frac{a}{b}",
    "\\sqrt{\\frac{a}{b}}",
    "\\sqrt{d_k}",
    "\\sqrt{QK}",
    "y = a + b",
    "y = a",
    "y = d_k",
    "QK",
    "a b",
    "\\frac{QK^{T}}{\\sqrt{d_k}}",
    "\\mathrm{softmax}(QK)V",
    "\\frac{a}{b}V",
    "\\sqrt{d_k}V",
    "QK\\sqrt{d_k}",
    "\\frac{\\frac{a}{b}}{c}",
    "\\frac{QK}{V}",
    "\\frac{h}{\\sqrt{d_k}}",
    "\\frac{QK^T}{d_k}",
    "\\frac{\\mathrm{softmax}(x)}{V}",
    "\\frac{QK}{V}W",
    "\\frac{x}{n}",
    "\\frac{\\sqrt{QK}}{V}",
    "\\frac{QK^{T}}{\\sqrt{d_k}}V",
    "\\mathrm{relu}(h)\\sqrt{d_k}",
    "\\frac{h}{d_k}",
    "QK^{T}V",
]


def _disjoint_spans(text: str, terms: list[Term]) -> list[tuple[int, int]]:
    """给每个 term 的 latex 选一个出现位置，要求选出的区间两两不重叠。

    latex 在公式里可能不唯一（R29 给 \\frac{\\frac{a}{b}}{c} 补的 'c'，在
    \\frac 这两个字母里也出现），按唯一出现定位会误报；穷举所有选法并断言
    存在一种两两不重叠的，既抓得到真重叠，也不被定位歧义卡住。
    """
    options = []
    for term in terms:
        hits, i = [], text.find(term.latex)
        while i >= 0:
            hits.append((i, i + len(term.latex)))
            i = text.find(term.latex, i + 1)
        assert hits, f"not a substring: {term.latex!r}"
        options.append(hits)
    for combo in itertools.product(*options):
        if all(a[1] <= b[0] or b[1] <= a[0] for a, b in itertools.combinations(combo, 2)):
            return list(combo)
    raise AssertionError(f"terms overlap in {text!r}: {[t.latex for t in terms]}")


def test_division_of_plain_symbols_is_one_scale_term():
    """R27 ②：\\frac{a}{b} 是缩放本身一项，分子分母不贴 matmul。"""
    assert split_formula("y = \\frac{a}{b}") == [Term(0, "\\frac{a}{b}", "scale")]
    assert split_formula("\\frac{a}{b}") == split_formula("y = \\frac{a}{b}")


def test_sqrt_of_division_is_one_scale_term():
    """R27 ③：\\sqrt{\\frac{a}{b}} 恰好一项，latex 覆盖整段。"""
    assert split_formula("\\sqrt{\\frac{a}{b}}") == [
        Term(0, "\\sqrt{\\frac{a}{b}}", "scale")
    ]


def test_isolated_symbol_is_not_a_term():
    """R27 ④：孤立变量不是运算；和别的因子并列时才是（见夹具第 4 项 V）。"""
    assert split_formula("y = a") == []
    assert split_formula("y = d_k") == []


@pytest.mark.parametrize("case", INVARIANT_CASES)
def test_terms_never_overlap_and_indices_increase(case):
    """R27 ⑤：任何两项区间不重叠 + index 严格递增 + latex 仍是原串真子串。

    index 是扫描序（后序：子项先于父项），所以夹具里 \\mathrm{softmax} 虽然在
    源串最前面却排在 index 2——这是 ① 钉死的契约，不能改成就近排序。
    """
    formula = _fixture_formula() if case == "fixture" else case
    rhs = formula.split("=", 1)[1] if "=" in formula else formula
    terms = split_formula(formula)
    for term in terms:
        assert term.latex in formula  # R15：真子串
    assert [t.index for t in terms] == list(range(len(terms)))
    spans = _disjoint_spans(rhs, terms)
    for (a0, a1), (b0, b1) in itertools.combinations(spans, 2):
        assert a1 <= b0 or b1 <= a0, f"overlap: {(a0, a1)} vs {(b0, b1)}"


def test_exposed_flag_changes_scan_behavior():
    """R27 ⑥：exposed 不是死参数——False 时同一段公式一个项都不产。"""
    from papertrace.parse_paper.split_terms import _scan  # 白盒：直接证明参数活着

    on: list[Term] = []
    off: list[Term] = []
    _scan("QK", 0, 2, True, on)
    _scan("QK", 0, 2, False, off)
    assert [t.latex for t in on] == ["QK"]
    assert off == []
    # 黑盒同一件事：根号内容不暴露，所以 \\sqrt{QK} 只有 1 项
    assert split_formula("y = \\sqrt{QK}") == [Term(0, "\\sqrt{QK}", "scale")]

# --- R29（fix round 2）：\frac 透明时两侧都必须有代表项 ---------------------------
#: 每一侧单独出现时的项（先探针钉死再当期望值，不用被测代码自证）；空列表 = 纯叶子，
#: 在分式里要按那一侧的原文补一个 scale 项。
SIDE_TERMS = {
    "a": [], "h": [], "c": [], "d_k": [],
    "QK": [("QK", "matmul")], "QK^T": [("QK^T", "matmul")],
    "K^{T}V": [("K^{T}V", "matmul")],
    "\\sqrt{d_k}": [("\\sqrt{d_k}", "scale")],
    "\\sqrt{QK}": [("\\sqrt{QK}", "scale")],
    "\\sqrt{\\frac{a}{b}}": [("\\sqrt{\\frac{a}{b}}", "scale")],
    "\\frac{a}{b}": [("\\frac{a}{b}", "scale")],
    "\\frac{p}{q}": [("\\frac{p}{q}", "scale")],
    "\\frac{\\frac{a}{b}}{c}": [("\\frac{a}{b}", "scale"), ("c", "scale")],
    "\\mathrm{softmax}(x)": [("\\mathrm{softmax}", "norm")],
    "\\mathrm{relu}(w)": [("\\mathrm{relu}", "act")],
}
#: 五族操作数：裸符号 / 乘积 / 根号 / 嵌套分式 / 函数调用
FRAC_SIDES = list(SIDE_TERMS)

#: R29 ② 钉死的精确输出，元素是 (index, latex, kind)——Term 的字段序
R29_FRAC_CASES = [
    ("y = \\frac{QK}{V}", [(0, "QK", "matmul"), (1, "V", "scale")]),
    ("y = \\frac{h}{\\sqrt{d_k}}", [(0, "h", "scale"), (1, "\\sqrt{d_k}", "scale")]),
    ("y = \\frac{QK^T}{d_k}", [(0, "QK^T", "matmul"), (1, "d_k", "scale")]),
    ("y = \\frac{\\frac{a}{b}}{c}",
     [(0, "\\frac{a}{b}", "scale"), (1, "c", "scale")]),
    ("y = \\frac{\\mathrm{softmax}(x)}{V}",
     [(0, "\\mathrm{softmax}", "norm"), (1, "V", "scale")]),
    ("y = \\frac{QK}{V}W",
     [(0, "QK", "matmul"), (1, "V", "scale"), (2, "W", "matmul")]),
    ("y = \\frac{x}{n}", [(0, "\\frac{x}{n}", "scale")]),
    ("y = \\frac{a}{b}", [(0, "\\frac{a}{b}", "scale")]),
    ("y = \\sqrt{\\frac{a}{b}}", [(0, "\\sqrt{\\frac{a}{b}}", "scale")]),
    ("y = a", []),
    ("y = \\sqrt{d_k}", [(0, "\\sqrt{d_k}", "scale")]),
    ("y = a + b", []),
]


@pytest.mark.parametrize("formula,expected", R29_FRAC_CASES)
def test_fraction_keeps_both_sides_represented(formula, expected):
    """R29 ②：一侧产项另一侧没有时，没项那一侧按原文补 scale 项，不许静默消失。"""
    terms = split_formula(formula)
    assert terms == [Term(i, latex, kind) for i, latex, kind in expected]
    for term in terms:  # R15：补项的 latex 也必须是原串真子串
        assert term.latex in formula


def test_transparent_fraction_has_one_term_per_side():
    """R29 ④：性质测试——\\frac 透明时两侧各有一个代表项，空的一侧按原文补 scale 项。

    遍历五族操作数的全部 16x16 组合；期望值来自上面的探针表而不是被测代码的自证，
    所以「一侧连同除法一起消失」这条测试自己就能发现。
    """
    pairs = list(itertools.product(FRAC_SIDES, repeat=2))
    assert len(pairs) >= 25
    for left, right in pairs:
        composed = f"\\frac{{{left}}}{{{right}}}"
        want = list(SIDE_TERMS[left]) or [(left, "scale")]
        want += list(SIDE_TERMS[right]) or [(right, "scale")]
        if not SIDE_TERMS[left] and not SIDE_TERMS[right]:
            want = [(composed, "scale")]  # 两侧都是叶子 → 整个分式自己是唯一一项
        terms = split_formula(composed)
        assert [(t.latex, t.kind) for t in terms] == want, composed
        assert [t.index for t in terms] == list(range(len(want)))
        for term in terms:  # R15：任何情况下 latex 都是原串真子串
            assert term.latex in composed


def test_exposed_flag_has_a_third_context():
    """R29 ⑤：exposed 不是死参数——第三种上下文决定要不要给空的一侧补项。"""
    from papertrace.parse_paper.split_terms import _scan  # 白盒：直接证明参数活着

    text = "\\frac{QK}{V}"
    on: list[Term] = []
    off: list[Term] = []
    _scan(text, 0, len(text), True, on)
    _scan(text, 0, len(text), False, off)
    assert [(t.latex, t.kind) for t in on] == [("QK", "matmul"), ("V", "scale")]
    assert off == []
    # 黑盒同一件事：两侧都是叶子时，暴露的父结构自己产一项
    assert split_formula("y = \\frac{a}{h}") == [Term(0, "\\frac{a}{h}", "scale")]

