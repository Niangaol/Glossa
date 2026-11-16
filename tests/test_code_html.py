"""Task C6 的 HTML 第 ⑥ 块「代码体检」守卫（R220–R226 / GC19 / GC23）。

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

from papertrace.code_analysis import METHOD_TEXT  # noqa: E402
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


def test_html_shows_the_method_text(real_doc):
    """GC19：方法说明必须逐字上页，不许截断 / 改写 / 摘要成一句话。"""
    block = _section(render_html(real_doc), "analysis")
    assert METHOD_TEXT in block, "方法说明被截断或改写了"


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
