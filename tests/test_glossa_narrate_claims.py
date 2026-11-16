"""R454/R455/R456/R459：叙述层与 project 级图不许替事实编原因、编承诺。"""
import json
import shutil
from pathlib import Path

from glossa import facts
from glossa.explain import narrate, render
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"


def _doc(name="ts-monorepo"):
    dst = scratch_dir("glossa-t10c-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return facts.build_repo_doc(dst)


def _page(doc):
    return render.render_explain(doc, narrate.program(doc))


def _note_repo():
    """R454 夹具（按需求内联，不写进 tests/fixtures）：start 只给命令，build 才是真复合命令。"""
    root = scratch_dir("glossa-t10c-repo-note")
    (root / "src").mkdir()
    (root / "index.js").write_text("console.log('hi');\n", encoding="utf-8")
    (root / "src" / "x.js").write_text("export const x = 1;\n", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({
        "name": "repo-note", "version": "1.0.0",
        "scripts": {"start": "node index.js", "build": "tsc && node src/x.js"}}), encoding="utf-8")
    return facts.build_repo_doc(root)


def _c5_doc():
    """130 链 + 5 孤立：truncated_nodes=10，页面必须承认截断但不承诺节点清单。"""
    root = scratch_dir("glossa-t10c-c5")
    (root / "chain").mkdir()
    (root / "iso").mkdir()
    for i in range(1, 131):
        text = "export const x%d = %d;\n" % (i, i)
        if i < 130:
            text = 'import { x } from "./f%03d";\n' % (i + 1) + text
        (root / "chain" / ("f%03d.ts" % i)).write_text(text, encoding="utf-8")
    for i in range(1, 6):
        (root / "iso" / ("i%03d.ts" % i)).write_text("export const i%d = %d;\n" % (i, i), encoding="utf-8")
    (root / "package.json").write_text('{"name": "c5", "version": "1.0.0"}\n', encoding="utf-8")
    return facts.build_repo_doc(root)


def _section4(doc):
    """第 4 节那段讲解文字（narrate 的 text 块本身，不含组件渲染）。"""
    return next(b["params"]["text"] for b in narrate.program(doc)
                if b["component"] == "text" and b.get("section") == 4)


def test_narrate_counts_only_the_real_composite_entry():
    """R454/M10：只有 note 说「复合命令」的入口才算数；两类都为 0 时整句不写。"""
    doc = _note_repo()
    assert {row["note"] for row in doc["entries"]} == {"命令不含文件路径", "复合命令未指向单文件"}
    html, report = _page(doc)
    assert report["untraced"] == 0
    assert "共 2 个入口" in html
    assert "其中 1 个是复合命令" in html
    assert "其中 2 个是复合命令" not in html
    assert "其中 1 个没解析到单文件目标，原因见入口表" in html
    clean, _ = _page(_doc("py-mini"))          # 2 个入口都有 target → 两类都是 0
    assert "个是复合命令" not in clean and "个没解析到单文件目标" not in clean


def test_project_graph_never_claims_isolated_files():
    """R455：project 级图没有可信的孤立数，整句省略；file 级仍照 R437 写。"""
    cs, _ = _page(_doc("cs-solution"))
    assert "没有进入关系图" not in cs
    assert "没有找到可解析的入口，可达性未计算" not in cs   # 它有 1 个入口，不许说没有入口
    assert "5 个文件没有进入关系图，其中 3 个是清单、文档等不产生 import 的文件" in _page(_doc())[0]


def test_narrate_never_promises_a_folded_list():
    """R456：页面没有「折叠清单」；截断时明说本页不列这份清单；N=0 连这句都不写。"""
    plain = _section4(_doc())
    assert "折叠清单" not in plain and "另有" not in plain
    cut = _section4(_c5_doc())
    assert "折叠清单" not in cut and "本页不列这份清单" in cut
    empty = _section4(_doc("empty"))
    assert "折叠清单" not in empty and "另有 0 个" not in empty and "本页不列这份清单" not in empty


def test_empty_unreachable_is_not_written_as_zero():
    """R459：有入口但 unreachable 为空时不许写「从入口到不了 0 个文件」。"""
    for name in ("cs-solution", "py-mini"):
        doc = _doc(name)
        assert doc["entries"] and not doc["graph"]["unreachable"]
        html, _ = _page(doc)
        assert "从入口到不了" not in html
    ts = _doc()
    assert ts["graph"]["unreachable"]
    assert "从入口到不了 2 个文件" in _page(ts)[0]
