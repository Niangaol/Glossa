"""S10：单文件离线 HTML 的九条具名测试（brief Step1 / RF5，叠加 R71–R93 裁决）。

纪律（与 tests/test_spine_end_to_end.py 逐字一致）：
- 假后端**单实例跨调用**，且必须断言调用计数 >= 1——否则测到的是 offline 兜底路径，
  结论是假的；
- 全程不联网；不用 pytest 的 tmp_path / --basetemp（沙箱递归删除 WinError 5），
  临时目录走 tests/_tmp.py::scratch_dir；
- R81：autoescape=True 下论文文本里的 '<' 会变成 &lt;，所以期望值一律用
  markupsafe.escape(reason) 逐字节比，绝不比对原始未转义串；
- R82：公式项清单 = anchors ∪ unresolved 里 ref 形如 *-t<N> 的 paper_unit
  （anchor 没有 kind 字段，不许编）。
"""

from __future__ import annotations

import copy
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from markupsafe import escape

from papertrace.align import embed as embed_module
from papertrace.align import judge as judge_module
from papertrace.build_trace import build_trace, load_entry, repo_commit, skeleton_trace
from papertrace.constants import HTML_MAX_BYTES
from papertrace.exceptions import BuildError
from papertrace.llm.client import ChatResult
from papertrace.render_html import render_html, write_html
from papertrace.schema_validate import load_trace, validate_trace
from papertrace.spine import attach_paper
from tests._tmp import scratch_dir

# 不依赖 cwd：从哪个目录跑 pytest 都得找得到夹具
ROOT = Path(__file__).resolve().parents[1]
REPO = str(ROOT / "tests" / "fixtures" / "nanogpt")
TEX = str(ROOT / "tests" / "fixtures" / "papers" / "vaswani2017" / "attention.tex")


class _FixedVerdictBackend:
    """单实例假后端：embed 全同向量（逐项 s_retr=1.0），chat 回固定判定。

    R84 控制器已验证配方：verdict=yes → 4 条 green c=0.862949；
    verdict=no → 4 条 yellow c=0.460085 source=static alternatives 各 2。
    """

    name = "fake-s10"

    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.chat_calls = 0
        self.embed_calls = 0

    def chat(self, prompt, *, system=None):
        self.chat_calls += 1
        if self.verdict == "yes":
            return ChatResult(text="Verdict: yes\nEvidence: 第 68 行的矩乘", model="f", backend="f")
        return ChatResult(text="Verdict: no\nEvidence: 不是同一个算子", model="f", backend="f")

    def embed(self, texts):
        self.embed_calls += 1
        return [[1.0, 0.0] for _ in texts]


def _run_cli(*args: str) -> subprocess.CompletedProcess:
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
    )


def _section(html: str, name: str) -> str:
    """取出 <section id="name">…</section>，用来证明内容真的落在该块里。"""
    start = html.index('<section id="' + name + '">')
    return html[start : html.index("</section>", start)]


@pytest.fixture(scope="module")
def base_doc() -> dict:
    """一次真实 build_trace（不带 --paper）：nodes=128 / edges=101，测试里 deepcopy 后用。"""
    return build_trace(REPO)


@pytest.fixture(scope="module")
def offline_doc() -> dict:
    """真实 CLI `build --paper <tex>`（offline 默认路径）：anchors=0、unresolved=4 条 term。"""
    out_dir = scratch_dir("s10-offline")
    result = _run_cli("build", "--repo", REPO, "--paper", TEX, "--out", str(out_dir), "--force")
    assert result.returncode == 0, result.stdout + result.stderr
    return load_trace(out_dir / "trace.json")


def _attached(doc: dict, monkeypatch, verdict: str):
    """走真实 attach_paper 路径造 anchor（R84：不许手捏 anchor 当产品输出）。"""
    fresh = copy.deepcopy(doc)
    model = load_entry(REPO, "model:build_model")
    backend = _FixedVerdictBackend(verdict)
    monkeypatch.setattr(embed_module, "get_llm", lambda: backend)
    monkeypatch.setattr(judge_module, "get_llm", lambda: backend)
    attach_paper(fresh, TEX, model)
    return fresh, backend


# ------------------------------------------------------------ 零外链 / 体积（RF5）


def test_html_has_no_external_refs(offline_doc):
    """R75：零外链。xmlns 是命名空间标识符不是资源引用，先剔除再扫。"""
    html = render_html(offline_doc)
    body = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', "", html)
    assert not re.search(r"https?://", body), "HTML 里出现了 http(s) 资源引用"
    assert not re.search(r'(?:src|href)\s*=\s*["\']?\s*(?:https?:)?//', body)
    assert "//cdn" not in body
    assert "@import" not in html and "url(" not in html


def test_html_under_size_cap(offline_doc):
    """R83：超 HTML_MAX_BYTES 抛 BuildError，不静默截断；正常体积必须在上限内。"""
    html = render_html(offline_doc)
    assert len(html.encode("utf-8")) <= HTML_MAX_BYTES


# ------------------------------------------------------- 未对齐清单必须可见（RF5/R81）


def test_unresolved_list_is_visible(offline_doc):
    """每条 unresolved 的 ref 与 reason 都必须出现在 HTML 里（R81 用 escape 比）。"""
    html = render_html(offline_doc)
    block = _section(html, "unresolved")
    assert offline_doc["unresolved"], "夹具本该有 4 条未对齐项"
    for entry in offline_doc["unresolved"]:
        assert str(escape(entry["ref"])) in block
        assert str(escape(entry["reason"])) in block
    # 真实 reason 含 '<'：原文绝不该以未转义形态出现（证明不是把 '<' 删掉冒充通过）
    assert any("<" in u["reason"] for u in offline_doc["unresolved"])
    for entry in offline_doc["unresolved"]:
        if "<" in entry["reason"]:
            assert entry["reason"] not in html
    # 论文 title 含双引号 → &#34;（R81）
    title = (offline_doc["meta"].get("paper") or {}).get("title")
    if title:
        assert str(escape(title)) in html


# ------------------------------------------------------------- 空 anchors 也要能渲染


def test_empty_anchors_renders():
    """anchors == [] 是 offline 的默认结果，不是错误；空节点集也不许画坏 SVG。"""
    doc = skeleton_trace(repo_url=REPO, commit=repo_commit(REPO))
    assert doc["nodes"] == [] and doc["anchors"] == []
    html = render_html(doc)
    validate_trace(doc)
    assert "骨架模式没有算子图" in html
    assert "没有未对齐项" in html
    assert "<svg" not in html  # 不画看起来像坏掉的空 SVG
    assert "lnk-green" not in html


# ------------------------------------------------- green / yellow 视觉区分（R84 配方）


def test_green_and_yellow_are_visually_distinct(base_doc, monkeypatch):
    """绿实线 / 黄虚线：class 与 stroke-dasharray 都必须不同。"""
    green_doc, green_backend = _attached(base_doc, monkeypatch, "yes")
    yellow_doc, yellow_backend = _attached(base_doc, monkeypatch, "no")
    # 注入的假后端必须真的被走到（否则测的是 offline 兜底，结论是假的）
    assert green_backend.chat_calls >= 1 and green_backend.embed_calls >= 1
    assert yellow_backend.chat_calls >= 1 and yellow_backend.embed_calls >= 1
    assert [a["tier"] for a in green_doc["anchors"]] == ["green"] * 4
    assert [a["tier"] for a in yellow_doc["anchors"]] == ["yellow"] * 4

    green_html = render_html(green_doc)
    yellow_html = render_html(yellow_doc)
    assert 'class="lnk lnk-green"' in green_html
    assert 'class="lnk lnk-yellow"' not in green_html
    assert 'class="lnk lnk-yellow"' in yellow_html
    assert 'class="lnk lnk-green"' not in yellow_html
    # 绿实线不带虚线；黄虚线必须带 stroke-dasharray
    assert "stroke-dasharray" not in green_html
    assert "stroke-dasharray=" in yellow_html


def test_no_none_tier_is_drawn_as_green(base_doc):
    """R84：tier==none（或缺 tier）绝不能被画成绿线。

    S9 实测 tier==none 根本不产 anchor，所以这里手工构造 doc 直接喂 render_html——
    渲染器的输入契约就是 trace dict，这是合法夹具；不许为此改 S9。
    """
    doc = copy.deepcopy(base_doc)
    doc["anchors"] = [
        {
            "paper_unit_id": "S3.2-eq-attn",
            "formula_term_index": 4,
            "code_expr_range": "root/@037",
            "aten_ops": ["matmul"],
            "confidence": 0.2,
            "tier": "none",
            "signals": {"s_retr": 0.0, "s_judge": 0.0, "s_struct": 0.8},
            "source": "static",
            "evidence": "对不上账",
        },
        {
            "paper_unit_id": "S3.2-eq-attn",
            "formula_term_index": 5,
            "code_expr_range": "root/@038",
            "aten_ops": ["mul"],
            "confidence": 0.1,
            "signals": {"s_retr": 0.0, "s_judge": 0.0, "s_struct": 0.0},
            "source": "static",
            "evidence": "连 tier 都没有",
        },
    ]
    html = render_html(doc)
    assert "S3.2-eq-attn-t4" in html and "S3.2-eq-attn-t5" in html  # 项仍在清单里可见
    assert "lnk-green" not in html  # 一条绿线都不许有
    assert "未连线" in html or "tier-none" in html


# ------------------------------------------------------------- 公式项清单（R82 偏离）


def test_formula_terms_are_listed(offline_doc):
    """R82：项清单 = anchors ∪ unresolved 里形如 *-t<N> 的 paper_unit。

    offline 默认路径 anchors=0，只读 anchors 的话默认页面一个公式项都不显示——
    所以 t0..t3 必须从 unresolved 侧进来。
    """
    assert offline_doc["anchors"] == []
    html = render_html(offline_doc)
    block = _section(html, "terms")
    for index in range(4):
        assert f"S3.2-eq-attn-t{index}" in block
    # 按 R82 改列：term_id / tier / confidence / aten_ops / evidence
    for column in ("term_id", "tier", "confidence", "aten_ops", "evidence"):
        assert column in block


# ---------------------------------------------------------------- 真实形状（R71）


def test_real_shapes_appear(offline_doc):
    """R71：形状格式化成 Python tuple repr（逗号后一个空格），出现在 SVG 标签里。"""
    html = render_html(offline_doc)
    block = _section(html, "ops")
    assert "(2, 4, 8, 8)" in block
    svgs = re.findall(r"<svg\b.*?</svg>", html, re.S)
    assert svgs and any("(2, 4, 8, 8)" in svg for svg in svgs)
    assert "(2,4,8,8)" not in html  # 不许退化成无空格 repr
    # 没有数据入参的画 -，不是 (?)
    assert "- → (8)" in block or "- → (64, 32)" in block


# ------------------------------------------------------------------ CLI 写 index.html


def test_cli_writes_index_html():
    """真跑 CLI 后 <out>/index.html 必须存在（R83：两路径汇合处都写）。"""
    out_dir = scratch_dir("s10-cli")
    result = _run_cli(
        "build", "--repo", REPO, "--paper", "none", "--out", str(out_dir), "--force"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    index = out_dir / "index.html"
    assert index.is_file()
    html = index.read_text(encoding="utf-8")
    assert len(html.encode("utf-8")) > 1000
    assert "<!DOCTYPE html>" in html
    body = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', "", html)
    assert not re.search(r"https?://", body)
    assert "Traceback" not in result.stderr


def test_cli_html_failure_keeps_trace_and_exits_2(monkeypatch, capsys):
    """R83：render 抛 BuildError → stderr 说清 trace.json 已写出 → exit 2，不删 trace。"""
    from papertrace.cli import main

    def _boom(doc, out_dir):
        raise BuildError("渲染出的 HTML 有 99999999 字节，超过上限 8000000；不静默截断")

    monkeypatch.setattr("papertrace.cli.write_html", _boom)
    out_dir = scratch_dir("s10-cli-fail")
    code = main(
        ["build", "--repo", REPO, "--paper", "none", "--out", str(out_dir), "--force"]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "trace.json 已写出" in err and "HTML 渲染失败" in err
    assert (out_dir / "trace.json").is_file()  # 绝不因 HTML 失败就删 trace
    assert (out_dir / "index.html").exists() is False


def test_render_over_cap_raises_build_error(offline_doc, monkeypatch):
    """R83：超体积抛 BuildError，不静默截断。"""
    import papertrace.render_html as render_module

    monkeypatch.setattr(render_module, "HTML_MAX_BYTES", 100)
    with pytest.raises(BuildError):
        render_html(offline_doc)


def test_write_html_overwrites_without_force(offline_doc):
    """R74：index.html 是派生产物，每次 build 都覆盖，不受 --force 约束。"""
    out_dir = scratch_dir("s10-r74")
    first = write_html(offline_doc, out_dir)
    assert first == out_dir / "index.html"
    stale = first.read_text(encoding="utf-8") + "<!-- 旧产物 -->"
    first.write_text(stale, encoding="utf-8")
    second = write_html(offline_doc, out_dir)
    assert second == first
    assert "旧产物" not in second.read_text(encoding="utf-8")