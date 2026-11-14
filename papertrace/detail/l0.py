"""L0：纯模板。零 LLM 调用——能由元数据填出来的东西不该烧 token。"""

from __future__ import annotations


def render_l0(node) -> object:
    raise NotImplementedError("detail.l0.render_l0 尚未实现")
