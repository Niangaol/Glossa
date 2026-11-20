"""R485/R486/R488/R493：页面与 degraded 同一个数、sln 文件夹、无入口的不可达、仓外路径。

这些都只在"真跑夹具"上成立才算数，所以每个用例都从 build_repo_doc / analyze 起步（不走手工 dict）。
"""
from tests.common import FIXTURES
import json
import re
import shutil
from pathlib import Path

from glossa import cli, facts
from glossa.explain import narrate, render
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"
_PAGE_M = re.compile(r"没有进入关系图，其中 (\d+) 个是清单")
_DEG_M = re.compile(r"（其中 (\d+) 个是清单")


def _chain163():
    """R485 夹具：130 个 ts 链 + 8 个挂在链上的 .css + 1 个孤立 package.json、无入口。

    关键：8 个 .css 在**截断前**的节点集里（各自被 f015/f030…import），截断按度数排序把它们全挤出去。
    于是"截断后现算"会给 9（8 css + package.json），"截断前算"只给 1（package.json）——差就是缺陷本身。
    """
    root = scratch_dir("glossa-final-a-chain")
    (root / "src").mkdir(parents=True)
    for i in range(1, 131):
        lines = []
        if i < 130:
            lines.append('import { n } from "./f%03d";\n' % (i + 1))
        else:
            lines.append("export const n = 0;\n")
        if i % 15 == 0:                       # 8 个：15,30,…,120
            rel = "web/c%d.css" % (i // 15)
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("body { color: #000; }\n", encoding="utf-8")
            lines.append('import "../%s";\n' % rel)
        (root / ("src/f%03d.ts" % i)).write_text("".join(lines), encoding="utf-8")
    (root / "package.json").write_text('{"name": "chain", "private": true}\n', encoding="utf-8")
    return facts.build_repo_doc(root)


def _doc_without_entries():
    """R488 夹具：两个互相 import 的 ts，没有 package.json → 一条入口都没有。"""
    root = scratch_dir("glossa-final-a-noentry")
    (root / "src").mkdir(parents=True)
    (root / "src/a.ts").write_text('import { b } from "./b";\nexport const a = b;\n', encoding="utf-8")
    (root / "src/b.ts").write_text('import { a } from "./a";\nexport const b = a;\n', encoding="utf-8")
    return facts.build_repo_doc(root)


def test_page_and_degraded_share_one_omitted_manifests_number():
    """R485（C1）：页面「其中 M 个是清单」与 degraded 那句必须是同一个数，且等于 graph.omitted_manifests。"""
    doc = _chain163()
    g = doc["graph"]
    assert g["truncated"] is True and g["truncated_nodes"] == 18, g["truncated_nodes"]
    assert g["omitted_isolated"] == 1, g["omitted_isolated"]
    assert g["omitted_manifests"] == 1, g["omitted_manifests"]   # 只有 package.json 没进图
    reasons = [d["reason"] for d in doc["degraded"] if d["scope"] == "graph.isolated"]
    assert len(reasons) == 1, doc["degraded"]
    page = render.render_explain(doc, narrate.program(doc))[0]
    page_m, deg_m = _PAGE_M.search(page), _DEG_M.search(reasons[0])
    assert page_m and deg_m, (reasons[0], "页面里没有那一句")
    assert int(page_m.group(1)) == int(deg_m.group(1)) == g["omitted_manifests"]
    assert "其中 9 个是清单" not in page, "页面又拿截断后的节点集现算了"


def test_cs_solution_folder_drop_lands_in_repo_json():
    """R486（I1）：sln 里被丢的解决方案文件夹必须能从 repo.json 的 degraded 读出来。"""
    root = scratch_dir("glossa-final-a-sln")
    shutil.copytree(FIX / "cs-solution", root, dirs_exist_ok=True)
    out = scratch_dir("glossa-final-a-sln-out")
    assert cli.main(["analyze", "--repo", str(root), "--out", str(out)]) == 0
    doc = json.loads((out / "repo.json").read_text(encoding="utf-8"))
    rows = [d for d in doc["degraded"] if str(d.get("scope") or "").startswith("sln:")]
    assert rows, doc["degraded"]
    assert "sln 里有 1 个解决方案文件夹，未纳入项目列表" in rows[0]["reason"], rows[0]


def test_fact_graph_says_uncomputed_instead_of_zero_unreachable():
    """R488（I3）：没有入口时 fact:graph 不许写「0 个不可达文件」。"""
    doc = _doc_without_entries()
    assert doc["entries"] == [], doc["entries"]
    fact = doc["facts"]["fact:graph"]
    assert "不可达文件" not in fact["text"], fact["text"]
    assert "可达性未计算（没有可解析的入口）" in fact["text"], fact["text"]
    assert doc["graph"]["unreachable"] == [] and doc["graph"]["reachable_from_entries"] == []


def test_out_of_repo_absolute_path_in_ledger_is_degraded():
    """R493：来源文件自带的仓外绝对路径原样保留时，台账必须记一条并给出真实条数。"""
    root = scratch_dir("glossa-final-a-leak")
    (root / "src").mkdir(parents=True)
    (root / "src/evil.ts").write_text(
        'import x from "file:///C:/Users/niangao/secret.js";\nexport const y = x;\n', encoding="utf-8")
    doc = facts.build_repo_doc(root)
    rows = [d for d in doc["degraded"] if d["scope"] == "repo:paths"]
    assert len(rows) == 1, doc["degraded"]
    hits = int(re.search(r"台账里有 (\d+) 处", rows[0]["reason"]).group(1))
    assert hits >= 2, rows[0]                     # 至少 import 行 + fact:import 的 text
    assert doc["totals"]["degraded"] == len(doc["degraded"])
    assert len(doc["degraded"]) in doc["facts"]["fact:degraded"]["numbers"], "降级表与事实各数一份"
