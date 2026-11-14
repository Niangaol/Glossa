# PaperTrace

把 PyTorch 仓库的算子级数据流图，与论文里的公式项逐项对上账。别人看结构，我们做对账。

## 现在是什么状态

**框架切片（M0）**。目前只有：包骨架、`trace.json` schema 校验器、可插拔 LLM 后端（默认 offline）、`build --skeleton`。算子追踪、论文 ingest、对齐、前端都还是桩。

本地模型（Ollama / 7B / nomic-embed-text）**故意没装**，不是缺步骤。默认后端是 `offline`，任何要模型的地方会直接报 `LLMUnavailable`，不允许编造结果。

## 文档

- 框架实现计划：`docs/superpowers/plans/2026-11-14-papertrace-framework.md`
- 完整工程计划（含 S1–S13 修订、Task 0–15、验收映射）：`docs/superpowers/plans/2026-11-14-papertrace-engineering-plan.md`
- 人读版计划书：`PaperTrace_工程落地计划书.docx`
- 环境说明：`docs/ENVIRONMENT.md`（Ollama 一节为后续可选）

## 快速跑通（框架阶段）

依赖装在仓库内的 `pydeps/`（见 `docs/ENVIRONMENT.md` 的说明），不污染系统 Python：

```bat
cd /d D:\AgentPrograms\PaperTrace
set PYTHONPATH=D:\AgentPrograms\PaperTrace\pydeps
python -m pytest -q
python -m papertrace --help
python -m papertrace build --repo tests/fixtures/nanogpt --paper none --out output --skeleton
```

## 铁律

- 结论必须带 `source ∈ {runtime, static, model}`。拿不到就空态 + 原因，禁止 mock 填界面。
- 对齐只能是「检索 Top-5 → yes/no 判断题 → 结构加权」，禁止让模型一次吐出「公式→行号」映射。
- `detail` 只追加不覆盖；子结论与父结论矛盾时写 `conflicts` 并把父节点标记 `stale`。
