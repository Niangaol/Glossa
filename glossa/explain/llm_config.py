"""AI 配置集中一处（A1）：显式入参 > GLOSSA_* > PAPERTRACE_*。

这里只回答三件事——配置从哪来、配齐了没有、缺哪个变量；真正的后端仍然由
papertrace.llm 分派，本文件不联网、不构造后端、不猜默认模型名（R59 同尺）。
空串一律当成「没给」：环境里写 `GLOSSA_OPENAI_API_KEY=` 与没写等价，报错时
要能点名是「哪一层的那一个变量」。
`ready()` 只认真正的 openai（backend=="openai" 且 base_url / api_key / model 全非空）；
offline 永远不 ready——调用方据此决定「出事实底稿 + 红条」还是照旧 exit 4。

A1 派发书把 source 定成 cli / glossa / papertrace 三个值：显式入参给了任何一项
就是 cli；否则用到过 GLOSSA_* 就是 glossa；全都没配（等价于 papertrace 的默认
offline）算 papertrace。
"""
from __future__ import annotations

import os
from typing import NamedTuple

#: (GLOSSA_*, PAPERTRACE_*) 四对变量名，顺序就是「backend / base_url / api_key / model」。
ENV_PAIRS = (
    ("GLOSSA_LLM_BACKEND", "PAPERTRACE_LLM_BACKEND"),
    ("GLOSSA_OPENAI_BASE_URL", "PAPERTRACE_OPENAI_BASE_URL"),
    ("GLOSSA_OPENAI_API_KEY", "PAPERTRACE_OPENAI_API_KEY"),
    ("GLOSSA_LLM", "PAPERTRACE_LLM"),
)
#: 超时不是「连接参数」，缺了也算 ready；单独一对，让慢的推理模型能调长（R517）。
TIMEOUT_PAIR = ("GLOSSA_LLM_TIMEOUT", "PAPERTRACE_LLM_TIMEOUT")
#: 生成上限同理：不设就交给服务端默认，设了才不会等推理模型慢慢写满。
MAX_TOKENS_PAIR = ("GLOSSA_LLM_MAX_TOKENS", "PAPERTRACE_LLM_MAX_TOKENS")
BACKENDS = ("openai", "offline")
_LAYERS = ("glossa", "papertrace")


class Config(NamedTuple):
    """一份解析完的 AI 配置；source 说清这些值是哪一层给的。"""
    backend: str
    base_url: str
    api_key: str
    model: str
    source: str


def _clean(value):
    """空串 = 没给；显式入参与环境变量走同一条清洗。"""
    return str(value or "").strip()


def _pick(explicit, index):
    """显式入参 > GLOSSA_* > PAPERTRACE_*；返回 (值, 来源层)，都没给就 ("", "papertrace")。"""
    given = _clean(explicit)
    if given:
        return given, "cli"
    for layer, name in zip(_LAYERS, ENV_PAIRS[index]):
        found = _clean(os.environ.get(name))
        if found:
            return found, layer
    return "", "papertrace"


def _head(backend):
    """未知 backend 立刻 ValueError；`openai:deepseek` 的冒号后缀只是被容忍的写法（R59）。"""
    raw = _clean(backend)
    head = raw.lower().split(":", 1)[0]
    if raw and head not in BACKENDS:
        raise ValueError("未知的 AI backend=%r；只接受 %s。设置 GLOSSA_LLM_BACKEND（或 "
                         "PAPERTRACE_LLM_BACKEND）为其中之一。" % (raw, " / ".join(BACKENDS)))
    return head or "offline"


def resolve(*, backend=None, base_url=None, api_key=None, model=None) -> Config:
    """按优先级合成一份 Config；不读网络、不校验连通性，只决定「配齐了没有」。"""
    values, layers = [], set()
    for index, explicit in enumerate((backend, base_url, api_key, model)):
        value, layer = _pick(explicit, index)
        values.append(value)
        layers.add(layer)
    source = "cli" if "cli" in layers else "glossa" if "glossa" in layers else "papertrace"
    return Config(_head(values[0]), values[1], values[2], values[3], source)


def missing(cfg: Config):
    """缺哪几项连接参数：两个变量名都写出来，让人一眼知道该设哪一个。"""
    gaps = []
    for field, (glossa_name, paper_name) in zip(("base_url", "api_key", "model"), ENV_PAIRS[1:]):
        if not getattr(cfg, field):
            gaps.append("%s / %s" % (glossa_name, paper_name))
    return gaps


def ready(cfg: Config) -> bool:
    """真能问模型的唯一判据：选了 openai 且三项连接参数都非空。"""
    return cfg.backend == "openai" and not missing(cfg)




def timeout_seconds(default=None):
    """R517：真模型（尤其推理模型）比 60 秒慢，超时用环境变量调。

    读 GLOSSA_LLM_TIMEOUT，再读 PAPERTRACE_LLM_TIMEOUT；都没设返回 default（让调用方
    用后端的默认值）。写错值响亮 ValueError，不悄悄退回默认秒数。
    """
    for name in TIMEOUT_PAIR:
        raw = _clean(os.environ.get(name))
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            raise ValueError("%s=%r 不是秒数（要一个正数）" % (name, raw)) from None
        if value <= 0:
            raise ValueError("%s=%r 必须是正数秒" % (name, raw))
        return value
    return default


def max_tokens(default=None):
    """R520：一次最多生成多少 token（推理模型必须给个上限，否则慢到超时）。

    读 GLOSSA_LLM_MAX_TOKENS，再读 PAPERTRACE_LLM_MAX_TOKENS；写错值响亮 ValueError。
    """
    for name in MAX_TOKENS_PAIR:
        raw = _clean(os.environ.get(name))
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            raise ValueError("%s=%r 不是整数（要一个正整数）" % (name, raw)) from None
        if value <= 0:
            raise ValueError("%s=%r 必须是正整数" % (name, raw))
        return value
    return default


def describe(cfg: Config) -> str:
    """一行摘要；没配齐时把缺的变量点名写在同一行里。"""
    line = "%s · %s（来源 %s）" % (cfg.backend, cfg.model or "未指定模型", cfg.source)
    gaps = missing(cfg)
    return line + ("；缺 " + "、".join(gaps) if gaps else "")
