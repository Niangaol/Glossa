"""组装层：把角色表、指标表、代码符号表合成 trace.analysis（Task C4，GC22 / R206–R210）。

口径（要改先改这段 docstring，再改测试，GC19）：
- 只写两个字段：doc["symbols"]["code"] 与 doc["analysis"]（R210）。
- modules = 角色表 ∪ 指标表按 module_id 内接；两边集合不一致就抛 BuildError
  （R206），绝不静默丢模块。
- roles 只列真出现过的角色，计数从合并后的 modules 现数，不写 0 项（R207）。
- totals 只用 analysis_totals 的返回值，不另算一遍（R208 / R204）。
- empty_analysis() 是骨架模式的同形状空壳，也必须过 schema（R209）。
- method 必须是粗估口径的自述（GC19），全文照抄 METHOD_TEXT。
"""

from papertrace.analyze_metrics import analysis_totals, module_metrics
from papertrace.analyze_roles import module_roles
from papertrace.exceptions import BuildError
from papertrace.symbols.code_table import build_code_symbols

#: 粗估口径的自述：GC19 要求估算必须自称估算，禁止「精确计算量」「实测 FLOPs」。
METHOD_TEXT = (
    "参数量按权重张量元素数精确统计；FLOPs 只对 matmul/linear 估算"
    "（2×输出元素数×输入最后一维），未考虑转置语义与逐元素算子，属于粗估，"
    "并随 batch/序列长度线性变化。"
)

#: 合并后每条 module 恰好 8 个键：角色 5 个 + 指标 3 个。
_METRIC_KEYS = ("params", "max_activation", "est_flops")


def analyze_code(doc: dict, model) -> dict:
    """原地填 doc["symbols"]["code"] 与 doc["analysis"]，返回同一个 doc。"""
    doc["symbols"]["code"] = build_code_symbols(model, doc)
    roles = {row["module_id"]: row for row in module_roles(doc["nodes"])}
    metrics = {row["module_id"]: row for row in module_metrics(doc["nodes"])}
    rows = _merge(roles, metrics)
    doc["analysis"] = {
        "modules": rows,
        "totals": analysis_totals(rows, doc["nodes"]),
        "roles": _count_roles(rows),
        "method": METHOD_TEXT,
    }
    return doc


def empty_analysis() -> dict:
    """骨架模式用：结构齐全但 modules 空、totals 全 0、roles 空，method 用同一份 METHOD_TEXT。"""
    return {
        "modules": [],
        "totals": {
            "modules": 0,
            "params": 0,
            "max_activation": 0,
            "est_flops": 0,
            "degraded": 0,
            "degraded_reasons": [],
        },
        "roles": {},
        "method": METHOD_TEXT,
    }


def _merge(roles: dict, metrics: dict) -> list[dict]:
    """按 module_id 内接角色表与指标表，产出 34 条 8 键 module（升序）。"""
    only_roles = sorted(set(roles) - set(metrics))
    only_metrics = sorted(set(metrics) - set(roles))
    if only_roles or only_metrics:
        raise BuildError(
            "模块角色表与指标表对不上："
            f"只有角色没有指标 {only_roles}；只有指标没有角色 {only_metrics}"
        )
    rows = []
    for module_id in sorted(roles):
        row = dict(roles[module_id])
        for key in _METRIC_KEYS:
            row[key] = metrics[module_id][key]
        rows.append(row)
    return rows


def _count_roles(rows: list[dict]) -> dict:
    """R207：只数真出现的角色，0 项不写（真夹具 unknown 为 0，就不该有那个键）。"""
    counts: dict = {}
    for row in rows:
        role = row["role"]
        counts[role] = counts.get(role, 0) + 1
    return {role: counts[role] for role in sorted(counts)}
