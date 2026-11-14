# PaperTrace M1a 实施计划：真实算子追踪

> 前置：框架切片已完成（93 passed / 2 skipped，HEAD 1f26bf8）。
> 目标：让 `trace.json` 里出现**真的**算子节点与形状链，且能证明 nanoGPT 的 Attention
> 是 4 个独立算子（matmul / mul / masked_fill / softmax），不是 1 个融合 SDPA。
> 铁律：所有节点 `source="runtime"`，禁止示例节点、禁止 mock 形状。

**状态（2026-11-14）**：Task 7–11 全部落地，**140 passed**，第二轮评审的必修项已修完，
提交链 `73bb224` → `bc472d6` → `9fbb56b` → `d722f13` → `262eb69` → `58dc5c7` → `82228eb` → `cca2a1a`。
本轮最大的结构变化：形状不再靠 SSA 推断自证，而是把导出图**再用真实张量跑一遍**（`fx_observe`），
逐节点观察消费者真实入参和生产者真实输出，两边独立比较（见文末第三轮记录）。

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
节点字段：`id / parent_id / level / kind / op / label / loc / inputs / shape_in / shape_out /
outputs / dtype / inplace / source / degraded / degraded_reason / repeat=1 / stale=False`。
边：`{id, src, dst, label, shape, producer_shape, checked, dtype, inplace, shape_consistent}`——
`shape` 是消费者这一项的真实输入，`producer_shape` 是生产者真实输出，`checked` 表示两边都观察到了。

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
第一版修法是「按 `getitem` 的常量索引解析生产者形状」，但复审指出它仍然只读生产者
——消费者那侧是推断出来的，断链会被生产者形状抹平。现在的做法换了根基：

- `fx_observe.observe(gm, example_inputs)` 用 `torch.fx.Interpreter` 把导出图**执行一遍**，
  逐节点记 `{"args": [形状树...], "kwargs": {...}, "out": 形状树}`（只留形状，不留张量）；
- 边的 `shape` 从**消费者这次真实拿到的 args[i][j]** 取，`producer_shape` 从**生产者这次真实输出**
  取（多输出用 `_producer_item` 按 `getitem` 的索引取那一项）；
- 两边任一侧没观察到 → `checked=false`，**未核实不算一致**；只有 `checked` 且相等才是 True。
- 形状树原语（`val_shape / shape_tree / tree_leaf / tree_shapes / navigate`）拆到
  `fx_shapes.py`，避免 `fx_graph.py` 超 200 行。

守门测试：`tests/test_review_regressions.py::test_edge_shape_compares_consumer_against_producer`
（伪造生产者 (2,4,8,8)、消费者 (2,4,8,4)，必须 `checked=True` 且 `shape_consistent=False`）、
`test_inplace_then_transpose_is_not_a_broken_edge`、`test_edge_without_observation_is_unchecked_not_consistent`。

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

- [x] `dump --trace X --ops` 按拓扑序打印 `id 模块 (in) -> (out) op [degraded: 原因]`；
      `kind != "op"` 的输入形状打 `-`，输入确实未知打 `(?)`（与 0 维的 `()` 区分）。
- [x] `dump --trace X --edges` 一行一条边：消费者形状 + 生产者形状 + 两端节点；行首 `!` 断链、
      `?` 未核实；末行 `edges=N shape_broken=M shape_unchecked=K`。
- [x] 汇总行把算子与权重/输入分开计：`operators=75 (param=18 input=1)`，不再把权重算进算子数。
- [x] 测试：只打算子层、带 `->`、含 matmul/softmax/masked_fill、能看出模块路径；空 trace 不打印任何行；
      `--ops` 的输出必须按 id 序号递增（拓扑序）。

## Task 11: 端到端验收与评审（进行中）

- [x] `python -m papertrace build --repo tests/fixtures/nanogpt --out output/final-check --force`
      → nodes=126（算子 75 / 权重 18 / 输入 1），edges=101，degraded=2，fused=0，orphan=0，
      `shape_broken=0`、`shape_unchecked=0`；matmul `(2,4,8,8)`、softmax 同形、split 标 degraded。
- [x] `python -m papertrace dump --trace output/m1a/trace.json --ops` 人工核对。
- [x] 独立评审（m1a-reviewer）第一轮结果归档：C1/C2/C3 + I1–I9 + M1–M8，结论「需要修」。
- [x] 必修项全部落地（提交 `d722f13`、`262eb69`、`58dc5c7`）。
- [x] 第二轮评审必修项落地（提交 `82228eb`、`cca2a1a`）：C1 形状一致性改由第二遍真实执行判定；
      C2 inplace 后 `reshape/transpose` 不再误报；I1 先查 torch（真实仓库顶层 import torch 也走 4）；
      I3 `runtime.requested` 与实际形状分开；I4 融合表改真实 aten 名 + 前缀兜底；
      I5/I6/I7 计数、裸张量输入、0 维标量；M1/M3/M4/M5 输出与 schema。
- [x] 复审期间自查补的三处：边 id 重复、父子链成环、parent 指向算子——都改成
      `TraceSchemaError` 并配反例测试；130 passed。
- [x] 更新 `docs/ENVIRONMENT.md` 与 `README.md`（torch 装法、入口契约、退出码表、trace 字段约定）。

### 这一轮评审指出了什么（值得记住的）

第一轮 127 passed 里有一批测试是**恒真断言**：`shape_consistent` 的判定写成
`bool(edge_shape) and not (inplace and ...)`，只要边上有形状就是 True——这个仓库
101 条边 101 条 True，测试却「全绿」。同理 `cat([a,b])` 整条边丢光、embedding 的
`shape_in` 记成权重 `(64,32)`、`x.sum()` 的 0 维输出被当成「未知」、算子 id 与模块 id
可能撞车，这些都没被测试抓到。

教训：**测试要能失败**。现在每条关键行为都配了反例——`split([2,6])` 后 `b+1` 必须断链、
`cat` 必须两条边、`sum()` 必须 `outputs==[[]]`、重复 id/悬空边必须抛错。

## Review Focus

1. **融合漏检**：`flash=False` 若没生效，图上只会出现一个 SDPA 算子。
   现在不但测试钉死四个算子同时存在，还加了 `FUSED_OPS` 表：真的遇到融合算子时
   **标 degraded + stderr 警告**，绝不安静通过。
2. **假形状**：`shape_in/shape_out` 全部来自 `node.meta["val"]`，没有写死的列表。
3. **静默降级**：没有 torch 时退出码 4，不写空 trace；`--ops` 里 degraded 带原因。
4. **形状链断裂**：多输出按 `getitem` 索引取那一项；边的两端分别来自**同一次真实执行**的
   消费者入参与生产者输出，未核实记 `checked=false`（`?`），不拿「有形状」冒充「一致」。
5. **层级造假**：`parent_id` 已断言必须指向真实 module 节点。

---

## 评审与偏离记录

| 计划里写的 | 实际做的 | 为什么 |
| --- | --- | --- |
| `symbolic_trace + ShapeProp` | `torch.export.export` | Proxy 切片 / 控制流断言必炸；export 还顺带给了真实形状和模块栈 |
| `--entry` 默认 `model:GPT` | `model:build_model`（工厂） | `GPT(config)` 要参数，猜配置等于悄悄改变被测模型 |
| 边形状取生产者 `shape_out` | 多输出按 `getitem` 索引逐项解析 | 否则 `split([2,3])` 把 `(2,3)` 记成 `(2,2)`，形状链自断 |
| 只测「四个算子都在」 | 另加 `FUSED_OPS` 检测与警告 | 真实仓库默认开 SDPA，不报警就是静默漏检 |
| 单个 `fx_trace.py` | 拆成 `fx_graph/fx_nodes/fx_edges/fx_trace` | 357 行且混了四件事：形状原语、节点、边、导出 |
| 算子 id `root/op000` | `root/@000` | 模块可以叫 `op000`，普通路径会撞 id |
| 边形状取生产者 `shape_out` | 按消费者参数位置解析 | 否则 `cat` 丢边、`split` 第二项记错、权重冒充输入 |
| `shape_out: []` 表示 0 维 | `None`=未知、`[]`=0 维，另加 `outputs` | 原来「标量」和「不知道」没法区分 |
| trace 里不记运行条件 | `meta.runtime` 记设备/版本/dtype/输入/counts | 不记就没法判断这份 trace 能不能复现 |
| 只做 JSON Schema 校验 | 另加结构校验（重复 id / 悬空边 / parent / source） | schema 管不了图的自洽性 |
| 边形状从生产者的 `meta["val"]` 推 | `fx_observe` 用真实张量再跑一遍图，逐节点观察 | 只读生产者等于自证一致；消费者真相只有执行时才有 |
| 一条边的「形状」只有一列 | 拆成 `shape`（消费者）/ `producer_shape`（生产者）/ `checked` | 一列里塞两边，断链根本看不出来 |
| `shape_consistent = bool(shape)` | `checked and 两边相等`，没观察就 `?` | 恒真是最危险的绿灯 |
| `runtime.batch/seq_len` 写 CLI 的值 | 写**实际**喂进去的，CLI 值另记 `requested` | 否则 `example_inputs()` 与 CLI 冲突时 trace 自相矛盾 |

### 提交锚点

| commit | 内容 |
| --- | --- |
| `bc472d6` | build 接真追踪 + `dump --ops` + 工厂入口 |
| `9fbb56b` | 融合算子标 degraded + 多输出按 `getitem` 解析 |
| `3210dcd` | 文档与账本 |
| `82a159c` | dump 打印 degraded 明细与 shape_broken |
| `d722f13` | 评审必修项：诚实形状、逐边核实、结构校验、三文件拆分 |
| `262eb69` | 边加 `label`；三条测试改成「能失败」 |
| `58dc5c7` | 拒绝成环、重复边、非 module 父节点 |
| `82228eb` | 评审修复的文档与账本 |
| `cca2a1a` | 第二遍真实执行判定边形状；`fx_shapes` 拆出；`requested`/`real_execution`；模块路径禁 `@` |
