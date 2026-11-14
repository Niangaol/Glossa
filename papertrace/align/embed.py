"""向量化。默认后端是 offline，所以这里现在只会抛 LLMUnavailable。"""

from __future__ import annotations

import numpy as np


def embed_texts(texts: list[str]) -> "np.ndarray":
    raise NotImplementedError("align.embed.embed_texts 尚未实现")
