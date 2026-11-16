"""入口发现：npm scripts / py scripts / main guard / .NET 可执行项目（T2）。

R269：复合 shell 命令（&& / || / ; / |）target 必须 None + note「命令未指向单文件」。
R345：py script 的模块找不到文件 → None + note 含模块名，不许猜相近文件。
R346：只有 Exe / WinExe 产 dotnet_project 入口。
main_guard 本任务用按行正则；T3 完成后改吃 ast 结果（本任务不依赖 T3）。
"""

from __future__ import annotations

import pathlib
import re

_MAIN_GUARD = re.compile(r"""^\s*if\s+__name__\s*==\s*["']__main__["']\s*:""")


def _npm_target(cmd: str, paths: set[str]) -> tuple[str | None, str]:
    if "&&" in cmd or "||" in cmd or ";" in cmd or "|" in cmd:           # R269（变异锚 M1）
        return None, "复合命令未指向单文件"
    for tok in cmd.split():
        if "/" in tok or tok.startswith("."):
            cand = tok[2:] if tok.startswith("./") else tok
            for probe in (cand, cand + ".ts", cand + ".js"):
                if probe in paths:
                    return "file:" + probe, ""
            return None, f"未找到命令指向的文件: {tok}"
    return None, "命令不含文件路径"


def _py_target(spec: str, paths: set[str]) -> tuple[str | None, str]:
    """R345：冒号前模块名按 . 转 /，找 <mod>.py 或 <mod>/__init__.py。"""
    mod = spec.split(":", 1)[0].strip()
    base = mod.replace(".", "/")
    for probe in (base + ".py", base + "/__init__.py"):
        if probe in paths:
            return "file:" + probe, ""
    return None, f"未找到模块 {mod} 对应的文件"


def find_entries(root, files, manifests: dict, cs: dict | None = None) -> list[dict]:
    """汇总四类入口；每条含 kind/name/command/target/package/note。"""
    root = pathlib.Path(root)
    paths = {f["path"] for f in files}
    out: list[dict] = []
    for pkg in manifests.get("packages") or []:
        for name, cmd in (pkg.get("scripts") or {}).items():
            target, note = _npm_target(str(cmd), paths)
            out.append({"kind": "npm_script", "name": name, "command": str(cmd),
                        "target": target, "package": pkg.get("name"), "note": note})
    py = manifests.get("python") or {}
    for name, spec in (py.get("scripts") or {}).items():
        target, note = _py_target(str(spec), paths)
        out.append({"kind": "py_script", "name": name, "command": str(spec),
                    "target": target, "package": py.get("name"), "note": note})
    for f in files:
        if f.get("lang") != "python":
            continue
        try:
            text = (root / f["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(_MAIN_GUARD.match(line) for line in text.splitlines()):
            out.append({"kind": "main_guard", "name": f["path"],
                        "command": "python " + f["path"],
                        "target": "file:" + f["path"], "package": None, "note": ""})
    for proj in (cs or {}).get("projects") or []:
        if proj.get("output_type") in ("Exe", "WinExe"):                 # R346
            out.append({"kind": "dotnet_project", "name": proj["name"],
                        "command": "dotnet run --project " + proj["csproj"],
                        "target": "project:" + proj["name"], "package": None, "note": ""})
    return out
