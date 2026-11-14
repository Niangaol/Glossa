"""S4 符号表：代码侧、论文侧、两者的映射。

契约要点（控制器裁决，别传错参数）：
- `build_code_symbols(mod, bundle)` 的 bundle 是 **build_trace() 产出的 trace dict**，
  B 的值读 `bundle["meta"]["runtime"]["batch"]`；`build_paper_symbols(bundle)` 的
  bundle 是 **S2 的 PaperBundle**，读 `.units`。同名不同类（R2）。
- 五个符号冻结：B / T / D / H / Dh。D、H、T 来自实例化后的 `mod.config`；
  Dh = D // H 派生（夹具的 GPTConfig 没有 head_dim，猜一个就是假数据，RF4）；
  B 来自 trace 的 runtime。
- `defined_at` 必须是真实的 `文件:行号`：定位不到就**省略该符号**（R21），
  由 S9 用冻结集合做差集记 unresolved{kind:"symbol"}，本模块不编行号。
- 论文侧只抽下标标识符（`d_k` 这类），Q/K/V 无下标不抽（R22）。
- 映射冻结一对：`d_k <-> Dh`。论文侧没给数值（None）时无法比较，记 matched，
  mapping.value 取代码侧的值；两侧都有值且不等记 value_mismatch，
  两侧的值分别留在两个表里，绝不静默取一个当成两边共同的值（R22）。
"""

import pathlib
import shutil
import sys
from dataclasses import dataclass

import pytest

pytest.importorskip("torch", reason="本切片要真实例化模型，CPU 版 torch 即可")

from papertrace.build_trace import build_trace, load_entry  # noqa: E402
from papertrace.ingest.paper import ingest_paper  # noqa: E402
from papertrace.symbols.code_table import build_code_symbols  # noqa: E402
from papertrace.symbols.mapping import map_symbols  # noqa: E402
from papertrace.symbols.paper_table import build_paper_symbols  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402

HERE = pathlib.Path(__file__).resolve()
REPO = str(HERE.parents[1] / "tests" / "fixtures" / "nanogpt")
ENTRY = "model:build_model"
TEX = HERE.parents[1] / "tests" / "fixtures" / "papers" / "vaswani2017" / "attention.tex"

#: 冻结五符号 -> defined_at 那一行必须包含的子串（R31）。
#: 这不是同义反复：行号指错、或指向了别的变量，这些子串就对不上。
EXPECTED_LINE = {
    "B": "DEFAULT_BATCH",
    "T": "block_size",
    "D": "n_embd",
    "H": "n_head",
    "Dh": "n_head",
}


@pytest.fixture(scope="module")
def model_and_trace():
    """真模型 + 真 trace（夹具的 build_model 与一次真的 build_trace）。"""
    return load_entry(REPO, entry=ENTRY), build_trace(REPO, entry=ENTRY)


@pytest.fixture(scope="module")
def code_symbols(model_and_trace):
    mod, doc = model_and_trace
    return build_code_symbols(mod, doc)


@pytest.fixture(scope="module")
def paper_bundle():
    return ingest_paper(TEX)


def test_five_frozen_symbols_present(code_symbols):
    """五个符号一个都不能少，也不许多（符号名冻结 B,T,D,H,Dh）。"""
    assert {row["symbol"] for row in code_symbols} == {"B", "T", "D", "H", "Dh"}


def test_values_match_the_fixture(code_symbols):
    """值必须来自真配置/真 trace：batch=2、block_size=16、32//4=8。"""
    values = {row["symbol"]: row["value"] for row in code_symbols}
    assert values == {"B": 2, "T": 16, "D": 32, "H": 4, "Dh": 8}


def test_all_symbols_have_real_defined_at(code_symbols):
    """defined_at 必须是能打开、行号在界内、非空、且含该符号冻结子串的真位置。"""
    assert code_symbols, "一条都没有，后面全在空转"
    for row in code_symbols:
        where = row["defined_at"]
        path_text, sep, line_text = where.rpartition(":")
        assert sep, f"{row['symbol']} 的 defined_at 不是 文件:行号：{where!r}"
        line_no = int(line_text)
        path = pathlib.Path(path_text)
        assert path.is_file(), f"{where} 指向的文件不存在"
        body = path.read_text(encoding="utf-8").splitlines()
        assert 1 <= line_no <= len(body), f"{where} 越界（共 {len(body)} 行）"
        text = body[line_no - 1].strip()
        assert text, f"{where} 是空行"
        want = EXPECTED_LINE[row["symbol"]]
        assert want in text, f"{row['symbol']} 指向 {where}，但那行是 {text!r}，不含 {want!r}"


def test_head_dim_is_derived_not_invented(model_and_trace, code_symbols):
    """RF4：夹具没有 head_dim 字段，Dh 必须由 D // H 算出来，不能凭空读一个值。"""
    mod, _doc = model_and_trace
    # 夹具的 GPTConfig 只有 block_size/vocab_size/n_layer/n_head/n_embd/dropout/bias
    assert not hasattr(mod.config, "head_dim"), "夹具不该有 head_dim 字段"
    by_symbol = {row["symbol"]: row for row in code_symbols}
    d_value = by_symbol["D"]["value"]
    h_value = by_symbol["H"]["value"]
    assert by_symbol["Dh"]["value"] == d_value // h_value, "Dh 必须是 D // H 派生"
    # 定义点必须指向真正算 head 维的那一行：C // self.n_head
    where = by_symbol["Dh"]["defined_at"]
    path_text, _, line_text = where.rpartition(":")
    body = pathlib.Path(path_text).read_text(encoding="utf-8").splitlines()
    line = body[int(line_text) - 1]
    assert "//" in line and "n_head" in line, f"Dh 指向 {where}，但那行是 {line!r}"


def test_default_config_gives_768(model_and_trace):
    """换成默认 GPTConfig()（n_embd=768, n_head=12）：D=768、H=12、Dh=64。"""
    from tests.fixtures.nanogpt.model import GPT, GPTConfig

    mod, doc = model_and_trace
    default_model = GPT(GPTConfig())
    values = {row["symbol"]: row["value"] for row in build_code_symbols(default_model, doc)}
    assert (values["D"], values["H"], values["Dh"]) == (768, 12, 64)


@dataclass
class _NoNEmbConfig:
    """刻意缺 n_embd 的 config（测试替身只出现在 tests/ 下，GC2）。"""

    block_size: int = 8
    n_head: int = 2


class _StubModel:
    """只要 .config 就够的最小替身；其余符号的定位照常走它自己的源文件。"""

    def __init__(self, config):
        self.config = config


def test_missing_config_field_is_unresolved():
    """config 缺 n_embd -> D 与 Dh 不出现在返回值里。

    R21：本模块返回 list[dict]，没有 unresolved 通道；定位不到就**省略**，
    由 S9 拿冻结的五符号集合与实际返回值做差集，记
    unresolved{kind:"symbol", symbol, reason}。这里钉死「省略」这一侧：
    不编造行号，也不返回违反 schema 的 dict。
    """
    rows = build_code_symbols(_StubModel(_NoNEmbConfig()), {"meta": {"runtime": {"batch": 2}}})
    present = {row["symbol"] for row in rows}
    assert "D" not in present, "字段缺失时不得回退到某个默认值蒙一个 D"
    assert "Dh" not in present, "D 拿不到，Dh 无从派生，一起省略"
    assert {"B", "T", "H"} <= present, f"其余符号不该被连坐：{present}"


def test_non_divisible_heads_is_value_mismatch():
    """非整除 heads：Dh=32//5=6 对论文侧 32/5=6.4 -> value_mismatch 且两侧值都在。

    R20：build_code_symbols 只返回扁平的 codeSymbol 列表，没有 mismatch 通道，
    exact 对账是 M4 的事；这里用**手工构造的两侧列表**驱动 map_symbols。
    """
    code_rows = [
        {"var": "n_embd", "symbol": "D", "value": 32, "defined_at": "x.py:1", "used_by": []},
        {"var": "n_head", "symbol": "H", "value": 5, "defined_at": "x.py:2", "used_by": []},
        {"var": "Dh", "symbol": "Dh", "value": 32 // 5, "defined_at": "x.py:3", "used_by": []},
    ]
    paper_rows = [{"symbol": "d_k", "meaning": None, "value": 32 / 5, "first_seen": "S3.2-eq-attn"}]
    rows = map_symbols(code_rows, paper_rows)
    paired = [row for row in rows if row["paper_symbol"] == "d_k" and row["code_var"] == "Dh"]
    assert len(paired) == 1, f"d_k <-> Dh 必须成对出现一次：{rows}"
    assert paired[0]["status"] == "value_mismatch"
    # 两侧的值都还得在：mapping 记代码侧，论文侧留在 paperSymbol.value
    assert paired[0]["value"] == 6
    assert paper_rows[0]["value"] == 6.4, "map_symbols 不得改论文侧的值"


def test_paper_symbols_extract_d_k(paper_bundle):
    """只抽下标标识符：d_k 一个，Q/K/V 不抽；first_seen 是它首次出现的单元。"""
    rows = build_paper_symbols(paper_bundle)
    assert [row["symbol"] for row in rows] == ["d_k"]
    row = rows[0]
    assert row["first_seen"] == "S3.2-eq-attn"
    # 论文没给数值 -> None，绝不猜一个数（R22）
    assert row["value"] is None
    assert row["meaning"] is None


def test_mapping_marks_value_mismatch_explicitly(code_symbols, paper_bundle):
    """两种情形都覆盖：论文侧没给数 -> matched；两侧都有值且不等 -> value_mismatch。

    名字里的 value_mismatch 必须是真话（R35）：第一段用夹具，论文侧 d_k 的
    value=None，无法比较 -> matched，mapping.value 取代码侧 8；第二段用**手工
    构造的两侧列表**（代码侧 Dh=4、论文侧 d_k=8）钉死 value_mismatch，并断言
    两侧的值都还能从各自的表里取回——绝不静默取一个当成两边共同的值（R22）。
    """
    paper_rows = build_paper_symbols(paper_bundle)
    rows = map_symbols(code_symbols, paper_rows)
    paired = [row for row in rows if row["paper_symbol"] == "d_k"]
    assert len(paired) == 1, f"d_k 只能映射一次：{rows}"
    assert paired[0]["code_var"] == "Dh"
    # 论文侧 value=None -> 无法比较 -> matched，值取代码侧
    assert paired[0]["status"] == "matched"
    assert paired[0]["value"] == 8
    # 其余代码符号没有论文对手 -> code_only
    only_code = sorted(row["code_var"] for row in rows if row["status"] == "code_only")
    assert only_code == ["DEFAULT_BATCH", "block_size", "n_embd", "n_head"]
    # 手工两侧都有值且不等 -> value_mismatch：显式标记，不是 matched
    hand_code = [{"var": "Dh", "symbol": "Dh", "value": 4, "defined_at": "x.py:3", "used_by": []}]
    hand_paper = [{"symbol": "d_k", "meaning": None, "value": 8, "first_seen": "S3.2-eq-attn"}]
    mismatch = [row for row in map_symbols(hand_code, hand_paper) if row["paper_symbol"] == "d_k"]
    assert len(mismatch) == 1, f"d_k 只能映射一次：{mismatch}"
    assert mismatch[0]["code_var"] == "Dh"
    assert mismatch[0]["status"] == "value_mismatch", "两侧都有值且不等必须显式记 value_mismatch"
    # mapping.value 取代码侧；论文侧的 8 仍留在 paperSymbol.value，两边都留痕
    assert mismatch[0]["value"] == 4
    assert hand_code[0]["value"] == 4, "map_symbols 不得改代码侧的值"
    assert hand_paper[0]["value"] == 8, "map_symbols 不得改论文侧的值"


def test_mapping_never_silently_picks_one_value(code_symbols, paper_bundle):
    """绝不静默地把一个值当成两边共同的值：mismatch 时两侧的值都还得能取回。"""
    paper_rows = build_paper_symbols(paper_bundle)
    rows = map_symbols(code_symbols, paper_rows)
    paired = rows[0]
    assert paired["paper_symbol"] == "d_k"
    # 论文侧是 None：不许把代码侧的值塞回 paperSymbol，冒充论文也给了这个数
    assert paper_rows[0]["value"] is None, "map_symbols 不得改论文侧的值"
    assert paired["value"] == 8 and paired["status"] == "matched"
    # 真 mismatch：代码值在 codeSymbol.value，论文值在 paperSymbol.value，各在各家
    code_rows = [{"var": "Dh", "symbol": "Dh", "value": 6, "defined_at": "x.py:3", "used_by": []}]
    paper_rows = [{"symbol": "d_k", "meaning": None, "value": 6.4, "first_seen": "S3.2-eq-attn"}]
    mismatch = map_symbols(code_rows, paper_rows)[0]
    assert mismatch["status"] == "value_mismatch"
    assert code_rows[0]["value"] == 6 and paper_rows[0]["value"] == 6.4
    assert mismatch["value"] == 6, "mapping.value 取代码侧，论文侧的值仍留在论文表"

#: R36 场景 A 文件：config 类单独住一个文件（真实仓库里常见的独立 config.py）。
_SPLIT_CONFIG_SOURCE = '''\
"""R36 场景 A：config 类自己住一个文件。"""


class SplitConfig:
    block_size: int = 8
    n_head: int = 2
    n_embd: int = 48
'''

#: R36 场景 B 文件：模型类住这里，类体里放一个同名字段的诱饵赋值。
_SPLIT_MODEL_SOURCE = '''\
"""R36 场景 B：模型类 + 同名诱饵字段。"""

from s4_splitcfg_a import SplitConfig


class SplitModel:
    n_embd = 999

    def __init__(self):
        self.config = SplitConfig()


def build_model():
    return SplitModel()
'''


def test_config_field_definition_is_not_guessed_from_the_model_file():
    """R36：config 类在 A 文件时，字段声明点必须落在 A 的类体里，不是 B 的诱饵行。

    真实仓库里 config 常独立成文件，模型文件里也可能出现同名字段的赋值
    （本测试的诱饵是 `n_embd = 999`）。fail-closed：某个候选文件里圈不到该
    config 类的类体，就整个跳过这个文件，绝不退回整文件查找——一个指错文件
    错行的 defined_at 是静默产出错误事实，比省略该符号更坏（R36/R21）。
    """
    repo = scratch_dir("s4-split-config")
    (repo / "s4_splitcfg_a.py").write_text(_SPLIT_CONFIG_SOURCE, encoding="utf-8")
    (repo / "s4_model_b.py").write_text(_SPLIT_MODEL_SOURCE, encoding="utf-8")
    try:
        mod = load_entry(repo, entry="s4_model_b:build_model")
        rows = build_code_symbols(mod, {"meta": {"runtime": {"batch": 2}}})
        # 先把两个文件的内容读出来：finally 会删掉这个临时目录
        a_lines = (repo / "s4_splitcfg_a.py").read_text(encoding="utf-8").splitlines()
        b_text = (repo / "s4_model_b.py").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        sys.modules.pop("s4_splitcfg_a", None)
        sys.modules.pop("s4_model_b", None)

    assert "999" in b_text, "诱饵行必须真的写在 B 文件里，否则这个场景是空的"
    row = next(item for item in rows if item["symbol"] == "D")
    # 值来自实例化后的 config，不是模型文件里的诱饵 999
    assert row["value"] == 48, f"值必须来自 SplitConfig 实例：{row}"
    file_part, _, line_text = row["defined_at"].rpartition(":")
    assert pathlib.Path(file_part).name == "s4_splitcfg_a.py", (
        f"defined_at 必须指向 config 类所在的 A 文件，实际：{row['defined_at']}"
    )
    line_no = int(line_text)
    assert 1 <= line_no <= len(a_lines), f"行号越界：{row['defined_at']}"
    assert "n_embd" in a_lines[line_no - 1], (
        f"那一行必须是 n_embd 的声明，实际：{a_lines[line_no - 1]!r}"
    )
    assert "s4_model_b.py" not in row["defined_at"], "绝不指向模型文件里的诱饵行"

