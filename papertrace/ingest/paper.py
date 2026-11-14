"""论文 ingest：本地 tex → arXiv 源码 → PDF 兜底。v1 不做 Nougat。

本切片只实现本地 .tex。PDF / arxiv: / 路径不存在 / 非 UTF-8 一律抛 IngestError，
原因写进消息——S9 靠这句话填 trace.json 的 unresolved，CLI 不该因为论文读不了
就吐 traceback。title 只放论文标题，绝不拿来装错误信息。
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from papertrace.exceptions import IngestError
from papertrace.parse_paper.units import PaperUnit, extract_units


class PaperBundle(NamedTuple):
    source: str
    ingest_mode: str
    unit_count: int
    title: str | None
    #: 加在末尾且带默认值：既有四字段构造点不受影响。
    units: list[PaperUnit] = []


def _read_title(text: str) -> str | None:
    """R-a：第一个 \\begin{equation} 之前的第一行注释，去掉 % 与首尾空白。"""
    cut = text.find("\\begin{equation")
    region = text if cut < 0 else text[:cut]
    for line in region.splitlines():
        stripped = line.strip()
        if stripped.startswith("%"):
            return stripped.lstrip("%").strip()
    return None


def ingest_paper(src: str | Path) -> PaperBundle:
    """读一个本地 .tex 论文，返回 PaperBundle（ingest_mode="tex"）。

    不支持或读不成的输入抛 IngestError，消息里写明原因；不抛 NotImplementedError。
    """
    raw = str(src)
    if raw.lower().startswith("arxiv:"):
        raise IngestError(
            f"arxiv 源尚未实现（本切片不联网）：{raw}。"
            "请先下载论文源码，把里面的 .tex 路径传给 papertrace。"
        )
    path = Path(raw)
    if path.suffix.lower() == ".pdf":
        raise IngestError(
            f"PDF 论文暂不支持（v1 不做 Nougat，也不抽 PDF 公式）：{raw}。"
            "请提供论文源码里的 .tex。"
        )
    if not path.is_file():
        raise IngestError(f"找不到论文文件：{raw}。请确认路径存在，且是 .tex。")
    if path.suffix.lower() != ".tex":
        raise IngestError(f"只支持 .tex 论文（收到 {path.suffix or '无扩展名'}）：{raw}。")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise IngestError(f"{raw} 不是 UTF-8 编码的 .tex：{exc}。请转成 UTF-8 后再试。") from exc
    except OSError as exc:
        raise IngestError(f"{raw} 读不出来：{exc}。") from exc
    units = extract_units(text)
    return PaperBundle(
        source=raw,
        ingest_mode="tex",
        unit_count=len(units),
        title=_read_title(text),
        units=units,
    )
