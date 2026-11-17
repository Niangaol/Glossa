"""R517：模型后端的接线层（llm_bridge.py）——把「只有 chat() 的真后端」接成编排要的形状。

真后端（papertrace.llm.client.LLMBackend）只有 chat(prompt, *, system=None) -> ChatResult，
而 ai_pipeline 要的是 complete(prompt, system) -> str。离线桩恰好有 complete，所以这一层不
存在时，测试全绿、用户配好 key 跑 --ai --llm openai 却直接 AttributeError——这是整个 AI 讲解
唯一被用户期待的那条路，必须有适配器，也必须被单测钉住。

超时同理：StepPlan 的 step-5-preview 真跑一节要 35.9 秒，默认 60 秒太紧；而写错的超时值
（非数字、非正数）不许静默退回默认值，要响亮报错（llm_config.timeout_seconds）。
"""

from __future__ import annotations

import os

from glossa.explain import fake_llm, llm_config, narrate
from papertrace.exceptions import BuildError, LLMUnavailable

DEV_FAKE = "本页由离线桩生成，未调用真实模型"
STUB_MODE = "本页由离线桩分节组装，未调用真实模型"   # R519：不许与「模型分节撰写」并存
_EMPTY = "模型后端返回了空文本（%s）：没有正文可组装，不拿空串当内容"


def backend():
    """把 GLOSSA_* 各项（含超时）临时映射成 papertrace 认的变量，问完立刻恢复原样。

    「读哪一层、配齐了没有」由 llm_config 决定；这里只保证真后端读到同一份值，否则
    GLOSSA_OPENAI_API_KEY 配齐了、后端却回头去点名 PAPERTRACE_OPENAI_API_KEY。
    """
    saved = {}
    pairs = tuple(llm_config.ENV_PAIRS) + (llm_config.TIMEOUT_PAIR, llm_config.MAX_TOKENS_PAIR)
    for glossa_name, paper_name in pairs:
        value = (os.environ.get(glossa_name) or "").strip()
        if value:
            saved[paper_name] = os.environ.get(paper_name)
            os.environ[paper_name] = value
    try:
        timeout, limit = llm_config.timeout_seconds(), llm_config.max_tokens()
        if timeout is None and limit is None:
            return narrate.get_llm()          # 两项都没配：保持后端自己的默认
        from papertrace.llm.openai_backend import OpenAICompatBackend
        kwargs = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if limit is not None:
            kwargs["max_tokens"] = limit
        return OpenAICompatBackend(**kwargs)
    finally:
        for name, previous in saved.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous


class ChatAdapter:
    """只有 chat() 的后端 → 有 complete() 的编排接口（真模型唯一的入口）。"""

    def __init__(self, backend):
        self.backend = backend
        self.name = str(getattr(backend, "name", "") or type(backend).__name__)

    def complete(self, prompt: str, system: str = "") -> str:
        """R524：推理模型偶发返回空 content（token 全花在思维链）——给一次重试，不把空串当正文。"""
        for attempt in (1, 2):
            try:
                result = self.backend.chat(prompt, system=system or None)
            except LLMUnavailable:
                if attempt == 2:
                    raise
                continue
            text = getattr(result, "text", result)
            if isinstance(text, str) and text.strip():
                return text
        raise BuildError(_EMPTY % self.name)


def as_completer(llm):
    """已经有 complete 的就原样用（FakeLLM），只有 chat 的包一层。"""
    return llm if hasattr(llm, "complete") else ChatAdapter(llm)


def build_llm(kind="openai", backend_factory=None):
    """fake 走离线桩，其它走真后端（配不齐是 BuildError，连不上是 LLMUnavailable）。

    backend_factory 让调用方（ai_pipeline）把「怎么造真后端」传进来，测试才能注入假的。
    """
    if str(kind or "").strip().lower() == fake_llm.NAME:
        return fake_llm.FakeLLM()
    cfg = llm_config.resolve()
    if not llm_config.ready(cfg):
        gaps = list(llm_config.missing(cfg))
        if cfg.backend != "openai":
            gaps.insert(0, "GLOSSA_LLM_BACKEND / PAPERTRACE_LLM_BACKEND（现在是 %s，要设成 openai）"
                        % cfg.backend)
        raise BuildError("AI 讲解需要一个可用的模型后端（%s · 来源 %s）；缺 %s；"
                         "没有 key 时先用离线桩（--llm fake / llm=\"fake\"）跑通。"
                         % (cfg.model or "未指定模型", cfg.source, "、".join(gaps)))
    return as_completer((backend_factory or backend)())


def deviation(llm) -> str:
    """「无 AI / 离线桩」的说明串：桩跑出来就必须在页头承认（设计 §12）。"""
    return DEV_FAKE if str(getattr(llm, "name", "") or "") == fake_llm.NAME else ""


def mode_text(llm):
    """页头徽章文字：桩跑出来就说桩；真模型返回 None，让 assemble 用默认那句（R519）。"""
    return STUB_MODE if str(getattr(llm, "name", "") or "") == fake_llm.NAME else None
