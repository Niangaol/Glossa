"""T2：manifest 与入口。真跑夹具，数字不手编。

R480：本文件只留 workspace / 包扫描；csproj、sln 与入口在 test_glossa_manifests2.py。
"""
import json
import shutil
from pathlib import Path

from glossa import manifests, scan
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"


def _scan(name):
    dst = scratch_dir("glossa-t2-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst, scan.scan_repo(dst)


def test_workspaces_map_package_names_to_dirs():
    root, sc = _scan("ts-monorepo")
    m = manifests.read_manifests(root, sc["files"])
    assert manifests.workspace_map(m["packages"]) == {
        "@x/a": "packages/a", "@x/b": "packages/b"}
    # R360：通配展开只认已解析索引；被排除目录不许报「缺 package.json」
    pkg = root / "package.json"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    data["workspaces"] = ["packages/*"]
    pkg.write_text(json.dumps(data), encoding="utf-8")
    for sub, nm in (("packages/node_modules/left-pad", "left-pad"),
                    ("packages/.git/inner", "inner")):
        d = root / sub
        d.mkdir(parents=True)
        (d / "package.json").write_text(json.dumps({"name": nm}), encoding="utf-8")
    sc = scan.scan_repo(root)
    m = manifests.read_manifests(root, sc["files"])
    assert manifests.workspace_map(m["packages"]) == {
        "@x/a": "packages/a", "@x/b": "packages/b"}
    assert m["degraded"] == [], m["degraded"]


def test_unsupported_workspace_glob_is_reported_not_ignored():
    """R366：packages/** 这类形状不许静默零候选——记一条 degraded，且不猜目录凑数。"""
    root, sc = _scan("ts-monorepo")
    cli = root / "apps" / "cli"                       # 有真 package.json 的子目录
    cli.mkdir(parents=True)
    (cli / "package.json").write_text(json.dumps({"name": "@x/cli"}), encoding="utf-8")
    sc = scan.scan_repo(root)
    base = manifests.read_manifests(root, sc["files"])
    pkg = root / "package.json"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    data["workspaces"] = ["packages/*", "apps/**"]
    pkg.write_text(json.dumps(data), encoding="utf-8")
    sc = scan.scan_repo(root)
    m = manifests.read_manifests(root, sc["files"])
    hit = [d for d in m["degraded"] if d["scope"] == "package.json#workspaces"]
    assert len(hit) == 1, m["degraded"]
    assert "apps/**" in hit[0]["reason"], hit[0]
    assert len(m["packages"]) == len(base["packages"])          # 不猜目录：包数不变
    assert manifests.workspace_map(m["packages"]) == manifests.workspace_map(base["packages"])


def test_multi_level_and_negated_globs_are_reported():
    """R373：多级通配与取反形状都记 degraded；取反不是目录，不许说「目录里没有文件」。

    这条同时冻结 _workspace_dirs 的 count("*") == 1 守卫：守卫去掉后 packages/**/* 会被
    当成一层通配（prefix=packages/**，零候选、零 degraded），下面断言立刻红。
    """
    root, sc = _scan("ts-monorepo")
    base = manifests.read_manifests(root, sc["files"])
    pkg = root / "package.json"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    data["workspaces"] = ["packages/*", "packages/**/*", "!packages/legacy"]
    pkg.write_text(json.dumps(data), encoding="utf-8")
    sc = scan.scan_repo(root)
    m = manifests.read_manifests(root, sc["files"])
    hit = [d for d in m["degraded"] if d["scope"] == "package.json#workspaces"]
    assert len(hit) == 2, m["degraded"]                 # 多级通配 + 取反，各一条
    assert "packages/**/*" in hit[0]["reason"], hit[0]
    assert hit[1]["reason"] == "workspace 取反形状第一版不支持：!packages/legacy", hit[1]
    # 取反从来不是目录：不许再出现「该目录里没有任何文件」的假事实（scope 不许是路径）
    assert not any("!packages/legacy" in d["scope"] for d in m["degraded"]), m["degraded"]
    # 两条不支持形状各贡献 0 个候选：成员集与改前一致（packages/* 照旧展开 a、b）
    assert manifests.workspace_map(m["packages"]) == manifests.workspace_map(base["packages"])
    assert set(manifests.workspace_map(m["packages"])) == {"@x/a", "@x/b"}
    assert len(m["packages"]) == len(base["packages"])   # 不猜目录：包数不变


def test_missing_manifest_is_degraded_not_crash():
    root, sc = _scan("ts-monorepo")
    (root / "packages" / "b" / "package.json").unlink()
    sc = scan.scan_repo(root)
    m = manifests.read_manifests(root, sc["files"])   # 不许抛
    assert any("packages/b" in d["scope"] for d in m["degraded"])


def test_deps_and_dev_deps_are_separated():
    root, sc = _scan("ts-monorepo")
    m = manifests.read_manifests(root, sc["files"])
    top = next(p for p in m["packages"] if p["name"] == "ts-mono")
    assert top["deps"] == {"left-pad": "1.0.0"}
    assert top["dev_deps"] == {"tsx": "4.0.0", "typescript": "5.0.0"}
    assert top["workspace"] is False          # R344：根包在列表里但不是 workspace 成员
    a = next(p for p in m["packages"] if p["name"] == "@x/a")
    assert a["workspace"] is True
    assert a["path"] == "packages/a"


def test_requirements_txt_lists_names_only():
    root, sc = _scan("py-mini")
    (root / "requirements.txt").write_text(
        "# comment\nnumpy>=1.0\nrequests[security]==2.0\n-r other.txt\n",
        encoding="utf-8")
    sc = scan.scan_repo(root)
    m = manifests.read_manifests(root, sc["files"])
    assert m["python"]["deps"] == ["numpy", "requests"]
    assert any("-r" in d["reason"] for d in m["degraded"])
    assert len(m["degraded"]) == 1                 # R358：注释行与空行不是降级
    assert all("comment" not in d["reason"] for d in m["degraded"])
