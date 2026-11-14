"""可插拔的模型后端。

设计约束（来自规格书第 12 章的 S13 修订）：

- 默认 `offline`。没装本地模型、也没配中转时，任何 chat/embed 都必须抛
  `LLMUnavailable`，禁止返回固定的 "yes" 或假向量——那会让后续的对齐
  看起来有结果，实际上全是幻觉。
- S8 起 `openai`（OpenAI 兼容中转）已实现，见 `papertrace.llm.openai_backend`；
  `ollama`（本地）仍未实现：认得这个名字，但仍然如实报未实现。
  冒号后缀（`openai:deepseek`）只是被容忍的写法，**不是模型名**（R59）——
  模型名只从 `PAPERTRACE_LLM` 读。
"""

from __future__ import annotations

import os
from typing import NamedTuple, Protocol, runtime_checkable

from papertrace.exceptions import LLMUnavailable

ENV_BACKEND = "PAPERTRACE_LLM_BACKEND"
KNOWN_BACKENDS = ("offline", "ollama", "openai")


class ChatResult(NamedTuple):
    text: str
    model: str
    backend: str


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    def chat(self, prompt: str, *, system: str | None = None) -> ChatResult: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _offline_hint(configured: str) -> str:
    """报错要如实说明「你配了什么、为什么还是不能用」。"""
    if configured == "offline":
        return (
            "LLM backend=offline。当前既没有安装本地模型，也没有配置云端中转；"
            "如果只是想跑框架，这是预期行为。要接模型请设置 "
            "PAPERTRACE_LLM_BACKEND=openai（OpenAI 兼容中转，已实现，还需要 "
            "PAPERTRACE_OPENAI_BASE_URL / PAPERTRACE_OPENAI_API_KEY / PAPERTRACE_LLM）"
            "或 =ollama（本地，尚未实现）。"
        )
    return (
        f"LLM backend={configured} 尚未实现（openai 兼容中转已实现，ollama 本地后端仍未实现）。"
        f"你已经设置了 PAPERTRACE_LLM_BACKEND={configured}，但这条路径还没有代码；"
        "要现在用模型请改设 openai（见 README「接云端中转」），或等 M3 补 ollama。"
    )


class OfflineBackend:
    """没有模型时的唯一后端：什么都不做，只诚实报错。"""

    def __init__(self, configured: str = "offline") -> None:
        self.name = "offline"
        self.configured = configured
        self._hint = _offline_hint(configured)

    def chat(self, prompt: str, *, system: str | None = None) -> ChatResult:
        raise LLMUnavailable(self._hint)

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise LLMUnavailable(self._hint)


def configured_backend() -> str:
    """读环境变量，容忍 `openai:deepseek` 这类带冒号的写法。"""
    raw = (os.environ.get(ENV_BACKEND) or "").strip().lower()
    if not raw:
        return "offline"
    head = raw.split(":", 1)[0]
    if head not in KNOWN_BACKENDS:
        raise ValueError(
            f"未知的 {ENV_BACKEND}={raw!r}；只接受 {' / '.join(KNOWN_BACKENDS)}。"
        )
    return head


def get_llm() -> LLMBackend:
    """按 `configured_backend()` 分派：openai → 真后端，其余 → offline。

    `openai` 走 `papertrace.llm.openai_backend.OpenAICompatBackend`（S8 起已实现）。
    `ollama` 仍未实现：返回 OfflineBackend 并如实报未实现——假装能用比直接报错
    更危险。函数内 import 是为了避开 client ↔ openai_backend 的循环导入
    （openai_backend 要从这里拿 ChatResult）。
    """
    configured = configured_backend()  # 非法值在这里就以 ValueError 暴露
    if configured == "openai":
        from papertrace.llm.openai_backend import OpenAICompatBackend

        return OpenAICompatBackend()
    return OfflineBackend(configured)
