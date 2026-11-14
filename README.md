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
python -m papertrace build --repo tests/fixtures/nanogpt --paper none --out output/m1a
python -m papertrace dump --trace output/m1a/trace.json
python -m papertrace dump --trace output/m1a/trace.json --ops
```

`--ops` 一行一个算子，形如：

```text
root/op037  transformer.h.0.attn  (2, 4, 8, 8) -> (2, 4, 8, 8) matmul
root/op043  transformer.h.0.attn  (2, 4, 8, 8) -> (2, 4, 8, 8) softmax
```

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
| 2 | 用法/入口错误（仓库不存在、entry 对不上、论文 ingest 未实现） |
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
