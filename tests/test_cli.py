import subprocess
import sys


def test_module_version():
    import papertrace

    assert papertrace.__version__ == "0.1.0"


def test_help_exits_zero():
    r = subprocess.run(
        [sys.executable, "-m", "papertrace", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0, r.stderr
    out = (r.stdout or "") + (r.stderr or "")
    for cmd in ("build", "dump", "serve", "eval"):
        assert cmd in out
