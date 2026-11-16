r"""repo.json 的便携化与泄漏诊断（T6，R291：trace 专用函数不可复用）。

papertrace.paths.portable_path 的五类行为照用（base 之下转相对、base 自身 '.', 相对输入
只统一分隔符、base 之外原样返回、URL 原样返回），但 schema_validate.relativize_doc /
leaked_absolute 只认 trace 的四处字段；repo.json 有 11 个键、facts 里还有模型可能写进
text 的字符串，所以这里另写递归遍历：
- portable_doc 改写**所有**本机绝对路径串，返回改写条数；
- leaked 递归到每个嵌套值（含 facts.*.text），返回仍含本机绝对路径的字段路径。
第五类行为（URL 原样返回）必须保住：'node:fs/promises' 与 http(s) 不是路径。

R398 M5（评审实测的三处漏网）：句内的 base（'详情 .\glossa\facts.py 第 3 行'）要按词替换成
'./glossa/facts.py'；反斜杠相对串（'src\y.ts'）要归一成 './src/y.ts'；'file:///D:/…'
要剥掉协议再洗（不能因为含 '://' 就整条放过）；leaked 不能只看串首（'看 D:\x.ts 这个文件'
是泄漏），得全文找绝对路径 token。
"""

from __future__ import annotations

import pathlib
import re

from papertrace.paths import portable_path

_ABS = re.compile(r"^[A-Za-z]:[\\/]|^\\\\|^/")
_ABS_TOKEN = re.compile(r"[A-Za-z]:[\\/][^\s，。、；：\"'（）]*|\\\\[^\s，。、；：\"'（）]*")
_FILE_URL = re.compile(r"^file:///?", re.IGNORECASE)
_FILE_DRIVE = re.compile(r"^/([A-Za-z]:[\\/])")
_WIN_REL = re.compile(r"^(?:\.{1,2}[\\/])?(?:[A-Za-z0-9_@.+-]+[\\/])+[A-Za-z0-9_@.+-]*$")
_RUN = re.compile(r"[^\s，。、；：\"'（）\n]*")


def _dot(rel: str) -> str:
    """base 之内的相对串统一成 './' 开头的 posix 形态。"""
    posix = rel.replace("\\", "/").lstrip("/")
    if posix in ("", "."):
        return "."
    return posix if posix.startswith("./") else "./" + posix


def _sentence(value: str, needle: str) -> str:
    """句内出现 base：base 换成 '.'，紧随的路径段归一成 './…'（不留反斜杠）。"""
    head, *tails = value.split(needle)
    for tail in tails:
        seg = _RUN.match(tail).group(0)
        body = seg.replace("\\", "/").lstrip("/\\")
        head += ("./" + body if body else "./") + tail[len(seg):]
    return head


def _wash(value: str, base) -> tuple[str, bool]:
    """单个本机路径串 → './…'；洗不动（base 之外）就原样返回。"""
    base_s = str(pathlib.Path(base)) if base is not None else ""
    if _ABS.match(value):
        rel = portable_path(value, base)
        return (value, False) if rel == value else (_dot(rel), True)
    for needle in (base_s, base_s.replace("\\", "/")):
        if needle and needle in value:
            return _sentence(value, needle), True
    if "\\" in value and _WIN_REL.match(value):
        return _dot(value), True
    return value, False


def _rewrite(value: str, base) -> tuple[str, bool]:
    """改写单个字符串：普通 URL 不动；file:// 与绝对/相对 Windows 路径交给 _wash。"""
    if not value:
        return value, False
    if value.lower().startswith("file://"):
        body = _FILE_DRIVE.sub(r"\1", _FILE_URL.sub("", value))
        if not _ABS.match(body) and not _WIN_REL.match(body):
            body = "/" + body
        return _wash(body, base)
    if "://" in value:
        return value, False
    return _wash(value, base)


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
    """URL 不算泄漏（file:// 例外）；全文找本机绝对路径与未洗掉的 base。"""
    low = value.lower()
    if "://" in low and not low.startswith("file://"):
        return False
    body = _FILE_DRIVE.sub(r"\1", _FILE_URL.sub("", value)) if low.startswith("file://") else value
    base_s = str(pathlib.Path(base)) if base is not None else ""
    if base_s and (base_s in body or base_s.replace("\\", "/") in body):
        return True
    tokens = _ABS_TOKEN.findall(body) or ([body] if body.startswith("/") else [])
    return any(portable_path(token, base) == token for token in tokens)


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
