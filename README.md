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

`--ops` 一行一个算子，形如（形状是真实跑出来的，不是推的）：

```text
root/@037  transformer.h.0.attn  (2, 4, 8, 8) -> (2, 4, 8, 8) matmul
root/@043  transformer.h.0.attn  (2, 4, 8, 8) -> (2, 4, 8, 8) softmax
```

`--edges` 一行一条边，断链行首打 `!`，末行给 `edges=N shape_broken=M`：

```text
  (2, 8)           root/@018 (placeholder) -> root/@020 (embedding) e:root/@018->root/@020:args[1]
! (2, 6)           root/@031 (split) -> root/@034 (add) e:root/@031->root/@034:args[1][0]
```

### trace.json 的字段约定

- **节点 id**：模块节点是路径（`root`、`root/transformer.h.0.attn`），算子/输入/权重节点一律
  `root/@037`——`@` 不会出现在模块路径里，所以两种 id 不可能撞车。
- **`kind`**：`op` | `input` | `param`。`input` 是图入口，`param` 是权重/缓冲（torch.export
  把权重抬成图输入，名字带 `p_`/`b_` 前缀），`parent_id` 指向它真正所属的模块。
- **形状**：`shape_out` 是第 1 项输出；`outputs` 是全部输出（`[]` = 无张量输出，
  `[[]]` = 0 维标量）。`shape_in` 只从 `op`/`input` 入边取，权重边不会冒充输入。
- **边**：按参数位置一条条连（`args[1][0]` 这种 label），`torch.cat([a, b])` 不会丢边。
  `shape_consistent` 只在能独立核实的地方判 True：多输出索引解析、inplace 保持形状；
  形状缺失或对不上就是 False，`dump --edges` 会打 `!`。
- **`meta.runtime`**：这次追踪怎么来的——设备、torch 版本、dtype、batch/seq_len、示例输入、
  entry，以及 `counts`（operators/degraded/fused/orphan/shape_broken）。没有它就没法判断
  这份 trace 能不能复现。
- **结构校验**：`validate_trace` 除了 JSON Schema 还查重复 id、悬空边、`parent_id` 不存在、
  module 节点必须 `source=static`。这些错误一律 `TraceSchemaError`，不静默放过。

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
- 缺 torch → 退出码 **4**；模型追不动（自定义算子、数据依赖分支）→ 退出码 **5**；仓库/入口对不上 → 退出码 **2**。三种情况都**不写** `trace.json`。

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 内部错误：生成的 trace 不合 schema（属 bug，不是用法问题） |
| 2 | 用法/入口错误（仓库不存在、entry 对不上、论文 ingest 未实现、trace.json 非法） |
| 3 | 目标文件已存在，未加 `--force` |
| 4 | 缺运行时（没装 torch） |
| 5 | 模型可加载但追不动 |

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
