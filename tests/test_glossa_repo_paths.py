"""R470：`--repo .` 不许把每个点变成路径分隔符；仓库根只允许一种形状（resolve 后的绝对路径）。

控制器复现的坏形态：`README./md`、`papertrace/cli./py`。根因是 `_wash` 拿 `str(base)` 当 needle
做子串替换，而 `--repo .` 时 `base_s == "."`。这里钉两件事：
1. 同一棵树用 `--repo .` 与 `--repo <绝对路径>` 扫出的 repo.json 除 meta 外完全相同，且路径里没有
   任何「点紧跟分隔符」的坏形态；
2. `_wash` 对空串、`.`、`/`、单盘符这四个退化 needle 一律不做子串替换（宁可不洗，也不许错洗）。
"""
import json
import re
import shutil
from pathlib import Path

import pytest

from glossa import cli, facts, repo_paths
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"
_DOT_SLASH = re.compile(r"\.[/\\]")


def _repo(name="ts-monorepo"):
    dst = scratch_dir("glossa-r470-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst


def _analyze(monkeypatch, root, repo_arg, out):
    """在 root 下跑 analyze，返回落盘的 repo.json（含 meta，供对比前剔除）。"""
    monkeypatch.chdir(root)
    assert cli.main(["analyze", "--repo", repo_arg, "--out", str(out), "--force"]) == 0
    return json.loads((out / "repo.json").read_text(encoding="utf-8"))


def _all_paths(doc):
    """台账里所有「路径位」：files[].path、graph 节点 id / 边两端、entries[].target 的文件部分。"""
    paths = [row["path"] for row in doc.get("files") or []]
    graph = doc.get("graph") or {}
    paths += [str(row.get("id")) for row in graph.get("nodes") or []]
    for edge in graph.get("edges") or []:
        paths += [str(edge.get("from")), str(edge.get("to"))]
    for entry in doc.get("entries") or []:
        target = str(entry.get("target") or "")
        if target.startswith("file:"):
            paths.append(target.split(":", 1)[1])
    return paths


def test_dot_repo_matches_absolute_repo_and_has_no_dotted_paths(monkeypatch):
    """R470 ①：两种写法必须产出同一本台账；且不许出现 `README./md` 这类坏路径。"""
    root = _repo()
    out_dot = scratch_dir("glossa-r470-out-dot")
    out_abs = scratch_dir("glossa-r470-out-abs")
    dot = _analyze(monkeypatch, root, ".", out_dot)
    absolute = _analyze(monkeypatch, root, str(root), out_abs)
    bad = [p for p in _all_paths(dot) if _DOT_SLASH.search(p) or p.startswith("./")]
    assert bad == [], "坏路径（点被当成路径分隔符）：%r" % (bad[:5],)
    dot.pop("meta"), absolute.pop("meta")
    assert (json.dumps(dot, ensure_ascii=False, sort_keys=True)
            == json.dumps(absolute, ensure_ascii=False, sort_keys=True)), "两种根写法产出的台账不一致"


def test_build_repo_doc_resolves_a_relative_root(monkeypatch):
    """R470 ③：facts 层自己也 resolve——build_repo_doc('.') 与绝对路径必须是同一本台账。"""
    root = _repo()
    monkeypatch.chdir(root)
    relative = facts.build_repo_doc(".")
    absolute = facts.build_repo_doc(str(root))
    bad = [p for p in _all_paths(relative) if _DOT_SLASH.search(p) or p.startswith("./")]
    assert bad == [], "相对根把点当路径分隔符：%r" % (bad[:5],)
    assert relative["meta"]["repo"] == absolute["meta"]["repo"], "相对根的 meta.repo 和绝对根不一致"
    relative.pop("meta"), absolute.pop("meta")
    assert relative == absolute


@pytest.mark.parametrize("base, value", [
    ("", "README.md"),
    (".", "README.md"),
    (".", "papertrace/cli.py"),
    ("/", "src/x.ts"),
    ("D:", "D:packages/a/src/server.ts"),
])
def test_wash_never_substitutes_degenerate_needles(base, value):
    """R470 ②：四个退化 needle 一律不做子串替换（宁可不洗，也不许错洗）。"""
    assert repo_paths._wash(value, base) == (value, False)
