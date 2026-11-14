# PaperTrace

把 PyTorch 仓库的算子级数据流图，与论文里的公式项逐项对上账。别人看结构，我们做对账。

## 现在是什么状态

**M1a：真实算子追踪。** 已经能跑通的链路：

```text
仓库 + 入口模型 → torch.export 真实执行 → 抓每个 aten 算子 → trace.json（节点带真实形状、模块层级、shape 一致性）
```

还没做的：论文 ingest、公式-算子对齐、mismatch 判定、前端。这些仍然是桩，**空就是空**，不会塞示例数据。

本地模型（Ollama / 7B / nomic-embed-text）**故意没装**，不是缺步骤。默认后端是 `offline`，任何要模型的地方会直接报 `LLMUnavailable`，不允许编造结果。

## 快速跑通

依赖装在仓库内的 `pydeps/`（见 `docs/ENVIRONMENT.md`），不污染系统 Python：

```bat
cd /d D:\AgentPrograms\PaperTrace
set PYTHONPATH=D:\AgentPrograms\PaperTrace\pydeps
python -m pytest -q
python -m papertrace --help
```

真实追踪一个 nanoGPT（本仓库自带夹具）：

```bat
python -m papertrace build --repo tests/fixtures/nanogpt --entry model:build_model --out output/m1a
python -m papertrace dump --trace output/m1a/trace.json
python -m papertrace dump --trace output/m1a/trace.json --ops
python -m papertrace dump --trace output/m1a/trace.json --edges
```

`--ops` 一行一个算子，下面是本仓库夹具的**真实输出**（形状是第二遍执行跑出来的，不是推的）：

```text
root/@020        transformer.wte                    (2, 8) -> (2, 8, 32) embedding
root/@037        transformer.h.0.attn               (2, 4, 8, 8) -> (2, 4, 8, 8) matmul
root/@043        transformer.h.0.attn               (2, 4, 8, 8) -> (2, 4, 8, 8) softmax
```

权重/输入节点不是算子，`--ops` 里它们的输入形状打 `-`；算子**确实没有数据入参**（只用权重/缓冲，
比如 `slice`）也打 `-`。只有老格式 trace 缺 `inputs` 字段时才打 `(?)`——`(?)`、`-`、0 维标量的
`()` 三者互不混淆。

`--edges` 一行一条边，左列是**消费者真实拿到的输入形状**，右列是**生产者真实吐出的输出形状**。
行首空格 = 两边核实相等，`!` = 对不上，`?` = 有一边没观察到（未核实，不等于一致）：

前两行是夹具的真实输出（embedding 的数据入边是 token id `(2, 8)`，权重边 `(64, 32)` 也在，但不冒充主输入）：

```text
  (64, 32)         生产者 (64, 32)         root/@015 (placeholder) -> root/@020 (embedding) e:root/@015->root/@020:args[0]
  (2, 8)           生产者 (2, 8)           root/@020 (embedding) -> root/@022 (add) e:root/@020->root/@022:args[0]
```

第三行是**反例**（不是夹具输出）：消费者只取了 split 的第 2 项 `(2, 8)`，却拿到 `(2, 6)`——

```text
! (2, 6)           生产者 (2, 8)           root/@031 (split) -> root/@034 (add) e:root/@031->root/@034:args[1][0]
```

末行给 `edges=N shape_broken=M shape_unchecked=K`。两边的形状不是同一条推断抄两遍：导出图会用真实张量
**再跑一遍**（`fx_observe`），边两端取的是这次执行里各自的实际形状。

### trace.json 的字段约定

- **节点 id**：模块节点是路径（`root`、`root/transformer.h.0.attn`），算子/输入/权重节点一律
  `root/@037`——`@` 不会出现在模块路径里，所以两种 id 不可能撞车。真有子模块名里带 `@`，
  `build` 直接报 `BuildError` 要求改名，而不是生成一份 id 打架的 trace。
- **`kind`**：`op` | `input` | `param` | `const`。**谁是谁由 `graph_signature.input_specs` 说了算**：
  `PARAMETER`/`BUFFER` → `param`，`CONSTANT_TENSOR` → `const`，`USER_INPUT` → `input`；
  `parent_id` 用 `spec.target` 的点分路径（`transformer.h.0.attn`）定位所属模块，不靠名字猜。
  常量（`torch.ones(...)`、`self.const = torch.ones(...)`）不是数据入参，也不是可训练权重：
  `self.const`（CONSTANT_TENSOR）单独标 `kind=const`，摘要写「常量 N」而不是塞进「权重 N」；
  纯字面量 `torch.ones(2,4)` 在导出图里就是一个 `ones` 算子（`kind=op`），它的
  `inputs` 为空，两者都不会冒充数据输入。
  **拿不到 `input_specs` 就 fail-closed**：判据是「**每个 placeholder 都被 spec 覆盖**」，
  不是「plan 是不是空字典」——`classify([])` 是个非空 dict，只看真假会被它绕过去。
  有未覆盖的 placeholder、spec 多出图里没有的名字、同一个名字既被标成权重又被标成输入、
  spec 顺序与 placeholder 顺序不一致、或出现**不认识的 `InputKind`**（不默认成 input），
  一律 `BuildError`（**exit 2**，CLI 与直接调 `build_op_nodes` 同一个码），不再退回 mangled 名猜：
  `p_+参数全名` 会把 `sub.x` 与根上的 `sub_x` 压成同一个 `p_sub_x`，也会把形参 `p_x` 和
  参数 `x` 的压平名混为一谈，猜错的代价是整份 trace 的 kind 反过来（权重标 input、
  输入标 param、常量消失），而且计数可能「看起来正常」。
  真的没有 placeholder（纯常量模型）时，空 plan 是合法的。
  **边界要说清**：`build_op_nodes` 只保证「覆盖齐全、不重叠、无幽灵名、kind 都认识」；
  「这个 kind 标得**对不对**」由 `placeholder_args` 拿模块的真实参数/缓冲核对
  （spec 说它是权重，模块里就必须真有这个参数，否则拒绝）。trace.json 里不存 input_specs，
  所以 `validate_trace` 只查 schema 与结构，**查不出 kind 标反**——那一道关在 build 时把。
- **形状**：`shape_out` 是第 1 项输出；`outputs` 是全部输出（`[]` = 无张量输出，
  `[[]]` = 0 维标量）。`inputs` 是**数据**入参形状（按参数顺序，权重位置整个跳过），
  `shape_in` 就是 `inputs[0]`；权重边不会冒充输入（藏在 `cat([w, x])` 这类**容器**里的权重也照样
  整个跳过），只用权重的算子 `inputs` 为空、`shape_in` 也为空（`--ops` 打 `-`，绝不回退成
  权重形状）。权重本身的形状看 param 节点和它的入边。
- **`dump --ops` 每行带 `kind`**（`kind=param`/`kind=input`/`kind=const`）：param 与 input 互换时
  终端上直接看得出来，不用去翻 JSON。
- **权重派生量不算数据输入**：`self.w[0]`、`self.w[:, :2]`、权重的转置/切片这类**只由权重算出来**
  的中间张量，和权重本身同等对待——它们不进 `inputs`，`shape_in` 仍是模型数据入参的形状。
  反过来 `x[0]` 这种从数据张量上取的切片仍是输入，不会被误伤。
- **常量派生量也不算数据输入**：`ones_like(x)`/`zeros_like(x)`/`full_like`/`new_*` 只借输入
  的形状和 dtype，产出的是常量——它们自己的 `inputs` 记空，下游 `cat([ones_like(x), y])`
  的 `shape_in` 是 `y` 的形状。`rand_like` 不在这个名单里（随机数不是常量）。
  `example_inputs()` 必须按 `forward` 形参顺序给。数量对不上时 `build` 一律 `exit 5`：
  多数情况 `torch.export` 当场报「missing a required argument」，漏到我们这层的则由
  `placeholder_args` 明说「按 forward 形参顺序给，多/少都不猜」——两种情况都不写 trace。
- **边**：按参数位置一条条连（`args[1][0]` 这种 label），`torch.cat([a, b])` 不会丢边。
  每条边同时记 `shape`（消费者这一项的真实输入）、`producer_shape`（生产者真实输出）和
  `checked`。`shape_consistent` 只在 `checked` 时才有意义；两边对不上就是 False，
  `dump --edges` 打 `!`；没观察到就打 `?`，**未核实不算通过**。
- **`meta.runtime`**：这次追踪怎么来的——设备、torch 版本、dtype、**实际**的 batch/seq_len、
  示例输入、entry，`requested`（命令行请求的 batch/seq_len，和实际值分开记，免得自相矛盾），
  `real_execution`（第二遍真实执行是否成功；**失败时根本不写 trace**，见退出码 5），以及 `counts`
  （operators/degraded/fused/orphan/shape_broken/shape_unchecked）。没有它就没法判断这份 trace 能不能复现。
  **orphan = 既没有入边也没有出边的算子**（两个方向都要断）。只看入边会把「被下游用着的
  数据源」误报成孤点——`torch.rand(2,4)` 没有入边但有出边，它是源不是孤点；常量源同理，
  被用着就有出边，所以**不需要给常量开豁免名单**。反过来，一个谁都不用的 `torch.ones`
  会被数出来（死代码）。「有入边但没人用」的死算子按这个定义不算 orphan，它属于另一类问题。
- **结构校验**：`validate_trace` 除了 JSON Schema 还查 `id`/`parent_id`/边的 `id`/`src`/`dst`
  必须是字符串（是 list/dict 时报「必须是字符串」，**不会漏成 `TypeError` 和 traceback**）、重复 id、悬空边、`parent_id` 不存在、
  module 节点必须 `source=static`、**边两端必须是算子节点**（不接受 module→op / op→module）、
  **不接受自环**（`src == dst`）。这些错误一律 `TraceSchemaError`，不静默放过。

### 入口契约：模块:工厂函数

`--entry` 指向一个**零参可调用对象**，它返回模型实例。推荐写成工厂函数，而不是直接给类：

```python
# 你仓库里的 model.py
def build_model():
    return GPT(GPTConfig(n_layer=2, n_head=4, n_embd=32, block_size=16, vocab_size=64))
```

```bat
python -m papertrace build --repo path\to\repo --entry model:build_model --paper none --out output
```

- 零参类也能用（`--entry model:TinyNet`），但 `GPT(config)` 这种必须给工厂，我们不猜你的配置。
- 示例输入优先用模型自带的 `example_inputs()`；没有就按 `config.vocab_size` + `config.block_size` 造 token id；都没有就报 `BuildError`，不会拿随机形状糊弄。
- 缺 torch → 退出码 **4**；追不动 → 退出码 **5**；仓库/入口对不上、`input_specs` 与图对不上 → 退出码 **2**。三种情况都**不写** `trace.json`。
  「追不动」有两种：① `torch.export` 就失败（数据依赖分支）；② 导出图能画出来，但拿真实张量
  **再跑一遍会炸**（自定义算子只有 meta 实现、真 CPU 实现抛错）。第二种以前会照常产出
  `source=runtime` 的 trace，把推断形状冒充成真实形状；现在一律 exit 5——没有第二遍执行，
  就不许说自己是 runtime。
- 退出码 5 时 stderr 前面可能有 torch 自己打的一二十行诊断图/警告（那是它的内部输出，
  我们拦不住）；**papertrace 的结论永远在最后一行**，脚本里请只看退出码。

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 内部错误：生成的 trace 不合 schema（属 bug，不是用法问题） |
| 2 | 用法/入口/契约错误（仓库不存在、entry 对不上、论文 ingest 未实现、trace.json 非法、`input_specs` 与图对不上） |
| 3 | 目标文件已存在，未加 `--force` |
| 4 | 缺运行时（没装 torch） |
| 5 | 模型可加载但追不动（export 失败，或导出图无法真实再执行） |

## 文档

- 框架实现计划：`docs/superpowers/plans/2026-11-14-papertrace-framework.md`
- M1a 算子追踪计划：`docs/superpowers/plans/2026-11-14-papertrace-m1a.md`
- 完整工程计划（含 S1–S13 修订、Task 0–15、验收映射）：`docs/superpowers/plans/2026-11-14-papertrace-engineering-plan.md`
- 人读版计划书：`PaperTrace_工程落地计划书.docx`
- 环境说明：`docs/ENVIRONMENT.md`（torch 与 Ollama 都属可选，见该文）

## 铁律

- 结论必须带 `source ∈ {runtime, static, model}`。拿不到就空态 + 原因，禁止 mock 填界面。
- 对齐只能是「检索 Top-5 → yes/no 判断题 → 结构加权」，禁止让模型一次吐出「公式→行号」映射。
- `detail` 只追加不覆盖；子结论与父结论矛盾时写 `conflicts` 并把父节点标记 `stale`。
- 多输出算子（如 `split`）必须标 `degraded=true` 并说明原因，不能假装形状完整；多输出节点的边形状按 `getitem` 的索引逐项解析。
- 融合算子（`scaled_dot_product_attention` 等）必须标 degraded 并在 stderr 警告：它把论文里好几个公式项吞成了一个 aten 算子，安静通过等于漏检。
