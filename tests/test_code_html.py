"""Task C6 的 HTML 第 ⑥ 块「代码体检」守卫（R220–R246 / GC19 / GC23）。

纪律（与 tests/test_code_only_cli.py 逐字一致）：
- 模块级 fixture 真跑一次 CLI：29,856 / 884,736 这些数字必须取自真夹具的
  trace.json，不许手编假 dict（R222：数字是真产物的数字，测试不另算一遍）；
- 全程不联网；不用 pytest 的 tmp_path / --basetemp（沙箱递归删除 WinError 5），
  临时目录走 tests/_tmp.py::scratch_dir；
- 真夹具的 unknown 角色数是 0（R207：roles 不写 0 项键），所以「unknown 必须
  列出」只能靠合成 doc 测——deepcopy 真 doc 后只换 analysis，其余字段照抄
  真产物，不另搭一个假 trace；
- 断言一律落在 _section 块内与数据行上，不整页搜子串（散文即能满足子串断言、
  数据行全错仍全绿的教训，见 test_spine_html.py::_layer_cells 的 docstring）。
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("torch", reason="真跑 CLI 追踪需要 torch（CPU 版即可）")

from papertrace.code_analysis import METHOD_TEXT, empty_analysis  # noqa: E402
from papertrace.render_analysis import analysis_panel, role_counts  # noqa: E402
from papertrace.render_html import render_html  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = str(ROOT / "tests" / "fixtures" / "nanogpt")


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """真跑一次 CLI：cwd 钉在仓库根，PYTHONPATH 沿用测试环境（含 pydeps）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.pop("PAPERTRACE_LLM_BACKEND", None)
    env.pop("PAPERTRACE_LLM", None)
    return subprocess.run(
        [sys.executable, "-m", "papertrace", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(ROOT),
    )


def _section(html: str, name: str) -> str:
    """取出 <section id="name">…</section>，用来证明内容真的落在该块里。"""
    start = html.index('<section id="' + name + '">')
    return html[start : html.index("</section>", start)]


@pytest.fixture(scope="module")
def real_doc() -> dict:
    """一次真实 `build --repo <nanogpt>`（不带 --paper）的 trace.json。

    R222：第 ⑥ 块里每个数字都从这个 doc 现取；json.loads 读真产物，
    不 deepcopy 别的测试的 fixture、不手捏 dict。
    """
    out_dir = scratch_dir(f"c6-html-{os.getpid()}")
    result = _run_cli("build", "--repo", FIXTURE, "--out", str(out_dir), "--force")
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))


def test_html_has_a_code_health_section(real_doc):
    """R221：<section id="analysis"> 存在，块内含标题、真数字与「粗估 FLOPs」列头。

    GC19 钉子：列头必须自称粗估，「计算量」一个字都不许出现在块内。数据行数
    按 <tr><td 解析计数（不整页搜 "29,856"——总量行就能满足子串断言），
    必须等于真夹具的模块数。
    """
    html = render_html(real_doc)
    assert '<section id="analysis">' in html, "没有第 ⑥ 块"
    block = _section(html, "analysis")
    assert "代码体检" in block
    assert "29,856" in block, "总量行的参数量不是真夹具的 29,856"
    assert "884,736" in block, "总量行的粗估 FLOPs 不是真夹具的 884,736"
    # 变异探针 A 补强：29,856 在 summary 行也出现，光靠它钉不住数据行的
    # 千位分隔。27,808 只出现在 root/transformer 的参数量格里，加 class="mono"
    # 一起钉（去掉 _num 或去掉 class 都会让这条红）。
    assert '<td class="mono">27,808</td>' in block, "数据行的参数量没走千位分隔/mono"
    assert "粗估 FLOPs" in block, "列头必须自称粗估（GC19）"
    assert "计算量" not in block, "块内出现「计算量」：估算不自称估算了（GC19）"
    # R241/M3：三列都要钉住——根行三个单元格都在块内（不是只有 summary 行有数字）
    assert '<td class="mono">29,856</td>' in block, "根行参数量单元格没钉住"
    assert '<td class="mono">2,048</td>' in block, "根行峰值激活单元格没钉住"
    assert '<td class="mono">884,736</td>' in block, "根行粗估 FLOPs 单元格没钉住"
    assert "粗估 FLOPs 884,736" in block, "总量行没自称粗估（GC19：去掉「粗估」必红）"
    # 另一行（root/transformer.h.0.attn）：证明不是只有根行走千位分隔
    assert '<td class="mono">4,352</td>' in block, "attn 行参数量没走千位分隔"
    assert '<td class="mono">1,536</td>' in block, "attn 行峰值激活没走千位分隔"
    assert '<td class="mono">147,456</td>' in block, "attn 行粗估 FLOPs 没走千位分隔"
    data_rows = len(re.findall(r"<tr><td", block))
    expected = len(real_doc["analysis"]["modules"])
    assert data_rows == expected, "模块表数据行 %d != 模块数 %d" % (data_rows, expected)


def test_html_lists_unknown_and_degraded(real_doc):
    """R223/GC21：unknown 角色必须出现在角色分布里，降级计数与原因原文都要可见。

    真夹具 unknown=0（R207 不写 0 项键），所以 deepcopy 真 doc 后只把
    analysis 换成合成的：roles 含 unknown:1，totals 带 degraded:2 与一条
    degraded_reasons。表里的 unknown 模块行也要在——「不折叠」要落在数据行上。
    """
    doc = copy.deepcopy(real_doc)
    reason = "多输出算子，shape_out 记的是第 1 项（共 3 项：(2, 8, 32)、…）"
    doc["analysis"] = {
        "modules": [
            {"module_id": "root/known", "class": "Linear", "role": "linear",
             "evidence": "nn.Linear", "params": 64, "max_activation": 8, "est_flops": 128},
            {"module_id": "root/mystery", "class": "Mystery", "role": "unknown",
             "evidence": "判据认不出来", "params": 12, "max_activation": 4, "est_flops": 24},
        ],
        "totals": {"modules": 2, "params": 76, "max_activation": 8, "est_flops": 152,
                   "degraded": 2, "degraded_reasons": [reason]},
        "roles": {"linear": 1, "unknown": 1},
        "method": METHOD_TEXT,
    }
    block = _section(render_html(doc), "analysis")
    assert "unknown" in block, "unknown 角色被折叠了"
    assert "unknown 1" in block, "unknown 的计数没显示：%r" % block[:200]
    assert "linear 1" in block, "真角色的计数也没显示"
    assert "降级 2 个" in block, "降级计数没显示"
    assert reason in block, "降级原因原文没逐字出现"
    assert '<td class="mono">root/mystery</td>' in block, "unknown 模块行没进表"
    # R240：HTML 层也要有排序网——精确分布串（count 相同按 role 升序）
    assert "角色分布：linear 1 · unknown 1" in block, (
        "角色分布不是「linear 1 · unknown 1」：%r" % block[:300])
    assert "dropout" not in block, "不补 0：dropout 不在 roles 里却出现在块内（R207）"


def test_html_shows_the_method_text(real_doc):
    """GC19：方法说明必须逐字上页，不许截断 / 改写 / 摘要成一句话。"""
    block = _section(render_html(real_doc), "analysis")
    assert METHOD_TEXT in block, "方法说明被截断或改写了"
    assert "方法说明（逐字原文，不许截断）：" in block, "有原文时标签没自称逐字原文"
    # R238 回落分支：method="" → 回落 METHOD_TEXT，但标签必须改口
    doc = copy.deepcopy(real_doc)
    doc["analysis"]["method"] = ""
    fallback = _section(render_html(doc), "analysis")
    assert METHOD_TEXT in fallback, "method 缺失时回落文本没显示"
    assert "方法说明（内置默认文本，不是 trace 里的原文）：" in fallback, (
        "回落时标签没改口（R238）")
    assert "逐字原文" not in fallback, "回落时还自称逐字原文：provenance 过强（R238）"


def test_symbols_table_says_there_is_no_paper(real_doc):
    """R225：无论文 build 时，⑤ 符号表里必须有代码侧行 + 一句「没有论文」的说明。

    真夹具（不带 --paper）meta.paper.source == "none"：符号表只有代码侧可列，
    上页面不能让人以为论文侧符号被藏起来了。
    """
    assert real_doc["meta"]["paper"]["source"] == "none", "本测试要的是无论文 doc"
    block = _section(render_html(real_doc), "symbols")
    # 代码侧行的真实形状：symbol 列是变量名（var），含义列才是冻结符号 B/T/D/H/Dh
    assert '<td class="mono">Dh</td>' in block, "⑤ 符号表没有 Dh 代码侧行"
    assert '<td class="mono">n_embd</td>' in block and "<td>D</td>" in block, (
        "⑤ 符号表没有 D 的代码侧行")
    assert "没有论文" in block, "无论文时符号表没有如实说明"
    # R242/R225 正分支：有论文的 doc 不许再说「没有论文」
    doc = copy.deepcopy(real_doc)
    doc["meta"]["paper"] = {
        "source": "tests/fixtures/papers/vaswani2017/attention.tex",
        "unit_count": 4,
        "ingest_mode": "tex",
        "title": "Attention",
    }
    with_paper = _section(render_html(doc), "symbols")
    assert "没有论文" not in with_paper, "有论文时符号表还在说没有论文（R225 正分支）"


def test_html_survives_a_trace_without_analysis(real_doc):
    """R226/GC23：旧 trace 没有 analysis 键——块要显示，还要如实说没有。

    doc.pop("analysis") 后 render_html 不许抛（StrictUndefined 下裸访问
    doc.analysis 会炸）；页面不许出现 Traceback；<section id="analysis">
    仍要在，里面是一句 emptybox，不是把块藏掉。
    """
    doc = copy.deepcopy(real_doc)
    doc.pop("analysis")
    html = render_html(doc)  # 不抛就是过
    assert "Traceback" not in html
    block = _section(html, "analysis")
    assert "没有代码分析数据" in block, "空态没有如实说没有"


def test_role_counts_sort_by_count_desc_then_role_asc():
    """R223/R240：纯函数级排序钉子 + 不补 0 + bool 不当 int。

    背景：评审自跑 M1/M7/M2 三条排序变异全绿（5 passed），R223 只有实现没有
    回归网。这里直接调 role_counts 断言完整列表，不再依赖 HTML 子串。

    直接调 role_counts 断言完整列表（按顺序，不是子串）：
    {"unknown": 3, "linear": 2, "attention": 1, "mlp": 0}
    → [("unknown",3),("linear",2),("attention",1),("mlp",0)]
    排序键改成正序、两个键对调、过滤 unknown，这条都必须红（V1/V2/V3）。
    """
    panel = role_counts({"roles": {"unknown": 3, "linear": 2, "attention": 1, "mlp": 0}})
    assert [(r["role"], r["count"]) for r in panel] == [
        ("unknown", 3), ("linear", 2), ("attention", 1), ("mlp", 0)], (
        "排序不是 count 降序 + role 升序：%r" % panel)
    assert [r["role"] for r in panel] == ["unknown", "linear", "attention", "mlp"], (
        "同 count 时不是 role 升序：%r" % panel)
    for absent in ("dropout", "residual", "embedding", "layernorm"):
        assert absent not in [r["role"] for r in panel], (
            "不补 0：%s 不在 roles 里却出现了（R207）" % absent)
    # R239：bool 是 int 子类，True 不许输出成 True
    assert [(r["role"], r["count"]) for r in role_counts({"roles": {"linear": True}})] == [
        ("linear", 0)], "bool 计数被当成 int 原样输出了（R239）"


def test_html_is_honest_when_totals_are_missing(real_doc):
    """R235/I1：totals 缺失时摘要不许伪造「0 个模块」，degraded 不许说「降级 0 个」。

    合成 doc = 真 modules（34 行照旧渲染）+ 没有 totals 键。同时守 R237：
    第一行模块挖掉 est_flops → 该单元格是 "-"，不是 0。
    """
    doc = copy.deepcopy(real_doc)
    modules = copy.deepcopy(real_doc["analysis"]["modules"])
    modules[0].pop("est_flops", None)
    doc["analysis"] = {"modules": modules, "roles": {"linear": 9}, "method": METHOD_TEXT}
    html = render_html(doc)
    assert "Traceback" not in html
    block = _section(html, "analysis")
    assert "总计缺失" in block, "totals 不完整时摘要没有如实说缺失（R235）"
    assert "0 个模块" not in block, "totals 缺失却伪造「0 个模块」（R235）"
    assert "降级 0 个" not in block, "totals 缺失却伪造「降级 0 个」（R235）"
    assert block.count("<tr><td") == 34, "totals 坏了不该把真实的模块行也藏了（R235）"
    row = re.search(
        r'<tr><td class="mono">' + re.escape(str(modules[0]["module_id"])) + r"</td>.*?</tr>",
        block,
    )
    assert row, "第一行模块没渲染出来"
    assert '<td class="mono">-</td>' in row.group(0), (
        "缺 est_flops 的单元格不是 -（R237）：%r" % row.group(0))


def test_panel_survives_a_non_dict_analysis(real_doc):
    """R236/M1：analysis 是 int（或 list/str）时不许抛 AttributeError。

    九个键都要齐全（模板 StrictUndefined，缺键即炸；R246 起多一个 rows_note）。

    归一化后 has is False，模板走 else 分支出 emptybox，不是炸在 .get 上。
    """
    panel = analysis_panel({"analysis": 5})
    assert panel["has"] is False, "非 dict analysis 的 has 不是 False"
    for key in ("has", "summary", "roles", "rows", "rows_note", "method",
                "degraded", "symbols_note", "method_label"):
        assert key in panel, "非 dict analysis 时缺键 %s（StrictUndefined 会炸）" % key
    doc = copy.deepcopy(real_doc)
    doc["analysis"] = 5
    html = render_html(doc)  # 不抛就是过
    assert "Traceback" not in html
    assert "没有代码分析数据" in _section(html, "analysis"), (
        "非 dict analysis 没走空态（R236）")


def test_role_counts_breaks_ties_by_role_asc():
    """R245/R223：count 相同的角色必须按 role 升序，插入顺序不许漏过去。

    背景（定向复核 Q2 的 T1 变异 8 passed）：旧测试四个 count 全不同，删掉
    tie-break 也看不出来。这里插入顺序故意 z/a/m，只有真按 role 升序才过得去。
    """
    panel = role_counts({"roles": {"z": 2, "a": 2, "m": 3}})
    assert [(r["role"], r["count"]) for r in panel] == [
        ("m", 3), ("a", 2), ("z", 2)], (
        "同 count 时不是 role 升序：%r" % panel)


def test_html_says_module_rows_are_missing(real_doc):
    """R246：modules 键缺失而 totals 有效——说「模块行缺失」，不许假归因骨架。

    定向复核 Q1/Q5 的 Important 残留：摘要照样报「34 个模块」、表 0 行、
    空态却写「骨架模式…抽不到模块」——静默错误事实 + 假归因。合成 doc 只
    pop 真 analysis 的 "modules"，totals 原样保留。
    """
    doc = copy.deepcopy(real_doc)
    doc["analysis"].pop("modules")
    html = render_html(doc)
    assert "Traceback" not in html
    block = _section(html, "analysis")
    assert "模块行缺失" in block, "modules 缺失时没有如实说缺失（R246）"
    assert "骨架模式" not in block, "modules 缺失被假归因成骨架模式（R246）"
    assert "34 个模块" in block, "totals 完好时摘要仍要报真模块数（R246）"
    assert block.count("<tr><td") == 0, "modules 缺失却还有数据行"


def test_html_flags_totals_rows_mismatch_when_module_rows_are_empty(real_doc):
    """R246：modules=[] 而 totals.modules=34——说「数据不一致」，不许说骨架模式。

    同一条测试里再断言真空 empty_analysis()（totals.modules=0、modules=[]）
    仍走「骨架模式不加载模型」——三态必须分得开：真空 ≠ 数据不一致。
    """
    doc = copy.deepcopy(real_doc)
    doc["analysis"]["modules"] = []
    block = _section(render_html(doc), "analysis")
    assert "数据不一致" in block, "行数与 totals 对不上却没说（R246）"
    assert "骨架模式" not in block, "totals 说 34 行却是空表被假归因骨架（R246）"
    vacuum = copy.deepcopy(real_doc)
    vacuum["analysis"] = empty_analysis()
    empty_block = _section(render_html(vacuum), "analysis")
    assert "骨架模式不加载模型" in empty_block, (
        "真空（0 个模块）时空态句不该消失（R246 三态）")


def test_html_flags_count_mismatch_when_some_rows_are_listed(real_doc):
    """R246：totals.modules=40 而真列出 34 行——行照列，另说「实际列出 34 行」。"""
    doc = copy.deepcopy(real_doc)
    doc["analysis"]["totals"]["modules"] = 40
    block = _section(render_html(doc), "analysis")
    assert block.count("<tr><td") == 34, "对不上账就把真实行藏了（R246）"
    assert "实际列出 34 行" in block, "没说出实际列出的行数（R246）"
    assert "40" in block, "没说出 totals 宣称的 40（R246）"

