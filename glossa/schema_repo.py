"""repo.json 的唯一校验入口（T6，R291/R295）。

**不复用** papertrace.schema_validate.validate_trace：它内部调 structural_errors 查
nodes/symbols，是 trace 专用；硬复用会让 repo.json 的校验静默漏掉全部字段。
这里用 Draft202012Validator + glossa/schema/repo.json（11 顶层键全 required、
additionalProperties: false 覆盖到每个嵌套对象），错误**一次全报**、按字段路径排序。
"""

from __future__ import annotations

import json
import pathlib

import jsonschema

from papertrace.exceptions import TraceSchemaError

SCHEMA_PATH = pathlib.Path(__file__).parent / "schema" / "repo.json"


def load_schema() -> dict:
    """读契约文件；每次调用都重新读（测试会原地改 schema 做探针）。"""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_repo(doc: dict) -> None:
    """合法返回 None；非法抛 TraceSchemaError（errors 是全部原因，按路径排序）。"""
    validator = jsonschema.Draft202012Validator(load_schema())
    errors: list[str] = []
    for err in sorted(validator.iter_errors(doc),
                      key=lambda e: [str(p) for p in e.absolute_path]):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{where}: {err.message}")
    if errors:
        raise TraceSchemaError(errors)
