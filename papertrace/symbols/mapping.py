"""把论文符号与代码符号对上账：配对、状态、以及**显式**标记值冲突。

语义表本切片冻结为恰好一对：论文 `d_k` ↔ 代码 `Dh`（R22）。
其它符号一律不成对：没有论文对手的代码符号记 code_only，
没有代码对手的论文符号记 paper_only。
"""

from __future__ import annotations

#: 冻结语义表：论文符号 → 代码侧 var（本切片只有一对）。
PAPER_TO_CODE = {"d_k": "Dh"}

#: 状态枚举（schema：恰为这四个）。
_MATCHED = "matched"
_MISMATCH = "value_mismatch"
_CODE_ONLY = "code_only"
_PAPER_ONLY = "paper_only"


def map_symbols(code_symbols: list, paper_symbols: list) -> list[dict]:
    """把两侧的符号表连起来，返回 symbolMapping 行。

    入参是 build_code_symbols / build_paper_symbols 的返回值；本函数只读它们、
    不改写——调用方还要拿原表去填 symbols.code / symbols.paper。

    状态规则（R22）：
    - 论文侧 `value is None` → 无法比较 → matched，`value` 取**代码侧**的值
      （paperSymbol.value 保持 None，不把代码值塞回论文表冒充论文也给数）。
    - 两侧都是数值且不相等 → value_mismatch：`value` 记代码侧，论文侧的值
      仍留在 paperSymbol.value 里，两侧都还能翻出来——绝不静默取一个值
      当成两边共同的值。
    - 语义表里没有这一对，或代码侧把该符号省略了（R21）→ paper_only。
    - 没有论文对手的代码符号 → code_only。

    行序：先按论文符号的顺序出映射行，再补没有论文对手的代码符号。
    """
    code_by_var = {}
    for row in code_symbols or []:
        code_by_var.setdefault(row.get("var"), row)
    rows = []
    paired_vars = set()
    for paper_row in paper_symbols or []:
        symbol = paper_row.get("symbol")
        code_var = PAPER_TO_CODE.get(symbol)
        code_row = code_by_var.get(code_var) if code_var else None
        if code_row is None:
            rows.append({
                "paper_symbol": symbol,
                "code_var": code_var,
                "status": _PAPER_ONLY,
                "value": paper_row.get("value"),
            })
            continue
        paired_vars.add(code_var)
        code_value = code_row.get("value")
        paper_value = paper_row.get("value")
        if paper_value is None or paper_value == code_value:
            # 论文没给数（None）无从比较，或两侧相等：都记 matched
            status, value = _MATCHED, code_value
        else:
            status, value = _MISMATCH, code_value
        rows.append({
            "paper_symbol": symbol,
            "code_var": code_var,
            "status": status,
            "value": value,
        })
    for code_row in code_symbols or []:
        var = code_row.get("var")
        if var in paired_vars:
            continue
        rows.append({
            "paper_symbol": None,
            "code_var": var,
            "status": _CODE_ONLY,
            "value": code_row.get("value"),
        })
    return rows
