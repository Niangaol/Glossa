"""模型后端。默认 offline：没有模型就明确报错，绝不编造结论。"""

from papertrace.llm.client import ChatResult, LLMBackend, OfflineBackend, get_llm

__all__ = ["ChatResult", "LLMBackend", "OfflineBackend", "get_llm"]
