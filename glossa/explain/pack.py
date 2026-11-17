"""A3：段素材包（pack.py）——把 repo.json 剪成「一节够用」的小包。

模型只看得见包里的东西：repo 摘要、这一节的题目与目标、点名的若干条事实、六张图的字段契约、几个文件的原文片段——包外的一律看不见，也就编不出来。

口径（派发书 §1）：sources 只读 doc["files"] 里真存在的路径（别处一个字节都不碰，secrets_seen
即便混进 files 也绝不读）；单段最多 MAX_SOURCES 个片段、每段 MAX_SOURCE_LINES 行；包超过
MAX_PACK_BYTES 就先砍 sources、再缩图事实的边、最后砍 facts，并置 truncated（悄悄缩水比明说
截断更糟）。pack_for_plan 是「分几节」那次的包：三样摘要 + 按种类抽样的事实（R501：每组至少
1 条、逐层轮转补到 60 条或 8000 字节，fact:graph 带 edges 与 has_edges），不读原文。
"""

from __future__ import annotations

import json
import pathlib

from glossa.explain.patterns import PATTERNS

MAX_PACK_BYTES = 8000
MAX_SOURCES = 6
MAX_SOURCE_LINES = 40
MAX_FACTS = 40          # 没点名事实时的兜底条数：包永远比台账小
MAX_PLAN_FACTS = 60     # 分节那次最多看这么多条事实：按种类抽样，不是前 60 条（R501）
MAX_EDGES = 40          # 段包里图事实附带的边：够模型选点，不至于撑爆
MAX_PLAN_EDGES = 8      # 分节那次只带这么多条边：40 条边就能吃掉整个 8000 字节预算（R501）
_KINDS = ("totals", "files", "graph", "pkg", "project", "entry", "degraded", "file",
          "symbol", "source", "bonus", "import", "namespace", "excluded")
_TRUNC_NOTE = "素材包超过 %d 字节，已先砍 sources、再缩图事实的边、最后砍 facts" % MAX_PACK_BYTES


def _repo(doc: dict) -> dict:
    """四样能公开的仓库身份（url 是便携化的目录名，commit 是 40 位 sha 或 unknown）。"""
    repo = (doc.get("meta") or {}).get("repo") or {}
    return {"url": repo.get("url"), "commit": repo.get("commit"), "root_name": repo.get("root_name"), "language": repo.get("language")}


def _graph_summary(doc: dict) -> dict:
    """图摘要只报计数，不搬节点/边清单——那是段包的事。"""
    graph, count = doc.get("graph") or {}, len
    return {"level": graph.get("level") or "file", "nodes": count(graph.get("nodes") or []),
            "edges": count(graph.get("edges") or []), "project_edges": count(graph.get("project_edges") or []),
            "cycles": count(graph.get("cycles") or []), "layers": count(graph.get("layers") or []),
            "unreachable": count(graph.get("unreachable") or []), "truncated": bool(graph.get("truncated"))}


def _edge_rows(doc: dict) -> list[dict]:
    """段包里的边只留 from/to/label：patterns.validate_figure 逐条核得出处用得上这些。"""
    graph = doc.get("graph") or {}
    rows = list(graph.get("edges") or []) or list(graph.get("project_edges") or [])
    out = [{"from": row["from"], "to": row["to"],
            "label": row.get("label") or row.get("kind") or ""}
           for row in rows if isinstance(row, dict) and row.get("from") and row.get("to")]
    return out[:MAX_EDGES]


def _fact(rows: dict, fact_id: str, edges: list[dict]) -> dict:
    """一条事实：id 是引用凭据，text 是人话，numbers 原样（A4 复算就靠它）。"""
    row = rows.get(fact_id) or {}
    out = {"id": fact_id, "text": str(row.get("text") or ""),
           "numbers": list(row.get("numbers") or [])}
    if fact_id.startswith("fact:graph"):
        out["edges"] = [dict(edge) for edge in edges]
        out["has_edges"] = bool(out["edges"])     # 有边才画得出关系图（R501）
    return out


def _facts(doc: dict, section: dict, notes: list[str]) -> list[dict]:
    """点名的事实优先；点了但没有的记一句；一条没点就兜底前 MAX_FACTS 条。"""
    rows = doc.get("facts") or {}
    wanted = [item for item in (section.get("facts") or []) if isinstance(item, str)]
    missing = [item for item in wanted if item not in rows]
    if missing:
        notes.append("素材包里没有这些 fact id，已跳过：" + "、".join(missing))
    chosen = [item for item in wanted if item in rows] if wanted else list(rows)[:MAX_FACTS]
    edges = _edge_rows(doc)
    return [_fact(rows, fact_id, edges) for fact_id in chosen]


def _source_specs(section: dict, doc: dict) -> list[dict]:
    """这一节要读哪几段：section.sources 可写路径或 {path, start}，不写就按行数取大文件。"""
    names = section.get("sources") or section.get("files") or []
    specs = [{"path": str(item), "start": 1} if isinstance(item, str)
             else {"path": str(item["path"]), "start": item.get("start") or 1}
             for item in names if isinstance(item, str) or (isinstance(item, dict) and item.get("path"))]
    if specs:
        return specs
    files = [row for row in doc.get("files") or [] if row.get("path")]
    files.sort(key=lambda row: (-int(row.get("lines") or 0), str(row["path"])))
    return [{"path": str(row["path"]), "start": 1} for row in files]


def _sources(doc: dict, section: dict, root, notes: list[str]) -> list[dict]:
    """只读真存在的路径；读不到就说一句，绝不拿别处的文字凑数。"""
    base = pathlib.Path(root)
    known = {str(row.get("path")) for row in doc.get("files") or [] if row.get("path")}
    excluded = (doc.get("excluded") or {}).get("secrets_seen") or []
    secret = {str(item.get("path")) for item in excluded if isinstance(item, dict)}
    out: list[dict] = []
    for spec in _source_specs(section, doc):
        if len(out) >= MAX_SOURCES:
            break
        rel = str(spec.get("path") or "")
        if not rel or rel not in known:          # 只读 doc["files"] 里登记过的路径
            continue
        if rel in secret:
            notes.append("%s 在 excluded.secrets_seen 里，不读它的内容" % rel)
            continue
        start = max(1, int(spec.get("start") or 1))
        try:
            text = (base / rel).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            notes.append("%s 读不到，已跳过：%s" % (rel, exc.strerror or type(exc).__name__))
            continue
        chunk = text.splitlines()[start - 1:start - 1 + MAX_SOURCE_LINES]
        if not chunk:
            notes.append("%s 从第 %d 行起没有内容，已跳过" % (rel, start))
            continue
        out.append({"path": rel, "start": start, "end": start + len(chunk) - 1,
                    "text": "\n".join(chunk)})
    return out


def _size(pack: dict) -> int:
    """按 UTF-8 实际字节算——中文一字三字节，按字符数算会把上限算松。"""
    return len(json.dumps(pack, ensure_ascii=False).encode("utf-8"))


def _trim(pack: dict) -> bool:
    """超限就先砍 sources、再缩图事实的边（单项最大）、最后砍 facts。砍过返回 True。"""
    dropped = False
    while _size(pack) > MAX_PACK_BYTES and pack["sources"]:
        pack["sources"].pop()
        dropped = True
    while _size(pack) > MAX_PACK_BYTES and any(len(row.get("edges") or ()) > 1 for row in pack["facts"]):
        row = next(row for row in pack["facts"] if len(row.get("edges") or ()) > 1)
        row["edges"] = row["edges"][:len(row["edges"]) // 2]   # 每次砍半：别为字节把图事实丢掉
        dropped = True
    while _size(pack) > MAX_PACK_BYTES and pack["facts"]:
        pack["facts"].pop()
        dropped = True
    return dropped


def build_pack(doc: dict, section: dict, root, *, extra=None) -> dict:
    """装配一节的素材包；extra 原样并入（例如数据闸的提示），同样计入字节上限。"""
    notes: list[str] = []
    pack = {
        "repo": _repo(doc),
        "section": {"index": int(section.get("index") or 0),
                    "title": str(section.get("title") or ""),
                    "goal": str(section.get("goal") or "")},
        "facts": _facts(doc, section, notes),
        "patterns": [{"name": name, "fields": list(row.get("fields") or []),
                      "summary": str(row.get("summary") or "")}
                     for name, row in PATTERNS.items()],
        "sources": _sources(doc, section, root, notes),
    }
    if extra:
        pack.update(extra)
    truncated = _trim(pack)
    pack["truncated"] = truncated
    pack["notes"] = notes + ([_TRUNC_NOTE] if truncated else [])
    if _size(pack) > MAX_PACK_BYTES:      # 说明与标志也要算进上限：包本身绝不能超
        _trim(pack)
    return pack


def _groups(rows: dict) -> list[list[str]]:
    """按种类分组（fact: 后第一段），组内保持台账顺序；组序先按 _KINDS 再按首见顺序。"""
    groups: dict[str, list[str]] = {}
    for fact_id in rows:
        parts = str(fact_id).split(":")
        key = parts[1] if len(parts) > 1 and parts[0] == "fact" else "other"
        groups.setdefault(key, []).append(fact_id)
    return [groups[key] for key in [k for k in _KINDS if k in groups]
            + [k for k in groups if k not in _KINDS]]


def _sampled(rows: dict) -> list[str]:
    """每组先各取 1 条，再逐层轮转：任何一类都不会被大群淹没（R501）。"""
    groups, chosen, depth = _groups(rows), [], 1
    while len(chosen) < MAX_PLAN_FACTS and any(len(group) >= depth for group in groups):
        for group in groups:
            if len(chosen) < MAX_PLAN_FACTS and len(group) >= depth:
                chosen.append(group[depth - 1])
        depth += 1
    return chosen


def pack_for_plan(doc: dict) -> dict:
    """「分几节」那次的包：三样摘要 + 按种类抽样的事实（每组至少 1 条、带边），不读原文。"""
    rows, edges = doc.get("facts") or {}, _edge_rows(doc)[:MAX_PLAN_EDGES]
    pack = {"repo": _repo(doc), "totals": dict(doc.get("totals") or {}),
            "graph": _graph_summary(doc), "has_edges": bool(edges),
            "facts": [_fact(rows, fact_id, edges) for fact_id in _sampled(rows)], "truncated": False}
    while _size(pack) > MAX_PACK_BYTES and pack["facts"]:   # 先到者为准：60 条或 8000 字节
        pack["facts"].pop()
        pack["truncated"] = True
    return pack
