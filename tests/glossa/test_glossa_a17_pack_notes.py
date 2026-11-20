"""D8：源文件大面积读不到时，说明本身会把素材包撑爆（实测 486 条 / 42,756 字节）。

真模型分节后会点名很多文件；这些文件在台账里登记过、磁盘上却读不到时，每读失败一次加一条
说明，条数没有上限 → 说明把 8000 字节预算吃光，facts 被 trim 到 0，模型什么都看不到。
"""

import re

from glossa.explain import pack, pack_trim
from tests._tmp import scratch_dir

FACT = {"fact:totals": {"id": "fact:totals", "text": "共 300 个文件。", "numbers": [300], "cites": []}}


def _doc(paths):
    return {"meta": {"repo": {"root_name": "r", "commit": "x", "url": "r", "language": "python"}},
            "totals": {}, "files": [{"path": p} for p in paths], "packages": [],
            "projects": [], "entries": [], "graph": {"level": "file", "nodes": [], "edges": []},
            "excluded": {"secrets_seen": []}, "facts": dict(FACT)}


def _section(paths):
    return {"index": 1, "title": "规模", "goal": "讲清楚",
            "sources": [{"path": p} for p in paths[:300]], "facts": ["fact:totals"]}


def test_unreadable_sources_cannot_flood_the_pack():
    root = scratch_dir("pack-notes")
    paths = ["gone/f%03d.py" % i for i in range(300)]
    built = pack.build_pack(_doc(paths), _section(paths), root)
    assert len(built["notes"]) <= pack.MAX_NOTES + 1, built["notes"]
    spill = [line for line in built["notes"] if "已略（只附前" in line]
    assert len(spill) == 1 and int(re.search(r"另有 (\d+) 条", spill[0]).group(1)) >= 200, spill
    assert pack_trim.size(built) <= pack.MAX_PACK_BYTES
    assert [row["id"] for row in built["facts"]] == ["fact:totals"], built["facts"]
    assert not built["truncated"], "说明不该把 facts 挤成截断"


def test_the_missing_fact_list_is_capped():
    root = scratch_dir("pack-notes2")
    section = {"index": 1, "title": "t", "goal": "g", "facts": ["fact:n%d" % i for i in range(40)]}
    built = pack.build_pack(_doc([]), section, root)
    line = [row for row in built["notes"] if "fact id，已跳过" in row][0]
    assert "等 40 个" in line and line.count("fact:n") == 12, line
