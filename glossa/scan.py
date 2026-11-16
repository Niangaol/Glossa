"""仓库扫描：白名单 + 排除 + 大小/数量守卫（T1）。

R264：不写 parse 键，四态由 T6 按语言与解析结果填。
R265：大小守卫在读之前判，超限只记 path+bytes，绝不 read_bytes。
R266：密钥文件只 stat，内容一个字节都不读（GC30）。
R267：os.walk 的 dirnames[:] 原地剪枝 + dirnames/filenames 全排序 → 可复现。
R268/R341：truncated 只在「确实还有本应保留的文件没扫」时 True；恰好扫完 → False。
R339：被剪目录内文件只 listing 计数，报 pruned_files / pruned_files_partial。
R340：白名单外扩展名归因 ext:<小写后缀>，使 excluded.files 可逐条核对（GC31）。
R342：R265 由 test_oversize_file_is_never_read 的计数桩看守。
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


def _count_files_inside(path: pathlib.Path) -> tuple[int, bool]:
    """R339：只 listing 数文件——不 stat 内容、不 read_bytes、不跟随符号链接。

    返回 (文件数, 计数是否可能不完整)。OSError → bad=True 并继续数能数的
    部分，不静默吞（GC31：省略必须计数上页面）。
    """
    total, bad = 0, False
    try:
        with os.scandir(path) as entries:
            items = list(entries)
    except OSError:
        return 0, True
    for entry in items:
        try:
            if entry.is_symlink():
                continue                     # 不跟随符号链接
            if entry.is_dir(follow_symlinks=False):
                n, sub_bad = _count_files_inside(pathlib.Path(entry.path))
                total += n
                bad = bad or sub_bad
            elif entry.is_file(follow_symlinks=False):
                total += 1
        except OSError:
            bad = True
    return total, bad


def scan_repo(root, *, max_file_bytes: int = 1_000_000, max_files: int = 20_000,
              use_default_excludes: bool = True, extra_ignore: list[str] | None = None) -> dict:
    """扫仓库，返回 files / excluded / secrets_seen / language_counts；不含 parse 键（R264）。"""
    if max_files < 1:                      # R350：未定义行为必须响亮拒绝，不许静默扫一个
        raise ValueError(f"max_files 必须 >= 1（收到 {max_files}）")
    root = pathlib.Path(root)
    ignore = exclude.load_glossaignore(root) + list(extra_ignore or [])
    files: list[dict] = []
    oversize: list[dict] = []
    secrets: list[dict] = []
    rules: dict[str, int] = {}
    ex_files = 0
    ex_bytes = 0
    truncated = False
    hit_limit = False                          # R341：达上限只记标志，不立即停
    pruned_files, pruned_partial = 0, False    # R339
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = pathlib.Path(dirpath).relative_to(root).as_posix()
        keep: list[str] = []
        for name in sorted(dirnames):
            rule = exclude.match_dir(name, rel_dir, ignore, use_default_excludes)
            if rule is None:
                keep.append(name)
            else:
                rules[rule] = rules.get(rule, 0) + 1
                n, bad = _count_files_inside(pathlib.Path(dirpath) / name)   # R339
                pruned_files += n
                pruned_partial = pruned_partial or bad
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
                key = "ext:" + (pathlib.Path(name).suffix.lower() or "<none>")  # R340
                rules[key] = rules.get(key, 0) + 1
                ex_files += 1
                ex_bytes += size
                continue
            if size > max_file_bytes:
                oversize.append({"path": rel, "bytes": size})
                continue                         # R265 只登记不读
            if hit_limit:
                truncated = True                 # R341 还有可保留文件才算真截断
                break
            data = (pathlib.Path(dirpath) / name).read_bytes()
            lines = len(data.decode("utf-8", errors="replace").splitlines())
            files.append({"path": rel, "lang": lang, "bytes": len(data),
                          "lines": lines, "package_hint": _package_hint(rel)})
            if len(files) >= max_files:
                hit_limit = True                 # R341 不立即 break，也不立即置真
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
            "pruned_files": pruned_files,          # R339 目录剪枝规模
            "pruned_files_partial": pruned_partial,
        },
        "secrets_seen": secrets,
        "language_counts": language_counts,
    }
