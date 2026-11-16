"""dump 子命令的正文。

从 papertrace/cli.py 逐字搬出（Task C1，纯重构）：cli 只留参数解析与退出码
汇总，这里做「读文件 → 校验 → 选一种打印」。排版仍在 papertrace/report.py。
用户可见行为（stdout / stderr / 退出码）与搬走前逐字节相同。
"""

from __future__ import annotations

import sys
from pathlib import Path

from papertrace.exit_codes import UNIMPLEMENTED
from papertrace.exceptions import TraceSchemaError
from papertrace.report import print_edges, print_ops, print_overview
from papertrace.schema_validate import load_trace, validate_trace


def run_dump(trace_path: str, ops: bool = False, edges: bool = False) -> int:
    path = Path(trace_path)
    if not path.is_file():
        print(f"papertrace dump：找不到 {path}", file=sys.stderr)
        return 2
    try:
        doc = load_trace(path)
    except (OSError, ValueError) as exc:  # ValueError 覆盖 JSONDecodeError
        print(f"papertrace dump：{path} 读不成 JSON：{exc}", file=sys.stderr)
        return UNIMPLEMENTED
    try:
        validate_trace(doc)
    except TraceSchemaError as exc:
        print(f"papertrace dump：{path} 不是合法 trace：\n{exc}", file=sys.stderr)
        return 2
    if ops:
        print_ops(doc)
    elif edges:
        print_edges(doc)
    else:
        print_overview(doc)
    return 0
