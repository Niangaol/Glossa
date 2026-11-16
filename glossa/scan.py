"""仓库扫描：白名单 + 排除 + 大小/数量守卫（T1）。

R264：不写 parse 键，四态由 T6 按语言与解析结果填。
R265：大小守卫在读之前判，超限只记 path+bytes，绝不 read_bytes。
R266：密钥文件只 stat，内容一个字节都不读（GC30）。
R267：os.walk 的 dirnames[:] 原地剪枝 + dirnames/filenames 全排序 → 可复现。
R268：按已保留文件数截断，达到 max_files 立即停并置 truncated=True，不静默（GC31）。
"""

from __future__ import annotations

import os
import pathlib

from glossa import exclude


def _package_hint(rel: str) -> str:
    """包提示：src/ 之后第一段，无 src/ 则第一段；只作提示不作事实。"""
    parts = rel.split("/")
    if len(parts) > 1 and parts[0] == "src":
        parts = parts[1:]
    return parts[0]


def scan_repo(root, *, max_file_bytes: int = 1_000_000, max_files: int = 20_000,
              use_default_excludes: bool = True, extra_ignore: list[str] | None = None) -> dict:
    """扫仓库，返回 files / excluded / secrets_seen / language_counts；不含 parse 键（R264）。"""
    root = pathlib.Path(root)
    ignore = exclude.load_glossaignore(root) + list(extra_ignore or [])
    files: list[dict] = []
    oversize: list[dict] = []
    secrets: list[dict] = []
    rules: dict[str, int] = {}
    ex_files = 0
    ex_bytes = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = pathlib.Path(dirpath).relative_to(root).as_posix()
        keep: list[str] = []
        for name in sorted(dirnames):
            rule = exclude.match_dir(name, rel_dir, ignore, use_default_excludes)
            if rule is None:
                keep.append(name)
            else:
                rules[rule] = rules.get(rule, 0) + 1
        dirnames[:] = keep                       # R267 原地剪枝
        for name in sorted(filenames):
            rel = (pathlib.Path(dirpath) / name).relative_to(root).as_posix()
            rule = exclude.match_file_rule(name, rel, ignore)
            if rule is not None:
                rules[rule] = rules.get(rule, 0) + 1
                ex_files += 1
                continue
            size = (pathlib.Path(dirpath) / name).stat().st_size
            if exclude.is_secret_name(name):
                secrets.append({"path": rel, "bytes": size})
                continue                         # R266 只登记不读
            lang = exclude.LANG_BY_EXT.get(pathlib.Path(name).suffix.lower())
            if lang is None:
                ex_files += 1
                ex_bytes += size
                continue
            if size > max_file_bytes:
                oversize.append({"path": rel, "bytes": size})
                continue                         # R265 只登记不读
            data = (pathlib.Path(dirpath) / name).read_bytes()
            lines = len(data.decode("utf-8", errors="replace").splitlines())
            files.append({"path": rel, "lang": lang, "bytes": len(data),
                          "lines": lines, "package_hint": _package_hint(rel)})
            if len(files) >= max_files:
                truncated = True                  # R268 明示截断
                break
        if truncated:
            break
    language_counts: dict[str, int] = {}
    for row in files:
        language_counts[row["lang"]] = language_counts.get(row["lang"], 0) + 1
    return {
        "files": files,
        "excluded": {
            "rules": [{"rule": name, "hits": rules[name]} for name in sorted(rules)],
            "files": ex_files,
            "bytes": ex_bytes,
            "oversize": oversize,
            "truncated": truncated,
        },
        "secrets_seen": secrets,
        "language_counts": language_counts,
    }
