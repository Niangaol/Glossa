"""import 解析：specifier → internal / workspace / builtin / external / dynamic / unresolved（T4）。

绝不猜 target（GC33）：只有确实命中已解析文件索引才给 file:<relpath>，否则
target=None 并把**试过的候选**写进 reason。
R279：workspace 包入口按 main / module / exports 找；都没有则依次试 src/index.ts、
      index.ts、src/index.js、index.js；全不中 → target=None、package 照给、kind 仍 workspace。
R280：Python 的 import os → builtin（sys.stdlib_module_names）；仓库内没有这个模块
      → external（第三方包本来就在仓库外）；相对 import 或仓库内顶层模块存在的绝对
      import 却找不到文件 → unresolved。
R283：相对 specifier 候选后缀顺序 .ts .tsx .js .jsx .vue，然后 /index.ts、/index.js
      （原后缀优先：./a.js 先试 a.js 再试 a.ts —— SafeTrace 的真实形态）。
R355：TS/JS builtin 只认 `node:` 前缀，裸名一律 external（不自建内置名单）。
R356：动态 import 的 kind 恒为 dynamic；解析不到时 target=None + reason 列候选。
R357：索引只含传入 files（已解析语言）。unresolved 的 reason 措辞是「候选都不在已解析
      文件索引里：<候选>」，绝不写「文件不存在」——目标可能是个没解析的 .json/.md。
已知局限（如实声明）：
- T2 的 packages 条目不带 main/module/exports，所以第一版实际只走 R279 的回退候选
  （某条目若带了这些键会优先，见 _entry_from）；
- 只按文件路径解析，不读 tsconfig 的 paths / 别名；不猜（GC33）；
- namespace 恒 None（C# 的概念，TS/Python 没有等价物）。
"""

from __future__ import annotations

import posixpath
import sys

from glossa import manifests

_TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".vue")
_WS_FALLBACK = ("src/index.ts", "index.ts", "src/index.js", "index.js")


def _result(kind: str, target: str | None = None, package: str | None = None,
            reason: str | None = None) -> dict:
    return {"kind": kind, "target": target, "package": package,
            "namespace": None, "reason": reason}


def _missing(candidates: list[str]) -> str:
    """R357：只说「不在已解析文件索引里」，绝不说「文件不存在」。"""
    return "候选都不在已解析文件索引里：" + ", ".join(candidates)


def _candidates(rel: str) -> list[str]:
    """R283：原后缀优先，再 .ts/.tsx/.js/.jsx/.vue，最后 /index.ts 与 /index.js。"""
    out = [rel]
    low = rel.lower()
    known = next((suffix for suffix in _TS_SUFFIXES if low.endswith(suffix)), None)
    if known is None:
        out.extend(rel + suffix for suffix in _TS_SUFFIXES)
        tail = rel.rstrip("/")
    else:                                   # 已有后缀：换成其余后缀，不再叠加
        tail = rel[: -len(known)]
        out.extend(tail + other for other in _TS_SUFFIXES if other != known)
    out.append(tail + "/index.ts")
    out.append(tail + "/index.js")
    return out


def _resolve_file(spec: str, from_file: str, files: dict) -> dict:
    """相对路径：只认索引里真实存在的文件，绝不猜（GC33）。"""
    base = posixpath.dirname(from_file)
    rel = posixpath.normpath(posixpath.join(base, spec))
    candidates = _candidates(rel)
    for cand in candidates:
        if cand in files:
            return _result("internal", "file:" + cand)
    return _result("unresolved", reason=_missing(candidates))


def _entry_from(pkg: dict) -> str | None:
    """R279：main / module / exports 声明的入口文件（相对包目录）。"""
    raw = pkg.get("module") or pkg.get("main")
    if raw is None:
        exports = pkg.get("exports")
        if isinstance(exports, str):
            raw = exports
        elif isinstance(exports, dict):
            dot = exports.get(".") or exports.get("./")
            if isinstance(dot, str):
                raw = dot
            elif isinstance(dot, dict):
                raw = dot.get("import") or dot.get("require") or dot.get("default")
    if not isinstance(raw, str) or not raw.strip():
        return None
    clean = raw.strip()
    clean = clean[2:] if clean.startswith("./") else clean.lstrip("/")
    return posixpath.normpath(posixpath.join(pkg.get("path") or "", clean))


def _package_name(spec: str) -> str:
    """@scope/name 取两段，其余取第一段。"""
    parts = spec.split("/")
    if spec.startswith("@") and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def _workspace_candidates(spec: str, index: dict) -> list[str]:
    """带子路径时只在包目录下试（不退回入口）；否则入口字段 + R279 回退候选。"""
    name = _package_name(spec)
    root = (index.get("workspaces") or {}).get(name) or ""
    sub = spec[len(name):].lstrip("/")
    if sub:
        return _candidates(posixpath.normpath(posixpath.join(root, sub)))
    prefix = "" if root in ("", ".") else root + "/"
    entry = (index.get("entries") or {}).get(name)
    return ([entry] if entry else []) + [prefix + cand for cand in _WS_FALLBACK]


def _workspace_target(spec: str, index: dict) -> str | None:
    """R279：入口字段优先，回退候选次之；都不中就是 None（不猜）。"""
    files = index.get("files") or {}
    return next((cand for cand in _workspace_candidates(spec, index) if cand in files), None)


def _has_top(files: dict, top: str) -> bool:
    """仓库内有没有这个顶层模块/包：区分 Python 绝对 import 的 unresolved 与 external。"""
    return bool(top) and any(rel == top + ".py" or rel.startswith(top + "/") for rel in files)


def _resolve_python(spec: str, from_file: str, index: dict) -> dict:
    """R280：相对 import 按 level 上跳；绝对 import 先查仓库内，再看 stdlib 与第三方。"""
    files = index.get("files") or {}
    if spec.startswith("."):
        level = len(spec) - len(spec.lstrip("."))
        base = posixpath.dirname(from_file)
        for _ in range(level - 1):
            base = posixpath.dirname(base)
        stem = spec[level:].replace(".", "/")
        rel = posixpath.normpath(posixpath.join(base, stem)) if stem else base
        candidates = [rel + ".py"] if stem else []
        candidates.append((rel + "/" if rel and rel != "." else "") + "__init__.py")
        for cand in candidates:
            if cand in files:
                return _result("internal", "file:" + cand)
        return _result("unresolved", reason=_missing(candidates))
    top = spec.split(".")[0]
    if top in (index.get("py_stdlib") or frozenset()):
        return _result("builtin")
    stem = spec.replace(".", "/")
    candidates = [stem + ".py", stem + "/__init__.py"]
    for cand in candidates:
        if cand in files:
            return _result("internal", "file:" + cand)
    if _has_top(files, top):
        return _result("unresolved", reason=_missing(candidates))
    return _result("external", package=top or None)


def resolve_one(specifier: str, from_file: str, index: dict) -> dict:
    """解析一条 import，返回 kind/target/package/namespace/reason；不猜 target（GC33）。"""
    files = index.get("files") or {}
    if specifier.startswith("node:"):
        return _result("builtin")                      # R355：只认前缀
    if files.get(from_file) == "python":
        return _resolve_python(specifier, from_file, index)
    if specifier.startswith((".", "/")):
        return _resolve_file(specifier, from_file, files)
    name = _package_name(specifier)
    if name in (index.get("workspaces") or {}):
        found = _workspace_target(specifier, index)
        reason = None if found else _missing(_workspace_candidates(specifier, index))
        return _result("workspace", "file:" + found if found else None, name, reason)
    deps = index.get("deps") or {}
    return _result("external", package=name if name in deps else None)   # R355：裸名 external


def resolve_imports(files: list[dict], packages: list[dict],
                    projects: list[dict] | None = None) -> list[dict]:
    """把 files 的 imports 全部解析成依赖边；projects 本切片不用（C# 留给 T5）。"""
    index = {
        "files": {f["path"]: f.get("lang") for f in files if f.get("path")},
        "workspaces": {name: (path or "") for name, path
                       in manifests.workspace_map(packages or []).items() if name},
        "deps": {key: value for pkg in packages or []
                 for field in ("deps", "dev_deps")
                 for key, value in (pkg.get(field) or {}).items()},
        "py_stdlib": frozenset(getattr(sys, "stdlib_module_names", frozenset())),
        "entries": {pkg["name"]: entry for pkg in packages or [] if pkg.get("name")
                    for entry in [_entry_from(pkg)] if entry},
    }
    out: list[dict] = []
    for entry in files:
        source = entry.get("path")
        for imp in entry.get("imports") or []:
            spec = imp.get("specifier") or ""
            got = resolve_one(spec, source, index)
            out.append({"from": source, "specifier": spec,
                        "kind": "dynamic" if imp.get("dynamic") else got["kind"],
                        "target": got["target"], "package": got["package"],
                        "namespace": got["namespace"], "line": imp.get("line"),
                        "type_only": bool(imp.get("type_only")),
                        "reason": got["reason"]})         # R356：动态仍记 dynamic
    return out
