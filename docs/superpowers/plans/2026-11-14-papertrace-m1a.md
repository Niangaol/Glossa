# PaperTrace M1a 实施计划：真实算子追踪

> 前置：框架切片已完成（93 passed / 2 skipped，HEAD 1f26bf8）。
> 目标：让 `trace.json` 里出现**真的**算子节点与形状链，且能证明 nanoGPT 的 Attention
> 是 4 个独立算子（matmul / mul / masked_fill / softmax），不是 1 个融合 SDPA。
> 铁律：所有节点 `source="runtime"`，禁止示例节点、禁止 mock 形状。

**状态（2026-11-14）**：Task 7–11 全部落地，**329 passed**，第三至第十二轮评审的必修项都已修完。
第十一轮把 kind 的最终权威交给 `torch.export` 自己（plan 逐项核对），并堵住了「两边互换」这个
前四轮关卡全过却 kind 相反的洞；另外新增一条能力边界（`forward` 内 `no_grad` → exit 5）。
第十二轮发现「与导出器核对」的 expected 也是从调用方传进来的对象重生的（同源），补了三道防线：
类型守卫（拒 `SimpleNamespace` 替身）、torch 自己写死的**顺序不变量**（权重必须排在数据输入之前）、
**恰好认领一次**（`Counter` 而不是 `set`）；并如实写下残余边界（就地篡改真产物不在威胁模型内）。
（第三轮 C1/I1/I2/I3 + M2/M3/M5；第四轮 I-1/I-2 + M-1/M-3/M-4；第五轮 C1/I1/I2；
第六轮 C1/I2/I3；第七轮 C1 fail-closed + I1 `*_like` + I2 spec 契约校验；
第八轮 I-1 退出码统一 + I-2 守卫改判覆盖 + M-1…M-5；第九轮 I-1 orphan 双向语义 + I-2 未知/错位 kind fail-closed + M-1…M-3；
第十轮（自查）反向认领 + 常量不许顶替参数；第十一轮 C1 导出器逐项核对 + I-1 `CUSTOM_OBJ`/`TOKEN` + I-2 orphan 输出边界 + I-3 弱断言 + M-1…M-5；
第十二轮 I-1 同源 expected → 类型守卫 + 顺序不变量 + 恰好认领一次、I-3 补 CLI 级退出码用例、Minor zoo 集合相等/dict 输出/mutation CLI），
提交链 `73bb224` → `bc472d6` → `9fbb56b` → `d722f13` → `262eb69` → `58dc5c7` → `82228eb` → `cca2a1a` → `8b710ee` → `f58b123` → `fc1ca48` → `2de86a2` → `6a87f7d` → `fce6b2d` → `5fd9b7c` → `b48f361` → `f9e3546` → `94c2b28` → `66f2efd` → `feb6fc8` → `b8d39d2` → `d4c84a2` → `500c692` → `7dc55f2` → `0e9e608` → `e10d9d3` → `df7a8eb` → `d7d16f0` → `9ec97b3` → `967d664`。
本轮最大的结构变化：形状不再靠 SSA 推断自证，而是把导出图**再用真实张量跑一遍**（`fx_observe`），
逐节点观察消费者真实入参和生产者真实输出，两边独立比较（见文末第三轮、第四轮记录）。

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
     `meta["val"]`（静态形状）和 `meta["nn_module_stack"]`（模块路径）。
     注意：**形状最终不以 `meta["val"]` 为准**（见第 3 条与第四轮记录），它只用于
     `get_attr`/权重这类不进入真实执行的节点；模块层级仍用 `nn_module_stack`。
2. `_ensure_export_cache()`：本机 `TORCHINDUCTOR_CACHE_DIR` 指向 Unsloth 的不可写目录，
   `export` 拉起 inductor 就 `WinError 5`。先探测可写，不可写才退到临时目录，不改用户配置。
3. 形状来自**第二遍真实执行**：`fx_observe` 用真实张量把导出图再跑一遍，逐节点记下
   消费者实际入参与生产者实际输出（`torch.export` 的 `meta["val"]` 是第一遍 fake-tensor
   的静态值，只给 `get_attr`/权重这类节点兜底）。**没有任何写死的形状列表**。
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

**Files:** `papertrace/cli.py`、`papertrace/report.py`、`tests/test_cli.py`

（`cli.py` 只留参数与退出码，排版拆到 `report.py`：`cli.py` 曾涨到 275 行，违反 ≤200 行约束。）

- [x] `dump --trace X --ops` 按拓扑序打印 `id 模块 (in) -> (out) op [degraded: 原因]`；
      `kind != "op"` 的输入形状打 `-`，输入确实未知打 `(?)`（与 0 维的 `()` 区分）。
- [x] `dump --trace X --edges` 一行一条边：消费者形状 + 生产者形状 + 两端节点；行首 `!` 断链、
      `?` 未核实；末行 `edges=N shape_broken=M shape_unchecked=K`。
- [x] 汇总行把算子与权重/输入分开计：`operators=75 (param=18 input=1)`，不再把权重算进算子数。
- [x] 测试：只打算子层、带 `->`、含 matmul/softmax/masked_fill、能看出模块路径；空 trace 不打印任何行；
      `--ops` 的输出必须按 id 序号递增（拓扑序）。

## Task 11: 端到端验收与评审 ✅

- [x] `python -m papertrace build --repo tests/fixtures/nanogpt --out output/final-check --force`
      → nodes=128（算子 75 / 权重 18 / 输入 1 / 模块 34），edges=101，degraded=2，fused=0，orphan=0，
      `shape_broken=0`、`shape_unchecked=0`；matmul `(2,4,8,8)`、softmax 同形、split 标 degraded。
- [x] `python -m papertrace dump --trace output/m1a/trace.json --ops` 人工核对。
- [x] 独立评审（m1a-reviewer）第一轮结果归档：C1/C2/C3 + I1–I9 + M1–M8，结论「需要修」。
- [x] 必修项全部落地（提交 `d722f13`、`262eb69`、`58dc5c7`）。
- [x] 第二轮评审必修项落地（提交 `82228eb`、`cca2a1a`）：C1 形状一致性改由第二遍真实执行判定；
      C2 inplace 后 `reshape/transpose` 不再误报；I1 先查 torch（真实仓库顶层 import torch 也走 4）；
      I3 `runtime.requested` 与实际形状分开；I4 融合表改真实 aten 名 + 前缀兜底；
      I5/I6/I7 计数、裸张量输入、0 维标量；M1/M3/M4/M5 输出与 schema。
- [x] 复审期间自查补的三处：边 id 重复、父子链成环、parent 指向算子——都改成
      `TraceSchemaError` 并配反例测试；当时 130 passed。
- [x] 更新 `docs/ENVIRONMENT.md` 与 `README.md`（torch 装法、入口契约、退出码表、trace 字段约定）。

### 这一轮评审指出了什么（值得记住的）

第一轮 127 passed 里有一批测试是**恒真断言**：`shape_consistent` 的判定写成
`bool(edge_shape) and not (inplace and ...)`，只要边上有形状就是 True——这个仓库
101 条边 101 条 True，测试却「全绿」。同理 `cat([a,b])` 整条边丢光、embedding 的
`shape_in` 记成权重 `(64,32)`、`x.sum()` 的 0 维输出被当成「未知」、算子 id 与模块 id
可能撞车，这些都没被测试抓到。

教训：**测试要能失败**。现在每条关键行为都配了反例——伪造生产者 `(2,4,8,8)` 对消费者
`(2,4,8,4)` 必须判 `shape_consistent=false`（`tests/test_review_regressions.py::test_edge_shape_compares_consumer_against_producer`）、
`cat` 必须两条边、`sum()` 必须 `outputs==[[]]`、重复 id/悬空边/自环必须抛错、
observe 失败必须 `exit 5` 且不覆盖已有 trace。
注意：真实的 `split([2,6])` 每一项在真实执行里是**自洽**的（`tests/test_fusion_and_shapes.py` 断言每项边
`shape_consistent=True`）——断链要用伪造数据造，不能拿合法图当反例（第二版文档这里写错过）。

### 第三轮评审（基线 8b710ee，140 passed）指出了什么

结论仍是「需要修」，四条 Critical/Important 全部成立：

| 编号 | 问题 | 修法 |
| --- | --- | --- |
| C1 | observe 失败仍照常写 trace，算子照样 `source="runtime"`、`runtime.ok=true`，摘要还写「真实追踪」——与 README 承诺的「追不动就退出码 5、不写 trace」相反 | observe 一失败就 `raise TraceUnsupported`，**exit 5 且不写/不覆盖 trace.json**（含 `--force`）；删掉「real_execution 不 ok 也放行」的死分支 |
| I1 | 工厂函数/example_inputs/模块顶层抛异常 → 裸 traceback + exit 1；畸形 JSON 做 dump 也 exit 1 | 全部翻成 `BuildError`（exit 2）或 `TraceUnsupported`（exit 5）；dump 捕 `OSError/ValueError` → exit 2，不出 traceback |
| I2 | `inputs` 里塞着权重，param-only 算子把权重冒充 `shape_in` | `inputs` 只放数据入参：按参数位置跳过 `param_names` 里的名字；param-only → `inputs=[]`、`shape_in=[]`，dump 打 `-` |
| I3 | 结构校验允许 module→op、op→module、自环 | 边两端必须 `level=="op"`，禁 `src==dst`，补四条反例 |
| M5 | getitem 的多生产者容器把同一索引套到每个生产者 | 只有 `args[0]` 本身就是一个生产者节点时才按索引取项，否则 `checked=false` |
| M2 | `FUSED_OPS` 有死键（`multi_head_attention_forward` 在 `torch.ops.aten` 不存在） | 删死键；参数化测试逐个 `hasattr(torch.ops.aten, name)`，前缀兜底单独测 |
| M3 | 测试用相对路径，只有从仓库根跑才成立 | 夹具路径改 `Path(__file__).resolve().parents[1]` |
| M1 | exit 5 时 stderr 前面有 torch 自己打的十几行诊断图 | 拦不住（torch 内部输出），改为 README 明说「结论永远在最后一行」 |

守门测试：`tests/test_third_review.py`（24 条，含真实自定义算子 `boom` 的 exit 5、
工厂/example_inputs 异常的 exit 2、畸形 JSON 的 exit 2、param-only 的 `inputs=[]`）。

### 第四轮评审（基线 fc1ca48，164 passed）指出了什么

无 Critical，但两个必修项都是「文档说了、代码没做」那类：

| 编号 | 问题 | 修法 |
| --- | --- | --- |
| I-1 | 权重藏在**容器**里（`torch.cat([self.w, x])`）时，整段 `tree_shapes` 都被塞进 `inputs`，`shape_in` 变权重形状 | 新增 `_data_shapes(raw, tree, is_param, out)`，按原始参数树与观察到形状树**递归**配对，任一深度的 param 叶子整个跳过 |
| I-2 | trace 根或字段类型不对（`[1,2,3]`、`nodes: "x"`）时 `_structural_errors` 仍无条件跑，`list.get` → AttributeError + exit 1 | 先判根是否 dict、`nodes/edges` 是否数组、每项是否对象，报「必须是 JSON 对象/数组/对象」并继续收集其它错误 |
| M-1 | `--ops` 把「确实没有数据入参」（`slice` 只有 buffer 入边）和「输入未知」都打 `(?)` | `inputs==[]` → `-`；只有缺 `inputs` 字段的老格式才 `(?)`；三态互不混淆 |
| M-3 | 计划文档提交链缺 `fc1ca48`；`fx_observe`/`fx_nodes` 的 docstring 还写「失败退回 meta」 | 文档与注释同步；`module.eval()` 的异常也翻成 `TraceUnsupported`（M-4） |

守门测试：`tests/test_fourth_review.py`（10 条：`cat([w,x])`/`cat([x,w])` 的 `shape_in` 必须是数据的、
`stack([w])` 的 `inputs==[]`、四种畸形 JSON 都 exit 2 且无 traceback、`slice` 打 `-` 不打 `(?)`、
`eval()` 抛错变 `TraceUnsupported`）。

### 第五轮评审（基线 6a87f7d，174 passed）指出了什么

三条都是「上一轮只修了表面一层」：

| 编号 | 问题 | 修法 |
| --- | --- | --- |
| C1 | `owned_paths` 同时登记了参数全名（`self.x` → `x`），和形参 `x` 撞车：真输入被改判成 param，`cat` 的 `inputs=[]`，摘要写「输入 0」，build 仍 exit 0 | `owned_paths` 改为返回 `(全名表, mangled 表)`；`param_names` 只从 mangled 名（`p_`/`b_`）里收，全名只用来查 `get_attr` 的父模块 |
| I1 | `id`/`parent_id`/边 `id`/`src`/`dst` 是 list/dict 时 `x in ids` 抛 `TypeError: unhashable type`，exit 1 + traceback | 新增 `_check_key_types()`：非字符串项剔出后续校验并记「必须是字符串」，最后照常抛 `TraceSchemaError`（exit 2） |
| I2 | 权重**派生量**（`self.w[0]`、`self.w[:, :2]`）是算子节点不是 param 叶子，仍被当数据输入 | 新增 `fx_inputs.param_derived()`：只由权重算出的节点（含 getitem/slice/transpose）全部并入「权重集合」，`inputs` 与 getitem 特判都用它 |

守门测试：`tests/test_fifth_review.py`（10 条：同名参数下 `inputs==[[1,4]]` 与摘要「输入 1」、
`WIdx`/`WSlice` 的 `shape_in` 是数据形状、`x[0]`（导出成 `select`）仍算输入、四种坏字段类型都 exit 2
且无 traceback、进程内抛 `TraceSchemaError`）。

变异探针（每条都确认能红，改完全部还原）：`param_names` 塞回裸全名 → C1 两条红（摘要变「输入 0」）；
`derived = set()` → I2 两条红（`select` 混进 `inputs`）；删掉 `_check_key_types` 调用 → I1 五条红
（`TypeError: unhashable type: 'list'`）。

### 第五轮复审（基线 fce6b2d，184 passed）：压平名（mangled）还是撞

第五轮把「裸全名」从判定里摘掉了，但**压平名本身就会撞**：`sub.x` 与根上的 `sub_x`
都变成 `p_sub_x`，谁后写谁赢。评审给出的复现是必现的：

| 编号 | 问题 | 修法 |
| --- | --- | --- |
| C1 | `sub_x`（根参数）与 `sub.x`（子模块参数）压成同一个 `p_sub_x`，后者覆盖前者；`forward(p_x)` 与 `self.x` 的 `p_x`/`p_x_1` 也会整对调换 | 参数判定改由 `graph_signature.input_specs` 接管（`fx_signature.input_plan/classify`）：`spec.kind` 定 kind，`spec.target` 定所属模块。mangled 名兜底在第七轮被彻底删掉（见下）：没有 spec 就 fail-closed |
| I2 | 常量：`torch.cat([torch.ones(2,4), x])` 的 `cat inputs=[[2,4],[1,4]]`；`self.const` 被标成 `input` | `CONSTANT_TENSOR` → 新 kind `const`，与权重同等对待（不进 `inputs`）；`fx_inputs.constant_names()` 把无入参的 `ones/zeros/full/empty/arange/linspace/eye` 也并进派生集合。schema 的 kind enum、摘要的「常量 N」、`dump --ops` 的 `kind=const` 同步——否则 build 写得出、dump 校验不过 |
| I3 | 只有参数、没有算子的子模块（`Sub`）不进 `nn_module_stack`，权重的 `parent_id` 掉回 `root` | `fx_modules.``_all_module_types()`：先按 `named_modules()` 收全树（root 用类名），再拿图里的类型补，模块节点与 `module_ids` 因此完整 |
| I4 | README/计划写着「第五轮已修完」、提交链止于 `6a87f7d`、`meta["val"]` 取形状 | 本节与上两处已改回事实 |

observe 也跟着改了：`exported.module()` 的 placeholder 被换成 target 名（`sub_x`、`sub_x_1`），
拿它去 observe 和图里的 `p_sub_x` 对不上，连参数值都取不到。现在直接用
`torch.fx.GraphModule(nn.Module(), exported.graph)` 包住**原图**，再按 `input_specs` 把
权重/缓冲/常量/数据的真实张量按 placeholder 顺序排好（`fx_signature.placeholder_args`）。

守卫测试：`tests/test_sixth_review.py`（12 条：`sub.x`+`sub_x` 权重 2/输入 1 且 parent 分别是
`root`/`root/sub`、`forward(p_x)` 的 data 入参不被吞、字面常量与 `self.const` 都不算输入、
`--ops` 显示 kind、`edge.dst` 是 int 与 nodes 混字符串都 exit 2 且无 traceback、
无 spec 且图里有 placeholder 必 `BuildError`）。

变异探针（均已还原）：`plan = []` → 6 条红；`types = dict(module_types)` → parent 用例红；
去掉 kind 标注 → `--ops` 用例红。

拆分（都因为 ≤200 行）：`fx_modules.py`（模块树）、`fx_signature.py`（input_specs 与真实张量）、
`schema_structure.py`（结构校验）、`fx_runtime.py`（这次追踪怎么跑的，第九轮从 fx_signature 拆出）。

**行数口径（踩过坑，钉死）**：用 `len(pathlib.Path(f).read_text(encoding="utf-8").splitlines())`。
`Get-Content` 在这台机器上会**少算**（fx_nodes 实测 159 vs 真值 175、fx_signature 190 vs 208），
第八轮就是用它核的「≤200 行」，结果 fx_signature 实际已 208 行超标而没被发现。
当前真值（第十一轮末，全仓扫描 `OVER200=[]`）：`fx_signature` 187、`fx_nodes` 185、`fx_edges` 184、
`build_trace` 181、`report` 165、`fx_trace` 160、`cli` 157、`fx_graph` 148、`schema_structure` 129、
`fx_contract` 126、`schema_validate` 100、`fx_inputs` 98、`fx_runtime` 31。**没有一个文件超过 200 行。**
第十轮把契约校验从 fx_signature 拆到 `fx_contract.py` 后，fx_signature 从 202 降回 162；
第十一轮加 `check_plan_source` 让它回到 187，仍在上限内（`fx_contract` 54 → 126）。
测试文件不受这条约束，但也记一下最大的几个：`test_eleventh_review` 449、`test_seventh_review` 356、
`test_sixth_review` 341、`test_tenth_review` 296、`test_model_zoo` 246。

### 第七轮评审（基线 b48f361，196 passed）：兜底、`*_like`、spec 契约

const 修复本身通过了（build 摘要「算子 1 / 权重 0 / 常量 1 / 输入 1」，dump 接受），
但评审指出三条契约漏洞，其中 C1 会让整类标反：

| 编号 | 问题 | 修法 |
| --- | --- | --- |
| C1 | 没有 `input_specs` 的兜底分支仍按名字猜 param：`Shadow`（`self.x` + `forward(p_x)`）fallback 把 `p_x_1` 标 input、`p_x` 标 param（正好反了）；`ConstModel` 的 const 变 input；observe 也因 `exported.module()` 名错位拿不到参数值 | 删掉 mangled 兜底与 `owned_paths`/`mangled_collisions`：图里只要有 placeholder 而 plan 为空，直接 `BuildError`（exit 2，「无法区分权重/输入/常量，拒绝出图」）。真的没有 placeholder（纯常量模型）时空 plan 合法。observe 只剩一条路径：原图 GraphModule + `placeholder_args` |
| I1 | `ones_like/zeros_like` 被当数据输入：`cat([ones_like(x), y])` 的 `cat shape_in` 是 `x` 的 (2,4) 而不是 `y` 的 (2,6) | `CONSTANT_LIKE_OPS`（`*_like`/`new_*`）并入常量种子：输出不进 `inputs`，也不把 `x` 算成它的数据入参；`rand_like` 明确不在名单里 |
| I2 | `placeholder_args` 不校验 spec 完整性：缺 spec 的 placeholder 会被当普通输入 `pop`，example_inputs 顺序/数量不对会静默喂错 | 三道校验：spec 必须覆盖全部 placeholder；USER_INPUT 个数必须等于 `len(example_inputs)`（错误信息要求「按 forward 形参顺序给」）；正常路径再断言参数拿到的就是模块里那个 Parameter。（本轮缺/多抛 `TraceUnsupported`/exit 5，第八轮 I-1 统一改成 `BuildError`/exit 2） |

守卫测试：`tests/test_seventh_review.py`（9 条：有 placeholder 无 spec → `BuildError`；纯常量模型空 plan 仍出图；
spec 缺项/多出图里没有的名字/example_inputs 少一项都 `TraceUnsupported`；正常路径按 forward 顺序拿到真实张量；
`ones_like`/`zeros_like` 的 `inputs==[]` 且 `cat shape_in` 是 y；CLI 摘要「输入 2 / 权重 0」并能被 dump 接受）。

变异探针（均已还原）：关掉 fail-closed 守卫 → 2 条 `DID NOT RAISE BuildError`；
去掉 `CONSTANT_LIKE_OPS` 的 inputs 清空 → 2 条 `inputs==[[2,4]]`；
去掉 spec 完备性检查 → 「缺少 placeholder」用例红。


### 第八轮评审（基线 f9e3546，205 passed）：退出码契约与守卫判据

第七轮的 fail-closed 与 `*_like` 都通过了，但评审指出「拒绝的方式」本身有两处不一致：

| 编号 | 问题 | 修法 |
| --- | --- | --- |
| I-1 | README 承诺「有 placeholder 无 spec → `BuildError` / exit 2」，CLI 实际走 `placeholder_args` 的 `TraceUnsupported` → exit 5。评审 monkeypatch `fx_trace.input_plan = lambda exported: []` 复现：stderr 是「缺少 placeholder：p_x_1、p_x」，RET 5，sentinel trace 未被覆盖。测试只测了手工 `plan={}`，没测 CLI | **契约错误统一 exit 2**：spec 缺项/多项/顺序不符都抛 `BuildError`；`example_inputs` 数量不符仍是 `TraceUnsupported`（exit 5，那是「追不动」不是「契约不对」）。`fx_trace` 的 `except (TraceUnsupported, BuildError): raise` —— 否则 `BuildError` 会被包成 observe 失败又变回 5。新增 CLI 用例断言 exit 2 + stderr 含「缺少 placeholder」+ 不写 trace |
| I-2 | 守卫写成 `if not plan and ...`，而 `classify([])` 返回的是**非空 dict**（`{"params": set(), "consts": set(), "inputs": [], "owner": {}}`）。直接调 `build_op_nodes(..., plan=classify([]))` 能把参数和输入都标 input、`add` 的 inputs 为空，`validate_trace` 还不报错。CLI 路径因先走 `placeholder_args` 被拒所以安全，但测试给了假安全感 | 守卫改判**覆盖**：`covered = param_names \| spec_inputs`，凡有 placeholder 不在 covered 里就 `BuildError`，与 plan 的真假无关。两条新用例分别喂 `classify([])` 与「只覆盖一半」的 plan |
| M-1 | `fx_graph.py` docstring 仍写「形状只取自 `node.meta['val']`」 | 改成「形状优先取 `fx_observe` 观察值，只有 get_attr/权重回落 `meta['val']`」 |
| M-2 | orphan 只排除 `arange`，`cat([torch.ones(2,4), x])` 报 orphan=1 | `fx_inputs.CONSTANT_SOURCES = CONSTANT_OPS \| CONSTANT_LIKE_OPS`，orphan 判据用它；README 补「常量源天生没有数据入边，被下游用了就不算孤点」 |
| M-3 | 没有 spec 顺序断言；缺项与多项分两次报，用户要跑两遍 | 顺序断言 `[item["name"] for item in plan] == placeholders`；缺/多聚合成一条 problems 一次报全 |
| M-4 | 测试缺 `x→ones_like` 边断言、`full_like`/`new_*`/`rand_like` 对照、`classify([])` 与 CLI 用例 | `tests/test_seventh_review.py` 扩到 18 条：三种 `*_like` 参数化（含 x→like 边存在断言）、`rand_like`/`randn_like` 反向对照（cat inputs==[[2,4],[2,6]]）、orphan==0、顺序错位、缺+多聚合、两条守卫、一条 CLI |
| M-5 | plan 提交链缺 `f9e3546`；行数口径与评审不一致 | 提交链补齐 `f9e3546`/`94c2b28`；行数写明口径（`Get-Content` 含空行 vs 评审的非空非注释） |

评审对五个自问的答复（记录取舍，不再改）：① fail-closed 可接受；② `ones_like` 的**边没有消失**
（x→ones_like、ones_like→cat、y→cat 三条都 checked/consistent=True），M1a 语义接受，
**不要**把 x 塞回 like 的 inputs；③ 校验顺序不误导，但缺/多该聚合；④ 纯常量空 plan 在 CLI 无后门、
直接 API 有（即 I-2）；⑤ README 的数量承诺准确，只有 exit 2 那句不准。

变异探针（均已还原）：守卫加回 `and not plan` → `classify([])` 与 partial 两条 `DID NOT RAISE BuildError`；
关掉顺序断言 → reordered 用例红；orphan 退回只排 `arange` → orphan 用例红。

全量 **214 passed**。端到端 fixture build：nodes=128（算子 75 / 权重 18 / 输入 1 / 模块 34）、
edges=101、degraded=2、shape_broken=0、shape_unchecked=0。


### 第九轮评审（基线 66f2efd，214 passed）：orphan 语义与 kind 的 fail-closed

第八轮的退出码统一与覆盖判据都通过了，但评审指出「拒绝」与「计数」各自还差一层：

| 编号 | 问题 | 修法 |
| --- | --- | --- |
| I-1 | `orphan` 只判「没有入边」，README 却定义成「既无入边也无出边」。探针实测：`torch.rand(1,4)` 被 `cat` 用着仍报 orphan=1（`torch.ones` 因在豁免名单里才幸免）；直接构造 `b→a` 时数的是 b（有出边）而不是 a，与 README 正好相反 | 建 `outgoing = {e["src"] for e in edges}`，orphan = **无入边且无出边**。常量豁免名单 `CONSTANT_SOURCES` 整个删掉——被用着的常量源有出边，自然不算孤点；谁都不用的 `torch.ones` 现在会被数出来（死代码）。README 同步 |
| I-2 | 覆盖判据只查名字：`_spec_kind` 把不认识的 InputKind 默认成 `input`，`classify` 的 else 分支同样兜底；一个「名字全覆盖但 kind 标反」的 plan 能出图，`validate_trace` 也查不出 | ① `_spec_kind` 未知 kind → `BuildError`（torch 2.15 的 6 个 InputKind 全在 KIND_MAP 里，实测不会误伤）；② `classify` 只接受 param/const/input；③ `build_op_nodes` 守卫再加两条：同一名字不能既是权重又是输入（overlap）、spec 不能有图里不存在的幽灵名（ghost）。**kind 的正确性**由 `placeholder_args` 拿模块真实参数核对（spec 说权重 → 模块里必须真有），新增用例证明标反会被拒 |
| M-1 | orphan 用例只测常量源；like 边只断言存在，没断言 checked/consistent | 新增 `tests/test_ninth_review.py`（13 条）：rand 源端到端 orphan==0、双向都断才算孤点、死常量算孤点、like 两条边的 checked/shape_consistent |
| M-2 | plan 行数是 `Get-Content` 口径，**少算**：fx_signature 实际 208 行已超 200 而计划写 175 | 口径改成 python `splitlines()`（见上），并据此发现真实超标 |
| M-3 | `fx_signature` 职责偏混（input_specs + 分类 + 真实张量 + runtime meta），189 行接近上限 | `runtime_meta` 拆到新的 `fx_runtime.py`（31 行），fx_signature 降到 183 行；fx_trace 顺带删掉三个未使用的形状 helper import |

**主动不做的一件事**：评审建议把 input_specs 的 name/kind 摘要存进 `meta.runtime`，好让
`validate_trace` 也能查 kind。没做，理由是它**增加冗余而不增加验证力**——那份摘要与节点 kind
出自同一个 plan，classify 真出错时两边一起错，照样查不出；而真正的地面真相（模块里有哪些参数）
只在 build 时存在，已经由 `placeholder_args` 把住。trace.json 里不存 spec，README 明说
`validate_trace` 查不出 kind 标反，不假装它能。

变异探针（均已还原）：orphan 退回只看入边 → 4 条红；`_spec_kind` 恢复默认 input → 未知 kind 用例红；
`classify` 去掉 kind 校验 → `DID NOT RAISE BuildError`；去掉 overlap 守卫 → `DID NOT RAISE BuildError`。

全量 **227 passed**。端到端 fixture build 不变：nodes=128（算子 75 / 权重 18 / 输入 1 / 模块 34）、
edges=101、degraded=2、fused=0、orphan=0、shape_broken=0、shape_unchecked=0。


### 第十轮（自查，基线 b8d39d2）：kind 标反的反向核对

给评审出的第 5 问是「请证伪我的『同源冗余』论：有没有 classify 出错但 placeholder_args 抓不到的路径」。
没等回复，自己先用探针打了一遍——**找到了，而且不需要 CUSTOM_OBJ 那么绕**：

```
模型 A：self.w = nn.Parameter(ones(2,4))，forward(x)
真实 plan：[('p_w','param','w'), ('x','input',None)]
把 p_w 改成 ('p_w','input',None)，example_inputs 给 (w.detach(), zeros(2,4))
→ len(user_names)==2==len(example_inputs)，数量校验通过
→ 第九轮实现：**放行**，args=[(2,4),(2,4)]，权重顶着 kind=input 出图
```

根因：第九轮的核对是**单向**的——只查「spec 说权重 → 模块里真有」，没查反方向。
另一个同族洞：`const` 分支兜底到 `named`（含 named_parameters），于是「把可训练参数标成常量」也放行。

**修法（地面真相是模块，不是 plan）**：
- 新增反向判据：模块里**每个** `named_parameters`/`named_buffers` 的 target 都必须被某个
  `param`|`const` spec 认领；有未被认领的 → `BuildError`，消息点名是哪几个参数。
- `const` 分支拆开：`exported.constants` → 缓冲 → **参数则拒绝**（「常量与权重不能混」）。
- 退出码归一：spec 与图/模块对不上（含「说权重但模块找不到」「说常量但拿不到值」）一律
  `BuildError` / **exit 2**；只有 torch 追不动与 `example_inputs` 数量不符才是 exit 5。
  第九轮把前者留在 TraceUnsupported，与同族判据两个码，这次统一并把分界线写进 README。

**先证明不会误杀**（探针 B，7 个模型逐个量「未被认领的参数/缓冲」）：单参数、**参数名与形参名同名**
（torch 给 `p_x`/`x` 两个 placeholder，target 分别是 `x` 与 `None`）、**没用到的参数**、**没用到的缓冲**、
常量张量、子模块参数、GPT fixture（10 参数 + 1 缓冲）——**全部为空**，反向判据成立。
关键在于 USER_INPUT 的 `spec.target` 是 `None` 而不是形参名，所以同名遮蔽不会误伤。

**结构**：三条契约判据（缺项/多项、顺序、反向认领）拆到新文件 `papertrace/parse_code/fx_contract.py`
（54 行，`check_contract(placeholders, plan, params, buffers)`）。不拆的话 fx_signature 会到 **202 行**，
又超 200 行约束——这次是先用 python splitlines 量出来才发现的。拆完 fx_signature 162 行。

**测试**：`tests/test_tenth_review.py` 9 条（212 行）。其中第一条先断言
`sum(kind=='input')==2`（证明数量校验真被骗过去了），再断言 `BuildError` 且消息含「认领」与 `w`；
反向对照三条（缓冲标常量仍合法、同名遮蔽/未用参数缓冲/子模块都不误杀）；
CLI 一条（monkeypatch `fx_trace.input_plan` 把权重标成 input → exit 2、stderr 含「认领」、不写 trace）。
第九轮那条「spec 说权重但模块找不到」的断言随退出码归一改成 `BuildError`。

变异探针（均已还原）：`if unclaimed:` → `if False:` → **3 条红**（含 CLI）；
`if target in params:` → `if False:` → 常量顶替参数那条红；
`check_contract(...)` → `pass` → **7 条红**（第七轮的缺项/多项/顺序/聚合/CLI 全在）。

全量 **236 passed in 50.66s**。端到端 output/tenth-check：build exit 0，nodes=128（算子 75 / 权重 18 /
输入 1 / 模块 34）、edges=101、degraded=2、fused=0、orphan=0、shape_broken=0、shape_unchecked=0（逐项不变）。

**关于「要不要把 spec 摘要存进 meta.runtime」**：拒绝的理由仍然成立——摘要与节点 kind 同源，
标反时两边一起反，validate_trace 照样查不出。但这一轮说明我第九轮的**核对本身漏了一个方向**：
真正缺的不是冗余副本，而是**另一个地面真相（模块）**。补上之后，build 侧两个方向都闭合了。


### 第十一轮评审（基线 500c692，236 passed）：kind 的权威是导出器，不是调用方

评审拿**两份报告**打这一轮（第二份基线 500c692）。最狠的一条 C1 是：第十轮的四道关卡
（覆盖齐全、不重叠、无幽灵名、反向认领、数量校验）**全过，而 kind 正好相反**：

```
模型：self.x = nn.Parameter(...)，forward(x)      # 参数名与形参名同名
真实 plan：[('p_x','param','x'), ('x','input',None)]
改成：    [('p_x','input',None), ('x','param','x')]
→ 名字全覆盖、顺序对、模块的参数 x 被「认领」了、USER_INPUT 数 == example_inputs 数
→ 实测 CLI exit 0，trace 里 root/@000 kind=input（真参数）、root/@001 kind=param（真输入）
→ validate_trace PASS
```

根因：前面所有关卡的地面真相是**模块**和**名字集合**，而「哪个 placeholder 是权重」这件事的
权威其实是 `torch.export` 自己给的 `graph_signature.input_specs`。拿模块核只能证明「这个名字
在模块里存在」，证明不了「这个 placeholder 就是它」。

| 编号 | 问题 | 修法 |
| --- | --- | --- |
| C1 | plan 与导出器自己的 specs 从不比对，两边互换 kind 可全过四道关卡并 exit 0 | `fx_contract.check_plan_source(plan, expected)`：逐项比 name/kind/target/**顺序**，不一致 `BuildError`（exit 2），消息「传入的 input_specs 与 torch.export 自己给的不一致…kind 的权威是导出器而不是调用方」。`placeholder_args` 在 `check_contract` **之后**调它——顺序刻意，让第七/十轮 monkeypatch `fx_trace.input_plan` 的 CLI 用例仍拿到原文案 |
| I-1（第二份 C1） | `KIND_MAP` 把 `CUSTOM_OBJ` 与 `TOKEN` 都映射成 `input`。torch 只把 ScriptObject 建成 `CUSTOM_OBJ`（值在 `exported.constants`），`TOKEN` 是 `TokenArgument`（副作用/控制流令牌）。旧测试只断言 `set(KIND_MAP)=={k.name for k in InputKind}`，**只查键不查值**，错映射全绿 | `CUSTOM_OBJ → const`；`TOKEN` 进 `REFUSED_KINDS` 明确拒绝（带理由）；未知 kind 仍拒绝。测试改成**钉死每个值** + `set(KIND_MAP) \| set(REFUSED_KINDS)` 覆盖全部 InputKind + 六种 kind 逐个映射的参数化 + `CUSTOM_OBJ` 从 `exported.constants` 取 sentinel 的真实路径 |
| I-1（第一份） | `check_contract` 只做集合差：重复 target、常量不被认领、`const` 顶替缓冲都察觉不到 | ① `check_plan_source` 一旦生效，plan 就是导出器自己的，重复 target 无从伪造（探针实测 16 个模型 `dup_targets` 全为空，**再加唯一性判据不增加验证力反而有误杀风险**，故不加）；② `const` 分支删掉 `buffers` 兜底：值**只能**来自 `exported.constants`，顶替参数或缓冲一律 `BuildError`（评审 Q2：缓冲是可变状态，`BUFFER→param`，不能给 const 开第二套语义）；③ `build_op_nodes` 加可选 `exported=`，入口用 `check_plan_table` 核四张表（params/consts/inputs/owner），并标明它是**内部 API** |
| I-2 | `orphan` 误报「直接 `return` 的常量」：`return torch.ones(2,4)` → edges=0、orphan=1、exit 0 | 新增 `fx_edges.output_node_ids(graph, by_name)`（递归展开 tuple/dict 输出），`finish_nodes(nodes, edges, outputs=None)` 的 orphan 判据加 `and n["id"] not in outputs`。补 CLI 级用例（常量输出 / 零实参输出都断言 `orphan==0`）与 tuple 输出的单元用例 |
| I-3 | `test_legitimate_models_are_not_refused` 三个模型形参都叫 `x`，`assert table["params"]` 只判真值——自证弱断言 | 形参改成 `tokens` / `(y, z)`，断言**精确** params 集合、inputs 顺序、owner 字典，并逐个 param 位置断言 `arg is named[target]`；buffer-as-const 用例**反转**成「拒绝」；另建 `tests/test_model_zoo.py`：16 个模型的精确 kind 计数回归，期望值来自探针实测而不是从被测代码反推 |
| M-1 | 死算子（有入边没人用）不被任何计数捕获 | **取舍写死**：本切片不做死代码检测，README 明说 `orphan==0` 不等于没有死代码；加一条单元用例钉死这个语义，免得以后被当成 bug「修」掉 |
| M-2 | `example_inputs` 少一项时 CLI 文案来自 `torch.export`（`TypeError: missing a required argument`） | 接受现状（export 先炸，我们的友好文案走不到），README 已写清两种来源；补 CLI 用例断言 exit 5 且不写 trace |
| M-3 | README 把 `torch.ones(...)` 写成常量；orphan 定义没考虑图输出；exit 2 清单缺项 | README 六处同步：常量 vs 字面量算子（`self.const`→`CONSTANT_TENSOR`/`kind=const`，forward 里现写的 `torch.ones`→`ones` 算子/`kind=op`）、orphan 三条件、三道关与「两边互换」反例、`build_op_nodes` 内部 API、exit 2/5 清单 |
| M-4/M-5 | 文档漂移、`fx_signature` 职责偏重 | 行数按 python splitlines 重测（见上）；`fx_contract` 承担全部契约判据（126 行），`fx_signature` 187 行 |

**自己又挖出一条评审没测到的能力边界**：zoo 里的 `NoGrad`（`forward` 内 `with torch.no_grad()`）
走全链路会炸——导出器把那段包成子模块，图里出现 `get_attr submod_3 → target submod_1`。
评审只测了 `check_contract`（过得去），没测 `trace_module`。探针实测：
失败发生在 `torch.fx.GraphModule(nn.Module(), ex.graph)` 构造期（`AttributeError: 'Module' object
has no attribute 'submod_1'`）。试过把 `ex.module().named_children()` 挂回空根模块：observe 能跑通，
**但那个非张量 `get_attr` 被标成 `param`，「权重 1」变成「权重 2」**——是错数据。

裁决：**拒绝，不挂回去**。`fx_trace` 在拿到 `exported.graph` 后先查
`artifacts = [n for n in graph.nodes if n.op in ("get_attr", "call_module")]`，非空即
`TraceUnsupported`（exit 5），消息点名节点、说明常见于 `forward` 内 `no_grad`、给出绕过办法
（把 `no_grad` 移到 `forward` 外）。理由与全项目 fail-closed 一致：宁可说清楚追不动，
也不产权重数不对的 trace；给非张量节点发明新 kind 属 M1b 范围。zoo 相应改成 15 条正向 +
1 条「精确拒绝理由」（先证契约关是过的，再证 `trace_module` 拒绝且消息含「子模块」「no_grad」「权重」）。

**测试**：新增 `tests/test_eleventh_review.py`（24 条 + 后续追加，449 行）、`tests/test_model_zoo.py`
（15 条正向 + 1 条拒绝，246 行）；`test_ninth_review` 的 coverage 用例改成 `set(KIND_MAP) | set(REFUSED_KINDS)`、
flipped 用例改名并断言新文案；`test_tenth_review` 反转 buffer 用例 + 新增 `BufferOnly` 精确 plan +
`ConstAttr` 走「导出器自己的 plan 但 constants 清空」的路径。

变异探针（七组，均已还原）：关掉 `check_plan_source` 调用 → **4 条红**；`CUSTOM_OBJ` 退回 input → 3 条红；
`REFUSED_KINDS` 判断改 `if False` → TOKEN 文案那条红；删 orphan 的 `not in outputs` → 4 条红；
恢复 const→buffer 兜底 → 1 条红；`check_plan_table(...)` 换 `pass` → 1 条红；`if artifacts:` → `if False and artifacts:` → 1 条红。

全量 **288 passed in 49.22s**。端到端 `output/eleventh-check`：build exit 0，nodes=128（算子 75 /
权重 18 / 输入 1 / 模块 34）、edges=101、degraded=2、fused=0、orphan=0、shape_broken=0、
shape_unchecked=0、`real_execution={ok:True}`——与第八/九/十轮逐项一致，新守卫没误伤 fixture。

**这一轮的教训**：前四轮都在加「关卡」，但关卡的地面真相选错了就全是摆设。
名字集合、模块参数表都只能证明「存在」，证明不了「对应」。真正独立的第三方是导出器自己——
它早就把答案写在 `input_specs` 里，我们却一直没拿它当权威，只当初始值。

### 第十二轮评审（基线 0e9e608，288 passed）：权威本身也能被伪造

评审快照 `output/review11/0e9e608`，**Critical 0 条**，结论「修完 I-1/I-2/I-3 可进 M1b」。

**I-1（必修）`check_plan_source` 的 expected 也是同源的**：它从**调用方传进来的** `exported` 重生
（`papertrace/parse_code/fx_signature.py:138`），所以传一个 `SimpleNamespace(graph=…, graph_signature=…, constants=…)`
就能让 plan 与 expected 一起错、两道关全过。评审探针实测：`Shadowed`（`self.x` 是 Parameter、forward 形参也叫 x）
伪造 `p_x→input`、`x→param(target=x)` → `placeholder_args` 返回 `[Tensor(2,4), Parameter(2,4)]` 不报错，
`build_op_nodes` 输出 `root/@000 kind=input`、`root/@001 kind=param`；另一个探针把两个 PARAMETER 的 target
都设成同一个参数 → 返回两个 `module.x`、图里两个 param 节点，而 `check_contract` 的 `claimed` 是 **set**，
重复被压成一个，两道关都不响。评审用 15 个真实模型确认**没有真实重复 target**，所以这是直接 API 的信任边界问题，CLI 主路径不受影响。

**我先证伪了「加个类型守卫就够」**（`output/probes/probe13.py`）：`graph_signature.input_specs` 是可变 list、
`InputSpec` 是非 frozen dataclass（`pydeps/torch/export/graph_signature.py:90-95`，字段 kind/arg/target/persistent），
在**真** `ExportedProgram` 上就地互换 kind 同样放行。所以落成三道防线：

| 防线 | 地面真相 | 抓什么 |
| --- | --- | --- |
| ④ `require_real_export` 类型守卫 | `torch.export.ExportedProgram` 这个类型 | 鸭子类型替身（`SimpleNamespace`）；`placeholder_args` 与 `build_op_nodes(exported=)` 两个入口都加 |
| ⑤ 顺序不变量 | **torch 自己写死的约定**：`Inputs = [*parameters_buffers_constant_tensors, *flattened_user_inputs]`（`pydeps/torch/export/graph_signature.py:178-181`） | 「两边互换」——名字全覆盖、顺序与图一致、认领齐、数量还对，只有这条会破 |
| ⑥ 恰好认领一次 | 一个权重只该有一个 placeholder | 重复 target（`Counter` 而不是 `set`） |

⑤ 不是我们发明的启发式：`output/probes/probe13b.py` 量了 **24 个模型**（simple/shadowed/two-params/buffer-only/
non-persistent/const-attr/plain-list/parameter-list/parameter-dict/tied/nested/dict-in/list-in/kw-only/varargs/
int-arg/bool-arg/none-arg/tuple-out/dict-out/no-input/scalar-attr/frozen/multi-user），`prefix_ok` 全 True、
`dup` 全 False、`VIOLATIONS=[]`；`tests/test_twelfth_review.py` 里另有 18 个 zoo 模型的正向对照参数化用例。

**没有给 `check_contract` 加 `constants` 参数**（评审建议之一）：const 的 target 是否在 `exported.constants` 里
已由取值那一步逐个核过（每个 placeholder 都会被解析，拿不到值就 BuildError），再加一遍不增加验证力。
同理**没有去「独立重算 expected」**：评审明确指出 `signature.parameters/buffers/user_inputs` 全是从 `input_specs`
派生的 property（`pydeps/torch/export/graph_signature.py:280-389`），从同一份产物里拿不到第二个独立权威，
重算只是把 `KIND_MAP` 复制一遍。真正能用的第二地面真相只有 **torch 写死的结构不变量**与**模块本身**。

**诚实的残余边界**（写进 `require_real_export` 的 docstring 与 README）：就地篡改真产物的 `input_specs` 属于
「篡改权威本身」，与 monkeypatch 掉全部 `input_plan` 引用同一类，不在本切片威胁模型内；⑤⑥ 只抓其中最常见的两种改法。

**I-2 / I-3 评审读的是旧快照**：I-2（README 写「缓冲可以」与实现相反、kind 表缺 `CUSTOM_OBJ`）与
I-3（TOKEN→2 / no_grad→5 的文档契约）在第十一轮文档提交 `e10d9d3` 里已经修好，评审快照 `0e9e608` 早于它。
本轮补的是 I-3 缺的**CLI 级用例**：TOKEN（往真 export 追加 `InputSpec(kind=TOKEN, arg=TokenArgument)`）→ exit 2、
`forward` 内 `no_grad` → exit 5 且 stderr 无 traceback、重复认领 → exit 2，三条都断言不写 trace。

**Minor 一并修**：zoo 断言从「只查期望 kind」改成**集合相等**并把 `op` 计数也钉死
（`output/probes/probe14.py` 实测 18 个模型；`scalar-attr` 的期望改成 `{input:1, op:1}`——它根本没有 param/const 节点，
不是「有但数量为 0」，这条正是集合相等抓出来的）；补 `output_node_ids` 的**字典输出**用例（tuple 之外）；
补 mutation 结果的 **CLI 级** orphan=0 用例；`no_grad` 的能力边界与「本切片不做死代码检测」都已在 README 写死。

**测试**：新增 `tests/test_twelfth_review.py`（33 条，365 行）；`tests/test_model_zoo.py` 断言加牙（304 行）；
`test_tenth_review` 的 `_const_plan_without_values` 不再用 `SimpleNamespace`，改清真产物的 `_constants`
（`constants` 是只读 property，torch 2.15 没有公开 setter）；`test_eleventh_review` 的互换用例改名
`test_swapped_kinds_fool_names_and_counts_but_break_the_ordering`（顺序不变量先命中，逐项核对仍是第二道），
`CUSTOM_OBJ` 用例改用真导出 + 就地 `CONSTANT_TENSOR→CUSTOM_OBJ`（534 行）。

**自己又挖出一条能力边界（评审没测）**：`fx_trace.py:136` 把 `example_inputs` **原样**传给
`placeholder_args`，而 `torch.export` 会把 pytree 摊平——`forward(d)` 的 `d` 是 dict 时图里有
`d_a`、`d_b` 两个数据输入，`example_inputs()` 给的却是一个容器。`output/probes/probe15.py` 实测
CLI **exit 5**、不写 trace、消息「example_inputs 有 1 项，图里有 2 个数据输入（d_a、d_b）；请按
forward 形参顺序给，多/少都不猜」。**裁决：不自动摊平**——自定义 pytree 的 flatten 顺序不由我们
决定，猜错就是把两个输入静默喂反（与第七轮顺序断言同一个理由）。M1a 保持 fail-closed，README
「追不动」从三种扩到四种并补 CLI 级用例；直接调 `placeholder_args` 时自己给摊平后的元组即可
（`test_pytree_inputs_are_not_refused_by_the_new_invariants` 就是这么测的）。
变异探针（四组，均已还原）：类型守卫改 `if False and …` → **2 条红**（两个入口的替身用例）；
顺序不变量 `if late:` → `if False and late:` → **4 条红**（真 export 互换 + eleventh 三条）；
重复认领 `if twice:` → `if False and twice:` → **2 条红**（直接 API + CLI）；
`output_node_ids` 只取第一项输出 → **3 条红**（dict 两条 + tuple 一条）。

全量 **329 passed in 50.66s**。端到端 `output/twelfth-check`：build exit 0，nodes=128（算子 75 / 权重 18 /
输入 1 / 模块 34）、edges=101、degraded=2、fused=0、orphan=0、shape_broken=0、shape_unchecked=0、
`real_execution={ok:True}`——与第八至十一轮逐项一致，三道新防线没误伤 fixture。
行数（python `splitlines` 口径）：`OVER200=[]`，最大 `fx_signature` 193 / `fx_nodes` 187 / `fx_edges` 184 /
`build_trace` 181 / `fx_contract` 175 / `report` 165 / `fx_trace` 160 / `cli` 157。

**这一轮的教训**：「与权威核对」这句话里，权威是谁要问到底。expected 从调用方传进来的对象重生，
那它就不是第三方，只是同一份数据的第二个副本。能拿到的独立约束只有两种：别的实体（模块）、
以及权威自己公开写死的结构不变量（顺序）。找不到第三种时，就把边界如实写出来，不要假装关上了。
## Review Focus

1. **融合漏检**：`flash=False` 若没生效，图上只会出现一个 SDPA 算子。
   现在不但测试钉死四个算子同时存在，还加了 `FUSED_OPS` 表：真的遇到融合算子时
   **标 degraded + stderr 警告**，绝不安静通过。
2. **假形状**：`shape_in/shape_out` 来自导出图**再跑一遍**时观察到的真实张量（`fx_observe`），
   只有 `get_attr`/权重才回落到 `node.meta["val"]`；没有写死的列表。
3. **静默降级**：没有 torch 时退出码 4；export 追不动或导出图不能再真实执行时退出码 5；两者都不写 trace。`--ops` 里 degraded 一定带原因。
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
| observe 失败也照常写 trace（标 degraded） | 直接 `TraceUnsupported` / exit 5，不写 trace | 「降级写」和「真实追踪」在一个文件里没法自证；假形状比没有形状更坏 |
| `inputs` 含权重位置 | 只放数据入参，`shape_in = inputs[0]` | 否则 embedding 的输入是权重 `(64,32)`，形状链从第一跳就假 |
| 边可以接模块节点 | 边两端必须都是算子，且禁自环 | 模块不是算子，接上只会制造「看起来有形状链」的错觉 |
| `cli.py` 堆下所有打印 | 拆出 `papertrace/report.py` | 275 行违反 ≤200 行；参数/退出码与排版混在一起难审 |
| 只有顶层参数查 param | 递归到任意容器深度 | `cat([w, x])` 里的权重在 list 里，只看顶层就把权重当输入 |
| 权重只按「是不是 param 叶子」认 | 另加 `param_derived`：只由权重算出的中间量同样算权重 | `self.w[0]` 是 `select` 算子节点，不是 param 叶子，只看叶子就把它当数据输入 |
| placeholder 认参数全名 | 只认 mangled 名（`p_`/`b_`） | 全名 `x` 会和形参 `x` 撞车，真输入被吞成权重且会静默 exit 0 |
| `(?)` 表示「没有输入」 | `-` 表示确实没有数据入参，`(?)` 只给缺字段的老格式 | 两者语义不同，混在一起就看不出是「没有」还是「没看到」 |

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
| `8b710ee` | 第三轮前的文档与账本 |
| `f58b123` | 第三轮必修：observe 失败即 exit 5、异常翻成 2/5、inputs 只含数据、边两端必须算子且禁自环 |
| `fc1ca48` | `report.py` 拆出、第三轮文档与账本 |
| `2de86a2` | 第四轮必修：容器里的权重不当输入、畸形 trace 根 exit 2、`-`/`(?)` 三态、`eval()` 异常翻译 |
| `6a87f7d` | 第四轮文档与账本（README/计划/执行账本同步） |
| `fce6b2d` | 第五轮必修：mangled 名认权重、权重派生量不算输入、id/端点类型守卫 |
| `5fd9b7c` | 第六轮必修：input_specs 定 kind/层级、常量不算输入、参数-only 子模块的 parent；三个模块拆分 |
| `b48f361` | 常量独立成 `kind=const`（节点/schema/摘要/`--ops` 端到端） |
| `f9e3546` | 第七轮必修：没有 `input_specs` 就 fail-closed、`*_like` 不算数据输入、spec 完备性与数量校验 |
| `94c2b28` | 第七轮文档与账本（README/计划/执行账本同步） |
| `66f2efd` | 第八轮必修：契约错误统一 exit 2、守卫改判 placeholder 覆盖、spec 顺序断言与缺/多聚合、orphan 认常量源、docstring 与行数口径 |
| `feb6fc8` | 第八轮文档：钉住提交哈希、记录端到端复核 |
| `b8d39d2` | 第九轮必修：orphan 改判双向、未知/重叠/幽灵 kind 一律拒绝、runtime_meta 拆出 fx_runtime、行数口径改 python splitlines |
| `d4c84a2` | 第九轮文档：钉住提交哈希与行数口径 |
| `500c692` | 第十轮自查：反向认领判据（模块地面真相）、常量不许顶替参数、spec↔模块契约统一 exit 2、拆出 fx_contract |
| `7dc55f2` | 第十轮文档：记录自查、钉住提交哈希 |
| `0e9e608` | 第十一轮必修：plan 与导出器逐项核对（`check_plan_source`）、`CUSTOM_OBJ→const`/`TOKEN` 拒绝、orphan 认图输出、const 不许顶替缓冲、`build_op_nodes` 的 `exported` 入口断言、`no_grad` 子模块图 exit 5、16 模型 zoo 回归、弱断言加牙 |
| `e10d9d3` | 第十一轮文档：README 六处同步、计划记录、账本、行数重测 |
| `df7a8eb` | 钉住第十一轮文档提交哈希（自引用哈希不能 amend，改用后续小提交） |
| `d7d16f0` | 补全第十一轮提交链 |
| `9ec97b3` | 第十二轮必修：`require_real_export` 类型守卫、顺序不变量、恰好认领一次、zoo 集合相等 + op 计数钉死、CLI 级 TOKEN/no_grad/重复认领/mutation 用例、dict 输出用例 |
| `967d664` | 第十二轮文档：README 三道防线与残余边界、退出码表、计划记录、行数重测 |
