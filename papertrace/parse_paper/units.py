"""切出论文单元并分配稳定 ID（RF1：坏输入不许猜出项，也不许抛裸 traceback）。

只认 equation / equation*：align、gather 等多行环境没有「一个环境一个公式」的
语义，硬切就是猜。ID 分配故意不依赖 marker 是否存在——序号取方程在本文件里的
1 基位置，所以事后增删 marker 也不会让别的方程改 ID。
"""

from __future__ import annotations

import re
from typing import NamedTuple

#: 稳定 ID 注释：% papertrace-id: <id>，id 取到空白为止。
_MARKER_RE = re.compile(r"%\s*papertrace-id:\s*(\S+)")
#: \label{...}；标签名不含花括号（LaTeX 本身也不允许）。
_LABEL_RE = re.compile(r"\\label\{([^{}]*)\}")
#: 公式环境。\1 回引用保证 begin/end 同名；DOTALL 让公式体可以跨行。
_ENV_RE = re.compile(r"\\begin\{(equation\*?)\}(?P<body>.*?)\\end\{\1\}", re.DOTALL)


class PaperUnit(NamedTuple):
    """一个方程单元。unit_id 对同一文件必须稳定：重复解析得到同一个 ID。"""

    unit_id: str
    latex: str
    label: str | None


def _marker(region: str) -> str | None:
    """region 里第一个 papertrace-id 注释的值；没有则 None。"""
    found = _MARKER_RE.search(region)
    return found.group(1) if found else None


def extract_units(text: str) -> list[PaperUnit]:
    """按出现顺序切出全部 equation 环境，返回 PaperUnit 列表。

    unit_id：先看本方程之前那段文本里的 marker，再看公式体里的 marker，
    都没有才派生 eq-<序号>（序号 = 本文件全部方程里的 1 基位置）。
    latex：剔除全部 \\label{...} 后剥掉首尾空白，内部换行保留。
    """
    units: list[PaperUnit] = []
    prev_end = 0
    for index, match in enumerate(_ENV_RE.finditer(text), start=1):
        body = match.group("body")
        label_match = _LABEL_RE.search(body)
        units.append(
            PaperUnit(
                unit_id=_marker(text[prev_end : match.start()]) or _marker(body) or f"eq-{index}",
                latex=_LABEL_RE.sub("", body).strip(),
                label=label_match.group(1) if label_match else None,
            )
        )
        prev_end = match.end()
    return units
