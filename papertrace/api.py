"""`glossa` 唯一允许依赖的 papertrace 面。

为什么要有这个文件：`glossa` 是并列的第二条产线（把仓库讲成一份可读的说明书），
它跟 `papertrace` 只该有一种关系——拿几个稳定符号。在这之前它从 5 个模块里
各 import 了一点（exceptions / exit_codes / constants / schema.validate /
llm.client / paths），papertrace 内部一搬家就得跟着改 19 个文件。

规则：**新增跨包依赖先在这里加一行**，不要在 glossa 里直接 `from papertrace.xxx`。
这里只做转发，不写逻辑，免得变成第二个实现。
"""

from __future__ import annotations

from .constants import HTML_MAX_BYTES
from .exceptions import BuildError, LLMUnavailable, TraceSchemaError
from .exit_codes import MISSING_RUNTIME, UNIMPLEMENTED, UNTRACEABLE
from .llm.client import get_llm
from .llm.openai_backend import OpenAICompatBackend
from .paths import portable_path
from .schema.validate import dump_trace

__all__ = [
    "BuildError",
    "HTML_MAX_BYTES",
    "LLMUnavailable",
    "MISSING_RUNTIME",
    "OpenAICompatBackend",
    "TraceSchemaError",
    "UNIMPLEMENTED",
    "UNTRACEABLE",
    "dump_trace",
    "get_llm",
    "portable_path",
]
