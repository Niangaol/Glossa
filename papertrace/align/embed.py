"""向量化：只转调当前 LLM 后端的 embed，不捕获、不兜底、不造假向量。

控制器裁决（原文照录在 task-S6-report.md）：
- R44：本模块只做一件事——把文本交给 `get_llm().embed(...)`，`LLMUnavailable`
  原样上抛。捕获与归零只发生在 `papertrace.align.retrieve.retrieve_bidirectional`
  里，那是 offline 路径上唯一的承重点（RF2 变异探针瞄的就是那一行）。
- R45/S17：返回 `list[list[float]]`，与 `papertrace.llm.client.LLMBackend.embed`
  的协议一致。本机没有可用的第三方数组类型，也不许借（Constraint 13）。
"""

from __future__ import annotations

from papertrace.llm.client import get_llm


def embed_texts(texts: list[str]) -> list[list[float]]:
    """把文本列表变成向量列表；后端不可用时抛 LLMUnavailable，由调用方处理。"""
    return get_llm().embed(texts)
