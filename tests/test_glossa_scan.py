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
    (root / "SECRET.PEM").write_text("TOPSECRET-PEM", encoding="utf-8")   # R364
    (root / ".ENV.PROD").write_text("TOPSECRET-ENV", encoding="utf-8")    # R364
    r = scan.scan_repo(root)
    seen = {s["path"] for s in r["secrets_seen"]}
    assert {".env.local", "SECRET.PEM", ".ENV.PROD"} <= seen, seen
    assert "abc123" not in repr(r)          # 递归整棵返回结构都不许出现内容
    assert "TOPSECRET" not in repr(r)
    assert ".env.local" not in _paths(r)
    assert not ({"SECRET.PEM", ".ENV.PROD"} & _paths(r))


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
    # R362：裸名 / dir/ / *.ext 三种行型 + 注释与空行
    (root / ".glossaignore").write_text("# comment\n\nskipme\nassets/\n*.png\n",
                                        encoding="utf-8")
    (root / "assets").mkdir()
    (root / "assets" / "keep.ts").write_text("export const k = 1;\n", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    r = scan.scan_repo(root)
    assert _paths(r) == {"README.md", "src/app.ts"}
    rules = _rules(r)
    assert rules["ignore:skipme"] == 1
    assert rules["ignore:assets/"] == 1
    assert rules["ignore:*.png"] == 1
    assert r["excluded"]["pruned_files"] == 5   # 3 默认剪枝 + skipme 1 + assets 1
    assert r["excluded"]["files"] == 2          # logo.png(ignore) + .glossaignore(ext:<none>)
    logo = (root / "logo.png").stat().st_size
    ignore_file = (root / ".glossaignore").stat().st_size
    assert r["excluded"]["bytes"] == logo + ignore_file   # R365：ignore 也计字节
    assert r["excluded"]["bytes"] >= logo


def test_truncation_flag_is_false_when_nothing_was_cut():
    full = scan.scan_repo(_copy("py-mini"))
    n = len(full["files"])
    assert n == 6, "py-mini 应有 6 个可保留文件（R363 字面量钉死）"   # R363
    r = scan.scan_repo(_copy("py-mini"), max_files=n)
    assert len(r["files"]) == 6
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


def test_cache_dirs_are_pruned_and_counted():
    root = _copy("vendored-mix")
    cache = root / "src" / "cache"
    cache.mkdir(parents=True)
    (cache / "a.json").write_text("{}", encoding="utf-8")
    (cache / "b.json").write_text("{}", encoding="utf-8")
    dot = root / ".cache"
    dot.mkdir()
    (dot / "c.json").write_text("{}", encoding="utf-8")
    r = scan.scan_repo(root)
    rules = _rules(r)
    assert rules["dir:cache"] == 1, rules
    assert rules["dir:.cache"] == 1, rules
    assert r["excluded"]["pruned_files"] == 6, r["excluded"]
    assert r["excluded"]["pruned_files_partial"] is False
    assert _paths(r) == {"README.md", "src/app.ts", "skipme/hidden.ts"}


def test_max_files_must_be_positive():
    root = _copy("py-mini")
    for bad in (0, -1):
        try:
            scan.scan_repo(root, max_files=bad)
        except ValueError as exc:
            assert "max_files" in str(exc), str(exc)
        else:
            raise AssertionError("max_files=%d 应响亮拒绝，却静默返回了结果" % bad)
