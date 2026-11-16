"""T7b：关键文件挑选（用户拍板「只讲关键文件」）。顺序与理由必须可复算。"""
import shutil
from pathlib import Path

from glossa import facts, keyfiles
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"


def _doc(name):
    dst = scratch_dir("glossa-t7b-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return facts.build_repo_doc(dst)


def test_key_files_rank_entry_then_indegree_then_symbols():
    doc = _doc("ts-monorepo")
    got = keyfiles.key_files(doc)
    # 10 个可讲解文件（9 个 ts + 1 个 vue）；三个 package.json 是 file_only，不进候选
    assert len(got) == 10
    assert [g["path"] for g in got] == [
        "packages/a/src/server.ts",        # 入口 serve
        "packages/b/src/index.test.ts",    # 入口 test
        "packages/a/src/circuit.ts",       # 被 2 个文件依赖
        "packages/b/src/index.ts",         # 被 2 个文件依赖
        "packages/a/src/types.ts",         # 被 1 个依赖、2 个符号
        "packages/a/src/lazy.ts",          # 被 1 个依赖、1 个符号
        "packages/a/src/comments.ts",      # 同分按 path 升序
        "packages/a/src/missing.ts",
        "packages/a/src/multiline.ts",
        "apps/web/App.vue",                # 0 符号，排最后
    ]
    assert got[0]["is_entry"] is True
    assert "入口" in got[0]["reasons"][0]
    assert got[2]["indegree"] == 2
    assert "被 2 个文件依赖" in got[2]["reasons"]
    assert got[4]["symbols"] == 2
    assert all(g["lang"] in {"typescript", "vue"} for g in got)
    assert all("package.json" not in g["path"] for g in got)
    # 可复现：打乱 files 顺序，结果必须一样
    shuffled = dict(doc)
    shuffled["files"] = list(reversed(doc["files"]))
    assert keyfiles.key_files(shuffled) == got


def test_key_files_caps_at_twelve_and_is_deterministic():
    files = [{"path": f"src/f{i:02d}.py", "lang": "python", "package": None,
              "bytes": 10, "lines": 3, "parse": "exact", "symbols": [],
              "imports": [], "doc_first_line": None, "main_guard": False,
              "degraded": []} for i in range(20)]
    doc = {"files": files, "entries": [], "graph": {"edges": []},
           "totals": {"files": 20}}
    got = keyfiles.key_files(doc)
    assert len(got) == keyfiles.KEY_FILE_LIMIT == 12
    assert [g["path"] for g in got] == [f"src/f{i:02d}.py" for i in range(12)]
    assert keyfiles.key_files(doc, limit=3) == got[:3]
    assert keyfiles.key_files({"files": [], "entries": [],
                               "graph": {"edges": []},
                               "totals": {"files": 0}}) == []
    assert keyfiles.candidate_files(doc) == sorted(files, key=lambda f: f["path"])
