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
    # 没有数据入参的画 -，不是 (?)。R96：inputs 三态的 - 仍然合法
    # （print_ops 口径），只有 shape 的空列表要改成 ()。
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
    assert "旧产物" not in second.read_text(encoding="utf-8")# ==================================================== fix round 1（R96 / R97 / R98）
def _note(html: str, section_name: str) -> str:
    """取出某节的说明文字（<p class="sub">…</p>）：R97 要钉住「说明与数据一致」。"""
    block = _section(html, section_name)
    start = block.index('<p class="sub">')
    return block[start : block.index("</p>", start)]
def test_fmt_shape_matches_report():
    """R96：render_html.fmt_shape 必须与 report.fmt_shape 逐输入一致。

    R96 取代 R71 的空列表条款：report.py:17 docstring 明写「() 是 0 维标量；
    (?) 是形状未知。两者不能混为一谈」，而 render 侧曾把 [] 渲染成「-」——
    那是 print_ops 的 **inputs（数据入参列表）** 三态，不是 shape 的口径。
    不许 import report 进 render_html（report 顶层 import build_trace，会把 torch
    拖进纯渲染器的 import 图），所以用这条测试把两个口径钉在一起。
    """
    from papertrace.render_html import fmt_shape as render_fmt_shape
    from papertrace.report import fmt_shape as report_fmt_shape

    for shape in (None, [], [2, 4], [2, 4, 8, 8], [1]):
        assert render_fmt_shape(shape) == report_fmt_shape(shape), shape
    # R96 核心条款显式钉住：空列表是 0 维标量，不是「没有数据」
    assert render_fmt_shape([]) == "()"
    assert render_fmt_shape(None) == "(?)"
def test_header_shows_provenance(offline_doc):
    """R98：页眉必须显示 meta.schema_version / meta.created_at，不许渲染成空。

    模板曾写 doc.schema_version / doc.created_at（顶层 doc 没有这两个键），
    Jinja 默认 Undefined 静默渲染空串 → 每页页眉都是「schema v · 生成于 」。
    """
    html = render_html(offline_doc)
    meta = offline_doc["meta"]
    assert "schema v" + str(meta["schema_version"]) in html
    assert "生成于 " + str(meta["created_at"]) in html
    # R70 可追溯性：prompt_version 以前在页面里完全不出现
    assert str(meta["model"]["prompt_version"]) in html
def test_strict_undefined_raises_on_bad_path(offline_doc):
    """R98：Environment 必须配 StrictUndefined——路径笔误要响亮抛错，不许静默吞。"""
    import papertrace.render_html as render_module
    from jinja2 import StrictUndefined
    from jinja2.exceptions import UndefinedError

    assert render_module._ENV.undefined is StrictUndefined
    broken = copy.deepcopy(offline_doc)
    broken.pop("meta")  # doc.meta.* 全部不可解析
    with pytest.raises(UndefinedError):
        render_html(broken)
def test_symbol_note_matches_mapping_status():
    """R97：符号表说明文字必须与真实 mapping status 一致，不许说反。

    实测骨架 + 论文的映射是 paper_only（symbols/mapping.py:47-52 回填
    code_var=Dh），模板说明却写 code_only——两者含义相反
    （code_only = 论文侧缺；paper_only = 代码侧缺）。
    数据忠于 trace，失真只在说明文字，但说明失实与数据失实同族（R76）。
    """
    doc = skeleton_trace(repo_url=REPO, commit=repo_commit(REPO))
    attach_paper(doc, TEX, None)  # CLI 的 --skeleton --paper 正是这条路径
    statuses = {str(m.get("status")) for m in doc["symbols"]["mapping"] if m.get("status")}
    assert statuses, "骨架 + 论文本该产出映射行"
    html = render_html(doc)
    note = _note(html, "symbols")
    for status in sorted(statuses):
        assert status in note, f"说明文字漏说了真实状态 {status}"
    assert "code_only" not in note


def test_cli_writes_index_html_for_skeleton():
    """R73：--skeleton 也要写 index.html（R83 两路径汇合处，不只真实 build 路径）。"""
    out_dir = scratch_dir("s10-fix1-skel-cli")
    result = _run_cli(
        "build", "--repo", REPO, "--skeleton", "--out", str(out_dir), "--force"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    index = out_dir / "index.html"
    assert index.is_file()
    html = index.read_text(encoding="utf-8")
    assert "骨架模式没有算子图" in html
    assert "schema v1.0.0" in html  # R98：骨架页眉也不许渲染成空
    body = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', "", html)
    assert not re.search(r"https?://", body)
    assert "Traceback" not in result.stderr


def test_skeleton_with_paper_renders_unresolved_kinds():
    """R92 场景三：--skeleton --paper → nodes=0/unresolved=9，两种 kind 都显示。"""
    out_dir = scratch_dir("s10-fix1-skel-paper-cli")
    result = _run_cli(
        "build", "--repo", REPO, "--paper", TEX, "--skeleton",
        "--out", str(out_dir), "--force",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    doc = load_trace(out_dir / "trace.json")
    assert doc["nodes"] == [] and doc["edges"] == [] and doc["anchors"] == []
    assert len(doc["unresolved"]) == 9
    kinds = {str(u["kind"]) for u in doc["unresolved"]}
    assert kinds == {"symbol", "paper_unit"}
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    block = _section(html, "unresolved")
    assert "symbol" in block and "paper_unit" in block  # 不许只过滤 paper_unit
    for entry in doc["unresolved"]:
        assert str(escape(entry["ref"])) in block
        assert str(escape(entry["reason"])) in block


def test_schema_valid_trace_missing_runtime_renders_without_crash():
    """Important-4 (FIX-4 / NB-1 & NB-2): meta.runtime 或 real_execution.ok 缺失时模板不抛 UndefinedError。"""
    trace_path = ROOT / "output" / "deliver" / "1-code-only" / "trace.json"
    if not trace_path.is_file():
        from papertrace.schema_validate import minimal_trace

        base_doc = minimal_trace()
    else:
        base_doc = load_trace(trace_path)

    # 1. 缺 meta.runtime（NB-1）
    d1 = copy.deepcopy(base_doc)
    d1["meta"].pop("runtime", None)
    assert validate_trace(d1) is None, "schema 校验必须通过（runtime 非必填）"
    html1 = render_html(d1)
    assert "骨架模式，没有真实执行" in html1

    # 2. real_execution 存在但缺 ok（NB-2）
    # R107（控制器裁决）：Jinja2 里空 dict 是 falsy，real_execution={} 会走
    # {% if ... and ... %} 的 else 分支「骨架模式，没有真实执行」——与 :52/:53/:54
    # 同风格守卫一致，模板不许为此改。要真正走到 .ok | default(false, true)
    # 并渲染「未通过」，real_execution 必须**非空但缺 ok**。
    d2 = copy.deepcopy(base_doc)
    d2["meta"]["runtime"] = {
        "torch_version": "2.0.0",
        "device": "cpu",
        "real_execution": {"reason": None},
    }
    assert validate_trace(d2) is None
    html2 = render_html(d2)
    assert "未通过" in html2

    # 空 dict 的 real_execution 同样不许抛（falsy → 骨架文案，与 S10 既有语义一致）
    d3 = copy.deepcopy(base_doc)
    d3["meta"]["runtime"] = {
        "torch_version": "2.0.0",
        "device": "cpu",
        "real_execution": {},
    }
    assert validate_trace(d3) is None
    html3 = render_html(d3)
    assert "骨架模式，没有真实执行" in html3

# ---------------------------------------------------- 真实源码行号显示（R116 / M1b）


def test_operator_rows_show_basename_and_full_path_in_title(base_doc):
    """R116：算子行显示 basename:line，完整路径只进 <title>，正文不留本机目录。"""
    doc = copy.deepcopy(base_doc)
    ops = [n for n in doc["nodes"] if n.get("level") == "op" and n.get("kind") == "op"]
    assert ops, "夹具本该有真算子"
    html = render_html(doc)
    for node in ops:
        loc = str(node.get("loc") or "")
        head, sep, line = loc.rpartition(":")
        assert sep and line.isdigit(), "M1b 之后算子 loc 必须是 file:line：%r" % (loc,)
        short = "%s:%s" % (Path(head).name, line)
        assert short in html, "算子行没显示 %s" % short
        assert "<title>%s</title>" % (escape(loc),) in html, "完整路径不可查：%s" % loc
    assert "model.py:147" in html
    # 正文里不许出现完整路径（title 之外）
    body = re.sub(r"<title>.*?</title>", "", html, flags=re.S)
    for node in ops:
        assert str(node["loc"]) not in body, "绝对路径漏进正文：%s" % node["loc"]


def test_module_rows_do_not_show_module_path_as_a_line(base_doc):
    """同一 loc 字段两种语义：module 节点的模块名不许被当成行号显示（R116）。"""
    doc = copy.deepcopy(base_doc)
    mods = [
        n
        for n in doc["nodes"]
        if n.get("level") == "module" and ":" not in str(n.get("loc") or "")
    ]
    assert mods, "夹具本该有模块节点"
    html = render_html(doc)
    for node in mods:
        loc = str(node["loc"])
        assert "<title>%s</title>" % (escape(loc),) not in html
        assert (loc + ":") not in html

