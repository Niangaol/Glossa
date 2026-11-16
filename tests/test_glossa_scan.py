"""T1：扫描与排除。夹具真跑，数字不手编。"""
import shutil
from pathlib import Path

from glossa import exclude, scan
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"


def _copy(name: str) -> Path:
    dst = scratch_dir("glossa-t1-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst


def _paths(result):
    return {f["path"] for f in result["files"]}


def _rules(result):
    return {r["rule"]: r["hits"] for r in result["excluded"]["rules"]}


def test_vendored_dirs_are_excluded_and_counted():
    r = scan.scan_repo(_copy("vendored-mix"))
    assert _paths(r) == {"README.md", "src/app.ts", "skipme/hidden.ts"}
    rules = _rules(r)
    for name in ("dir:node_modules", "dir:third_party", "dir:pythoncore"):
        assert name in rules, rules
        assert rules[name] >= 1
    assert r["language_counts"] == {"markdown": 1, "typescript": 2}
    assert r["excluded"]["pruned_files"] == 3
    assert r["excluded"]["pruned_files_partial"] is False
    assert r["excluded"]["files"] == 0


def test_oversize_file_is_skipped_and_recorded():
    root = _copy("vendored-mix")
    (root / "big.ts").write_bytes(b"x" * 1_000_001)
    r = scan.scan_repo(root)
    assert "big.ts" not in _paths(r)
    over = {o["path"]: o["bytes"] for o in r["excluded"]["oversize"]}
    assert over == {"big.ts": 1_000_001}


def test_env_files_are_named_but_never_read():
    root = _copy("vendored-mix")
    (root / ".env.local").write_text("SECRET=abc123", encoding="utf-8")
    r = scan.scan_repo(root)
    assert ".env.local" in {s["path"] for s in r["secrets_seen"]}
    assert "abc123" not in repr(r)          # 递归整棵返回结构都不许出现内容
    assert ".env.local" not in _paths(r)


def test_binary_assets_are_counted_not_parsed():
    root = _copy("vendored-mix")
    (root / "assets").mkdir()
    (root / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    r = scan.scan_repo(root)
    assert "assets/logo.png" not in _paths(r)
    assert "png" not in r["language_counts"]
    assert r["excluded"]["files"] == 1
    assert _rules(r)["ext:.png"] == 1


def test_max_files_truncation_is_declared():
    r = scan.scan_repo(_copy("py-mini"), max_files=2)
    assert len(r["files"]) == 2
    assert r["excluded"]["truncated"] is True


def test_empty_repo_returns_zero_counts():
    r = scan.scan_repo(_copy("empty"))
    assert r["files"] == []
    assert r["language_counts"] == {}
    assert r["excluded"]["truncated"] is False


def test_lines_and_bytes_use_read_bytes_semantics():
    root = _copy("vendored-mix")
    (root / "crlf.ts").write_bytes(b"a\r\nb\r\nc\r\n")
    r = scan.scan_repo(root)
    row = next(f for f in r["files"] if f["path"] == "crlf.ts")
    assert row["lines"] == 3
    assert row["bytes"] == 9


def test_glossaignore_adds_rules():
    root = _copy("vendored-mix")
    (root / ".glossaignore").write_text("skipme\n", encoding="utf-8")
    r = scan.scan_repo(root)
    assert "skipme/hidden.ts" not in _paths(r)
    assert "ignore:skipme" in _rules(r)


def test_truncation_flag_is_false_when_nothing_was_cut():
    full = scan.scan_repo(_copy("py-mini"))
    n = len(full["files"])
    r = scan.scan_repo(_copy("py-mini"), max_files=n)
    assert len(r["files"]) == n
    assert r["excluded"]["truncated"] is False


def test_oversize_file_is_never_read(monkeypatch):
    root = _copy("vendored-mix")
    (root / "big.ts").write_bytes(b"x" * 1_000_001)
    reads = []
    real = Path.read_bytes

    def counting(self):
        reads.append(self.name)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", counting)
    r = scan.scan_repo(root)
    assert "big.ts" not in reads
    assert {o["path"] for o in r["excluded"]["oversize"]} == {"big.ts"}
