# PaperTrace M1a 实施计划：真实算子追踪

> 前置：框架切片已完成（93 passed / 2 skipped，HEAD 1f26bf8）。
> 目标：让 `trace.json` 里出现**真的**算子节点与形状链，且能证明 nanoGPT 的 Attention
> 是 4 个独立算子（matmul / mul / masked_fill / softmax），不是 1 个融合 SDPA。
> 铁律：所有节点 `source="runtime"`，禁止示例节点、禁止 mock 形状。

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

## Task 7: fx_trace 真实追踪与形状传播

**Files:**
- Modify: `papertrace/parse_code/fx_trace.py`（现在是 raise NotImplementedError）
- Create: `tests/test_fx_trace.py`

**Interfaces:**
- Consumes: 一个 `nn.Module` 实例 + example inputs。
- Produces:
  ```python
  def trace_module(module, example_inputs, *, module_id: str = "root") -> dict:
      """返回 {"nodes": [...], "edges": [...]}，形状直接符合 schema 的 node/edge。"""
  ```
  节点字段：`id / parent_id / level="op" / op / label / loc / shape_in / shape_out /
  dtype / inplace / source="runtime" / degraded=False / repeat=1 / stale=False`。
  边：`{id, src, dst, shape, dtype, inplace, shape_consistent}`。

**实现要点：**
1. `torch.fx.symbolic_trace(module)` 拿 GraphModule。
2. `ShapeProp(gm).propagate(*example_inputs)` 让每个 node 带 `meta["tensor_meta"]`。
3. 遍历 `gm.graph.nodes`：`placeholder` / `call_function` / `call_method` / `call_module` / `output`。
4. `shape_in`：第一个 tensor 型 args 的 shape（没有就 []）；`shape_out`：tensor_meta.shape。
5. 边由「node 的 args 里出现了哪些 node」生成，`shape` 取生产者的 shape_out，
   `shape_consistent` 与消费者 `shape_in` 比对（长度不一致时记 false，不抛）。
6. `inplace`：target 以 `_` 结尾（`masked_fill_` `add_` …）。
7. `loc`：`f"{type(module).__module__}.{type(module).__name__}"`（真源码行号留给 M1b）。

**TDD 步骤：**
- [ ] 写 `tests/test_fx_trace.py::test_attention_ops_are_not_fused`：
      对 `CausalSelfAttention`（n_embd=32, n_head=4, block_size=8）trace，
      断言 ops 里**同时**出现 `matmul` / `mul` / `masked_fill` / `softmax`。
- [ ] 跑 → 红（NotImplementedError）。
- [ ] 实现 trace_module → 绿。
- [ ] 加 `test_no_scaled_dot_product_attention_node`（防回退到融合路径）。
- [ ] 加 `test_shapes_follow_the_attention_math`：
      QKᵀ 的输出最后两维必须是 `(T, T)`；softmax 输出与 QKᵀ 同形。
- [ ] 加 `test_edges_are_shape_consistent`：每条边 `shape_consistent is True`。
- [ ] 加 `test_missing_torch_raises_runtime_unavailable`：mock 掉 torch 导入，
      断言抛 `RuntimeUnavailable` 而不是 ImportError 泄漏。
- [ ] `pytest -q` 全绿；提交 `feat: real fx tracing with shape propagation`。

**验收：** 不装 torch 的机器上 `pytest` 仍全绿（相关用例 skip 且**有显式的 skip 原因**），
装了 torch 必须无 skip 全绿。

## Task 8: 模块层级与 parent_id

**Files:** Modify `papertrace/parse_code/fx_trace.py`；Create `tests/test_fx_hierarchy.py`

- [ ] `trace_module(..., level="op")` 之外再加 `module_of(node)` 归属：
      用 `gm.graph` 的 `node.meta["nn_module_stack"]` 生成 stage/module 层节点。
- [ ] 断言：每个 op 节点 `parent_id` 指向一个 `level="module"` 的节点，且该节点存在。
- [ ] 断言：`CausalSelfAttention` 下挂的 op ≥4 个（attn 的四个算子）。
- [ ] 提交 `feat: module hierarchy nodes and parent links`。

## Task 9: build 接真路径

**Files:** Modify `papertrace/cli.py`, `papertrace/build_trace.py`；Create `tests/test_build_real.py`

- [ ] `build --repo <pkg> --paper none`（不带 `--skeleton`）走真追踪：
      用 `--entry`（默认 `model:GPT`）导入模块、构造 tiny config、前向一次。
- [ ] 没有 torch → 退出码 **4**，stderr 说明缺什么（不得写 trace.json）。
- [ ] `--skeleton` 行为不变（回归测试已在 `tests/test_cli.py`）。
- [ ] 生成的 trace 必须过 `validate_trace`，且 `nodes` 非空。
- [ ] 提交 `feat: build traces a real module or refuses loudly`。

## Task 10: dump 可读输出

**Files:** Modify `papertrace/cli.py`；Create `tests/test_dump_ops.py`

- [ ] `dump --trace X --ops` 按拓扑序打印 `序号  op  shape_in -> shape_out`。
- [ ] 断言 Attention 那段四行顺序正确（matmul → mul → masked_fill → softmax）。
- [ ] 提交 `feat: dump --ops prints the operator chain`。

## Task 11: 端到端验收与评审

- [ ] `python -m papertrace build --repo tests/fixtures/nanogpt --entry model:CausalSelfAttention --paper none --out output`
- [ ] `python -m papertrace dump --trace output/trace.json --ops` 人工核对四行。
- [ ] 派独立评审（同框架切片流程），按 Critical/Important 修。
- [ ] 更新 `docs/ENVIRONMENT.md` 与执行账本。

## Review Focus

1. **融合漏检**：`flash=False` 若没生效，图上只会出现一个 SDPA 算子。测试必须钉死四个算子同时存在。
2. **假形状**：`shape_in/shape_out` 若由我们手填常量而非 `tensor_meta`，等于自欺。评审要 grep 有没有写死的列表。
3. **静默降级**：没有 torch 时必须报错，不得写空 trace 或跳过 build。
4. **形状链断裂**：`shape_consistent=False` 的边必须能被 `dump` 看见，而不是被吞掉。
5. **层级造假**：`parent_id` 指不到真实 module 节点视为失败。
