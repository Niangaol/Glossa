"""R511：素材包的份额预算与应急裁剪（pack_trim.py）。

一份素材包有两本字节账：
- **份额账**：sources 最多占包的 40%（3200 字节）。超了就把最长的切片从尾部减行，减到装得
  下为止，写一句「按 3200 字节预算截断，共保留 K 段」，**不置 truncated**——正常取舍不是事故，
  不该在页面上每节喊一遍超限；
- **总账**：包本身 ≤8000 字节。真到那一步才依次整段弃源码、砍短图边、删事实尾部，并置
  truncated 与写一句应急说明：说清砍了什么，比喊「超限」有用（措辞里也不出现「超过 8000 字节」，
  那句话曾被三个真仓每节重复 3–5 次，读起来像故障）。

口径与 pack 一致：json.dumps(ensure_ascii=False) 的 UTF-8 真字节——中文一字三字节，按字符数
算会把两个上限都算松。
"""

from __future__ import annotations

import json

SHARE = 0.40               # sources 的份额：包的四成
SHARE_BYTES = 3200         # 8000 × 40%，与 MAX_PACK_BYTES 同一口径
MIN_SOURCE_LINES = 1       # 一段源码至少留一行；一行都放不下就整段弃掉
SHARE_NOTE = "源码片段按 %d 字节预算截断，共保留 %d 段"
EDGE_NOTE = "图的边按字节预算留了 %d 条（共 %d 条）"


def size(value) -> int:
    """UTF-8 真字节。"""
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def share_note(count: int) -> str:
    """份额截断的唯一说明：每节一条，写成事实（保留了几段），不写成告警。"""
    return SHARE_NOTE % (SHARE_BYTES, count)


def _lines(row: dict) -> list[str]:
    return str(row.get("text") or "").splitlines()


def budget_sources(sources: list, budget: int = SHARE_BYTES) -> tuple[list[dict], bool]:
    """把 sources 压进份额预算：每次砍最长那一行切片的一行，返回 (新列表, 砍过没有)。

    最长的先砍、同样长从后往前砍，所以各段是均匀变短的，不会把第一段砍光、后面原封不动。
    """
    rows, cut = [dict(row) for row in sources], False
    while rows and size(rows) > budget:
        pos = max(range(len(rows)), key=lambda i: (len(_lines(rows[i])), i))
        lines = _lines(rows[pos])
        if len(lines) <= MIN_SOURCE_LINES:          # 单行都放不下：整段不要
            rows.pop(pos)
        else:                                       # 从尾部减一行，行号区间跟着收
            kept = lines[:-1]
            rows[pos] = dict(rows[pos], text="\n".join(kept),
                             end=int(rows[pos].get("start") or 1) + len(kept) - 1)
        cut = True
    return rows, cut


def edge_note(kept: int, total: int) -> str:
    """边的裁剪也只报事实：留了几条、原本几条（一句，别和源码那句挤在一起）。"""
    return EDGE_NOTE % (kept, total)


def trim_edges(pack: dict, max_bytes: int) -> tuple[int, int] | None:
    """预算内的图边裁剪：把最长的边表砍半，直到包装得下；返回 (留几条, 原几条) 或 None。

    图事实是 PokemonData 的真形：40 条长路径就能吃掉整个 8000 字节。边是「够模型选点」的
    信息，砍半比丢掉整条图事实划算，所以这一步算正常取舍（不置 truncated，只写一句边数）。
    """
    rows = [row for row in pack.get("facts") or () if len(row.get("edges") or ()) > 1]
    if not rows or size(pack) <= max_bytes:
        return None
    longest = max(rows, key=lambda row: len(row["edges"]))
    total = len(longest["edges"])
    while size(pack) > max_bytes and len(longest["edges"]) > 1:
        longest["edges"] = longest["edges"][:len(longest["edges"]) // 2]
    return len(longest["edges"]), total


def emergency_note(dropped: dict, max_bytes: int) -> str:
    """应急裁剪的自白：砍了多少条事实、多少段源码，一个数都不许省。"""
    return ("素材包到 %d 字节上限，应急裁剪：删掉 %d 条事实、弃掉 %d 段源码"
            % (max_bytes, dropped["facts"], dropped["sources"]))


def trim(pack: dict, max_bytes: int) -> dict:
    """总账仍然超限时的应急裁剪（原地改 pack），返回各项砍掉的量。

    源码已经付过 40% 的份额、图边也已经砍过，到这里只剩删事实：先删事实尾部，事实删光了
    还超才回头弃源码。事实被删才置 truncated（由调用方决定）。
    """
    dropped = {"facts": 0, "sources": 0}
    while size(pack) > max_bytes and pack.get("facts"):
        pack["facts"].pop()
        dropped["facts"] += 1
    while size(pack) > max_bytes and pack.get("sources"):
        pack["sources"].pop()
        dropped["sources"] += 1
    return dropped
