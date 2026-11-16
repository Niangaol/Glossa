"""R460：facts 分页边界——坏的参数响亮 exit 2，头行夹取到真实条数。"""
import shutil
from pathlib import Path

import pytest

from glossa import cli
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"
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


def test_facts_offset_past_end_says_zero_and_clamps(capsys):
    code = cli.main(["facts", "--repo", str(_root()), "--kind", "file", "--offset", "999"])
    assert code == 0
    out = capsys.readouterr().out
    assert "共 %d 条 fact 命中 kind=file，本次显示 0 条（offset 超出共 %d 条）" % (TOTAL, TOTAL) in out
    assert "999" not in out.splitlines()[-1]
    assert cli.main(["facts", "--repo", str(_root()), "--kind", "file",
                     "--offset", "4", "--limit", "10"]) == 0
    assert "本次显示第 5–6 条" in capsys.readouterr().out
