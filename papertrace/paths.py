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

__all__ = ["portable_path", "portable_loc", "relativize_doc"]


def portable_path(p: str, base: str | pathlib.Path | None = None) -> str:
    """把单个路径转成相对 base（默认 cwd）、以 '/' 分隔的便携形式；

    空串与 base 之外的绝对路径原样返回。"""
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
    """只把「<文件路径>:<行号>」的路径段便携化；模块路径（如 model.GPT）原样返回。"""
    head, sep, tail = loc.rpartition(":")
    if sep and head and tail.isdigit():
        return f"{portable_path(head, base)}:{tail}"
    return loc


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
