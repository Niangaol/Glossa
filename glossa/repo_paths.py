"""repo.json 的便携化与泄漏诊断（T6，R291：trace 专用函数不可复用）。

papertrace.paths.portable_path 的五类行为照用（base 之下转相对、base 自身 '.', 相对输入
只统一分隔符、base 之外原样返回、URL 原样返回），但 schema_validate.relativize_doc /
leaked_absolute 只认 trace 的四处字段；repo.json 有 11 个键、facts 里还有模型可能写进
text 的字符串，所以这里另写递归遍历：
- portable_doc 改写**所有**本机绝对路径串，返回改写条数；
- leaked 递归到每个嵌套值（含 facts.*.text），返回仍含本机绝对路径的字段路径。
第五类行为（URL 原样返回）必须保住：'node:fs/promises' 与 http(s) 不是路径。
"""

from __future__ import annotations

import pathlib
import re

from papertrace.paths import portable_path

_ABS = re.compile(r"^[A-Za-z]:[\\/]|^\\\\|^/")


def _rewrite(value: str, base) -> tuple[str, bool]:
    """改写单个字符串：URL 不动；绝对路径交给 portable_path；base 内嵌则换掉。"""
    if not value or "://" in value:
        return value, False
    if _ABS.match(value):
        return portable_path(value, base), True
    base_s = str(pathlib.Path(base)) if base is not None else ""
    if base_s and base_s in value:
        return value.replace(base_s, "."), True
    return value, False


def portable_doc(doc: dict, base) -> int:
    """原地改写文档里所有本机绝对路径串，返回实际改写的字符串条数。"""
    changed = 0

    def walk(node):
        nonlocal changed
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if isinstance(value, str):
                    new, hit = _rewrite(value, base)
                    if hit and new != value:
                        node[key] = new
                        changed += 1
                else:
                    walk(value)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                if isinstance(value, str):
                    new, hit = _rewrite(value, base)
                    if hit and new != value:
                        node[index] = new
                        changed += 1
                else:
                    walk(value)

    walk(doc)
    return changed


def _is_leak(value: str, base) -> bool:
    """URL 不算泄漏；绝对路径仍无法便携化（或 base 内嵌未被换掉）才算。"""
    if "://" in value:
        return False
    if _ABS.match(value):
        return portable_path(value, base) == value
    base_s = str(pathlib.Path(base)) if base is not None else ""
    return bool(base_s) and base_s in value


def leaked(doc: dict, base=None) -> list[str]:
    """仍含本机绝对路径的字段路径（如 'meta.repo.url'、'facts.fact:x.text'）。"""
    hits: list[str] = []

    def walk(node, where: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{where}.{key}" if where else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{where}[{index}]")
        elif isinstance(node, str) and node and _is_leak(node, base):
            hits.append(where)

    walk(doc, "")
    return hits
