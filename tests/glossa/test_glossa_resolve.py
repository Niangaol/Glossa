"""T4：import 解析。绝不猜 target（GC33）。"""
from tests.common import FIXTURES
import shutil
from pathlib import Path

from glossa import manifests, resolve, scan
from glossa.lang import python as pylang, tsjs, vue
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"


def _analyze(name):
    dst = scratch_dir("glossa-t4-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    sc = scan.scan_repo(dst)
    m = manifests.read_manifests(dst, sc["files"])
    files = []
    for f in sc["files"]:
        text = (dst / f["path"]).read_text(encoding="utf-8")
        lang = f["lang"]
        if lang == "python":
            r = pylang.parse_source(text, f["path"])
        elif lang == "vue":
            r = vue.parse_source(text, f["path"])
        elif lang in ("typescript", "javascript"):
            r = tsjs.parse_source(text, f["path"])
        else:
            continue
        files.append({**f, **r})
    return dst, sc, m, files


def test_relative_js_specifier_resolves_to_ts_file():
    _, _, m, files = _analyze("ts-monorepo")
    imps = resolve.resolve_imports(files, m['packages'])
    hit = next(i for i in imps if i["from"] == "packages/a/src/server.ts"
               and i["specifier"] == "./circuit.js")
    assert hit["kind"] == "internal"
    assert hit["target"] == "file:packages/a/src/circuit.ts"


def test_workspace_specifier_resolves_to_package_and_entry():
    _, _, m, files = _analyze("ts-monorepo")
    imps = resolve.resolve_imports(files, m['packages'])
    hit = next(i for i in imps if i["specifier"] == "@x/b")
    assert hit["kind"] == "workspace"
    assert hit["package"] == "@x/b"
    assert hit["target"] == "file:packages/b/src/index.ts"   # R279 回退候选


def test_builtin_and_external_have_no_file_target():
    dst, _, m, files = _analyze("ts-monorepo")
    imps = resolve.resolve_imports(files, m['packages'])
    node = next(i for i in imps if i["specifier"] == "node:fs/promises")
    assert node["kind"] == "builtin" and node["target"] is None
    pad = next(i for i in imps if i["specifier"] == "left-pad")
    assert pad["kind"] == "external" and pad["target"] is None
    assert pad["package"] == "left-pad"
    # R355（控制器强化，条数不变）：不带 node: 前缀的裸名一律 external
    extra = dst / "bare.ts"
    extra.write_text('import fs from "fs";\nexport const z = 1;\n', encoding="utf-8")
    r = tsjs.parse_source(extra.read_text(encoding="utf-8"), "bare.ts")
    files.append({"path": "bare.ts", "lang": "typescript", **r})
    imps2 = resolve.resolve_imports(files, m['packages'])
    bare = next(i for i in imps2 if i["from"] == "bare.ts")
    assert bare["kind"] == "external" and bare["target"] is None


def test_dynamic_import_resolves_when_file_exists():
    dst, _, m, files = _analyze("ts-monorepo")
    imps = resolve.resolve_imports(files, m['packages'])
    dyn = [i for i in imps if i['specifier'] == './lazy.js']
    assert len(dyn) == 1
    assert dyn[0]["kind"] == "dynamic"
    assert dyn[0]["target"] == "file:packages/a/src/lazy.ts"
    # R356（控制器强化）：动态 import 解析不到也保持 dynamic，不猜 target
    extra = dst / "dynmissing.ts"
    extra.write_text('export async function g() { return await import("./ghost.js"); }\n', encoding="utf-8")
    r = tsjs.parse_source(extra.read_text(encoding="utf-8"), "dynmissing.ts")
    files.append({"path": "dynmissing.ts", "lang": "typescript", **r})
    imps2 = resolve.resolve_imports(files, m['packages'])
    d2 = next(i for i in imps2 if i["from"] == "dynmissing.ts")
    assert d2["kind"] == "dynamic" and d2["target"] is None
    assert "ghost" in d2["reason"]


def test_missing_specifier_is_unresolved_with_candidates_in_reason():
    _, _, m, files = _analyze("ts-monorepo")
    imps = resolve.resolve_imports(files, m['packages'])
    hit = next(i for i in imps if i["specifier"] == "./does-not-exist.js")
    assert hit["kind"] == "unresolved"
    assert hit["target"] is None
    assert "does-not-exist" in hit["reason"]
    # R357（控制器强化）：reason 不许声称「文件不存在」，且要列出试过的候选
    assert "不存在" not in hit["reason"]
    assert ".ts" in hit["reason"]


def test_import_kind_counts_match_measured_truth():
    _, _, m, files = _analyze("ts-monorepo")
    imps = resolve.resolve_imports(files, m['packages'])
    assert len(imps) == 9                     # 实测合计
    assert sum(1 for i in imps if i["kind"] == "unresolved") == 1
    assert sum(1 for i in imps if i["kind"] == "internal") == 3
    assert sum(1 for i in imps if i["kind"] == "workspace") == 2


def test_python_relative_import_resolves_by_level():
    _, _, m, files = _analyze("py-mini")
    imps = resolve.resolve_imports(files, m['packages'])
    rel = next(i for i in imps if i["from"] == "pkg/sub/util.py")
    assert rel["kind"] == "internal"
    assert rel["target"] == "file:pkg/core.py"
    top = next(i for i in imps if i["from"] == "main.py")
    assert top["target"] == "file:pkg/core.py"


def test_python_builtin_external_and_relative_unresolved():
    dst, sc, m, files = _analyze("py-mini")
    extra = dst / "kinds.py"
    extra.write_text("import os\nimport numpy\nfrom .nope import x\n", encoding="utf-8")
    r = pylang.parse_source(extra.read_text(encoding="utf-8"), "kinds.py")
    files.append({"path": "kinds.py", "lang": "python", **r})
    imps = resolve.resolve_imports(files, m['packages'])
    mine = [i for i in imps if i["from"] == "kinds.py"]
    by = {i["specifier"]: i for i in mine}
    assert by["os"]["kind"] == "builtin"          # R280
    assert by["numpy"]["kind"] == "external"
    assert by[".nope"]["kind"] == "unresolved"
    assert by[".nope"]["target"] is None
