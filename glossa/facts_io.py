"""facts.py / fact_ids.py / graph.py 共用的小工具：严格解码、行区间摘录、numbers 归一、包归属、便携化（T6 修复轮 2）。

GC1：fact_ids.py 与 graph.py 都已顶到 200 行上限，这里承载的是**真逻辑**（strict 解码、
行区间钳位、numbers 归一、密钥名册、节点语言/包归属），不是把 docstring 挪个地方凑行数。
R395：解码一律 strict——非法 UTF-8 必须抛，由调用方转 parse='skipped' + degraded；
scan.py 里为统计行数做的 errors='replace' 只算行数，**绝不**复用它解出的文本去解析。
R396：secrets_seen 只登记名与字节数（GC30：一个字节内容都不读）。
R398 M2：行区间先 min/max 再钳到文件行数内，绝不造 fact:source:a.ts:9-2 这种反向 id。
R389：便携化放在最后一步，能连 fact:source 摘录里的本机路径一起洗掉。
"""

from __future__ import annotations

import pathlib

from glossa.repo_paths import portable_doc


def read_text(path) -> str:
    """R395：strict 解码；非法字节抛 UnicodeDecodeError，不做替换。"""
    return pathlib.Path(path).read_bytes().decode("utf-8")


def read_lines(path) -> list[str]:
    """摘录用；读不到或不是合法 UTF-8 就返回空（由调用方记降级，不产假摘录）。"""
    try:
        return read_text(path).splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def unicode_error_reason(exc: UnicodeDecodeError) -> str:
    """R395：1 基字节序号写进降级原因，页面能指到具体位置。"""
    return f"文件不是合法 UTF-8，第 {exc.start + 1} 字节处解码失败，已跳过"


def source_span(path, line: int, end, cache: dict | None = None) -> tuple[int, int, int, str]:
    """R398 M2：按 1 基行区间取原文；返回 (钳后 low, 钳后 high, 文件行数, 原文)。"""
    lines = (cache or {}).get(str(path))
    if lines is None:
        lines = read_lines(path)
        if cache is not None:
            cache[str(path)] = lines
    low, high = sorted((int(line), int(line if end is None else end)))
    if lines:                                              # 钳到文件行数内，绝不越界/反向
        low, high = min(max(low, 1), len(lines)), min(max(high, 1), len(lines))
    text = " ".join(lines[low - 1:high]).strip() if lines and low <= high else ""
    return low, high, len(lines), text


def numbers_of(values) -> list[int]:
    """只收 int（排除 bool）、float 整数转 int、升序去重（fact_ids 原样再导出）。"""
    out: set[int] = set()
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out.add(value)
        elif isinstance(value, float) and value.is_integer():
            out.add(int(value))
    return sorted(out)


def degrade(bucket: list[dict], scope: str, reason: str) -> None:
    """同 scope+reason 合并计数：一句人话说一次，别刷屏。"""
    for row in bucket:
        if row["scope"] == scope and row["reason"] == reason:
            row["count"] += 1
            return
    bucket.append({"scope": scope, "reason": reason, "count": 1})


def secrets(items) -> list[dict]:
    """R396：scan 给 {path, bytes}，原样保留（不读内容、不加字段）。"""
    return [{"path": str(item["path"]), "bytes": int(item["bytes"])} for item in items or []]


def package_of(rel: str, packages: list[dict]) -> str | None:
    """R406：包目录最长前缀命中；根包（path 为 '' 或 '.'）只管根目录文件。"""
    spans = [(len(base), str(pkg["name"])) for pkg in packages if pkg.get("name")
             for base in [str(pkg.get("path") or "").strip("/")]
             if (base in ("", ".") and "/" not in rel) or rel.startswith(base + "/")]
    return max(spans)[1] if spans else None


def node_meta(files: list[dict], packages: list[dict]) -> dict:
    """R406：file 级节点的 lang 与包归属（T9 要按语言着色、按包分组，None 不是好默认值）。"""
    return {row["path"]: {"lang": row.get("lang"), "package": package_of(row["path"], packages)}
            for row in files}


def make_portable(doc: dict, base) -> int:
    """最后一步：整份文档（含 facts.text）就地便携化，返回改写条数。"""
    return portable_doc(doc, base=base)