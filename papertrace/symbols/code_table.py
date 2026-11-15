"""从代码里抽符号表：变量名 → 符号 → 值 → 定义位置。

契约（R2，别传错参数）：本函数的 `bundle` 是 **build_trace() 产出的 trace dict**，
不是 S2 的 PaperBundle——B 的值读 `bundle["meta"]["runtime"]["batch"]`。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

#: 冻结的五符号（brief：符号名冻结 B,T,D,H,Dh；Dh = D / H）。
_FROZEN_SYMBOLS = ("B", "T", "D", "H", "Dh")

#: 符号 → config 字段名（值来自实例化后的 `mod.config`）。
_CONFIG_FIELDS = {"T": "block_size", "D": "n_embd", "H": "n_head"}

#: config 字段的声明点：类体里 `name: type = default` 或 `name = value` 那行（R31）。
_FIELD_LINE = r"^\s*{name}\s*[:=]"

#: Dh 的真正算式：C // self.n_head（夹具 model.py:65）。绝不退回 head_dim。
_HEAD_DIM_LINE = re.compile(r"//\s*(?:self\.)?n_head\b")

#: B 的声明点：papertrace/build_trace.py 里的 DEFAULT_BATCH（brief/R31）。
_BATCH_CONST = "DEFAULT_BATCH"


def _read_lines(path):
    """读文件行；读不动就当没有（返回空表 = 定位不到，调用方会省略该符号）。"""
    try:
        return Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _find_line(lines, name, start=0, end=None):
    """在 [start, end) 里找 `name:` 或 `name=` 开头的行，返回 1 基行号或 None。"""
    pattern = re.compile(_FIELD_LINE.format(name=re.escape(name)))
    stop = len(lines) if end is None else min(end, len(lines))
    for index in range(max(start, 0), stop):
        if pattern.match(lines[index]):
            return index + 1
    return None


def _class_region(lines, class_name):
    """`class <name>:` 头部行到下一个顶层语句之前的区间（[start, end)）。"""
    header = re.compile(rf"^class\s+{re.escape(class_name)}\b")
    for index, line in enumerate(lines):
        if header.match(line):
            for tail in range(index + 1, len(lines)):
                text = lines[tail]
                if text and not text[0].isspace():
                    return index, tail
            return index, len(lines)
    return None


def _candidate_files(mod):
    """定义点候选文件：先模型自己的源文件，再 config 类的源文件（R31）。"""
    files = []
    config = getattr(mod, "config", None)
    owners = [type(mod)]
    if config is not None:
        owners.append(type(config))
    for owner in owners:
        try:
            path = inspect.getsourcefile(owner)
        except TypeError:
            path = None
        if path and path not in files:
            files.append(path)
    return files


def _locate_config_field(mod, field):
    """config 字段的声明点：只在**含该 config 类类体**的候选文件里找（R36）。

    fail-closed：圈不到该类类体的文件整个跳过，绝不退回整文件查找——那会在模型
    文件里命中同名诱饵行，产出指错文件错行的 defined_at，比省略该符号更坏。
    全都找不到 → None（调用方按 R21 省略）；没有 config 对象也返回 None，不猜。
    """
    config = getattr(mod, "config", None)
    if config is None:
        return None  # 没有 config 对象：没有依据，不猜（R36）
    class_name = type(config).__name__
    for path in _candidate_files(mod):
        lines = _read_lines(path)
        if not lines:
            continue
        region = _class_region(lines, class_name)
        if region is None:
            # 这个文件里没有该 config 类：整个跳过，绝不退回整文件查找（R36）
            continue
        hit = _find_line(lines, field, region[0], region[1])
        if hit is not None:
            return f"{path}:{hit}"
    return None


def _locate_head_dim(mod):
    """Dh 的声明点：真正把 C 切成多头的那一行 `C // self.n_head`（RF4/R101）。

    判据：收集全部命中 → 同文件内相邻的非注释命中折叠成一个 site（夹具 model.py
    的 k/q/v 三行 view 本就连续命中）→ 只剩一个且非注释才用，否则 None（R21 省略）。
    """
    sites: list[tuple[str, int, bool]] = []
    for path in _candidate_files(mod):
        last_line = -999
        for index, text in enumerate(_read_lines(path)):
            if _HEAD_DIM_LINE.search(text):
                is_comment = text.lstrip().startswith("#")
                line_no = index + 1
                if not is_comment and line_no == last_line + 1 and sites and not sites[-1][2]:
                    last_line = line_no
                    continue
                sites.append((path, line_no, is_comment))
                last_line = line_no
    if len(sites) == 1 and not sites[0][2]:
        return f"{sites[0][0]}:{sites[0][1]}"
    return None


def _batch_defined_at():
    """B 的声明点：build_trace.py 里的 `DEFAULT_BATCH = 2`（brief/R31）。"""
    path = None
    try:
        from papertrace import build_trace as _module

        path = inspect.getsourcefile(_module)
    except ImportError:
        path = None
    if not path:
        # 退化路径：build_trace 就在本包隔壁，读的是同一个文件，不 import 也不猜
        path = str(Path(__file__).resolve().parents[1] / "build_trace.py")
    hit = _find_line(_read_lines(path), _BATCH_CONST)
    return f"{path}:{hit}" if hit else None


def _runtime_batch(bundle):
    """R2：bundle 是 trace dict，batch 在 meta.runtime.batch（runtime 可为 null）。"""
    meta = bundle.get("meta") if isinstance(bundle, dict) else None
    runtime = meta.get("runtime") if isinstance(meta, dict) else None
    if isinstance(runtime, dict):
        batch = runtime.get("batch")
        if isinstance(batch, (int, float)) and not isinstance(batch, bool):
            return batch
    return None


def _symbol(var, name, value, where):
    """一条 codeSymbol（schema：var/symbol/defined_at 必填，value/used_by 可选）。"""
    return {"var": var, "symbol": name, "value": value, "defined_at": where, "used_by": []}


def build_code_symbols(mod, bundle) -> list[dict]:
    """从实例化模型 + trace dict 抽代码侧符号表。

    - `bundle` 是 **build_trace() 产出的 trace dict**（R2），不是 PaperBundle。
    - 五个符号冻结：B（runtime batch）、T（config.block_size，**声明的**超参数，
      不是运行时 seq_len——后者是 min(block_size, DEFAULT_SEQ_LEN)，R32）、
      D（config.n_embd）、H（config.n_head）、Dh（**派生** D // H，RF4）。
    - 值来自实例化后的 `mod.config`，定义位置来自**类源码**（R31）：
      B→build_trace.py 的 DEFAULT_BATCH，T/D/H→config 类体里的字段行，
      Dh→真正算 head 维的那一行 `C // self.n_head`。
    - Dh = D // H 向下取整（R20）：`D % H != 0` 时仍然发出向下取整的 Dh；
      与论文侧 d_k 的精确对账是 M4 的事。codeSymbol 没有"近似"字段，
      所以这里不发明一个，也不会自己发 mismatch（返回的是扁平列表，没这个通道）。
    - 定位不到定义行、或 config 缺字段 → **省略该符号**（R21）：本函数返回
      list[dict]，没有 unresolved 通道；S9 拿冻结的五符号集合做差集记
      `unresolved{kind:"symbol", symbol, reason}`。这里绝不编造行号，
      也绝不返回违反 schema 的 dict。
    - `used_by` 本切片恒为 []：使用边由 shape 传播（M1b）填，先给稳定形状。
    """
    rows = {}
    batch = _runtime_batch(bundle)
    if batch is not None:
        where = _batch_defined_at()
        if where is not None:
            rows["B"] = _symbol(_BATCH_CONST, "B", batch, where)
    config = getattr(mod, "config", None)
    for symbol, field in _CONFIG_FIELDS.items():
        value = getattr(config, field, None) if config is not None else None
        if value is None:
            continue  # 缺字段或 None：省略，由 S9 记 unresolved（R21）
        where = _locate_config_field(mod, field)
        if where is None:
            continue  # 定位不到定义行：省略，绝不编行号（R21）
        rows[symbol] = _symbol(field, symbol, value, where)
    if "D" in rows and "H" in rows:
        try:
            head_dim = rows["D"]["value"] // rows["H"]["value"]
        except (TypeError, ZeroDivisionError):
            head_dim = None
        if head_dim is not None:
            where = _locate_head_dim(mod)
            if where is not None:
                rows["Dh"] = _symbol("Dh", "Dh", head_dim, where)
    return [rows[symbol] for symbol in _FROZEN_SYMBOLS if symbol in rows]
