"""Task C5 的 CLI 收尾守卫：无论文也分析（R216–R219 / GC8）。

只钉 C5 的增量：不带 --paper 时 `symbols.code` 与 `analysis` 都非空、
`--skeleton` 仍有空 `analysis`、stdout 多一行代码分析摘要。论文侧的既有行为由
tests/test_spine_end_to_end.py 钉住，本文件不重复断言 spine 细节。

口径（GC19 / R204）：数字全部取自 `analysis["totals"]`，测试不另算一遍。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("torch", reason="真跑 CLI 追踪需要 torch（CPU 版即可）")

from papertrace.code_analysis import empty_analysis  # noqa: E402
from papertrace.schema_validate import load_trace, validate_trace  # noqa: E402
from tests._tmp import scratch_dir  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = str(ROOT / "tests" / "fixtures" / "nanogpt")
PAPER = str(ROOT / "tests" / "fixtures" / "papers" / "vaswani2017" / "attention.tex")

#: 黄金夹具 build_model()（block_size=16 / n_layer=2 / n_head=4 / n_embd=32）实测符号值：
#: B=meta.runtime.batch、T=config.block_size（声明值，不是运行时 seq_len=8，R32）、
#: D=config.n_embd、H=config.n_head、Dh=D//H。
CODE_SYMBOLS = {"B": 2, "T": 16, "D": 32, "H": 4, "Dh": 8}

#: C3 黄金 totals（analyze_metrics 的 root 行口径，R204：摘要数字从这里取，不另算）
GOLD_TOTALS = {"modules": 34, "params": 29856, "max_activation": 2048, "est_flops": 884736}

#: R218/R219：摘要行逐字（键名逐字 + 千位分隔 f"{n:,}"）
SUMMARY_LINE = (
    f"代码分析：{GOLD_TOTALS['modules']} 个模块 · 参数量 {GOLD_TOTALS['params']:,} · "
    f"峰值激活 {GOLD_TOTALS['max_activation']:,} 元素 · 粗估 FLOPs {GOLD_TOTALS['est_flops']:,}"
)

#: GC8：不带 --paper 时逐项不变
GC8_NODES = 128
GC8_EDGES = 101
GC8_COUNTS = {
    "operators": 75,
    "degraded": 2,
    "fused": 0,
    "orphan": 0,
    "shape_broken": 0,
    "shape_unchecked": 0,
}

#: GC8：新增只允许落在 symbols.code 与 analysis 两处，顶层键集合冻结
TOP_KEYS = {
    "meta",
    "symbols",
    "nodes",
    "edges",
    "anchors",
    "mismatches",
    "unresolved",
    "annotations",
    "conflicts",
    "view_state",
    "analysis",
}


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


def _build(*extra: str) -> tuple[dict, subprocess.CompletedProcess]:
    """真跑一次 `build --repo <nanogpt>`，返回 (trace.json, CLI 结果)。"""
    # 输出目录按 pid 隔开：scratch_dir 的 shutil.rmtree(ignore_errors=True) 在本机
    # 沙箱下可能静默失败（WinError 5，正是 tests/_tmp.py 存在的原因），复用同一批
    # 目录名会让上一轮次的 trace.json 留在盘上。目录全新 → 读到的必然是本次产物。
    out_dir = scratch_dir(f"c5-cli-{os.getpid()}")
    result = _run_cli("build", "--repo", FIXTURE, "--out", str(out_dir), "--force", *extra)
    assert result.returncode == 0, result.stdout + result.stderr
    return load_trace(out_dir / "trace.json"), result


def test_build_without_paper_writes_symbols_and_analysis():
    """R217：不带 --paper 也填 symbols.code 与 analysis（无论文也分析）。"""
    doc, _ = _build()
    assert doc["meta"]["paper"]["source"] == "none"
    code_rows = doc["symbols"]["code"]
    assert len(code_rows) == 5, [row["symbol"] for row in code_rows]
    values = {row["symbol"]: row["value"] for row in code_rows}
    assert values == CODE_SYMBOLS
    assert all(row["defined_at"] for row in code_rows), "五个符号都必须有定义点（R21）"
    analysis = doc["analysis"]
    assert isinstance(analysis, dict), "无论文也必须写 analysis（GC22）"
    modules = analysis["modules"]
    assert len(modules) == GOLD_TOTALS["modules"]
    assert all(row.get("module_id") and row.get("role") for row in modules)
    totals = analysis["totals"]
    assert (totals["modules"], totals["params"]) == (
        GOLD_TOTALS["modules"],
        GOLD_TOTALS["params"],
    )
    assert (totals["max_activation"], totals["est_flops"]) == (
        GOLD_TOTALS["max_activation"],
        GOLD_TOTALS["est_flops"],
    )
    assert analysis["method"].strip() != ""
    validate_trace(doc)


def test_gc8_numbers_are_untouched():
    """GC8：无论文也分析不许改动 nodes/edges/counts/anchors/unresolved 与顶层键集合。"""
    doc, _ = _build()
    assert len(doc["nodes"]) == GC8_NODES
    assert len(doc["edges"]) == GC8_EDGES
    counts = doc["meta"]["runtime"]["counts"]
    for key, expected in GC8_COUNTS.items():
        assert counts[key] == expected, (key, counts[key], expected)
    assert doc["anchors"] == []
    assert doc["unresolved"] == []
    # C5 评审 Minor：meta.paper 整字典钉住空态——不是只查 source 一个键，
    # 三个键都必须如实是 none/0（补键或改值都会在这里被抓）
    assert doc["meta"]["paper"] == {"source": "none", "unit_count": 0, "ingest_mode": "none"}
    assert set(doc) == TOP_KEYS, sorted(set(doc) ^ TOP_KEYS)


def test_skeleton_still_writes_empty_analysis():
    """R216：骨架路径写空 analysis，symbols.code 保持 []（不许伪造符号）。"""
    doc, result = _build("--skeleton")
    assert len(doc["nodes"]) == 0
    assert doc["symbols"]["code"] == []
    assert doc["analysis"]["modules"] == []
    assert doc["analysis"]["totals"]["params"] == 0
    assert doc["analysis"] == empty_analysis()
    validate_trace(doc)
    # R218：modules 空 → 摘要行不打
    assert "代码分析" not in result.stdout


def test_paper_path_still_fills_paper_symbols():
    """论文路径一行不许坏：paper 符号照旧，且复用同一份 model 的分析（R217）。"""
    doc, result = _build("--paper", PAPER)
    assert doc["symbols"]["paper"], "论文路径的 paper 符号不许空"
    assert doc["symbols"]["mapping"], "论文路径的 mapping 不许空"
    assert len(doc["symbols"]["code"]) == 5
    assert len(doc["analysis"]["modules"]) == GOLD_TOTALS["modules"]
    assert doc["analysis"]["totals"]["params"] == GOLD_TOTALS["params"]
    validate_trace(doc)
    # offline：论文接不上也照写 trace——anchors 空、unresolved 非空，绝不静默成功
    assert doc["anchors"] == []
    assert doc["unresolved"]
    assert SUMMARY_LINE in result.stdout


def test_build_summary_mentions_the_analysis():
    """R218/R219：stdout 多一行代码分析摘要，键名逐字、千位分隔。"""
    _, result = _build()
    assert result.stdout.count(SUMMARY_LINE) == 1
