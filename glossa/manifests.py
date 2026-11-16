"""manifest 读取：package.json / pyproject.toml / requirements.txt（T2）。

R272：requirements 只取包名（剥版本约束/extras/markers）；-r 等选项行记 degraded。
R273：读失败（JSON 坏/文件缺/TOML 坏）记 degraded，不抛。
R344：packages 列表含根包与子包；workspace 键是 bool；workspace_map 只收子包。
R347：没有任何 manifest 时仍返回完整三键；「没有」是正常事实不是降级。
R360：workspace 通配候选只从 files 索引派生（不 iterdir 磁盘），被排除目录零 degraded。
"""

from __future__ import annotations

import json
import pathlib
import re
import tomllib


def _load_json(root: pathlib.Path, rel: str, degraded: list[dict]) -> dict | None:
    """R273：坏 JSON / 缺文件 → degraded，不抛。"""
    try:
        return json.loads((root / rel).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        degraded.append({"scope": rel, "reason": f"package.json 读取失败: {exc}", "count": 1})
        return None


def _pkg_entry(rel: str, data: dict, workspace: bool) -> dict:
    """R344：path 是包目录（唯一真源），workspace 只记 bool。"""
    return {"name": data.get("name"),
            "path": pathlib.PurePosixPath(rel).parent.as_posix(),
            "manifest": rel,
            "deps": dict(data.get("dependencies") or {}),
            "dev_deps": dict(data.get("devDependencies") or {}),
            "scripts": dict(data.get("scripts") or {}),
            "workspace": workspace}


def _workspace_dirs(patterns: list, paths: set[str]) -> list[str]:
    """第一版只支持字面目录与 packages/* 一层通配；候选只从索引派生（R360）。"""
    out: list[str] = []
    for pat in patterns:
        pat = str(pat).strip().rstrip("/")
        if pat.endswith("/*"):
            prefix = pat[:-2]
            head = prefix + "/"
            dirs = sorted({p[len(head):].split("/", 1)[0] for p in paths
                           if p.startswith(head) and "/" in p[len(head):]})
            out.extend(prefix + "/" + d for d in dirs)
        elif pat:
            out.append(pat)
    return list(dict.fromkeys(out))


def _req_names(root: pathlib.Path, degraded: list[dict]) -> list[str]:
    """R272：只取包名；注释行跳过；-r 等选项行不展开并记 degraded。"""
    names: list[str] = []
    try:
        text = (root / "requirements.txt").read_text(encoding="utf-8")
    except OSError as exc:
        degraded.append({"scope": "requirements.txt",
                         "reason": f"requirements.txt 读取失败: {exc}", "count": 1})
        return names
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            degraded.append({"scope": "requirements.txt",
                             "reason": f"选项行未展开: {line}", "count": 1})
            continue
        hit = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
        if hit:
            names.append(hit.group(0))
    return names


def _read_python(root: pathlib.Path, paths: set[str], degraded: list[dict]) -> dict:
    """R347：没有 pyproject/requirements 时返回空壳，不记 degraded。"""
    out: dict = {"name": None, "scripts": {}, "deps": []}
    if "pyproject.toml" in paths:
        try:
            data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            degraded.append({"scope": "pyproject.toml",
                             "reason": f"pyproject.toml 读取失败: {exc}", "count": 1})
            data = {}
        proj = data.get("project") or {}
        out["name"] = proj.get("name")
        out["scripts"] = dict(proj.get("scripts") or {})
    if "requirements.txt" in paths:
        out["deps"] = _req_names(root, degraded)
    return out


def read_manifests(root: pathlib.Path, files: list[dict]) -> dict:
    """读 JS/Python manifest；返回 packages / python / degraded 三键（R347）。"""
    root = pathlib.Path(root)
    paths = {f["path"] for f in files}
    degraded: list[dict] = []
    packages: list[dict] = []
    seen: set[str] = set()
    root_data = None
    if "package.json" in paths:
        root_data = _load_json(root, "package.json", degraded)
        seen.add("package.json")
        if root_data is not None:
            packages.append(_pkg_entry("package.json", root_data, False))
    ws = (root_data or {}).get("workspaces") or []
    if isinstance(ws, dict):
        ws = ws.get("packages") or []
    for d in _workspace_dirs(ws, paths):
        rel = d + "/package.json"
        if not any(p.startswith(d + "/") for p in paths):
            degraded.append({"scope": rel,
                             "reason": "workspaces 声明的目录在已解析文件索引里没有任何文件（可能不存在或被排除）",
                             "count": 1})
            continue
        seen.add(rel)
        if rel in paths:
            data = _load_json(root, rel, degraded)
            if data is not None:
                packages.append(_pkg_entry(rel, data, True))
        else:
            degraded.append({"scope": rel, "reason": "在已解析文件索引里没有 package.json", "count": 1})
    for rel in sorted(paths - seen):
        if pathlib.PurePosixPath(rel).name == "package.json":
            data = _load_json(root, rel, degraded)
            if data is not None:
                packages.append(_pkg_entry(rel, data, False))
    return {"packages": packages, "python": _read_python(root, paths, degraded),
            "degraded": degraded}


def workspace_map(packages: list[dict]) -> dict[str, str]:
    """R344：只收 workspaces 声明的子包；根包在列表里但不进 map。"""
    return {p["name"]: p["path"] for p in packages if p["workspace"]}
