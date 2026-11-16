"""C# 项目结构：csproj / sln（T2）。

R270：sln 只取路径以 .csproj 结尾的 Project 条目；解决方案文件夹计 folders_dropped。
R271：ImplicitUsings enable → degraded「隐式全局 using 未展开，依赖可能少计」。
R273：XML 坏 / 文件缺 → degraded，不抛。
R346：缺 OutputType → 'Library'（SDK 风格默认值，不是未知）。
"""

from __future__ import annotations

import pathlib
import posixpath
import re
import xml.etree.ElementTree as ET

_SLN_PROJECT = re.compile(r'Project\("\{[^}]+\}"\)\s*=\s*"([^"]*)"\s*,\s*"([^"]*)"')


def _text(node: ET.Element, tag: str) -> str | None:
    el = node.find(".//" + tag)
    return el.text.strip() if el is not None and el.text else None


def read_cs_projects(root: pathlib.Path, files: list[dict]) -> dict:
    """读全部 csproj 与首个 sln；返回 projects / sln / degraded。"""
    root = pathlib.Path(root)
    degraded: list[dict] = []
    projects: list[dict] = []
    by_path: dict[str, dict] = {}
    for rel in sorted(f["path"] for f in files if f["path"].endswith(".csproj")):
        try:
            node = ET.fromstring((root / rel).read_text(encoding="utf-8"))
        except (OSError, ET.ParseError) as exc:
            degraded.append({"scope": rel, "reason": f"csproj 读取失败: {exc}", "count": 1})
            continue
        name = pathlib.PurePosixPath(rel).stem
        implicit = (_text(node, "ImplicitUsings") or "").lower() == "enable"
        proj = {"name": name,
                "path": pathlib.PurePosixPath(rel).parent.as_posix(),
                "csproj": rel,
                "target_framework": _text(node, "TargetFramework"),
                "root_namespace": _text(node, "RootNamespace") or name,
                "implicit_usings": implicit,
                "nullable": (_text(node, "Nullable") or "").lower() == "enable",
                "output_type": _text(node, "OutputType") or "Library",   # R346
                "package_refs": [{"name": el.get("Include"), "version": el.get("Version")}
                                 for el in node.iter("PackageReference")],
                "project_refs": []}
        if implicit:                                                     # R271（变异锚 M3）
            degraded.append({"scope": "project:" + name,
                             "reason": "隐式全局 using 未展开，依赖可能少计", "count": 1})
        raw_refs = [el.get("Include") or "" for el in node.iter("ProjectReference")]
        projects.append(proj)
        by_path[rel] = proj
        proj["_raw_refs"] = raw_refs
    for proj in projects:
        base = pathlib.PurePosixPath(proj["csproj"]).parent.as_posix()
        for inc in proj.pop("_raw_refs"):
            norm = posixpath.normpath(posixpath.join(base, inc.replace("\\", "/")))
            target = by_path.get(norm)
            if target is not None:
                proj["project_refs"].append(target["name"])
            else:
                degraded.append({"scope": "project:" + proj["name"],
                                 "reason": f"ProjectReference 未解析: {inc}", "count": 1})
    sln = None
    sln_paths = sorted(f["path"] for f in files if f["path"].endswith(".sln"))
    if sln_paths:
        rel = sln_paths[0]
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            degraded.append({"scope": rel, "reason": f"sln 读取失败: {exc}", "count": 1})
            text = ""
        names: list[str] = []
        dropped = 0
        for hit in _SLN_PROJECT.finditer(text):
            pname, ppath = hit.group(1), hit.group(2)
            if ppath.endswith(".csproj"):                                # R270（变异锚 M2）
                names.append(pname)
            else:
                dropped += 1
        sln = {"path": rel, "projects": sorted(names), "folders_dropped": dropped}
    return {"projects": projects, "sln": sln, "degraded": degraded}
