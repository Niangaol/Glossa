"""T10：CLI 三命令与退出码。in-process 调 main(argv)，不起子进程。"""
from tests.common import FIXTURES
import json
import shutil
from pathlib import Path

import pytest

from glossa import cli, facts, schema_repo
from papertrace.exceptions import LLMUnavailable
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"


def _repo(name='ts-monorepo'):
    dst = scratch_dir("glossa-t10c-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst


def test_analyze_writes_repo_json_that_passes_schema(capsys):
    root = _repo()
    out = scratch_dir("glossa-t10c-out")
    code = cli.main(["analyze", "--repo", str(root), "--out", str(out)])
    assert code == 0
    doc = json.loads((out / "repo.json").read_text(encoding="utf-8"))
    schema_repo.validate_repo(doc)
    assert doc["totals"]["files"] == 13
    printed = capsys.readouterr().out
    assert "13 个文件" in printed
    assert "9 条 import" in printed
    # 派发书 §4 M4：摘要的数字必须取 totals。换 py-mini（6 个文件）必须说 6，不许另算一份
    mini = _repo("py-mini")
    mini_out = scratch_dir("glossa-t10c-out-mini")
    assert cli.main(["analyze", "--repo", str(mini), "--out", str(mini_out)]) == 0
    assert json.loads((mini_out / "repo.json").read_text(encoding="utf-8"))["totals"]["files"] == 6
    mini_printed = capsys.readouterr().out
    assert "6 个文件" in mini_printed
    assert "13 个文件" not in mini_printed


def test_analyze_without_force_refuses_to_overwrite():
    root = _repo()
    out = scratch_dir("glossa-t10c-out2")
    args = ["analyze", "--repo", str(root), "--out", str(out)]
    assert cli.main(args) == 0
    assert cli.main(args) == 3                 # 已存在且无 --force
    assert cli.main(args + ["--force"]) == 0


def test_analyze_missing_repo_exits_five():
    out = scratch_dir("glossa-t10c-out3")
    code = cli.main(["analyze", "--repo", str(out / "nope"),
                     "--out", str(out)])
    assert code == 5


def test_explain_writes_program_page_and_bonus_adds_block(capsys):
    root = _repo()
    out = scratch_dir("glossa-t10c-out4")
    code = cli.main(["explain", "--repo", str(root), "--out", str(out)])
    assert code == 0
    html = (out / "explain.html").read_bytes().decode("utf-8")
    # R436：root_name 是传入 root 的目录名（scratch_dir 会带 glossa-t10c- 前缀），照 R387 取真值
    name = facts.build_repo_doc(root)["meta"]["repo"]["root_name"]
    assert "笺疏 · " + name in html
    assert "本页有 0 处数字未溯源" in html
    assert 'data-component="bonus"' not in html
    assert "未溯源 0 处" in capsys.readouterr().out


def test_facts_command_filters_and_pages(capsys):
    root = _repo()
    code = cli.main(["facts", "--repo", str(root), "--kind", "file",
                     "--offset", "0", "--limit", "5"])
    assert code == 0
    printed = capsys.readouterr().out
    assert printed.count("fact:file:") == 5
    assert "total" in printed or "共" in printed


def test_llm_flag_three_states_are_honest(capsys, monkeypatch):
    root = _repo()
    out = scratch_dir("glossa-t10c-out5")
    # ① 未配置后端 → 程序版 + 明示 + exit 0
    monkeypatch.delenv("GLOSSA_LLM_BACKEND", raising=False)
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    code = cli.main(["explain", "--repo", str(root), "--out", str(out),
                     "--llm", "--force"])
    assert code == 0
    assert "未配置模型后端" in capsys.readouterr().out
    # ② 配了但不可用 → exit 4，不静默降级
    def boom(*a, **k):
        raise LLMUnavailable("后端不可用：缺 PAPERTRACE_LLM")
    monkeypatch.setenv("GLOSSA_LLM_BACKEND", "openai")
    import glossa.explain.narrate as nmod
    monkeypatch.setattr(nmod, "get_llm", boom)
    code = cli.main(["explain", "--repo", str(root), "--out", str(out),
                     "--llm", "--force"])
    assert code == 4
    assert "后端不可用" in capsys.readouterr().out


def test_llm_success_state_is_end_to_end(capsys, monkeypatch):
    """R463：第③态（模型成功）——exit 0、徽章 model、模型名与「未溯源 0 处」都出自真接线。"""
    from glossa.explain import narrate
    root = _repo()
    out = scratch_dir("glossa-t10c-out6")
    monkeypatch.setenv("GLOSSA_LLM_BACKEND", "openai")
    import glossa.explain.narrate as nmod
    monkeypatch.setattr(nmod, "get_llm", lambda *a, **k: object())
    monkeypatch.setattr(nmod, "ask",
                        lambda doc, **kw: (narrate.program(doc), "stub-model-1"))
    assert cli.main(["explain", "--repo", str(root), "--out", str(out), "--llm"]) == 0
    printed = capsys.readouterr().out
    assert "stub-model-1" in printed and "未溯源 0 处" in printed
    page = (out / "explain.html").read_bytes().decode("utf-8")
    assert 'class="badge model"' in page
    assert "本页有 0 处数字未溯源" in page
    assert "笺疏 · " + facts.build_repo_doc(root)["meta"]["repo"]["root_name"] in page
