"""trace.json 的唯一校验入口。

所有模块只通过这一个契约交换数据。校验失败时把**全部**错误一次抛出，
不要只报第一条——排错时第一条往往只是后面的连锁反应。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from papertrace.exceptions import TraceSchemaError

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "trace.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _structural_errors(doc: dict) -> list[str]:
    """schema 管不到的整体约束：id 唯一、端点存在、父子存在、层级与来源一致。

    JSON Schema 没有 uniqueItems 之外的跨对象校验能力；这些错误若放过，UI 会静默
    用后一个节点覆盖前一个（id 撞车），或者画出一条指向空气的边。
    """
    errors: list[str] = []
    nodes = doc.get("nodes") or []
    edges = doc.get("edges") or []
    ids: set[str] = set()
    for node in nodes:
        node_id = node.get("id")
        if node_id in ids:
            errors.append(f"nodes: 节点 id 重复：{node_id}")
        ids.add(node_id)
    for node in nodes:
        parent = node.get("parent_id")
        if parent is not None and parent not in ids:
            errors.append(f"nodes: {node.get('id')} 的 parent_id 不存在：{parent}")
        level, source = node.get("level"), node.get("source")
        if level == "module" and source not in (None, "static"):
            errors.append(f"nodes: {node.get('id')} 是模块节点，source 必须是 static，实际 {source}")
        if level == "op" and source not in (None, "runtime", "static", "model"):
            errors.append(f"nodes: {node.get('id')} 的 source 非法：{source}")
    for edge in edges:
        for end in ("src", "dst"):
            endpoint = edge.get(end)
            if endpoint not in ids:
                errors.append(f"edges: {edge.get('id')} 的 {end} 端点不存在：{endpoint}")
    return errors


def validate_trace(doc: dict) -> None:
    """合法则返回 None，非法抛 TraceSchemaError（errors 里是全部原因）。"""
    validator = jsonschema.Draft202012Validator(load_schema())
    errors: list[str] = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{where}: {err.message}")
    errors.extend(_structural_errors(doc))
    if errors:
        raise TraceSchemaError(errors)


def minimal_trace(
    *,
    repo_url: str = "local://skeleton",
    commit: str = "dirty-skeleton",
    created_at: str | None = None,
) -> dict:
    """能通过校验的空骨架。节点/边/锚点全为空，绝不塞假数据。"""
    return {
        "meta": {
            "version": "1.0",
            "schema_version": "1.0.0",
            "repo": {
                "url": repo_url,
                "commit": commit,
                "language": "python",
                "entry_module": None,
            },
            "paper": {
                "source": "none",
                "unit_count": 0,
                "ingest_mode": "none",
            },
            "model": {
                "name": "offline",
                "prompt_version": "0",
                "embed_model": "none",
            },
            "created_at": created_at or _now_iso(),
            "runtime": None,
        },
        "symbols": {"code": [], "paper": [], "mapping": []},
        "nodes": [],
        "edges": [],
        "anchors": [],
        "mismatches": [],
        "unresolved": [],
        "annotations": [],
        "conflicts": [],
        "view_state": {"collapsed": [], "breadcrumb": [], "zoom": "module"},
    }


def load_trace(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_trace(doc: dict, path: str | Path, *, overwrite: bool = False) -> None:
    """写盘。默认**不覆盖**已存在的 trace.json——那可能是别人算了几十分钟的结果。

    确实要覆盖时显式传 overwrite=True（CLI 上是 --force）。
    """
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"{target} 已存在；要覆盖请显式加 --force（或 overwrite=True）。"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
