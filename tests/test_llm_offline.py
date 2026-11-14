import pytest

from papertrace.exceptions import LLMUnavailable
from papertrace.llm.client import OfflineBackend, get_llm
from papertrace.llm.prompts import DRILL_PROMPT, JUDGE_PROMPT


def test_default_backend_is_offline(monkeypatch):
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    backend = get_llm()
    assert backend.name == "offline"
    assert isinstance(backend, OfflineBackend)


def test_offline_chat_raises_with_actionable_message(monkeypatch):
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    with pytest.raises(LLMUnavailable) as excinfo:
        get_llm().chat("Attention 的 softmax 对应哪一行？")
    message = str(excinfo.value)
    assert "offline" in message
    assert "PAPERTRACE_LLM_BACKEND" in message


def test_offline_embed_raises(monkeypatch):
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    with pytest.raises(LLMUnavailable):
        get_llm().embed(["QK^T"])


@pytest.mark.parametrize("value", ["ollama"])
def test_configured_but_unimplemented_backend_never_fakes_answers(monkeypatch, value):
    monkeypatch.setenv("PAPERTRACE_LLM_BACKEND", value)
    backend = get_llm()
    assert backend.name == "offline", "未实现的后端必须退化为 offline，禁止偷偷打网"
    with pytest.raises(LLMUnavailable):
        backend.chat("yes or no")


@pytest.mark.parametrize("value", ["openai", "openai:deepseek"])
def test_openai_backend_is_real_but_still_refuses_without_env(monkeypatch, value):
    """R60：S8 起 openai 已实现，name 必须是 openai，而不是退化成的 offline。

    但未配 base_url / api_key / model 时 chat 仍然抛 LLMUnavailable 并点名缺的
    变量——开关点亮了不等于能打通，报错要能照着修。这是加强，不是放宽。
    """
    monkeypatch.setenv("PAPERTRACE_LLM_BACKEND", value)
    for name in (
        "PAPERTRACE_OPENAI_BASE_URL",
        "PAPERTRACE_OPENAI_API_KEY",
        "PAPERTRACE_LLM",
    ):
        monkeypatch.delenv(name, raising=False)
    backend = get_llm()
    assert backend.name == "openai", "openai 已实现，不许再退化成 offline"
    assert not isinstance(backend, OfflineBackend)
    with pytest.raises(LLMUnavailable) as excinfo:
        backend.chat("yes or no")
    message = str(excinfo.value)
    assert "PAPERTRACE_OPENAI_BASE_URL" in message
    assert "PAPERTRACE_OPENAI_API_KEY" in message
    assert "PAPERTRACE_LLM" in message


def test_unknown_backend_value_rejected(monkeypatch):
    monkeypatch.setenv("PAPERTRACE_LLM_BACKEND", "gpt-from-nowhere")
    with pytest.raises(ValueError):
        get_llm()


def test_judge_prompt_is_yes_no_only():
    assert "只能回答 yes / no" in JUDGE_PROMPT
    assert "对应关系如下" not in JUDGE_PROMPT
    assert "generate_alignment" not in JUDGE_PROMPT


def test_drill_prompt_requires_parent_claim():
    assert "已知父节点结论" in DRILL_PROMPT
    assert JUDGE_PROMPT != DRILL_PROMPT
