"""sqlite 缓存：键由 commit + 闭包源码 + 论文单元 + 层级 + 模型 + 提示词版本组成。"""

from __future__ import annotations


def cache_key(commit: str, closure_src: str, paper_unit: str, level: str, model: str, prompt_version: str) -> str:
    raise NotImplementedError("detail.cache.cache_key 尚未实现")
