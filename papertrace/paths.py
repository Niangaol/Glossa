"""把 trace.json 里的本机绝对路径改成相对构建目录（cwd）的便携形态。

动机：meta.repo.url / meta.paper.source / nodes[*].loc / symbols.code[*].defined_at
原样写出时全是发件人机器的目录结构（D:\\... 之类），分享 trace.json 等于
连目录一起送出去。本模块在**写出前**统一转成相对形式，分隔符一律 '/'.

铁律：不在 base 之下的路径（换盘符）**原样返回**——宁可留着绝对路径，
也不硬造 '..\\..' 这种会指错地方的跳出形态；更不许 os.chdir。
"""

from __future__ import annotations

import os
import pathlib
import re

__all__ = ["portable_path", "portable_loc", "relativize_doc", "leaked_absolute"]

#: 本机绝对路径三类判据：盘符+分隔符 / UNC / POSIX 根
_ABS_WIN = re.compile(r"^[A-Za-z]:[\\/]")
_ABS_UNC = re.compile(r"^\\\\")
_ABS_POSIX = re.compile(r"^/")


def _is_absolute_local(text: str) -> bool:
    """是否本机绝对路径；URL 一律不算（scheme 会被 PurePath 当成盘符）。"""
    if "://" in text:
        return False
    return bool(_ABS_WIN.match(text) or _ABS_UNC.match(text) or _ABS_POSIX.match(text))


def portable_path(p: str, base: str | pathlib.Path | None = None) -> str:
    """把单个路径转成相对 base（默认 cwd）、以 '/' 分隔的便携形式。

    五类行为写全，免得下一个人改动时靠猜：
    - base 之下的绝对路径 → 相对路径，分隔符一律 '/'；
    - base 自身 → '.'；
    - 相对输入只统一分隔符（'\\' → '/'），不解析、不拼 base；
    - base 之外的绝对路径（换盘符，或同盘但在 base 上级）**原样返回**：
      不抛 ValueError，更不硬造 '..\\..' 这种会指错地方的跳出形态；
    - 非路径串（URL 之类）**原样返回**：scheme 会被 Windows 的 PurePath
      当成盘符，由 relpath 的 ValueError 兜住（paths M4，行为本身不改，
      leaked_absolute 另行把含 '://' 的串排除在泄漏之外）。

    空串是「没有路径」，原样返回。
    """
    if p == "":
        return ""
    root = pathlib.Path(base) if base is not None else pathlib.Path.cwd()
    if pathlib.PurePath(p).is_absolute():
        try:
            rel = os.path.relpath(p, root)
        except ValueError:
            # 不同盘符：relpath 直接抛，原样返回，不造假跳出形态
            return p
        if rel == ".." or rel.startswith(f"..{os.sep}"):
            # 同盘但在 base 之外：relpath 不抛，但同样不许硬造 '..\..'
            return p
        return pathlib.Path(rel).as_posix()
    # 相对路径本来就是便携形态，只统一分隔符
    return p.replace("\\", "/")


def portable_loc(loc: str, base: str | pathlib.Path | None = None) -> str:
    """只把「<文件路径>:<行号>」的路径段便携化；模块路径（如 model.GPT）原样返回。

    head 非空守卫：rpartition 切出的 head 是空串时（形如 ':12'）不当 loc，
    整串原样返回——空 head 不是文件路径。
    """
    head, sep, tail = loc.rpartition(":")
    if sep and head and tail.isdigit():
        return f"{portable_path(head, base)}:{tail}"
    return loc


def leaked_absolute(doc: dict, base: str | pathlib.Path | None = None) -> list[str]:
    """诊断：relativize_doc 覆盖的四处字段里**仍然**泄漏本机绝对路径的值（原值）。

    「仍然」的口径与 relativize 对齐：portable_path(head, base) 没能改写它，
    且它确实是本机绝对路径（盘符 / UNC / POSIX 根）。在 base 之下的绝对路径
    会被相对化，不算泄漏；含 :// 的串不算泄漏（URL 的 scheme 会被 Windows 的
    PurePath 当成盘符，误报一次用户就再不看这条提示了）。

    只读不写：这是给 CLI 打提示用的（R155），不改变 relativize 的任何行为。
    """
    out: list[str] = []

    def _check(value: object) -> None:
        if not isinstance(value, str) or value == "":
            return
        head, sep, tail = value.rpartition(":")
        path = head if sep and head and tail.isdigit() else value
        if not _is_absolute_local(path):
            return
        if portable_path(path, base) != path:  # base 之下：会被相对化，不是泄漏
            return
        out.append(value)

    meta = doc.get("meta")
    if isinstance(meta, dict):
        repo = meta.get("repo")
        if isinstance(repo, dict):
            _check(repo.get("url"))
        paper = meta.get("paper")
        if isinstance(paper, dict):
            _check(paper.get("source"))
    for node in doc.get("nodes") or ():
        if isinstance(node, dict):
            _check(node.get("loc"))
    symbols = doc.get("symbols")
    if isinstance(symbols, dict):
        for sym in symbols.get("code") or ():
            if isinstance(sym, dict):
                _check(sym.get("defined_at"))
    return out


def relativize_doc(doc: dict, base: str | pathlib.Path | None = None) -> int:
    """原地把 doc 的四处路径字段便携化，返回实际改写的字段条数。

    只覆盖 meta.repo.url、meta.paper.source、nodes[*].loc、
    symbols.code[*].defined_at；缺键 / None / 非 str 一律跳过不抛
    （trace 可能是 minimal / skeleton）。"""
    changed = 0
    meta = doc.get("meta")
    if isinstance(meta, dict):
        repo = meta.get("repo")
        if isinstance(repo, dict):
            new = portable_path(repo["url"], base) if isinstance(repo.get("url"), str) else None
            if new is not None and new != repo["url"]:
                repo["url"] = new
                changed += 1
        source = meta.get("paper")
        if isinstance(source, dict):
            new = portable_path(source["source"], base) if isinstance(source.get("source"), str) else None
            if new is not None and new != source["source"]:
                source["source"] = new
                changed += 1
    for node in doc.get("nodes") or ():
        if isinstance(node, dict) and isinstance(node.get("loc"), str):
            new = portable_loc(node["loc"], base)
            if new != node["loc"]:
                node["loc"] = new
                changed += 1
    symbols = doc.get("symbols")
    if isinstance(symbols, dict):
        for sym in symbols.get("code") or ():
            if isinstance(sym, dict) and isinstance(sym.get("defined_at"), str):
                new = portable_loc(sym["defined_at"], base)
                if new != sym["defined_at"]:
                    sym["defined_at"] = new
                    changed += 1
    return changed
