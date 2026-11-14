"""PaperTrace 的异常类型。只在这里定义一次，禁止各模块各写一份。"""

from __future__ import annotations


class PaperTraceError(Exception):
    """本项目的基类异常。"""


class TraceSchemaError(PaperTraceError):
    """trace.json 不符合 schema。errors 里是给人和程序都能读的原因列表。"""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("trace.json 校验失败：\n" + "\n".join(f"- {e}" for e in self.errors))


class LLMUnavailable(PaperTraceError):
    """当前没有可用的模型后端。禁止拿假结果冒充对齐。"""


class IngestError(PaperTraceError):
    """输入仓库或论文无法 ingest（非 Python、非 PyTorch、解析失败等）。"""


class BuildError(PaperTraceError):
    """用户在命令行上给的东西对不上（仓库路径、entry、示例输入等）。"""


class TraceUnsupported(PaperTraceError):
    """torch.export 追不动这个模型（自定义算子、数据依赖分支等）。

    宁可明说「追不动」，也不要把半张图当完整结果交出去。
    """


class RuntimeUnavailable(PaperTraceError):
    """缺运行要件（例如没装 torch），无法做真实追踪。

    绝不降级成「写个空 trace 假装成功」——那条路会让整个产品变成演示。
    """
