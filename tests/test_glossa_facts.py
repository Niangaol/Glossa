"""T6：事实汇总与台账。数字全部来自真跑夹具。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from glossa import fact_ids, facts, repo_paths, schema_repo
from papertrace.exceptions import BuildError, TraceSchemaError
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"
TOP_KEYS = {"meta", "totals", "files", "packages", "projects", "entries",
            "imports", "graph", "excluded", "degraded", "facts"}


def _copy(name):
    dst = scratch_dir("glossa-t6-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst


def test_repo_doc_has_exactly_eleven_top_keys():
    doc = facts.build_repo_doc(_copy("ts-monorepo"))
    assert set(doc) == TOP_KEYS


def test_totals_match_measured_fixture_counts():
    doc = facts.build_repo_doc(_copy("ts-monorepo"))
    t = doc["totals"]
    assert t["files"] == 13          # 实测：3 json + 9 ts + 1 vue
    assert t["imports"] == 9         # 实测合计
    assert t["packages"] == 3        # ts-mono + @x/a + @x/b
    assert t["projects"] == 0
    assert t["entries"] == 3         # serve / check / test
    assert t["symbols"] == 10        # 实测 export 符号（R298：App.vue 0 个）
    assert t["edges"] == 0           # R292：T6 占位，T7 填
    assert t["unresolved"] == 1
    # R293 双向钉：塞一条 import，totals 必须跟着变
    doc["imports"].append({"from": "x.ts", "specifier": "./y.js",
                           "kind": "internal", "target": "file:y.ts",
                           "package": None, "namespace": None,
                           "line": 1, "type_only": False, "reason": ""})
    assert facts.totals_of(doc)["imports"] == 10
    # R293 双向钉：塞一条符号，totals.symbols 必须跟着变（M1 靠这条真红）
    doc["files"][0]["symbols"].append({"name": "probe", "kind": "const", "line": 1})
    assert facts.totals_of(doc)["symbols"] == 11


def test_every_file_carries_parse_precision():
    doc = facts.build_repo_doc(_copy("ts-monorepo"))
    kinds = {}
    for f in doc["files"]:
        kinds[f["parse"]] = kinds.get(f["parse"], 0) + 1
    assert kinds == {"approx": 10, "file_only": 3}


def _prefixes(facts_map):
    return {k.split(":")[1] for k in facts_map}


def test_fact_ids_cover_thirteen_kinds_without_bonus():
    ts = facts.build_repo_doc(_copy("ts-monorepo"))
    cs = facts.build_repo_doc(_copy("cs-solution"))
    got = _prefixes(ts["facts"]) | _prefixes(cs["facts"])
    assert got == {"totals", "files", "file", "pkg", "project", "entry",
                   "import", "symbol", "namespace", "graph", "excluded",
                   "degraded", "source"}
    assert "bonus" not in got


def test_bonus_adds_the_fourteenth_kind():
    root = _copy("ts-monorepo")
    doc = facts.build_repo_doc(root, bonus={"nodes": [1, 2], "edges": [],
                                            "anchors": []})
    assert "bonus" in _prefixes(doc["facts"])
    assert doc["facts"]["fact:bonus"]["numbers"] == [0, 2]


def test_numbers_are_int_sorted_dedup_and_bool_excluded():
    assert fact_ids.numbers_of([3, True, 2.0, 3, 1, False, 2]) == [1, 2, 3]
    assert fact_ids.numbers_of(["x", None, 4]) == [4]
    assert fact_ids.numbers_of([]) == []


def test_unknown_fact_id_is_rejected_loudly():
    doc = facts.build_repo_doc(_copy("ts-monorepo"))
    with pytest.raises(BuildError) as ei:
        fact_ids.require(doc["facts"], ["fact:totals", "fact:nope"])
    assert "fact:nope" in str(ei.value)


def test_schema_accepts_three_real_fixture_docs():
    for name in ("empty", "ts-monorepo", "cs-solution"):
        schema_repo.validate_repo(facts.build_repo_doc(_copy(name)))


def test_schema_rejects_a_missing_top_key():
    doc = facts.build_repo_doc(_copy("ts-monorepo"))
    doc.pop("totals")
    with pytest.raises(TraceSchemaError):
        schema_repo.validate_repo(doc)


def test_schema_rejects_an_unknown_parse_value():
    doc = facts.build_repo_doc(_copy("ts-monorepo"))
    doc["files"][0]["parse"] = "maybe"
    with pytest.raises(TraceSchemaError):
        schema_repo.validate_repo(doc)


def test_doc_has_no_absolute_paths():
    root = _copy("ts-monorepo")
    doc = facts.build_repo_doc(root)
    assert repo_paths.leaked(doc, base=root) == []
    assert not Path(doc["meta"]["repo"]["url"]).is_absolute()
    assert doc["meta"]["repo"]["root_name"] == root.name   # R387：root_name = 传入 root 的目录名


def test_empty_repo_doc_is_valid_and_all_zero():
    doc = facts.build_repo_doc(_copy("empty"))
    schema_repo.validate_repo(doc)
    t = doc["totals"]
    for key in ("files", "symbols", "imports", "packages", "projects",
                "entries", "edges", "cycles", "unreachable"):
        assert t[key] == 0, key
    assert doc["files"] == []


def test_commit_is_read_from_git_head_without_subprocess(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("不许起 subprocess（R297）")
    for name in ("run", "Popen", "check_output", "call"):
        monkeypatch.setattr(subprocess, name, boom)
    root = _copy("empty")
    (root / ".git" / "refs" / "heads").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    sha = "a" * 40
    (root / ".git" / "refs" / "heads" / "main").write_text(sha + "\n", encoding="utf-8")
    commit, reason = facts.repo_commit(root)
    assert commit == sha
    assert reason is None
    assert facts.repo_commit(root / "nope")[0] == "unknown"


def test_excluded_and_degraded_are_carried_into_doc():
    root = _copy("vendored-mix")
    (root / ".env.local").write_text("SECRET=abc123", encoding="utf-8")
    (root / "big.ts").write_bytes(b"x" * 1_000_001)
    doc = facts.build_repo_doc(root)
    ex = doc["excluded"]
    assert ex["files"] >= 3                 # node_modules / third_party / pythoncore
    assert len(ex["oversize"]) == 1
    assert ex["oversize"][0]["path"] == "big.ts"
    assert ".env.local" in ex["secrets_seen"]
    assert "abc123" not in json.dumps(doc, ensure_ascii=False)   # GC30
    assert doc["totals"]["degraded"] == len(doc["degraded"])
