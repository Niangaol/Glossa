# PaperTrace M1a 实施计划：真实算子追踪

> 前置：框架切片已完成（93 passed / 2 skipped，HEAD 1f26bf8）。
> 目标：让 `trace.json` 里出现**真的**算子节点与形状链，且能证明 nanoGPT 的 Attention
> 是 4 个独立算子（matmul / mul / masked_fill / softmax），不是 1 个融合 SDPA。
> 铁律：所有节点 `source="runtime"`，禁止示例节点、禁止 mock 形状。

**状态（2026-11-14）**：Task 7–11 全部落地，**184 passed**，第三、四、五轮评审的必修项都已修完
（第三轮 C1/I1/I2/I3 + M2/M3/M5；第四轮 I-1/I-2 + M-1/M-3/M-4；第五轮 C1/I1/I2），
提交链 `73bb224` → `bc472d6` → `9fbb56b` → `d722f13` → `262eb69` → `58dc5c7` → `82228eb` → `cca2a1a` → `8b710ee` → `f58b123` → `fc1ca48` → `2de86a2` → `6a87f7d`。
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
| （本轮） | 第五轮必修：mangled 名认权重、权重派生量不算输入、id/端点类型守卫 |
