# PaperTrace M1a 实施计划：真实算子追踪

> 前置：框架切片已完成（93 passed / 2 skipped，HEAD 1f26bf8）。
> 目标：让 `trace.json` 里出现**真的**算子节点与形状链，且能证明 nanoGPT 的 Attention
> 是 4 个独立算子（matmul / mul / masked_fill / softmax），不是 1 个融合 SDPA。
> 铁律：所有节点 `source="runtime"`，禁止示例节点、禁止 mock 形状。

**状态（2026-11-14）**：Task 7–10 已落地，114 → **117 passed**，提交 `73bb224` → `bc472d6` → `9fbb56b`。
Task 11 的端到端验收已跑通，独立评审已派出（见文末「评审与偏离记录」）。

**依赖**：CPU 版 torch（PyPI `torch-2.15.0-cp313-cp313-win_amd64.whl`，120.9 MB）
装在 `pydeps/`（gitignore）。装法：

```bat
cd /d D:\AgentPrograms\PaperTrace
python tmpinstall\fetch_deps.py pydeps wheels torch
set PYTHONPATH=D:\AgentPrograms\PaperTrace\pydeps
python -c "import torch; print(torch.__version__)"
```

装不上时的退路：**不要**用假图凑。让 `fx_trace` 抛 `RuntimeUnavailable`，
CLI 返回 4 并打印原因——「没有 torch」必须是一个显式的、可测试的状态。

## Global Constraints（继承，不可违反）

- 不装 Ollama、不拉 LLM 权重，默认 backend=offline。
- 不动用户代码：只读 import 目标模块，不写回。
- 探针默认 CPU（`torch.device("cpu")`）；12GB 显存留给将来。
- 单源文件 ≤200 行。
- 每个 Task 结束必须 `pytest` 全绿并提交。

---

## Task 7: fx_trace 真实追踪与形状传播 ✅

**Files:** `papertrace/parse_code/fx_trace.py`、`tests/test_fx_trace.py`

**Interfaces（已实现）：**
```python
def trace_module(module, example_inputs, *, module_id: str = "root") -> dict:
    """返回 {"nodes": [...], "edges": [...]}，形状直接符合 schema 的 node/edge。"""
```
节点字段：`id / parent_id / level="op" / op / label / loc / shape_in / shape_out /
dtype / inplace / source="runtime" / degraded / degraded_reason / repeat=1 / stale=False`。
边：`{id, src, dst, shape, dtype, inplace, shape_consistent}`。

**实现要点（与初版计划不同，已改）：**

1. 用 `torch.export.export(module, example_inputs)`，**不是** `symbolic_trace + ShapeProp`。
   - `symbolic_trace` 追 nanoGPT 必炸：`T = x.size()` 是 Proxy，
     `att.masked_fill(self.bias[:, :, :T, :T] == 0, ...)` 直接
     `TypeError: slice indices must be integers or None or have an __index__ method`；
     `assert t <= self.config.block_size` 还会抛
     `TraceError: symbolically traced variables cannot be used as inputs to control flow`。
   - `make_fx` 能跑，但 aten 图被拆碎（unsafe_view/expand/clone）且 `nn_module_stack` 为 None，做不了层级。
   - `torch.export` 是真实（fake-tensor）执行：切片/断言都能过，节点自带
     `meta["val"]`（真实静态形状）和 `meta["nn_module_stack"]`（模块路径），一举解决形状与层级。
2. `_ensure_export_cache()`：本机 `TORCHINDUCTOR_CACHE_DIR` 指向 Unsloth 的不可写目录，
   `export` 拉起 inductor 就 `WinError 5`。先探测可写，不可写才退到临时目录，不改用户配置。
3. 形状只从 `node.meta["val"]` 取，**没有任何写死的形状列表**。
4. 多输出算子（`split_with_sizes`）保留全部输出形状，`shape_out` 记第 1 项并标 degraded，
   reason 里把每一项形状都写出来。
5. `getitem` 消费多输出节点时，按 `args[1]` 的常量索引取**那一项**的形状（见 Task 8 补充）。
6. `inplace`：算子名以 `_` 结尾（`masked_fill_` `add_` …）。
7. `loc`：`f"{type(module).__module__}.{type(module).__name__}"`（真源码行号留给 M1b）。

**TDD 步骤：** 全部完成。
`test_attention_ops_are_not_fused` / `test_no_scaled_dot_product_attention_node` /
`test_shapes_follow_the_attention_math` / `test_edges_are_shape_consistent` /
`test_missing_torch_raises_runtime_unavailable` 均已绿。

**验收：** 不装 torch 的机器上相关用例 skip 且**有显式 skip 原因**；装了 torch 无 skip 全绿。

## Task 8: 模块层级与 parent_id ✅

**Files:** `papertrace/parse_code/fx_trace.py`、`tests/test_fx_hierarchy.py`

- [x] 用 `node.meta["nn_module_stack"]` 生成 `level="module"` 节点（`source="static"`），
      算子节点的 `parent_id` 指向**最内层**模块。
- [x] 模块 id：根 `module_id`、子模块 `f"{module_id}/{path}"`；父在前、子在后。
- [x] 断言：每个 op 的 `parent_id` 存在且是 module；父子链唯一根、不成环；
      `matmul` 挂在含 `attn` 的模块下；CausalSelfAttention 的父是 Block。

**补充（Task 8 之后发现的真 bug，已修）：**
多输出节点的边形状原来一律取第 1 项。`torch.split(x, [2, 3])` 的第 2 项是 `(2, 3)`，
但边被记成 `(2, 2)`，`getitem` 的 `shape_in` 跟着错——**形状链在自家输出里就断了**，
而旧的 `shape_consistent` 恒为 True，看不出来。
现在 `_resolve_arg_shape()` 按 `getitem` 的常量索引解析；`shape_consistent` 真的拿
「生产者这一项的形状」去比「消费者自己记下的形状」。
守门测试：`tests/test_fusion_and_shapes.py::test_split_items_keep_their_own_shapes_in_edges`。

## Task 9: build 接真路径 ✅

**Files:** `papertrace/cli.py`、`papertrace/build_trace.py`、`tests/test_build_real.py`

- [x] 不带 `--skeleton` 走真追踪；`--entry` 默认 **`model:build_model`**（工厂函数，不是 `model:GPT`）。
      原因：`GPT(config)` 需要配置，我们不猜用户的模型规模；零参类仍然可用。
- [x] 示例输入：`model.example_inputs()` > `config.vocab_size/block_size` 造 token id > `BuildError`。
- [x] 退出码：仓库/入口对不上 **2**、缺 torch **4**、追不动 **5**、目标已存在 **3**；
      四条路径都**不写** `trace.json`（含 `--force` 时）。
- [x] 融合算子警告：图里出现 SDPA 之类时往 stderr 打一行，节点同时标 degraded。

## Task 10: dump 可读输出 ✅

**Files:** `papertrace/cli.py`、`tests/test_cli.py`

- [x] `dump --trace X --ops` 按拓扑序打印 `id 模块 (in) -> (out) op [degraded: 原因]`。
- [x] 测试：只打算子层、带 `->`、含 matmul/softmax/masked_fill、能看出模块路径；空 trace 不打印任何行。

## Task 11: 端到端验收与评审（进行中）

- [x] `python -m papertrace build --repo tests/fixtures/nanogpt --paper none --out output/m1a`
      → 93 个算子节点 + 模块层级，matmul `(2,4,8,8)`、softmax 同形、split 标 degraded。
- [x] `python -m papertrace dump --trace output/m1a/trace.json --ops` 人工核对。
- [ ] 独立评审（m1a-reviewer）结果归档 + 按 Critical/Important 修。
- [x] 更新 `docs/ENVIRONMENT.md` 与 `README.md`（torch 装法、入口契约、退出码表）。

## Review Focus

1. **融合漏检**：`flash=False` 若没生效，图上只会出现一个 SDPA 算子。
   现在不但测试钉死四个算子同时存在，还加了 `FUSED_OPS` 表：真的遇到融合算子时
   **标 degraded + stderr 警告**，绝不安静通过。
2. **假形状**：`shape_in/shape_out` 全部来自 `node.meta["val"]`，没有写死的列表。
3. **静默降级**：没有 torch 时退出码 4，不写空 trace；`--ops` 里 degraded 带原因。
4. **形状链断裂**：多输出按索引解析；`shape_consistent` 不再恒真。
5. **层级造假**：`parent_id` 已断言必须指向真实 module 节点。

---

## 评审与偏离记录

| 计划里写的 | 实际做的 | 为什么 |
| --- | --- | --- |
| `symbolic_trace + ShapeProp` | `torch.export.export` | Proxy 切片 / 控制流断言必炸；export 还顺带给了真实形状和模块栈 |
| `--entry` 默认 `model:GPT` | `model:build_model`（工厂） | `GPT(config)` 要参数，猜配置等于悄悄改变被测模型 |
| 边形状取生产者 `shape_out` | 多输出按 `getitem` 索引逐项解析 | 否则 `split([2,3])` 把 `(2,3)` 记成 `(2,2)`，形状链自断 |
| 只测「四个算子都在」 | 另加 `FUSED_OPS` 检测与警告 | 真实仓库默认开 SDPA，不报警就是静默漏检 |
