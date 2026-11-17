"""repo.json 组装（T6）：把 T1–T5 的产物拼成恰好 11 个顶层键，并挂上事实台账。

R292：T6 的 graph 占位已由 T7 填真值（build_graph 在 totals/facts 之前跑，随后 totals 复算）；R293：totals 每个数都从 doc 列表复算。
R296：url 相对 cwd，仍在 cwd 之外 → 只登记 root.name + degraded；R297：commit 只读 .git/HEAD 与 refs 文件，绝不起 subprocess。
R299：单文件失败 fail-open（parse='skipped' + degraded），root 不存在/不是目录抛 BuildError。
R367：python 的 main_guard 只信 parse；行正则只在解析被 skipped 时兜底，且记 degraded。
R388：excluded.files 恒等于 scan.excluded.files（ext 白名单外 / ignore 命中 / oversize 三类直接归因），
不用被剪目录的数字凑；R339 的 pruned_files 是并列的 listing 计数，原样保留、不并入任何分子，bytes 不伪造。
R395：读字节后 strict 解码，UnicodeDecodeError → parse='skipped' + degraded（scan 的行数 replace 不喂解析器）。
R396：secrets_seen 保留 {path, bytes} 形状（§12「只登记名与字节数」），一个字节内容都不读。
顺序偏差（计划 Step 4 是 portable_doc→build_facts）：这里反过来——fact id 的路径是 scan 的 relpath（天然相对），portable 放最后才能连 fact:source 摘录里的本机路径一起洗掉。
"""

from __future__ import annotations

import collections
import datetime
import pathlib
import re

from glossa import entries as entries_mod
from glossa import (fact_ids, facts_io, graph, lang, manifests, manifests_cs, repo_paths,
                    resolve, resolve_cs, scan)
from glossa.lang import generic
from papertrace.exceptions import BuildError
from papertrace.paths import portable_path

_TOOL = {"name": "glossa", "version": "0.1.0"}
_SHA = re.compile(r"^[0-9a-f]{40}$")


def repo_commit(root) -> tuple[str, str | None]:
    """R297：只读 .git/HEAD 与 refs 文件；读不到就 'unknown' + 原因（绝不起 subprocess）。"""
    base = pathlib.Path(root)
    try:
        head = (base / ".git" / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
        if head.startswith("ref:"):
            ref = head[4:].strip()
            head = (base / ".git" / ref).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "unknown", "读不到 .git/HEAD 或它指向的 refs 文件，commit 记为 unknown"
    if _SHA.fullmatch(head):
        return head, None
    return "unknown", "HEAD 内容不是 40 位 sha，commit 记为 unknown"


def _attach(files: list[dict], root: pathlib.Path, degraded: list[dict]) -> None:
    """逐文件 parse 并挂回 files[i]：resolve 读的正是这里挂好的 imports，顺序不能反。

    R395：strict 解码；非法字节 → parse='skipped'、零符号零 import，并记字节位置。
    """
    for row in files:
        rel, language = row["path"], row.get("lang")
        if language not in lang.LANG_PARSERS:                 # file_only 是设计口径，不记 degraded
            parsed = generic.parse_source("", rel)
        else:
            try:
                parsed = lang.parse_file(language, facts_io.read_text(root / rel), rel)
            except UnicodeDecodeError as exc:                 # R395：解码失败必须真的会失败
                parsed = {"parse": "skipped", "degraded": [facts_io.unicode_error_reason(exc)]}
            except Exception as exc:                          # R299：单文件失败不拖垮整仓
                parsed = {"parse": "skipped", "degraded": [f"解析失败，按 skipped 处理：{exc!r}"]}
        # 符号契约拉齐：csharp 没有 end_line/parent/doc_first_line，补 None（其余键原样保留）
        row["symbols"] = [{"end_line": None, "parent": None, "doc_first_line": None, **sym}
                          for sym in parsed.get("symbols") or []]
        row["imports"] = [dict(item) for item in parsed.get("imports") or []]
        row["namespaces"] = [dict(item) for item in parsed.get("namespaces") or []]
        row["parse"] = parsed.get("parse") or "skipped"
        row["main_guard"] = bool(parsed.get("main_guard"))
        row["doc_first_line"] = parsed.get("doc_first_line")
        row["degraded"] = [str(item) for item in parsed.get("degraded") or []]
        for reason in row["degraded"]:
            facts_io.degrade(degraded, "file:" + rel, reason)


def _project_hint(path: str, projects: list[dict]) -> str | None:
    """最长目录前缀命中：csproj 所在目录下的文件才属于该项目（根项目只管根目录文件）。"""
    best: tuple[int, str] | None = None
    for proj in projects:
        base = str(proj.get("path") or "").strip().strip("/")
        if base in ("", "."):
            inside = "/" not in path
        else:
            inside = path.startswith(base + "/")
        if inside and (best is None or len(base) > best[0]):
            best = (len(base), str(proj.get("name")))
    return best[1] if best else None


def _entries_with_guards(found: list[dict], files: list[dict], degraded: list[dict]) -> list[dict]:
    """R367：丢掉行正则的 main_guard，按 parse 的 main_guard 重建；只有 skipped 文件用行正则兜底。"""
    py = [row for row in files if row.get("lang") == "python"]
    fallback = {row["path"] for row in py if row.get("parse") == "skipped"}
    out = [entry for entry in found if entry.get("kind") != "main_guard"]
    for entry in found:
        if entry.get("kind") == "main_guard" and entry.get("name") in fallback:
            facts_io.degrade(degraded, "entries:main_guard", "main_guard 用行正则兜底，未经 ast 确认")
            out.append(entry)
    return out + [{"kind": "main_guard", "name": row["path"], "command": "python " + row["path"],
                   "target": "file:" + row["path"], "package": None, "note": ""}
                  for row in py if row.get("main_guard")]


def totals_of(doc: dict) -> dict:
    """R293：每个数都从 doc 里的列表复算（T7 填了 graph 后自动跟上）。"""
    files, imports = doc.get("files") or [], doc.get("imports") or []
    graph, excluded = doc.get("graph") or {}, doc.get("excluded") or {}
    by_lang = collections.Counter(row["lang"] for row in files)
    return {"files": len(files), "by_lang": dict(sorted(by_lang.items())),
            "symbols": sum(len(row.get("symbols") or []) for row in files),
            "imports": len(imports), "packages": len(doc.get("packages") or []),
            "projects": len(doc.get("projects") or []), "entries": len(doc.get("entries") or []),
            "edges": len(graph.get("edges") or []), "cycles": len(graph.get("cycles") or []),
            "unreachable": len(graph.get("unreachable") or []),
            "excluded_files": int(excluded.get("files") or 0),
            "excluded_bytes": int(excluded.get("bytes") or 0),
            "oversize": len(excluded.get("oversize") or []),
            "degraded": len(doc.get("degraded") or []),
            "unresolved": sum(1 for row in imports if row.get("kind") == "unresolved")}


def build_repo_doc(root, *, max_file_bytes: int = 1_000_000, max_files: int = 20_000,
                   use_default_excludes: bool = True, extra_ignore=None, bonus=None) -> dict:
    """扫一遍仓库并组装 repo.json（11 顶层键）；facts 由 fact_ids.build_facts 生成。"""
    root = pathlib.Path(root).resolve()          # R470：根只有一种形状（绝对路径），相对写法在门口归一
    if not root.is_dir():
        raise BuildError(f"仓库根目录不存在或不是目录：{root}")
    sc = scan.scan_repo(root, max_file_bytes=max_file_bytes, max_files=max_files,
                        use_default_excludes=use_default_excludes, extra_ignore=extra_ignore)
    files, degraded = [dict(row) for row in sc.get("files") or []], []
    _attach(files, root, degraded)
    man, cs = manifests.read_manifests(root, files), manifests_cs.read_cs_projects(root, files)
    projects, packages = list(cs.get("projects") or []), list(man.get("packages") or [])
    for row in files:
        row["project_hint"] = _project_hint(row["path"], projects)
    entries = _entries_with_guards(entries_mod.find_entries(root, files, man, cs), files, degraded)
    plain = [row for row in files if row.get("lang") != "csharp"]
    sharp = [row for row in files if row.get("lang") == "csharp"]
    imports = list(resolve.resolve_imports(plain, packages, projects or None)) if plain else []
    if sharp:
        imports += list(resolve_cs.resolve_usings(sharp, projects))
    ex = dict(sc.get("excluded") or {})                      # R388：files 只认 scan 的直接归因
    ex["secrets_seen"] = facts_io.secrets(sc.get("secrets_seen"))   # R396：名 + 字节数
    for key, default in (("rules", []), ("bytes", 0), ("oversize", []), ("truncated", False),
                         ("pruned_files", 0), ("pruned_files_partial", False)):
        ex.setdefault(key, default)
    for row in list(man.get("degraded") or []) + list(cs.get("degraded") or []):
        facts_io.degrade(degraded, str(row.get("scope") or "manifest"), str(row.get("reason") or "未给出原因"))
    sln = cs.get("sln") or {}                                 # R486：sln 里的文件夹不许静默丢
    if int(sln.get("folders_dropped") or 0):
        facts_io.degrade(degraded, "sln:" + str(sln.get("path") or "?"),
                         f"sln 里有 {int(sln['folders_dropped'])} 个解决方案文件夹，未纳入项目列表")
    commit, reason = repo_commit(root)
    url = portable_path(str(root), base=pathlib.Path(root).parent)   # R461：恒为根目录名，不读 cwd
    if reason:
        facts_io.degrade(degraded, "meta.repo.commit", reason)
    if pathlib.PurePath(url).is_absolute():                   # R296 兜底：base 之外原样返回
        facts_io.degrade(degraded, "meta.repo.url", "仓库在当前工作目录之外，只登记目录名")
        url = root.name
    langs = collections.Counter(row["lang"] for row in files)
    doc = {
        "meta": {"repo": {"url": url, "commit": commit, "root_name": root.name,
                          "language": sorted(langs.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                          if langs else None},
                 "created_at": datetime.datetime.now(datetime.timezone.utc)
                 .replace(microsecond=0).isoformat(),
                 "tool": dict(_TOOL),
                 "scan_opts": {"max_file_bytes": max_file_bytes, "max_files": max_files,
                               "use_default_excludes": bool(use_default_excludes),
                               "extra_ignore": [str(item) for item in extra_ignore or []]}},
        "totals": {}, "files": files, "packages": packages,
        "projects": projects, "entries": entries, "imports": imports,
        "graph": {},
        "excluded": ex, "degraded": degraded, "facts": {}}
    doc["graph"] = graph.build_graph(doc)                     # 必须在 totals/facts 之前（R292）
    doc["totals"] = totals_of(doc)
    doc["facts"] = fact_ids.build_facts(doc, repo_root=root, bonus=bonus)
    if doc["totals"]["degraded"] != len(doc["degraded"]):     # R398 M2：摘录阶段的降级要追平 totals
        doc["totals"] = totals_of(doc)
        doc["facts"]["fact:totals"] = fact_ids.totals_fact(doc["totals"])
    facts_io.make_portable(doc, root)                          # 最后统一便携化（含 facts.text）
    leaks = repo_paths.leaked(doc, root)                       # R493：仓外绝对路径原样保留必须记账
    if leaks:
        facts_io.degrade(doc["degraded"], "repo:paths",
                         f"台账里有 {len(leaks)} 处仓外绝对路径原样保留（来源文件自带）")
        fact_ids.put_degraded(doc["facts"], doc)                # 降级表与事实台账不许各数一份
    if doc["totals"]["degraded"] != len(doc["degraded"]):      # R398 M2：泄漏阶段新增的降级要追平 totals
        doc["totals"] = totals_of(doc)
        doc["facts"]["fact:totals"] = fact_ids.totals_fact(doc["totals"])
    fact_ids.sync_numbers(doc["facts"])                        # R502：便携化改过文字后再对一遍账
    return doc
