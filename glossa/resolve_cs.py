"""using 四态解析与项目级边（T5）。

GC34/R290：C# **只画项目级图**。using 指向的是命名空间，一个命名空间可能散在几十个文件里，
硬画成文件级边就是造假（页面会画出几十条假依赖边，用户以为模块耦合严重）；所以 namespace
态只给「归属表 + 命中文件列表」，target 恒 None，边只来自 ProjectReference。
R289：判定顺序固定 —— ① 仓库内声明的命名空间（或是其前缀）→ namespace；② 任一项目的
PackageReference 名（或是其前缀）→ external；③ 'System' 或 'System.' 开头 → builtin；
④ 其余 → unresolved。为什么是这个顺序：把 builtin 提前会把 System.* 之外的都误判；把
package 提前会让仓库内同名命名空间（Demo.Core.Models）被 NuGet 抢走。
**前缀匹配方向不对称**（别写反）：namespace 方向是「已声明的命名空间以 specifier 开头」
（using Demo.Core 命中声明 Demo.Core.Models 的文件）；package 方向是「specifier 以包名开头」
（CommunityToolkit.Mvvm.ComponentModel 命中包 CommunityToolkit.Mvvm）。两边都按 '.' 边界切，
禁裸 startswith（否则 Demo.CoreX 会被 Demo.Core 命中）；前缀命中在 reason 里如实说明，
绝不装作精确命中。
'Microsoft.*' 不自动算 builtin（PokemonData 的 Microsoft.Data.Sqlite 是 NuGet 包）；未识别的
Microsoft.* 落 unresolved 并记 reason —— 本函数返回列表、没有独立 degraded 通道，所以降级说明
逐条挂在 reason 上（GC32/GC33 的口径：不静默、不猜）。
"""

from __future__ import annotations

BUILTIN_PREFIXES: tuple[str, ...] = ("System",)      # R289 ③：只认 System
_FRAMEWORK_TOPS = ("Microsoft", "Windows")           # 可能是框架命名空间，但不自动算 builtin


def _prefixed(child: str, head: str) -> bool:
    """按 '.' 边界判断 child 以 head 开头；禁裸 startswith（Demo.CoreX 不算 Demo.Core）。"""
    return child == head or child.startswith(head + ".")


def _ns_index(files: list[dict]) -> dict[str, list[str]]:
    """命名空间 → 声明它的仓库内文件（R287：一个文件只取它的第一个 namespace）。"""
    index: dict[str, list[str]] = {}
    for entry in files:
        path = entry.get("path")
        for ns in entry.get("namespaces") or []:
            if path and ns.get("name"):
                index.setdefault(ns["name"], []).append(path)
    return index


def _packages(projects: list[dict]) -> list[str]:
    """全部项目的 PackageReference 名（去重排序，输出可复现）。"""
    return sorted({ref.get("name") for proj in projects
                   for ref in proj.get("package_refs") or [] if ref.get("name")})


def _row(kind: str, **kw) -> dict:
    """统一形状：kind/target/package/namespace/files/reason —— target 默认 None（GC34）。"""
    row = {"kind": kind, "target": kw.get("target"), "package": kw.get("package"),
           "namespace": kw.get("namespace"), "files": kw.get("files") or [],
           "reason": kw.get("reason")}
    return row


def _namespace_row(spec: str, index: dict[str, list[str]]) -> dict | None:
    """① 命名空间态：精确同名优先，其次「已声明命名空间以 specifier 开头」的前缀命中。"""
    exact = sorted(index.get(spec) or [])
    if exact:
        return _row("namespace", namespace=spec, files=exact)
    hits = sorted({path for name, paths in index.items() if _prefixed(name, spec)
                   for path in paths})
    if not hits:
        return None
    return _row("namespace", namespace=spec, files=hits,
                reason=f"前缀命中：仓库内有命名空间以 {spec} 开头（不是精确同名命名空间）")


def _package_row(spec: str, packages: list[str]) -> dict | None:
    """② PackageReference 态：specifier 以包名开头（按 '.' 边界），返回命中的包名。"""
    for name in packages:
        if _prefixed(spec, name):
            return _row("external", package=name,
                        reason=None if spec == name else f"前缀命中：{spec} 以包名 {name} 开头")
    return None


def _builtin_or_unresolved(spec: str) -> dict:
    """③ builtin 只认 System；④ 其余 unresolved，并如实说明微软系可能只是框架命名空间。"""
    if spec in BUILTIN_PREFIXES or any(spec.startswith(p + ".") for p in BUILTIN_PREFIXES):
        return _row("builtin")
    return _row("unresolved", reason=(
        "可能是框架命名空间，未识别" if spec.split(".")[0] in _FRAMEWORK_TOPS
        else "不在仓库命名空间、PackageReference 与 System 之内"))


def _classify(spec: str, index: dict, packages: list[str]) -> dict:
    """R289：顺序固定 namespace → external → builtin → unresolved。"""
    return (_namespace_row(spec, index) or _package_row(spec, packages)
            or _builtin_or_unresolved(spec))


def resolve_usings(files: list[dict], projects: list[dict]) -> list[dict]:
    """把 files 的 using 全部解析成依赖行；**任何一态都不给文件级边**（GC34）。"""
    index, packages = _ns_index(files), _packages(projects)
    out: list[dict] = []
    for entry in files:
        for use in entry.get("imports") or []:
            spec = use.get("specifier") or ""
            got = _classify(spec, index, packages)
            out.append({"from": entry.get("path"), "specifier": spec, "kind": got["kind"],
                        "target": got["target"], "package": got["package"],
                        "namespace": got["namespace"], "files": got["files"],
                        "line": use.get("line"), "reason": got["reason"]})
    return out


def project_edges(projects: list[dict]) -> list[dict]:
    """R290：C# 的边只有项目级，来自 ProjectReference（不猜、不补、不画文件边）。"""
    names = {proj.get("name") for proj in projects}
    return [{"from": "project:" + str(proj.get("name")), "to": "project:" + str(ref),
             "kind": "internal_project"}
            for proj in projects for ref in proj.get("project_refs") or [] if ref in names]
