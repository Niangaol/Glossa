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


def test_build_without_skeleton_refuses():
    out_dir = scratch_dir("build-refuse")
    r = run_cli(
        "build",
        "--repo", "tests/fixtures/nanogpt",
        "--paper", "none",
        "--out", str(out_dir),
    )
    assert r.returncode == 2
    assert "算子追踪尚未实现" in r.stderr
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


def test_serve_and_eval_report_unimplemented():
    for cmd in ("serve", "eval"):
        r = run_cli(cmd)
        assert r.returncode == 2
        assert "本切片未实现" in r.stderr
