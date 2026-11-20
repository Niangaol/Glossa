"""A1：AI 配置集中一处（llm_config）与「未使用 AI」红条回退。

配置优先级：显式入参 > GLOSSA_* > PAPERTRACE_*；空串等于没给。
红条只属于程序版事实页，model 模式的页面永远不许出现（A1 派发书测试 1–8）。
"""
from tests.common import FIXTURES
import shutil
from pathlib import Path

import pytest

from glossa import cli, facts
from glossa.explain import llm_config, narrate, render
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"
BAR = "本页未使用 AI（仅事实底稿）"
FULL_BAR = ("本页未使用 AI（仅事实底稿）：只列台账事实，没有讲解。设置 GLOSSA_LLM_BACKEND=openai "
            "与 GLOSSA_OPENAI_BASE_URL / GLOSSA_OPENAI_API_KEY / GLOSSA_LLM 后重跑可得到人话讲解。")
ENV_NAMES = ("GLOSSA_LLM_BACKEND", "GLOSSA_OPENAI_BASE_URL", "GLOSSA_OPENAI_API_KEY", "GLOSSA_LLM",
             "PAPERTRACE_LLM_BACKEND", "PAPERTRACE_OPENAI_BASE_URL", "PAPERTRACE_OPENAI_API_KEY",
             "PAPERTRACE_LLM")


def _clean(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _env(monkeypatch, prefix, **over):
    base = {"LLM_BACKEND": "openai", "OPENAI_BASE_URL": "https://" + prefix + ".test/v1",
            "OPENAI_API_KEY": "sk-" + prefix, "LLM": prefix + "-model"}
    base.update(over)
    for key, value in base.items():
        monkeypatch.setenv(prefix + "_" + key if key != "LLM" else prefix + "_LLM", value)


def _render(name="ts-monorepo", *, fallback=False, mode="program", model_name=None):
    dst = scratch_dir("glossa-a1-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    doc = facts.build_repo_doc(dst)
    return render.render_explain(doc, narrate.program(doc), mode=mode,
                                 model_name=model_name, fallback=fallback)[0]


def test_glossa_env_is_ready_and_sourced_from_glossa(monkeypatch):
    _clean(monkeypatch)
    _env(monkeypatch, "GLOSSA")
    cfg = llm_config.resolve()
    assert (cfg.backend, cfg.base_url, cfg.api_key, cfg.model) == (
        "openai", "https://GLOSSA.test/v1", "sk-GLOSSA", "GLOSSA-model")
    assert cfg.source == "glossa"
    assert llm_config.ready(cfg) is True
    assert llm_config.describe(cfg) == "openai · GLOSSA-model（来源 glossa）"


def test_papertrace_env_alone_is_ready_and_sourced_from_papertrace(monkeypatch):
    _clean(monkeypatch)
    _env(monkeypatch, "PAPERTRACE")
    cfg = llm_config.resolve()
    assert cfg.backend == "openai" and cfg.source == "papertrace"
    assert llm_config.ready(cfg) is True


def test_glossa_env_overrides_papertrace_env(monkeypatch):
    _clean(monkeypatch)
    _env(monkeypatch, "PAPERTRACE")
    _env(monkeypatch, "GLOSSA")
    cfg = llm_config.resolve()
    assert (cfg.base_url, cfg.api_key, cfg.model) == (
        "https://GLOSSA.test/v1", "sk-GLOSSA", "GLOSSA-model")
    assert cfg.source == "glossa"


def test_explicit_arguments_override_env(monkeypatch):
    _clean(monkeypatch)
    _env(monkeypatch, "GLOSSA")
    cfg = llm_config.resolve(api_key="sk-cli", model="cli-model")
    assert (cfg.api_key, cfg.model) == ("sk-cli", "cli-model")
    assert cfg.base_url == "https://GLOSSA.test/v1"     # 没给的一项仍回落到环境
    assert cfg.source == "cli"


def test_missing_api_key_is_not_ready_and_describe_names_the_variable(monkeypatch):
    _clean(monkeypatch)
    _env(monkeypatch, "GLOSSA")
    monkeypatch.setenv("GLOSSA_OPENAI_API_KEY", "")      # 空串等于没给
    cfg = llm_config.resolve()
    assert llm_config.ready(cfg) is False
    said = llm_config.describe(cfg)
    assert "GLOSSA_OPENAI_API_KEY" in said and "PAPERTRACE_OPENAI_API_KEY" in said


def test_unknown_backend_raises_value_error_naming_openai(monkeypatch):
    _clean(monkeypatch)
    with pytest.raises(ValueError) as caught:
        llm_config.resolve(backend="foo")
    text = str(caught.value)
    assert "openai" in text and "offline" in text and "foo" in text
    monkeypatch.setenv("GLOSSA_LLM_BACKEND", "foo")
    with pytest.raises(ValueError):
        llm_config.resolve()


def test_fallback_bar_renders_exactly_once_and_cli_wires_it(monkeypatch, capsys):
    assert _render(fallback=True).count(BAR) == 1
    page = _render(fallback=True)
    assert FULL_BAR in page and 'class="fallback"' in page
    assert _render(fallback=False).count(BAR) == 0
    # CLI 接线：没配后端 + --llm → 程序版事实页 + 红条，exit 0（绝不 exit 4）
    _clean(monkeypatch)
    root = scratch_dir("glossa-a1-cli")
    shutil.copytree(FIX / "ts-monorepo", root, dirs_exist_ok=True)
    out = scratch_dir("glossa-a1-cli-out")
    code = cli.main(["explain", "--repo", str(root), "--out", str(out), "--llm"])
    assert code == 0
    assert "未配置模型后端，本页由程序生成" in capsys.readouterr().out
    written = (out / "explain.html").read_bytes().decode("utf-8")
    assert written.count(BAR) == 1 and FULL_BAR in written


def test_model_mode_page_never_carries_the_fallback_bar():
    assert _render(mode="model", model_name="stub-1").count(BAR) == 0
    assert _render(mode="model", model_name="stub-1", fallback=True).count(BAR) == 0
