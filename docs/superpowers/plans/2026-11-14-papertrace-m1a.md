# PaperTrace M1a 实施计划：真实算子追踪

> 前置：框架切片已完成（93 passed / 2 skipped，HEAD 1f26bf8）。
> 目标：让 `trace.json` 里出现**真的**算子节点与形状链，且能证明 nanoGPT 的 Attention
> 是 4 个独立算子（matmul / mul / masked_fill / softmax），不是 1 个融合 SDPA。
> 铁律：所有节点 `source="runtime"`，禁止示例节点、禁止 mock 形状。

**状态（2026-11-14）**：Task 7–11 全部落地，**448 passed**，第三至第十七轮评审的必修项都已修完。
**第十七轮结论：Critical 0，M1a 必修项为空，可以收尾、建议进入 M1b。**
第十三轮评审结论：**可以进入 M1b，必修项无**；唯一的条件项（target 互换）我选择**修**而不是只写文档——
补了第七道关：`placeholder_args` 取到真实张量后与 `node.meta["val"]` 的形状核对（两个独立字段，真核对）。
第十四轮评审推翻了第七道关留下的那句「同形状互换不可观测」：**同形状、跨模块**互换 target 会把
`parent_id` 写反（可见的错误数据，CLI 仍 exit 0）。补第八道关 `fx_names.check_name_target`：
placeholder 的**名字**在图上、`target` 在 spec 里，是两个独立字段，对不上就拒绝。
名字核对与模块无关，所以**同模块**的同形状互换也一并被拒。
第十六轮评审（**Critical 0，可以交付、建议进入 M1b**）指出第八道关**自己**会 fail-open：
认不出前缀就 `continue`（torch 一改命名规则这道关就无声失效）、`obj_` 两种写法都接受却没有
真实 CUSTOM_OBJ 导出背书。两处都改成 **fail-closed**：认不出前缀/没给 target → exit 2；
`CUSTOM_OBJ` 与 `TOKEN` 一样先拒绝，M1b 补真实 ScriptObject 导出再放开。
残余边界现在写全三条（压平撞名 / 这一关单独调不是完整权威 / CUSTOM_OBJ 属 M1b 验证项），
不留「已封死」的错觉。
第十五轮评审指出第八道关**自己**有映射缺口：torch 生成名字时会剥开头的 `self_`/`L__self___`、
sanitize 非字母数字、再 `lower()`，而我只按 `target.replace(".", "_")` 反推 —— 既**误杀**四个合法模型
（`self_attn`+`attn`、`a-b`+`a_b`、`W`+`w`、`x`+`self_x` 全部 exit 2），又**漏检** `self_a`/`self_b`
（索引查不到 → 静默跳过 → 互换后 `parent_id` 写反而 CLI exit 0）。改成**正向核对**：按 torch 的规则
把 spec 的 target 映射成期望的 base 再比，按构造不会误杀；六个真实模型与 torch **实际生成的名字**
逐个交叉核对，`parent_id` 精确断言。
第十一轮把 kind 的最终权威交给 `torch.export` 自己（plan 逐项核对），并堵住了「两边互换」这个
前四轮关卡全过却 kind 相反的洞；另外新增一条能力边界（`forward` 内 `no_grad` → exit 5）。
第十二轮发现「与导出器核对」的 expected 也是从调用方传进来的对象重生的（同源），补了三道防线：
类型守卫（拒 `SimpleNamespace` 替身）、torch 自己写死的**顺序不变量**（权重必须排在数据输入之前）、
**恰好认领一次**（`Counter` 而不是 `set`）；并如实写下残余边界（就地篡改真产物不在威胁模型内）。
（第三轮 C1/I1/I2/I3 + M2/M3/M5；第四轮 I-1/I-2 + M-1/M-3/M-4；第五轮 C1/I1/I2；
第六轮 C1/I2/I3；第七轮 C1 fail-closed + I1 `*_like` + I2 spec 契约校验；
第八轮 I-1 退出码统一 + I-2 守卫改判覆盖 + M-1…M-5；第九轮 I-1 orphan 双向语义 + I-2 未知/错位 kind fail-closed + M-1…M-3；
第十轮（自查）反向认领 + 常量不许顶替参数；第十一轮 C1 导出器逐项核对 + I-1 `CUSTOM_OBJ`/`TOKEN` + I-2 orphan 输出边界 + I-3 弱断言 + M-1…M-5；
第十二轮 I-1 同源 expected → 类型守卫 + 顺序不变量 + 恰好认领一次、I-3 补 CLI 级退出码用例、Minor zoo 集合相等/dict 输出/mutation CLI；
第十三轮 I-1 target 互换 → 形状核对（第七道关）、M-1 pytree 措辞改准、M-3 TOKEN 归类说明、M-5 `cond`/`while_loop` 点名、M-6 补 target 互换回归；
第十四轮 I-1 同形状跨模块互换 → 名字↔target 核对（第八道关）、M-1 「不可观测」用例按事实改写、M-3 拆出 `fx_kinds`、M-5 提交链与端到端路径补齐；
第十五轮 C1 误杀 + C2 漏检 → 第八道关改**正向核对**（复刻 torch 的 `_strip_name`+`lower`）、I-1 文档纠正、I-2 六个真实命名模型 + 与导出器实际名字交叉核对、M-1 补 `obj_` 前缀、M-3 sanitize/lower、M-4 提交链补齐；
第十六轮 I-1 未知前缀 fail-open → 拒绝、I-2 `CUSTOM_OBJ` 无真实导出背书 → 先拒绝（`obj_` 前缀一并删掉）、M-1 后缀伪造钉成「单关接受 + 端到端拒绝」两层、M-2 报错加观察到的 base、M-3 `checked` 改精确相等 + PARENTS 独立推导 + 补四类缺口、M-4 文档漂移），
提交链 `73bb224` → `bc472d6` → `9fbb56b` → `d722f13` → `262eb69` → `58dc5c7` → `82228eb` → `cca2a1a` → `8b710ee` → `f58b123` → `fc1ca48` → `2de86a2` → `6a87f7d` → `fce6b2d` → `5fd9b7c` → `b48f361` → `f9e3546` → `94c2b28` → `66f2efd` → `feb6fc8` → `b8d39d2` → `d4c84a2` → `500c692` → `7dc55f2` → `0e9e608` → `e10d9d3` → `df7a8eb` → `d7d16f0` → `9ec97b3` → `967d664` → `c6b6bec` → `b9ea76a` → `a7311fc` → `fb00b9b` → `870d614` → `aeea7e6` → `0ca6837` → `81581a1` → `c2608ea` → `e398d9f` → `e8757d2` → `af02aef` → `d83d2e5` → `ddeb9b9` → `db500fe` → `c1bb126`。
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
### 第十三轮评审（基线 9ec97b3，328 passed / HEAD 329）：结论「可以进 M1b」，条件项我选择修

评审快照 `output/review12/9ec97b3`（117 文件），探针未改源码。**Critical 0、必修项 0**，
总评「可以进入 M1b（论文侧对齐）」。唯一条件项：如果把「六道关」当成**防就地篡改**的完整性保证，
就必须补 I-1；否则 README 要写明「target 互换也能过」。**我选修**——因为不同形状的 target 互换
会在 trace 里留下**可见的错误数据**（权重形状被记反、`shape_broken` 还是 0），这正是本项目
一贯拒绝的那类静默错误，只写文档等于把它留给读者。

| 项 | 评审证据 | 处理 |
| --- | --- | --- |
| I-1 | `output/review12/probe13x.py`：`TwoParams`（a=(2,4)、b=(1,4)）在**真** `ExportedProgram` 上互换两个参数的 `target` → `check_contract` OK、`placeholder_args` OK、`build_op_nodes(exported=)` OK，trace 里 `root.p_a` 形状 `[1,4]`、`root.p_b` `[2,4]`，`shape_broken=0`。`ParamBuf`（参数↔缓冲）、`TwoConsts`（常量↔常量）同样全过；`ConstParam`（常量 target 改成真实参数）被 `Counter` 抓住。根因：`fx_contract.py:87-98` 只收集 target **集合**查重复，不校验 `name → target` 的对应；`fx_signature.py:158-160` 用 `params | buffers` 并集取张量；`check_plan_table` 只比四张表，target 互换后四张表**完全不变** | 新增**第七道关** `fx_shapes.check_value_shape(node, value, target)`：`placeholder_args` 排好 args 后，逐个与 `node.meta["val"].shape` 比。地面真相是导出器在图上做 fake 传播的结果，与 `input_specs` 的 target 映射是**两个独立字段**——所以这是真核对，不是同源比对。不同形状互换一律 `BuildError`/exit 2，消息点名「取到的张量是 (1,4)，但导出图里这个节点是 (2,4)」。非张量（int/bool/None/ScriptObject）与动态形状（SymInt）**不比**，不猜 |
| M-1 | pytree 不摊平是**保守边界**而非技术必需：`torch/export/_trace.py:1986` 用的就是 `pytree.tree_flatten((params_buffers_args, kwargs))`，与 `exported.call_spec.in_spec` 对照即可不猜顺序地支持。另评审说缺 dict 输入 CLI 用例 | README 措辞改准：「这是范围控制，不是技术上必须猜；M1b 用导出器同一个 `tree_flatten` + `call_spec.in_spec` 对照支持」。**CLI 用例其实已有**（`b9ea76a` 的 `test_cli_exits_5_when_pytree_inputs_are_not_flattened`，评审读的是更早的代码快照） |
| M-2 | `build_op_nodes(exported=None)` 仍是未受检的公开签名，建议拆成必填公开入口 + 私有未检入口 | **留到 M1b**，理由写死：拆分会让 `fx_nodes` 到 199 行、贴着 ≤200 行约束，且要改 10 处测试调用；评审明确「保持现状不算 M1a bug」。现状是 README 已标明内部 API、`fx_trace` 自己传 `exported=`，未检路径只有直接 API 调用方能走 |
| M-3 | TOKEN→2 与 no_grad→5 自洽，但用户可能把 exit 2 误解成「输入写错」 | README 退出码表后补一段：分界线是「**spec 合不合法**」而不是「用户有没有写错」——TOKEN 是已知但不支持的 InputKind（契约策略），no_grad/cond 是 spec 合法但图里有非张量节点（能力边界） |
| M-4 | 有入边没人用的死算子不计入 orphan | 不改（已写死的取舍）。M1b 若要对账，另加 `dead_op`（从 graph output 反向可达），**不要改 orphan 语义** |
| M-5 | `torch.cond`/`torch.while_loop` 也走 exit 5，但 README 没点名；评审实测它们的 spec 顺序正常、`check_contract` 通过，拒绝发生在更早的 `get_attr` 检查（`true_graph_0`/`while_loop_body_0`） | README 的 `get_attr`/`call_module` 段与退出码表都点名这两个高阶控制流，并写明**不是顺序不变量误杀** |
| M-6 | 缺 target 互换回归；zoo 18 个模型期望值评审用原始 `input_specs` 独立重算**全部一致** | 新增 `tests/test_thirteenth_review.py`（16 条）：三种互换（参数↔参数、参数↔缓冲、常量↔常量）各一条，**先断言前面几关全过**再断言形状核对拒绝；三条反向对照（真 spec 取到模块里那一个张量 / 常量取自 `exported.constants`）；**同形状互换不可观测**钉成显式用例；int 形参不被误杀；`check_value_shape` 五种边界参数化；CLI 级篡改 `torch.export.export` 返回值 → exit 2、不写 trace、无 Traceback，外加未篡改的同仓库 exit 0 对照 |

**为什么这道关不是同源比对**（与前几轮的关键区别）：`check_plan_source`/`check_plan_table` 的
expected 都从**调用方传进来的** exported 重生，篡改 spec 时两边一起错。而 `node.meta["val"]`
是导出器在**图上**做 fake 传播留下的形状，`input_specs.target` 是**另一个字段**：改后者不会改前者。
评审也确认「从原始 graph_signature 独立重算也只是把映射复制一遍」——所以正确的修法不是再造一个
看起来独立的 expected，而是找一个**真的**独立产物。形状就是。

**诚实边界（写进 README 与用例）**：同形状的 target 互换抓不到，但它在 trace 里也没有任何可见差异，
所以不假装封死；就地篡改真产物仍属「篡改权威本身」，与 monkeypatch 全部 `input_plan` 同一类。

变异探针（两组，均已还原）：`if want != got:` → `if False and …` → **5 failed**（三种互换 + 单元 + CLI）；
去掉 `if want is None or got is None: return` 守卫 → **4 failed**（int 形参 + 三种非张量边界，
`TypeError` at fx_shapes.py:90）——证明守卫不是死代码。还原后 16 passed。

全量 **345 passed in 51.80s**（329 + 16）。端到端（当时复跑写入 `output/twelfth-check`；
第十四轮起改用 `output/fourteenth-check`，见下节）：EXIT 0、nodes=128
（module 34/param 18/input 1/op 75）、edges=101、degraded 2、fused 0、orphan 0、shape_broken 0、
shape_unchecked 0、`real_execution={ok:true,reason:null}`——与第八至十二轮**逐项一致**，
第七道关没有误伤 fixture。行数（pathlib splitlines 口径）**OVER200=[]**：fx_signature **198**
（只剩 2 行余量，M1b 动它之前先拆）、fx_nodes 187、fx_edges 184、fx_contract 175、fx_shapes **98**、
fx_trace 160、cli 157；新测试 `tests/test_thirteenth_review.py` 16 条。

**教训**：一道关卡的价值取决于它的地面真相**独立性**，不取决于它看起来多严格。前六关里有三关
（③⑤⑥）的地面真相都来自同一个可被篡改的对象；第七关之所以有牙，是因为它比的是导出器留在
**图节点上**的另一份产物。评审那句「不要再造一个看起来独立的 expected」是这一轮最有用的一句话。

### 第十四轮评审（基线 fb00b9b，345 passed）：「同形状互换不可观测」是错的

评审结论 **需要修**，Critical 0。快照 `output/review13/fb00b9b`，345 passed in 52.68s，探针未改源码。

**I-1（必修）同形状、跨模块的 target 互换，七道关全过、CLI exit 0，`parent_id` 写反。**
评审的反例（`output/review13/repos/parent_swap/model.py`）：`Sub.w` 与根 `M.a` 都是 `(2,4)`，
`forward = self.sub(x) + self.a`。互换两个 spec 的 target 后：

```text
NODE root/@000 root.p_a     param parent= root/sub   ← 正确应是 root
NODE root/@001 root.p_sub_w param parent= root       ← 正确应是 root/sub
degraded=0 fused=0 orphan=0 shape_broken=0 shape_unchecked=0   validate_trace PASS   EXIT 0
```

根因链：`fx_shapes.check_value_shape` 只比形状（同形状当然过）；`fx_nodes.py:142` 的
`parent_key = spec_owner.get(node.name, parent_key)` 里 `spec_owner` 来自**被改过的 target**；
`fx_contract` 只查 target 集合与恰好一次（互换后集合不变）；`validate_trace` 只查 parent 是否存在
（`root/sub` 确实存在）。**README 那句「同形状互换在 trace 里没有任何可见差异」与实测相反。**

我自己复现（`output/probes/probe16.py`，只读源码）确认成立。两个踩坑值得记：
① 第一版伪造一个 `ex` 再调 `trace_module(m, ONE)`，`parent_id` 竟然正确——因为 **`trace_module`
内部自己重新 export**，伪造的是另一个对象；必须 monkeypatch `torch.export.export` 返回被改过的产物。
② `trace_module` 返回的顶层键是 `['edges','nodes','runtime']`（没有 `meta`），而 CLI 写出的
`trace.json` 是 `meta.runtime`——两个口径不同，探针里 `t['meta']` 报 `KeyError: 'meta'` 是探针 bug。

**修法：第八道关 `papertrace/parse_code/fx_names.py::check_name_target`。**
地面真相是 placeholder 的**名字**：torch 按 `前缀 + target.replace(".", "_")` 生成（重名再加 `_N`），
名字在**图上**、target 在 **spec 里**，改后者不改前者——与第七关同一个道理，找另一份产物，
而不是把同一份映射再算一遍。前缀表 `PARAMETER→p_`、`BUFFER→b_`、`CONSTANT_TENSOR/CUSTOM_OBJ→c_`。

落地前先做**命名普查**（11 个模型：nested/tied/plist/pdict/plainlist/nonpersist/constattr/
shadowed/ambiguous/deep/parentswap）：**零 mismatch**，全部满足 `name == 前缀 + 压平 target`。
普查同时量出三个必须处理的细节：

| 细节 | 实测 | 处理 |
| --- | --- | --- |
| 压平撞名 | `Ambiguous`（`self.a_b` + `self.a.b`）→ `p_a_b` 反推候选 **2 个** | 反推不唯一就**跳过不猜**（评审明确要求） |
| 重名后缀 | `p_a_b_1` 的 base `a_b_1` **不在索引里**，剥掉 `_1` 才查到 `a_b`（仍 2 个候选） | 查不到才剥 `_N`，剥完仍不唯一就跳过 |
| 数字尾巴 | `p_ws_0`（target `ws.0`）的 base `ws_0` **本来就在索引里** | **先按全名查、查不到才剥后缀**；剥错了会把 `ws.0` 当成 `ws` 而静默跳过 |
| 非持久缓冲 | `b_tmp` 候选数 2，但两个都是**同一个 target 字符串** `tmp`（同时在 `named_buffers` 与 `exported.constants`） | 索引用 **set of distinct targets**，不能数 list 长度 |

**比评审要求更强的一点**：名字反推与模块无关，所以**同模块**的同形状互换也被拒。
据此把第十三轮那条「不可观测」用例按事实改写：
`test_same_shape_target_swap_is_not_observable` → **`test_same_shape_target_swap_is_refused_by_the_name_gate`**。
评审 M-1 要求「改成 trace 级、限定同模块」，实测结果是它根本过不了新关，所以不需要那条对照；
真正需要 trace 级证据的是**残余洞**：`test_ambiguous_swap_really_does_change_parent_id` 构建整份
trace 比较 param 节点的 `parent_id`，`before != after` 且 `shape_broken == 0`——把「跳过不猜」的代价
钉成可见事实，不假装封死。

**M-3 拆分（部分采纳）**：`fx_signature` 198 行只剩 2 行余量，放不下新关。把 `KIND_MAP`/
`REFUSED_KINDS`/`spec_kind`（原 `_spec_kind`）搬进新文件 **`fx_kinds.py`**（54 行，不 import torch），
`fx_signature` 降到 **161 行**。评审建议的 `fx_args.py`（把 `placeholder_args` 也搬走）**留到 M1b**：
本轮只需腾出空间，搬动解析逻辑会牵动 10 处测试 import，风险大于收益。
调用顺序刻意安排成**形状关在前、名字关在后**：不同形状互换仍先命中形状关，保留带 `(1,4)/(2,4)`
数字的原文案，第十三轮 16 条用例一条不破。

**踩坑**：删 `KIND_MAP` 那一段时把中间的 `_spec_name` 一起删了 →
`NameError: name '_spec_name' is not defined` at `papertrace/parse_code/fx_signature.py:36`，20 failed。
补回后正常。教训：按「从 A 到 B」整段删除时，先确认 A、B 之间没有别的东西。

**新回归 `tests/test_fourteenth_review.py`（29 条，423 行）**：跨模块互换参数化（root-vs-sub /
sub-vs-sub，先显式跑 `check_contract`+`check_plan_source`+`check_plan_table`+`check_value_shape`
证明前几关全过，再断言拒绝）；`test_the_swap_really_would_write_the_wrong_parent_id` 用
`module_of_target` 复算 real `{'p_a':'','p_sub_w':'sub'}` vs forged `{'p_a':'sub','p_sub_w':''}`；
**CLI 级**篡改 `torch.export.export` → exit 2 + stderr 含「名字」「对不上」+ 无 Traceback + 不写 trace，
外加同仓库不篡改 exit 0 对照；`test_parameter_list_target_swap_is_refused` 钉死「先全名后剥后缀」；
歧义两条（合法不拒 + 互换也不猜）；11 个合法模型正向对照参数化；`check_name_target` 单元边界
（唯一 mismatch 拒绝、匹配接受、ambiguous/ambiguous-dedup/numeric-tail/user-input/unknown-target
五种不猜、非持久缓冲同一 target 不算歧义）。

变异探针（三组，均已还原，`restored=True` 逐个核过）：

| 变异 | 结果 |
| --- | --- |
| A 关掉 `check_name_target(...)` 调用 | **6 failed**（跨模块两条 + CLI + 同模块 + PList + 第十三轮改写那条） |
| B 唯一性判据 `if not candidates or len(candidates) != 1:` → `if True:` | **7 failed**（上面 6 条 + 单元 mismatch） |
| C 先剥数字后缀再查全名 | **1 failed**，正是 `test_parameter_list_target_swap_is_refused` |

C 只红一条是**预期的**：那条用例就是为钉这个顺序写的。还原后 46 passed。

全量 **375 passed in 51.62s**（345 + 29 + 1）。端到端 `output/fourteenth-check`：EXIT 0、nodes=128
（module 34/param 18/input 1/op 75）、edges=101、degraded 2、fused 0、orphan 0、shape_broken 0、
shape_unchecked 0、`real_execution={ok:true,reason:null}`、123655 bytes——与第八至十三轮**逐项一致**，
第八道关没有误伤 fixture。行数（pathlib splitlines 口径）**OVER200=[]**：fx_nodes 187、fx_edges 184、
build_trace 181、fx_contract 175、report 165、**fx_signature 161**、fx_trace 160、cli 157、fx_graph 148、
schema_structure 129、schema_validate 100、fx_shapes 98、fx_inputs 98、**fx_names 79**、**fx_kinds 54**。

**M-2（SymInt 静默跳过）留 M1b**：`check_value_shape` 对 `None`/非整数维直接 return，动态形状会让
第七关静默失效。评审建议返回 `checked/skipped_reason` 并在 `meta.runtime.counts` 记独立的
`shape_gate_skipped`（不复用边级 `shape_unchecked`）。M1a 的 fixture 与 zoo 全是静态形状，
现在加计数字段要动 schema 与 20 处断言；M1b 做 shape 传播时本来就要引入符号维度，那时一起加。
**M-4（`build_op_nodes(exported=None)`）留 M1b**：评审明确「不算本轮阻塞项」，拆公开
`build_from_export` + 私有 `_build_op_nodes` 会让 fx_nodes 贴近 200 行约束并牵动 10 处测试调用。
**M-5 已修**：提交链补 `aeea7e6`，端到端路径写明各轮实际写入的目录。

**M1b 的范围纠正（评审指出我给用户讲错了）**：按
`docs/superpowers/plans/2026-11-14-papertrace-engineering-plan.md:424-447`，**M1b = Task 6
「符号表与 shape 传播」**：先 `papertrace/symbols/code_table.py` + `tests/test_symbols_nanogpt.py`
（`n_embd→D`、`n_head→H`、`head_dim→Dh`、`block_size→T`，每个符号带 `defined_at`，纯 Python 不依赖
torch），再 `shape_prop.py`（推不出的边置 `shape_consistent=False`，**不得填 None 冒充成功**），
最后 `mapping.py`；符号名冻结 `B,T,D,H,Dh`（`Dh=D/H`）。论文 PDF/LaTeX 解析属 **M2.5（Task 9）**、
双向检索对齐属 **M3（Task 10）**，都不该在 M1b 之前做。我在给用户的阶段报告里把顺序讲反了，已纠正。

**教训**：「不可观测」是一个**需要证据的断言**，不是「我这关没抓到」的同义词。第十三轮我只比了
`args[0] is module.b` 就写下「trace 里没有任何可见差异」，而 `parent_id` 恰恰是用 target 定位的——
没构建整份 trace 就宣称无差异，等于把错误行为钉成了规格。评审 M-1 要求的「trace 级断言」是对的，
只是实测结果比它预期的更强：新关连同模块互换一起拒了。

### 第十五轮评审（基线 0ca6837，375 passed）：第八道关自己的映射缺口

评审结论「需要修」，两条 Critical 都在**我上一轮新写的那道关**里。它说得对，而且比我想的更严重：
不是「边界没写清」，是**既误杀又漏检**。

**C1 误杀合法模型**（`output/review14/repos/self_attn_clash/`）：`self_attn=Linear(4,4)` +
`attn=Linear(4,4)`，真实 spec 是 `p_attn_weight→self_attn.weight`、`p_attn_weight_1→attn.weight`。
我的反推索引键是 `self_attn_weight`，而图上观察到的 base 是 `attn_weight` → 索引里唯一指向
`attn.weight` → 与 spec 不符 → **CLI exit 2、不写 trace**。同族还有 `a-b`+`a_b`、`W`+`w`、`x`+`self_x`。

**C2 漏检 + 静默写错 parent**（`output/review14/repos/self_ab/`）：`self_a`/`self_b` 各一个同形状
`weight`，真实 spec `p_a_weight→self_a.weight`、`p_b_weight→self_b.weight`。base `a_weight` 在索引里
**查不到**（键是 `self_a_weight`）→ `candidates is None` → 跳过不猜。互换 target 后 `trace_module`
成功、CLI **exit 0**，`root.p_a_weight.parent_id` 变成 `root/self_b`、`root.p_b_weight` 变成 `root/self_a`，
counts 全 0。**这不是已文档化的压平歧义**（`a_weight`/`b_weight` 本来唯一），是映射缺失。

**根因：我把 torch 的命名规则近似成了 `target.replace(".", "_")`。** 读
`pydeps/torch/_export/utils.py` 的真实实现：

| 位置 | 规则 |
| --- | --- |
| `:58-65` | `placeholder_prefixes`：`USER_INPUT:""`、`PARAMETER:"p_"`、`BUFFER:"b_"`、`CONSTANT_TENSOR:"c_"`、**`CUSTOM_OBJ:"obj_"`**、`TOKEN:"token"` |
| `:1113-1119` | `_strip_name(x)`：剥**开头**的 `L__self___`（10 字符）`elif` `self_`（5 字符），再 `re.sub(r"[^a-zA-Z0-9]", "_", x)`。**是函数内闭包，import 不到，只能复刻** |
| `:1168-1169` | `base_name = _strip_name(spec.target).lower()`，再 sanitize 一次（冗余） |
| `:1171-1178` | `_rename_without_collisions(..., prefix + base_name, is_placeholder=True)` → 撞名加 `_N` |
| `:1206-1210` | `spec.arg.name = name_map[spec.arg.name]`（名字回写 spec，所以两者确实同步） |
| `:1211-1215` | **CUSTOM_OBJ 特例**：`spec.target = name_map[spec.target][4:]` → 命名 pass 之后 target **就等于 `name[4:]`**，不再是原始属性路径 |

六个模型实测（`output/probes/probe17d.py` → `p17.txt`，修前）：

| 模型 | torch 真实名字 → target | 修前 |
| --- | --- | --- |
| `self_attn`+`attn` | `p_attn_weight→self_attn.weight`、`p_attn_weight_1→attn.weight` | **REFUSES**（C1） |
| `self_a`/`self_b` | `p_a_weight→self_a.weight`、`p_b_weight→self_b.weight` | pass（其实是**跳过** → C2） |
| `a-b`+`a_b` | `p_a_b_weight→a-b.weight`、`p_a_b_weight_1→a_b.weight` | **REFUSES** |
| `W`+`w` | `p_w→W`、`p_w_1→w` | **REFUSES**（缺 `lower()`） |
| 嵌套 `sub.self_attn` | `p_sub_self_attn_weight→sub.self_attn.weight` | pass（**证实 `self_` 只剥开头**） |
| `x`+`self_x` | `p_x→x`、`p_x_1→self_x` | **REFUSES** |

**修法：反推索引 → 正向核对。** 新 `fx_names.strip_name(target)` 复刻 torch 的规则，
`_matches(base, expected)` 判「base == expected，或 base == expected + `_数字`」
（**先比全名**：`ws.0` 的 base 本来就是 `ws_0`，先剥后缀会漏检）。对每个非 input 的 placeholder：
剥前缀得 base，`expected = strip_name(spec.target)`，不匹配就 BuildError。
**不再需要索引，也不再需要 `named`/`constants` 参数** → 签名从
`check_name_target(placeholders, plan, named, constants)` 变成 `check_name_target(placeholders, plan)`。

为什么正向严格更好（不只是「换个写法」）：

- **反推是有损的**。`_strip_name` 不是单射：参数真名叫 `self_` 时 base 是空串，反推索引会把它
  映射到空键、与 target `self_` 不符 → **误杀**。正向按构造无误杀（`strip_name("self_") == ""`）。
- **歧义不需要显式检测**。压平撞名时两个 target 正向映射到同一个 base，核对自然通过 ——
  那正是已文档化的残余洞，不必再维护「唯一候选」这套逻辑（它恰恰是 C2 的来源）。
- **代码更短**：`_flat_index` 整个删掉，fx_names 79 → 106 行（多出来的是复刻规则与 docstring）。

修后六模型全部建得出来，`parent_id` 精确正确（`output/probes/probe18.py` 实测，期望值写死在
`tests/test_fifteenth_review.py::PARENTS`，**不是从被测代码反推**）：
`SelfAttnClash` 四个权重分别挂 `root/self_attn`×2、`root/attn`×2；`SelfAB` 挂 `root/self_a`/`root/self_b`；
`Hyphen` 挂 `root/a-b`/`root/a_b`；`NestedSelf` 挂 `root/sub.self_attn`/`root/sub.attn`
（嵌套模块 id 保留点分路径作为一个 module 节点，实测**无悬挂 parent**）。

**M-1（`obj_` 前缀）已补**：`PREFIXES` 加 `obj_`；CUSTOM_OBJ 的 target 既可能等于 base 本身
（命名 pass 改写过）也可能仍是原始路径（`:1211` 的 `if spec.target in name_map` 不成立时），两种都接受。
**诚实说明**：试着用 `@torch.jit.script` 的 ScriptObject 造真 CUSTOM_OBJ 导出，torch 2.15 把
`self.obj.add(x)` **常量折叠**成了 `x + 3`，spec 里只剩 `x` 一个 USER_INPUT，没能产生 CUSTOM_OBJ。
所以 `obj_` 分支是**按源码实现 + 单元用例钉死**（`custom-obj-rewritten`/`custom-obj-raw`/`custom-obj` 拒绝），
没有真实导出背书，这一点不假装。

**I-1（文档过度声称）已纠正**：README 删掉「11 个真实模型普查零 mismatch」这种以偏概全的话，
改成写明 C1/C2 两个方向的反例与修法；「真正剩下的洞只有压平撞名」这句**修后仍然成立**，
但现在它是有证据的：残余洞多了第二个实例（`self_attn.weight` ↔ `attn.weight`），
`test_flattening_clash_swap_is_still_not_observable_by_name` 构建整份 trace 证明 `parent_id` 写反。
plan 提交链补 `c2608ea`（M-4）。

**I-2（正向模型自选、断言偏弱）已修**：

- 新增 `tests/test_fifteenth_review.py`（19 条）：六个真实命名模型 × 2（合法 build + `parent_id` 精确断言；
  `strip_name` 与 torch **实际生成的名字**逐个交叉核对，后缀规则在测试里独立写出来、不调被测的 `_matches`）；
  `self_a`/`self_b` 互换的直接 API 拒绝（先跑 `_older_gates` 证明前几关全过）、owner 复算证明错误可见、
  **CLI 级 exit 2**（篡改 `torch.export.export` 返回值）+ 不写 trace + 无 Traceback；
  三个合法命名仓库的 **CLI 级 exit 0** 并从写出的 `trace.json` 里核 `parent_id`；压平撞名的 trace 级洞证据。
- `test_ambiguous_flattening_swap_is_not_guessed` 从 `len(args)==3` 改成
  `args[0] is module.a.b and args[1] is module.a_b` —— 直接证明洞是可观测的，不是「没报错就算过」。
- `test_fourteenth_review.py` 的单元边界重写：`strip_name` 九条（含 `self_`→空串、嵌套不剥、`L__self___`）、
  一致对 16 条（含 `obj_` 两种写法、`p_`+`self_`、大写、连字符、重名后缀）、不一致对 5 条。29 → 53 条。

**M-3（不 lower/不 sanitize）**：随 `strip_name` 一起修好。**M-2（SymInt 静默跳过）仍留 M1b**，
理由与第十四轮相同（要动 schema 与 20 处断言，M1b 引入符号维度时一起加 `shape_gate_skipped`）。

**五组变异探针**（`output/probes/mutate15.py`，跑 fifteenth+fourteenth，全部 restored=True）：

| 变异 | 结果 |
| --- | --- |
| A 关掉 `self_` 剥离（`elif False`） | 1 failed：`SelfAttnClash` 合法 build |
| B 去掉 `.lower()` | 1 failed：`Upper` 合法 build |
| C 去掉 sanitize（`return text.lower()`） | 1 failed：`SelfAttnClash`（`.` 没被换成 `_`） |
| D 关掉 `check_name_target` 调用 | 1 failed：`self_a`/`self_b` 互换不再被拒 |
| E `_matches` 的后缀分支恒 False | 1 failed：`p_attn_weight_1` 这类重名后缀被误杀 |

还原后 targeted **72 passed**。全量 **417 passed in 51.80s**（375 + 19 + 23）。
端到端 `output/fifteenth-check`：EXIT 0、nodes=128（module 34/param 18/input 1/op 75）、edges=101、
degraded 2、fused 0、orphan 0、shape_broken 0、shape_unchecked 0、`real_execution={ok:true,reason:null}`。
与第十四轮产物做**结构化逐字段 diff**（`output/probes/diff15.py`）：只有 `meta.created_at` 与
`meta.repo.url`（这次传的是绝对路径）两处不同，**其余完全一致** —— 不是「看起来一样」。
行数（pathlib splitlines）**OVER200=[]**：fx_nodes 187、fx_edges 184、build_trace 181、fx_contract 175、
report 165、fx_signature 161、fx_trace 160、cli 157、fx_graph 148、schema_structure 129、**fx_names 106**、
schema_validate 100、fx_shapes 98、fx_inputs 98、fx_kinds 54。

**教训（这轮最贵的一条）**：评审第十二轮说过「expected 从调用方对象重生就不是第三方」，
这轮它换了个说法——**「地面真相独立」不等于「我的映射正确」**。名字确实独立于 target（torch 回写同步），
但我用来比较两者的**映射**是我自己近似的，近似错了就同时产生误杀与漏检，而且 29 条自选温和命名的
用例全绿也发现不了。对策不是再加一道关，而是：①去读权威的**实现**（不是 docstring、不是我的记忆）；
②让期望值来自权威的**实际输出**（交叉核对），而不是来自我的实现；③优先选**按构造不会误杀**的
方向（正向映射）而不是需要「唯一性」兜底的方向（有损反推）。
### 第十六轮评审（基线 e398d9f，417 passed / 文档 HEAD af02aef）：关自己也会 fail-open

结论：**Critical 0，可以交付、建议进入 M1b**。两条 Important 不是「trace 数据错了」，
而是**我上一轮新写的第八道关自己在某些输入下悄悄失效**。评审明确它们是「M1b 开工前的硬化项」，
不是当前 torch 2.15 CLI 主路径的阻塞项。我仍然全部修完再交付——理由与前几轮一致：
一道会静默跳过的关，比没有这道关更危险，因为文档会让读者以为它一直在工作。

#### I-1 未知前缀 fail-open（已修）

`fx_names.check_name_target` 原来写 `prefix = next(...); if prefix is None: continue`。
评审实跑 `check_name_target([N('weird')], [{'name':'weird','kind':'param','target':'a'}])` → **ACCEPTED**。
torch 2.15 的前缀表是 `USER_INPUT:''`/`PARAMETER:'p_'`/`BUFFER:'b_'`/`CONSTANT_TENSOR:'c_'`/
`CUSTOM_OBJ:'obj_'`/`TOKEN:'token'`（`pydeps/torch/_export/utils.py:58-65`），所以当前 CLI 不触发；
但 torch 一改命名规则、或直接 API 传个怪名字，这道关就无声失效。
修法：`prefix is None` 且 `kind != 'input'` → 收集 problem → `BuildError`，消息里点名
**实际的 node.name**、它的 kind、已知前缀表。同时把「非输入 spec 没给 target」也改成拒绝
（原来也是 continue）。`item is None` 仍 continue——覆盖率是 `fx_contract.check_contract`
的 uncovered 判据负责，不在这里重复。

#### I-2 CUSTOM_OBJ 两种写法都接受但没有真实导出背书（已修：改为拒绝）

第十五轮我给 `obj_` 前缀开了「两种写法都接受」的分支（`expected.insert(0, str(target))`），
依据是 `utils.py:1211-1215` 会把 CUSTOM_OBJ 的 target 改写成 `name[4:]`。
但**我自己在 plan 里承认造不出真实 CUSTOM_OBJ 导出**：torch 2.15 把 `self.obj.add(x)`
常量折叠成 `x+3`，`input_plan` 里只剩 `x` 一条 USER_INPUT。评审的理论反例：
constants 同时有 `foo` 与 `self_foo` 时，把 `obj_foo` 的 target 改成 `self_foo` →
`strip_name` 得 `foo` → 放行，parent 可能变错。
**裁决：M1a 先 fail-closed**，与 TOKEN 同一处理。`CUSTOM_OBJ` 从 `KIND_MAP` 移进 `REFUSED_KINDS`，
`PREFIXES` 删掉 `obj_`。原则写进 `fx_kinds` 注释：**只有验证过的种类才进 KIND_MAP**；
没验证过的分支不写成「已支持」，也不留「支持了但没测」的中间态。M1b 补真实 ScriptObject
端到端导出用例后再放开。

#### M-1 `_matches` 的 `_N` 后缀单关放行伪造（已钉成两层用例，不改实现）

`check_name_target([p_a_1], target='a')` 会被接受（后缀分支）。但端到端被 ⑥ 关门：
模型 Two（同时有 `a` 与 `a_1`）改 target 后报「同一个参数/常量被 input_specs 认领了多次：a」；
模型 One（只有 `a_1`）报「模块里有参数/缓冲没被任何 param|const 的 input_specs 认领：a_1」。
评审确认常量没有 unclaimed 检查、理论上更薄，但**没构造出真实反例**。
处理：不收紧 `_matches`（精确复刻 torch 的冲突计数会引入新的误杀风险，第十五轮的 C1 就是这么来的），
而是把两层都钉死——`test_suffix_forgery_is_accepted_by_the_name_gate_alone` 明确「单关接受」，
Two/One 参数化明确「端到端拒绝」，并在 README 残余边界里写「这一关单独调不是完整权威」。

#### M-2 报错把 expected 与 target 印成同一个值（已修）

原消息只印 `expected[0]` 与 `target`；当 `strip_name(target) == target` 时两者相同，
用户看到「p_x 的名字对应 'a'，但 spec 说它是 'a'」，完全看不出为什么被拒。
改成同时给**观察到的 base** 与**按 target 应当得到的 base**：
「p_x 去掉前缀 'p_' 后的 base 是 'x'，而 target='a' 按 torch 的命名规则应当是 'a'」。

#### M-3 弱断言（已修）

- `tests/test_fifteenth_review.py` 的 `checked >= 2` → `checked == non_input and checked > 0`
  （`non_input` 由 `input_plan` 数出来）。11 个参数的模型只核 2 个也绿的漏洞关掉。
- `PARENTS` 表原来与被测 trace 同管线。新增
  `test_parents_table_is_derived_from_the_module_not_the_trace`：六模型参数化，
  用 `input_plan` 的 name→target + `module.named_modules()` **独立**推 owner，
  断言 `owner in owners` 且与 PARENTS 表相等，**不经 trace 管线**。
- 补齐评审点名的四类缺口：未知前缀（5 条 + CLI 级真改 `node.name`）、`p_a_1→a`（两层）、
  CUSTOM_OBJ 端到端（CLI exit 2 + 不改 kind 时 exit 0 的反向对照）。
  「CUSTOM_OBJ 真实导出」这一类**做不到**，所以改成拒绝而不是补测（见 I-2）。

#### M-4 文档漂移（已修）

提交链补 `af02aef`；README 的「真正剩下的洞只有压平撞名」改成**三条并列**
（压平撞名 / 单关不是完整权威 / CUSTOM_OBJ 属 M1b 验证项）；kind 表与退出码表同步。

#### 新增回归与变异证据

`tests/test_sixteenth_review.py` **25 条**。既有三份测试按新语义适配：
`test_eleventh_review` 的 kind 映射用例改成四项 + `REFUSED_KINDS=={'TOKEN','CUSTOM_OBJ'}`，
CUSTOM_OBJ 用例**反转**成「因为没有真实导出背书所以拒绝」并新增反向对照
（同一真产物不改 kind → `consts=={'c_w'}`、`args[0] is exported.constants['w']`）；
`test_fourteenth_review` 的一致对表删掉 `obj_*`，不一致对表新增 `obj_foo`/`weird`/无 target。

| 变异 | 结果 |
| --- | --- |
| A 未知前缀退回 `continue` | 9 failed（5 条 unknown-prefix + CLI 改名 + fourteenth 三条） |
| B CUSTOM_OBJ 回到 KIND_MAP、删 REFUSED_KINDS 条目 | 4 failed（pin_the_decision、CLI custom-obj、eleventh 两条） |
| C 报错退回只印 expected | 1 failed（M-2） |

三组均能红后还原（还原锚点必须唯一：B 第一次用 `old_string='}'` 报 matched 5 times，
一度停在半变异态，用 TOKEN 条目末行做唯一锚点补回，targeted 134 passed 确认）。

全量 **442 passed in 52.35s**（417 + 25）。端到端 `output/sixteenth-check`：EXIT 0、
nodes=128（module 34/param 18/input 1/op 75）、edges=101、degraded 2、fused 0、orphan 0、
shape_broken 0、shape_unchecked 0、`real_execution={ok:true,reason:null}`、123688 bytes。
与第十五轮产物**结构化逐字段 diff 只差 1 处 `/meta/created_at`**（repo url 这次同为绝对路径）。
行数（pathlib splitlines）**OVER200=[]**：fx_nodes 187、fx_edges 184、build_trace 181、
fx_contract 175、report 165、fx_signature 161、fx_trace 160、cli 157、fx_graph 148、
schema_structure 129、**fx_names 125**、schema_validate 100、fx_shapes 98、fx_inputs 98、**fx_kinds 61**。

#### 留给 M1b 的（评审同意，不阻塞）

- **M-2（上一轮的）SymInt 静默跳过**：`check_value_shape` 对非整数维直接 return，
  动态形状下第七道关会静默失效。M1b 必须记独立的 `shape_gate_skipped` 计数
  （不复用边级 `shape_unchecked`），或动态形状直接 `TraceUnsupported`。
- **M-4（上一轮的）`build_op_nodes(exported=None)`**：拆成必填 exported 的公开入口
  + 私有未检入口。评审明确「保持现状不算 M1a bug」。
- **拆分建议**：先把 `placeholder_args` 拆到 `fx_args.py`、`check_value_shape` 移到
  `fx_contract`/`fx_args`、`fx_shapes` 保持纯原语。`fx_signature` 161 行，M1b 一动就顶 200。

**教训**：第十五轮的教训是「地面真相独立 ≠ 我的映射正确」；这轮再加一条——
**一道关的 `continue` 分支就是它的失效模式**。写守卫时要把「我认不出这个输入」当成错误，
而不是当成「与我无关」。fail-open 的关在测试全绿时看起来和 fail-closed 一模一样，
只有专门构造「关认不出的输入」才分得出来，所以这类用例必须显式存在。
### 第十七轮评审（基线 d83d2e5，442 passed / 文档 HEAD db500fe）：M1a 必修项为空

结论：**Critical 0，正常 CLI 路径上未发现「所有检查全过却写出错误 trace」的问题；
本轮新增的 fail-closed 判断没有误拒已测的合法模型。M1a 可以收尾，建议进入 M1b。**
评审快照 `output/review16/d83d2e5` 实跑 442 passed in 52.96s，fixture build 逐项一致，OVER200=[]。

#### 五个自问的答复（都给了实测，不是确认）

1. **新 fail-closed 会不会误杀？** 不会（已测范围内）。评审造了 `PxInput`（forward 形参 `p_x`
   + `self.x` 参数）、`PxParam`、`PxBuffer`、`SelfName`（参数名就叫 `self_`），全部 `trace_module`
   成功且 kind/计数正确。`DictInput`/`KwOnly` 的失败来自既有的 `tuple(example_inputs)`
   pytree/kwargs 限制，**不是名字关**。证据 `output/review16/probe_17_falsepos.py`。
2. **CUSTOM_OBJ 拒绝有没有代价？** 本机造不出可证伪的反例。评审试了
   `torch.jit._recursive.create_script_class(obj)._c` 当输入，export 依次报 `__obj_flatten__` 缺失、
   `Expect flat x to be a tuple`、`Could not split full_qualname='__torch__.C1', expected 5 parts`，
   `strict=True/False` 都一样。**纯 Python 造不出完整 CUSTOM_OBJ 导出** → 先拒绝是当前最安全的做法。
3. **不收紧 `_matches` 有没有「单关接受且端到端也接受」的模型？** 没找到。常量场景报
   「target=a，但拿不到它的值」或重复认领。故不收紧可接受。
4. **PARENTS 独立推导是否同源？** **半独立**——它用 `input_plan`（被测代码）取 target，
   能抓 trace 管线写错 parent，抓不到 `input_plan` 自己把 name→target 映射错。
   真正独立的地面真相应是 `module.named_parameters()/named_buffers()` 的键 + 手写预期表。
5. **CLI 改名用例是否自娱自乐？** 不是，但**只证明 fail-closed**，不证明新前缀下映射仍正确。

#### Minor 处理（五条全修）

| 项 | 处理 |
| --- | --- |
| 1 README:112 句子残缺（「在 build 时把，」缺谓语） | 改成「在 build 时**把守**」 |
| 2 计划提交链漏文档 pin `db500fe` | 已补 |
| 3 PARENTS 测试半独立 | **新增手写 `TARGETS` 表 + 6 条用例**（见下） |
| 4 CLI 改名用例只是模拟 | README 写明「证明的是认不出前缀会 exit 2，不是映射仍正确」 |
| 5 动态形状未在 README 说明 | ⑦ 段补「SymInt 时静默跳过；M1a 无路径；M1b 必须记 `shape_gate_skipped`」 |

**Minor 3 的修法与变异证据**：`tests/test_sixteenth_review.py` 新增手写 `TARGETS` 表
（placeholder 名 → 模块属性路径，依据是六个模型类的**源码结构**，不是 `input_plan` 的输出），
用例 `test_hand_written_targets_are_real_module_attributes_and_match_input_plan` 三层断言：
①每个 target 真的是 `named_parameters()/named_buffers()` 的键；②`input_plan` 的输出与手写表相等；
③由手写表推的 owner 与 `PARENTS` 相等。
变异：在 `input_plan` 里**互换同一模块内前两个 target**（`self_attn.weight` ↔ `self_attn.bias`，
owner 不变）→ **新用例 4 failed（SelfAttnClash/Upper/NestedSelf/SelfX），旧用例 6 条全过**。
这正是评审说的「半独立」的实证：旧用例抓不到 `input_plan` 自身的映射错，新用例抓得到。已还原。

全量 **448 passed in 52.74s**（442 + 6）。

#### I-1（M1b 范围，不阻塞 M1a）：压平撞名

评审确认这是**唯一**仍能写出错误 trace 的路径，且需要就地修改真导出产物，正常 CLI 不可达。
**M1b 若承诺完整 parent 正确性，必须处理**：不再靠名字反推，改为从**模块结构 +
`graph_signature.input_specs`** 直接建 owner 映射；对无法唯一判定的组 **fail-closed 而不是跳过**。
这条写进 M1b 的开工前提，不是「以后再说」。

#### M1b 开工前的工程卫生（评审建议，采纳）

- `fx_nodes` 187 / `fx_edges` 184 已接近 200 行，**加字段前先按职责拆**（如 `fx_plan` / `fx_node_fields`），
  否则行数约束会挡路。`placeholder_args` 先拆到 `fx_args.py`。
- M-2 SymInt 静默跳过 → M1b 补 `shape_gate_skipped` 计数；M-4 `build_op_nodes(exported=None)`
  → M1b 拆公开/私有入口。评审确认这两项留 M1b 可接受（M1a 静态形状下无路径；CLI 始终传 `exported=`）。
- 第一块按工程计划 **Task 6 符号表与 shape 传播**：`symbols/code_table.py` → `shape_prop.py` → `mapping.py`，
  先钉 `B/T/D/H/Dh`、`n_embd↔D`、`Dh=D/H`；**不要先做论文 PDF/LaTeX 解析或双向检索**（属 M2.5 / M3）。
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
| `c6b6bec` | 钉第十二轮提交链 |
| `b9ea76a` | pytree 输入不摊平的能力边界：README「追不动」四种 + CLI 级 exit 5 用例，329 passed |
| `a7311fc` | 钉 pytree 边界提交 |
| `fb00b9b` | 第十三轮条件项：第七道关——取到的张量形状与 `node.meta["val"]` 核对（target 互换），16 条新回归，345 passed |
| `870d614` | 第十三轮文档：七道关与残余边界、TOKEN 归类说明、`cond`/`while_loop` 点名、pytree 措辞改准、M-2 留 M1b 的理由 |
| `aeea7e6` | 钉第十三轮提交链 |
| `0ca6837` | 第十四轮必修：第八道关 `fx_names.check_name_target`（名字↔target，反推唯一才比）、拆出 `fx_kinds`、「不可观测」用例按事实改写、残余洞钉成 trace 级证据、29 条新回归，375 passed |
| `81581a1` | 第十四轮文档：八道关与残余边界、计划记录、行数重测 |
| `c2608ea` | 钉第十四轮提交链 |
| `e398d9f` | 第十五轮必修：第八道关改**正向核对**（复刻 torch `_strip_name`+`lower`+sanitize，补 `obj_`）、六个真实命名模型 + 与导出器实际名字交叉核对、CLI 级互换 exit 2 与合法 exit 0、歧义断言加牙，417 passed |
| `e8757d2` | 第十五轮文档：README 第八道关改正向核对与 C1/C2 反例、计划记录（torch 命名规则表、六模型实测、五组变异、结构化 diff）、提交链补 `c2608ea` |
| `af02aef` | 钉第十五轮提交链 |
| `d83d2e5` | 第十六轮硬化：未知前缀/无 target → fail-closed、`CUSTOM_OBJ` 移进 `REFUSED_KINDS`（删 `obj_` 前缀）、报错加观察到的 base、25 条新回归 + 三份既有测试按新语义适配，442 passed |
| `db500fe` | 钉第十六轮提交链 |
| `c1bb126` | 第十七轮 Minor 全修：README 残句/动态形状说明/改名用例边界、手写 `TARGETS` 表 + 6 条独立回归（变异证明旧用例半独立），448 passed |
| `ddeb9b9` | 第十六轮文档：README kind 表/⑧ 段/残余边界三条/退出码表、计划记录（I-1/I-2/M-1…M-4、三组变异、结构化 diff 只差 created_at）、提交链补 `af02aef` |
