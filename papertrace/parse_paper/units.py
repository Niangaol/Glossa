"""切出论文单元并分配稳定 ID（RF1：坏输入不许猜出项，也不许抛裸 traceback）。

只认 equation / equation*：align、gather 等多行环境没有「一个环境一个公式」的
语义，硬切就是猜。ID 分配故意不依赖 marker 是否存在——序号取方程在本文件里的
1 基位置，所以事后增删 marker 也不会让别的方程改 ID。

匹配前先把原文过一遍「掩码」，生成等长的 code / comment 双视图：
- code 视图里，未转义 % 到行尾的注释、以及 verbatim / lstlisting 逐字环境整体
  换成等长空格——被注释掉的 \begin{equation} 和印在 verbatim 里的都不是公式，
  公式体内的行尾 % 注释也活不进 latex；
- comment 视图相反：代码换成等长空格，注释原文保留。
_ENV_RE 只扫 code 视图（找公式），_MARKER_RE 只扫 comment 视图（找注释里的
marker）；两个视图与原文偏移一一对应，区间可以互相套用。\\% 是转义百分号，
尊重它。marker 只认「上一个 \\end{equation} 之后、本 \\begin{equation} 之前」那段
注释区（裁决 R14）：写在公式体里的 marker 会被上一条公式偷走，造成两条公式的
ID 互换错配，一律忽略。
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
#: 逐字环境：里面印出来的 \begin{equation} 是文本，不是公式。
_VERBATIM_RE = re.compile(
    r"\\begin\{(verbatim|lstlisting|Verbatim|BVerbatim|minted)\}"
    r"(?P<vbody>.*?)\\end\{\1\}",
    re.DOTALL,
)


class PaperUnit(NamedTuple):
    """一个方程单元。unit_id 对同一文件必须稳定：重复解析得到同一个 ID。"""

    unit_id: str
    latex: str
    label: str | None


def _mask_views(text: str) -> tuple[str, str]:
    """返回等长的 (code 视图, comment 视图)，偏移与原文一一对应。

    code 视图：注释（未转义 % 到行尾）与逐字环境换成等长空格；
    comment 视图：代码换成等长空格，注释原文保留。
    逐字符扫：遇到 \\ 先试逐字环境，否则跳过这个转义对（于是 \\% 不会被当成
    注释起点）；遇到未转义 % 就把到行尾整段挖空。
    """
    code = list(text)
    comment = list(text)
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            verbatim = _VERBATIM_RE.match(text, i)
            if verbatim:
                for k in range(i, verbatim.end()):
                    code[k] = " "
                    comment[k] = " "
                i = verbatim.end()
                continue
            i += 2
            continue
        if ch == "%":
            end = text.find("\n", i)
            if end < 0:
                end = n
            for k in range(i, end):
                code[k] = " "
            i = end
            continue
        i += 1
    return "".join(code), "".join(comment)


def _marker(region: str) -> str | None:
    """region 里第一个 papertrace-id 注释的值；没有则 None。"""
    found = _MARKER_RE.search(region)
    return found.group(1) if found else None


def extract_units(text: str) -> list[PaperUnit]:
    """按出现顺序切出全部 equation 环境，返回 PaperUnit 列表。

    unit_id：本方程之前那段注释区（上一个 \\end{equation} 之后、本
    \\begin{equation} 之前）里的 marker；没有才派生 eq-<序号>（序号 = 本文件
    全部方程里的 1 基位置）。写在公式体里的 marker 一律忽略（裁决 R14）。
    latex：code 视图里的公式体剔除全部 \\label{...} 后剥掉首尾空白，内部换行
    保留——注释已在掩码阶段挖空，行尾 % 注释不会活进来。
    """
    code, comments = _mask_views(text)
    units: list[PaperUnit] = []
    prev_end = 0
    for index, match in enumerate(_ENV_RE.finditer(code), start=1):
        body = match.group("body")
        label_match = _LABEL_RE.search(body)
        units.append(
            PaperUnit(
                unit_id=_marker(comments[prev_end : match.start()]) or f"eq-{index}",
                latex=_LABEL_RE.sub("", body).strip(),
                label=label_match.group(1) if label_match else None,
            )
        )
        prev_end = match.end()
    return units
