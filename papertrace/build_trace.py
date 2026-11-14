"""build 的编排入口。

M1a 只做一件事：把一个 nn.Module 的真实算子图抓进合法的 trace.json。
论文 ingest、对齐、mismatch 仍然是空的——**空就是空**，不塞示例数据。
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

from papertrace.exceptions import BuildError
from papertrace.parse_code.fx_graph import fused_items
from papertrace.parse_code.fx_trace import _require_torch, trace_module
from papertrace.schema_validate import minimal_trace

#: 默认示例输入：batch=2、序列长度 8（够让 Attention 的 (B, H, T, T) 显形）。
DEFAULT_BATCH = 2
DEFAULT_SEQ_LEN = 8


def repo_commit(repo: str | Path) -> str:
    """尽量拿到真实 commit；拿不到就写 dirty-<hash>，绝不假装是个真 commit。"""
    path = Path(repo)
    if path.is_dir():
        try:
            out = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if out.returncode == 0 and out.stdout.strip():
                head = out.stdout.strip()
                # 只认「path 本身就是仓库根」：否则会把外层仓库的 HEAD 记成目标仓库的提交
                top = subprocess.run(
                    ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if top.returncode == 0 and top.stdout.strip():
                    if Path(top.stdout.strip()).resolve() == path.resolve():
                        return head
                return "dirty-subdir"
        except (OSError, subprocess.SubprocessError):
            pass
    return "dirty-skeleton"


def skeleton_trace(*, repo_url: str, commit: str | None = None) -> dict:
    """合法的空 trace。nodes 必须是 []，锚点必须是 []。"""
    return minimal_trace(
        repo_url=repo_url,
        commit=commit or "dirty-skeleton",
    )


def load_entry(repo: str | Path, entry: str):
    """把 `模块:类名` 解析成一个已构造的模型实例。

    约定：entry 形如 `model:GPT`，模块按仓库根目录 import。
    """
    root = Path(repo)
    if not root.is_dir():
        raise BuildError(f"仓库目录不存在：{root}")
    module_name, sep, attr = entry.partition(":")
    if not sep or not module_name or not attr:
        raise BuildError(f"--entry 要写成 模块:类名（例如 model:GPT），收到 {entry!r}")
    root_str = str(root.resolve())
    inserted = root_str not in sys.path
    if inserted:
        sys.path.insert(0, root_str)
    try:
        sys.modules.pop(module_name, None)  # 别让上一次 build 的旧模块顶替
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise BuildError(f"导入 {module_name} 失败：{exc}") from exc
    finally:
        if inserted and root_str in sys.path:
            sys.path.remove(root_str)
    obj = getattr(module, attr, None)
    if obj is None:
        raise BuildError(f"{module_name} 里没有 {attr}")
    try:
        return obj()
    except TypeError as exc:
        raise BuildError(
            f"{entry} 不能零参构造（{exc}）。"
            "请改成 模块:工厂函数，比如 def build_model(): return GPT(GPTConfig(n_layer=2))"
        ) from exc


def _as_input_tuple(value):
    """example_inputs() 可能返回裸张量；裸张量不能被 tuple() 拆成按维度的多个参数。"""
    try:
        from torch import Tensor
    except ImportError:  # pragma: no cover - 没 torch 时走不到这里
        Tensor = ()  # type: ignore[assignment]
    if Tensor and isinstance(value, Tensor):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def example_inputs_for(model, *, batch: int = DEFAULT_BATCH, seq_len: int | None = None):
    """给模型造一组示例输入。

    优先级：模型自带的 `example_inputs()` > 按 GPT 惯例造 token id。
    两条都不成立就报错，绝不拿随机形状糊弄过去。
    """
    factory = getattr(model, "example_inputs", None)
    if callable(factory):
        return _as_input_tuple(factory())

    torch_mod = _require_torch()
    config = getattr(model, "config", None)
    vocab_size = getattr(config, "vocab_size", None)
    block_size = getattr(config, "block_size", None)
    if vocab_size and block_size:
        length = seq_len or min(int(block_size), DEFAULT_SEQ_LEN)
        generator = torch_mod.Generator().manual_seed(0)
        return (torch_mod.randint(0, int(vocab_size), (batch, length), generator=generator),)

    raise BuildError(
        f"{type(model).__name__} 既没有 example_inputs()，也没有 config.vocab_size/block_size；"
        "请给它加一个 example_inputs() 返回示例张量。"
    )


def build_trace(
    repo: str | Path,
    *,
    entry: str = "model:build_model",
    module_id: str = "root",
    batch: int = DEFAULT_BATCH,
    seq_len: int | None = None,
) -> dict:
    """真实追踪一个模型，返回可校验的 trace 文档（节点/边已填充）。"""
    # 先确认 torch 在，再 import 用户仓库：否则顶层 import torch 会先炸成 BuildError（exit 2），
    # 把「没装 torch」误报成「仓库写错了」。缺 torch 必须是 RuntimeUnavailable（exit 4）。
    _require_torch()
    model = load_entry(repo, entry)
    inputs = example_inputs_for(model, batch=batch, seq_len=seq_len)
    traced = trace_module(model, inputs, module_id=module_id)

    doc = minimal_trace(repo_url=str(repo), commit=repo_commit(repo))
    doc["meta"]["repo"]["entry_module"] = entry
    doc["nodes"] = traced["nodes"]
    doc["edges"] = traced["edges"]
    # 这次追踪是怎么跑的：不写进去，同一个 trace 就没法复现也没法解释
    runtime = dict(traced.get("runtime") or {})
    runtime["entry"] = entry
    # batch/seq_len 是**实际喂进去的**形状，不是命令行请求的值；请求值单独记，免得自相矛盾。
    runtime["requested"] = {"batch": batch, "seq_len": seq_len}
    doc["meta"]["runtime"] = runtime
    return doc


def fused_ops_in(doc: dict) -> list[str]:
    """图里被融合吞掉的算子名（去重、按出现顺序），调用方拿它决定要不要喊人。"""
    seen: list[str] = []
    for node in doc.get("nodes", []):
        if node.get("level") == "op" and fused_items(node.get("op")) is not None and node["op"] not in seen:
            seen.append(node["op"])
    return seen
