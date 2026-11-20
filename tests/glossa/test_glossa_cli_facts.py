"""R460：facts 分页边界；R487：explain 复用 --out/repo.json。"""
from tests.common import FIXTURES
import json
import shutil
from pathlib import Path

import pytest

from glossa import cli
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"
TOTAL = 6                                  # py-mini 的 kind=file fact 条数（实测）


def _root():
    dst = scratch_dir("glossa-t10f-py-mini")
    shutil.copytree(FIX / "py-mini", dst, dirs_exist_ok=True)
    return dst


def _reject(capsys, flag, value):
    with pytest.raises(SystemExit) as ei:
        cli.main(["facts", "--repo", str(_root()), "--kind", "file", flag, value])
    assert ei.value.code == 2
    assert flag in capsys.readouterr().err


def test_facts_limit_zero_exits_two(capsys):
    _reject(capsys, "--limit", "0")


def test_facts_negative_limit_exits_two(capsys):
    _reject(capsys, "--limit", "-5")


def test_facts_negative_offset_exits_two(capsys):
    _reject(capsys, "--offset", "-3")


def test_explain_reuses_ledger_and_force_rescans(capsys):
    """R487（I2）：explain 默认渲染 --out/repo.json；源文件改了也不重扫，--force 才重扫并覆盖台账。"""
    root, out = _root(), scratch_dir("glossa-t10f-explain-ledger")
    assert cli.main(["analyze", "--repo", str(root), "--out", str(out)]) == 0
    base = json.loads((out / "repo.json").read_text(encoding="utf-8"))["totals"]["files"]
    assert cli.main(["explain", "--repo", str(root), "--out", str(out)]) == 0
    page = (out / "explain.html").read_text(encoding="utf-8")
    assert "全仓 %d 个文件" % base in page
    assert "本页数据来自本次重扫" not in page          # 复用了台账，页脚不该多这句
    (root / "extra.py").write_text("def extra():\n    return 1\n", encoding="utf-8")
    assert cli.main(["explain", "--repo", str(root), "--out", str(out)]) == 0
    page = (out / "explain.html").read_text(encoding="utf-8")
    assert "全仓 %d 个文件" % base in page             # 改了源文件也没重扫：证明读的是台账
    assert cli.main(["explain", "--repo", str(root), "--out", str(out), "--force"]) == 0
    page = (out / "explain.html").read_text(encoding="utf-8")
    assert "全仓 %d 个文件" % (base + 1) in page       # --force 重扫，页面反映新内容
    assert json.loads((out / "repo.json").read_text(encoding="utf-8"))["totals"]["files"] == base + 1


def test_explain_without_ledger_rescans_and_says_so():
    """R487 §1：目录里没有 repo.json 时重扫，并在页脚明说数据来自本次重扫。"""
    root, out = _root(), scratch_dir("glossa-t10f-explain-noledger")
    assert cli.main(["explain", "--repo", str(root), "--out", str(out)]) == 0
    page = (out / "explain.html").read_text(encoding="utf-8")
    assert "本页数据来自本次重扫（目录里没有 repo.json）" in page
    assert not (out / "repo.json").exists()            # 只有 --force 才写台账，缺失时只重扫


def test_broken_ledger_exits_one_without_rescan(capsys):
    """R487 §2：台账坏 JSON / 过不了 schema → exit 1 + stderr 原文，绝不静默回落重扫。"""
    root, out = _root(), scratch_dir("glossa-t10f-explain-bad")
    (out / "repo.json").write_text("{ 半个 JSON", encoding="utf-8")
    assert cli.main(["explain", "--repo", str(root), "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "repo.json" in err and "Expecting" in err
    assert not (out / "explain.html").exists()
    (out / "repo.json").write_text('{"meta": {}}', encoding="utf-8")   # 合法 JSON，schema 不过
    assert cli.main(["explain", "--repo", str(root), "--out", str(out)]) == 1
    assert "repo.json" in capsys.readouterr().err


def test_facts_offset_past_end_says_zero_and_clamps(capsys):
    code = cli.main(["facts", "--repo", str(_root()), "--kind", "file", "--offset", "999"])
    assert code == 0
    out = capsys.readouterr().out
    assert "共 %d 条 fact 命中 kind=file，本次显示 0 条（offset 超出共 %d 条）" % (TOTAL, TOTAL) in out
    assert "999" not in out.splitlines()[-1]
    assert cli.main(["facts", "--repo", str(_root()), "--kind", "file",
                     "--offset", "4", "--limit", "10"]) == 0
    assert "本次显示第 5–6 条" in capsys.readouterr().out
