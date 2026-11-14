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
from papertrace.schema_structure import structural_errors

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "trace.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_trace(doc: dict) -> None:
    """合法则返回 None，非法抛 TraceSchemaError（errors 里是全部原因）。"""
    validator = jsonschema.Draft202012Validator(load_schema())
    errors: list[str] = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{where}: {err.message}")
    errors.extend(structural_errors(doc))
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