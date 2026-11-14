"""offline 后端的报错必须如实反映「你配了什么」。"""

import pytest

from papertrace.exceptions import LLMUnavailable
from papertrace.llm.client import get_llm


def test_offline_hint_explains_expected_state(monkeypatch):
    monkeypatch.delenv("PAPERTRACE_LLM_BACKEND", raising=False)
    with pytest.raises(LLMUnavailable) as exc:
        get_llm().chat("hi")
    msg = str(exc.value)
    assert "backend=offline" in msg
    assert "预期行为" in msg


def test_configured_but_unimplemented_backend_says_so(monkeypatch):
    """设了 ollama 却还报「没装模型」会让人查错方向。"""
    monkeypatch.setenv("PAPERTRACE_LLM_BACKEND", "ollama")
    with pytest.raises(LLMUnavailable) as exc:
        get_llm().chat("hi")
    msg = str(exc.value)
    assert "backend=ollama" in msg
    assert "尚未实现" in msg


def test_unknown_backend_is_a_loud_error(monkeypatch):
    monkeypatch.setenv("PAPERTRACE_LLM_BACKEND", "gpt5")
    with pytest.raises(ValueError):
        get_llm()
