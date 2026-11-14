import os
import subprocess
import sys

from papertrace.schema_validate import load_trace, validate_trace
from tests._tmp import scratch_dir


def run_cli(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Windows 默认控制台编码是 cp936；不强制 UTF-8 的话中文错误信息会被读成乱码。
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "papertrace", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_module_version():
    import papertrace

    assert papertrace.__version__ == "0.1.0"


def test_help_exits_zero():
    r = run_cli("--help")
    assert r.returncode == 0, r.stderr
    out = (r.stdout or "") + (r.stderr or "")
    for cmd in ("build", "dump", "serve", "eval"):
        assert cmd in out


def test_skeleton_build_writes_valid_empty_trace():
    out_dir = scratch_dir("skeleton-build")
    r = run_cli(
        "build",
        "--repo", "tests/fixtures/nanogpt",
        "--paper", "none",
        "--out", str(out_dir),
        "--skeleton",
    )
    assert r.returncode == 0, r.stderr
    trace_path = out_dir / "trace.json"
    assert trace_path.is_file()
    doc = load_trace(trace_path)
    validate_trace(doc)
    assert doc["nodes"] == []
    assert doc["anchors"] == []
    assert doc["meta"]["paper"]["ingest_mode"] == "none"
    assert doc["meta"]["paper"]["unit_count"] == 0
    assert doc["meta"]["model"]["name"] == "offline"
    # 夹具是 PaperTrace 仓库的子目录，不能把外层仓库的 HEAD 冒充成它的提交
    assert doc["meta"]["repo"]["commit"] == "dirty-subdir"


def test_build_without_skeleton_runs_real_trace():
    """去掉 --skeleton 就该真的追踪；没 torch 的话必须退出码 4 且不写文件。"""
    import pytest

    pytest.importorskip("torch", reason="真实追踪需要 torch")
    out_dir = scratch_dir("build-real")
    r = run_cli(
        "build",
        "--repo", "tests/fixtures/nanogpt",
        "--paper", "none",
        "--out", str(out_dir),
    )
    assert r.returncode == 0, r.stderr
    doc = load_trace(out_dir / "trace.json")
    validate_trace(doc)
    assert len(doc["nodes"]) > 10


def test_build_exits_4_when_torch_missing(monkeypatch):
    """缺运行时要件时必须退出码 4，并且**不能**留下一个假的 trace.json。"""
    from papertrace import cli
    from papertrace.exceptions import RuntimeUnavailable
    from papertrace.parse_code import fx_trace

    def boom():
        raise RuntimeUnavailable("没有 torch")

    monkeypatch.setattr(fx_trace, "_require_torch", boom)
    out_dir = scratch_dir("no-torch")
    code = cli.main(
        ["build", "--repo", "tests/fixtures/nanogpt", "--paper", "none", "--out", str(out_dir)]
    )
    assert code == 4
    assert not (out_dir / "trace.json").exists()


def test_build_with_paper_refuses():
    out_dir = scratch_dir("build-with-paper")
    r = run_cli(
        "build",
        "--repo", "tests/fixtures/nanogpt",
        "--paper", "arxiv:1706.03762",
        "--out", str(out_dir),
        "--skeleton",
    )
    assert r.returncode == 2
    assert "论文 ingest 尚未实现" in r.stderr


def test_dump_prints_counts():
    out_dir = scratch_dir("dump")
    built = run_cli(
        "build",
        "--repo", "tests/fixtures/nanogpt",
        "--paper", "none",
        "--out", str(out_dir),
        "--skeleton",
    )
    assert built.returncode == 0, built.stderr
    r = run_cli("dump", "--trace", str(out_dir / "trace.json"))
    assert r.returncode == 0, r.stderr
    assert "nodes=0" in r.stdout
    assert "edges=0" in r.stdout
    assert "anchors=0" in r.stdout


def test_dump_ops_prints_topological_operator_list():
    """--ops 是 M1a 的肉眼验收入口：一行一个算子，带形状和所属模块。"""
    import pytest

    pytest.importorskip("torch", reason="真实追踪需要 torch")
    out_dir = scratch_dir("dump-ops")
    built = run_cli(
        "build",
        "--repo", "tests/fixtures/nanogpt",
        "--paper", "none",
        "--out", str(out_dir),
    )
    assert built.returncode == 0, built.stderr

    r = run_cli("dump", "--trace", str(out_dir / "trace.json"), "--ops")
    assert r.returncode == 0, r.stderr
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert lines, "没有打印任何算子"

    # 只打算子层，不打模块层
    assert all(ln.startswith("root/op") for ln in lines), lines[:3]
    # 形状用 (a, b) -> (a, b) 的形式
    assert all("->" in ln for ln in lines), lines[:3]
    joined = "\n".join(lines)
    for want in ("matmul", "softmax", "masked_fill"):
        assert want in joined, f"缺 {want}"
    # 所属模块要能看出来（挂到 attn 上，而不是笼统的 root）
    assert "transformer.h.0.attn" in joined


def test_dump_ops_on_empty_trace_prints_nothing():
    out_dir = scratch_dir("dump-ops-empty")
    built = run_cli(
        "build",
        "--repo", "tests/fixtures/nanogpt",
        "--paper", "none",
        "--out", str(out_dir),
        "--skeleton",
    )
    assert built.returncode == 0, built.stderr
    r = run_cli("dump", "--trace", str(out_dir / "trace.json"), "--ops")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_dump_surfaces_degraded_nodes_and_broken_shapes():
    """降级和断链必须出现在 dump 里，不能只在 JSON 里躺着。"""
    import pytest

    pytest.importorskip("torch", reason="真实追踪需要 torch")
    out_dir = scratch_dir("dump-degraded")
    built = run_cli(
        "build",
        "--repo", "tests/fixtures/nanogpt",
        "--paper", "none",
        "--out", str(out_dir),
    )
    assert built.returncode == 0, built.stderr

    r = run_cli("dump", "--trace", str(out_dir / "trace.json"))
    assert r.returncode == 0, r.stderr
    assert "shape_broken=" in r.stdout
    assert "degraded=" in r.stdout
    # nanoGPT 的 split 一定是多输出节点 → 至少一条 degraded 明细
    assert "~ " in r.stdout
    assert "多输出算子" in r.stdout


def test_second_build_refuses_to_clobber_without_force():
    """默认不覆盖已有的 trace.json——那可能是算了几十分钟的结果。"""
    out_dir = scratch_dir("no-clobber")
    args = (
        "build",
        "--repo", "tests/fixtures/nanogpt",
        "--paper", "none",
        "--out", str(out_dir),
        "--skeleton",
    )
    assert run_cli(*args).returncode == 0
    (out_dir / "trace.json").write_text('{"sentinel": true}', encoding="utf-8")

    second = run_cli(*args)
    assert second.returncode == 3
    assert "--force" in second.stderr
    assert (out_dir / "trace.json").read_text(encoding="utf-8") == '{"sentinel": true}'

    forced = run_cli(*args, "--force")
    assert forced.returncode == 0, forced.stderr
    assert '"sentinel"' not in (out_dir / "trace.json").read_text(encoding="utf-8")


def test_serve_and_eval_report_unimplemented():
    for cmd in ("serve", "eval"):
        r = run_cli(cmd)
        assert r.returncode == 2
        assert "本切片未实现" in r.stderr
