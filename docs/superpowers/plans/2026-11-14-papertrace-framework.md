# PaperTrace 无本地模型框架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在空仓 `D:\AgentPrograms\PaperTrace` 搭起可测试的 PaperTrace 包骨架：CLI、冻结的 `trace.json` 校验器、可插拔 LLM（默认 offline）、模块桩、关 flash 的 nanoGPT 夹具、Vaswani Attention 公式夹具；全程不装 Ollama、不 pull 任何本地模型。

**Architecture:** 本切片只做「能 import、能校验、能写出合法空 trace、LLM 缺席时失败得干净」的框架。`parse_code` / `align` / 前端 / fx 追踪不在本计划实现。所有模块只通过 `trace.json` 交换数据。LLM 走 `LLMBackend` Protocol，默认 `OfflineBackend`（明确抛错，禁止静默 mock 对齐）。

**Tech Stack:** 当前系统 Python 3.13 可跑本切片测试；`pyproject.toml` 写 `requires-python = ">=3.11"`。本切片依赖只有 `jsonschema` + `pytest`。不装 torch / Ollama / marker。后续 fx 任务另开，那时再装 Python 3.11 + torch。

**Spec:** `C:\Users\niangao\Downloads\PaperTrace_技术规格书.docx`（抽取 `_spec_extract.txt`）。工程修订以本计划 **Spec Amendments** 为准，优于规格原文与旧计划书里的日历 / Task 0 装模型步骤。

## 用户已拍板（2026-11-14，本计划锁定）

- 工期不管。删掉按天日历对实现的约束。里程碑仍按 **M0 骨架 → M1a fx → … → M5** 的依赖顺序，但不排 D1–D50，也不逼 MVP-M3lite。
- 黄金论文改 **Vaswani 2017（arXiv:1706.03762）**。GPT-2 报告只做反向对账辅样例。
- **不安装本地模型。** 禁止 `ollama pull`、禁止把 Ollama/7B 写成 Task 0 前置。
- 先搭框架，再写后续实现计划。本文件就是框架切片；旧文件 `docs/superpowers/plans/2026-11-14-papertrace-engineering-plan.md` 只修订约束，不在本切片实现 Task 3–15。

## Global Constraints

- 不 fork `deepwiki-open`；不引入 code2flow / repo-visualizer 为依赖。
- v1 只支持 Python + PyTorch 仓库。本切片对非 Python 只把拒绝接口留成桩。
- 任何结论必须带 `source ∈ {runtime, static, model}`。拿不到数据就空态 + 原因，禁止 mock 填界面。
- 对齐禁止自由生成对应。本切片的 `align/` 只放文件桩 + grep 守卫，不接模型。
- 置信度写死：`w_retr=0.30, w_judge=0.50, w_struct=0.20`，`SIGMOID_GAIN=4.0`、`SIGMOID_CENTER=0.5`（S14：原式 `sigmoid(a)` 上限 0.731 达不到 0.75 绿线）。本切片只写进常量 + 边界测试，不接模型。
- 单源文件不超过 200 行。
- 本切片结束时：`pytest` 全绿、`python -m papertrace --help` 退出 0、`build --skeleton` 写出通过 schema 的 `trace.json`。
- 本切片 **允许** 在 Python 3.13 上跑测试。**禁止** 把「装 3.11 / 装 Ollama / pull 7B」写成本切片步骤。

## Review Focus

1. **假装对齐：** `align` 桩若返回假锚点或空 evidence 绿线，视为失败。期望：未实现时 `NotImplementedError` 或 CLI 拒绝，不写 anchors。
2. **LLM 缺席被吞掉：** `get_llm().chat()` 必须抛 `LLMUnavailable`，错误信息含如何配置 backend。期望：测试断言异常类型与中文原因。
3. **空 trace 冒充完成：** `build --skeleton` 的 `nodes` 必须是 `[]`，`meta.paper.ingest_mode=="none"`。期望：禁止塞假 Attention 节点。
4. **flash 夹具被改回：** nanoGPT fixture 必须 `CausalSelfAttention.flash is False`。期望：有 torch 才跑该断言；无 torch 则 skip，但源码字面量仍含 `self.flash = False`。
5. **自由生成接口名：** `papertrace/align/` 源码不得出现 `generate_alignment` / 「对应关系如下」。期望：本切片就放 grep 测试。

---

## Spec Amendments（实现以本表为准）

沿用旧计划 S1–S12，**新增并锁定 S13**，并改写 S1/S3/S12 与本切片冲突的部分：

| ID | 锁定内容 |
|---|---|
| S1′ | 若配置了生成模型，默认仍是 7B 不是 14B。**未配置时 backend=offline，不拉模型。** |
| S2 | 禁止 fork deepwiki-open。 |
| S3′ | M0 本切片 = git + 包骨架 + schema + CLI + 夹具文件。**Ollama / Python 3.11 从 M0 拿掉，改为 fx 任务的前置。** |
| S4 | M1a 主路径 fx，关 flash（本切片只准备 fixture，不跑 fx）。 |
| S5 | 黄金论文 Vaswani 2017；GPT-2 报告只做 reverse。**用户已同意。** |
| S6 | 论文优先 TeX。本切片只放 Attention 最小 `.tex` 夹具，不下载 arXiv、不装 marker。 |
| S7 | L0 模板化零 LLM（后续任务）。 |
| S8–S11 | 不依赖调图工具；Mermaid 仅 dump；FastAPI 只 serve；探针默认 CPU。 |
| S12′ | 工期不排。完整路径与 MVP 的切开仍写在工程计划里，但不作为本切片验收。 |
| **S13（新）** | `PAPERTRACE_LLM_BACKEND` ∈ `{offline, openai, ollama}`，**默认 `offline`**。Offline 禁止编造 chat/embed 结果。后续可接 DeepSeek 中转（openai-compatible）或 Ollama，本切片都不装。 |

---

## File Structure（本切片创建 / 修改）

```
PaperTrace/
  .git/                          # Task 0 初始化
  .gitignore
  pyproject.toml
  README.md
  schema/trace.schema.json       # 已存在，只在测试证明缺字段时改
  papertrace/
    __init__.py                  # __version__ = "0.1.0"
    exceptions.py                # TraceSchemaError, LLMUnavailable, IngestError
    cli.py                       # build|dump|serve|eval；本切片 serve/eval 打印未实现
    schema/validate.py
    constants.py                 # W_RETR/W_JUDGE/W_STRUCT, JUDGE 权重
    build/trace.py               # skeleton_trace(repo_meta) -> dict
    llm/client.py                # Protocol + OfflineBackend + get_llm()
    llm/prompts.py               # JUDGE_PROMPT / DRILL_PROMPT 常量占位（从规格附录迁标题，不接模型）
    ingest/{__init__,repo,paper,arxiv}.py          # 桩
    parse_code/{__init__,fx_trace,loc,einops_expand,loop_fold,treesitter_fallback,export_try}.py
    parse_paper/{__init__,units,split_terms,latex_safe}.py
    symbols/{__init__,code_table,paper_table,mapping,shape_prop}.py
    align/{__init__,embed,retrieve,judge,score}.py
    diff/{__init__,dim,struct,missing,reverse}.py
    trace_runtime/{__init__,discover,probe,profile}.py
    detail/{__init__,l0,l1,l2,l3,closure,cache,stale,annotations}.py
  tests/
    test_schema.py
    test_cli.py
    test_llm_offline.py
    test_imports.py
    test_align_no_generation.py
    test_fixture_flash.py
    fixtures/nanogpt/model.py    # vendor 精简，self.flash = False
    fixtures/nanogpt/__init__.py
    fixtures/papers/vaswani2017/attention.tex
  docs/superpowers/plans/2026-11-14-papertrace-framework.md   # 本计划落盘
  docs/superpowers/plans/2026-11-14-papertrace-engineering-plan.md  # 修订 S13 / 去 Task0 装模型
  docs/ENVIRONMENT.md            # 标注 Ollama 为后续可选，不是现在
```

**不创建：** `frontend/` 实现、`data/cache.db`、真实 arXiv 下载、Ollama 安装脚本作为必做步骤。

职责：`cli.py` 只编排；`build_trace.skeleton_trace` 只填 meta + 空数组；`llm` 不知道 schema；`align` 本切片不可被 `build` 调用。

---

### Task 0: Git 仓库与包装箱

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `README.md`, `papertrace/__init__.py`, `papertrace/exceptions.py`
- Create: `papertrace/cli.py`（先能 `--help`）
- Test: `tests/test_cli.py`（`--help` 退出 0）

**Interfaces:**
- Consumes: 无
- Produces:
  - `papertrace.__version__ == "0.1.0"`
  - `python -m papertrace --help` 退出 0，stdout 含 `build` / `dump` / `serve` / `eval`
  - `pyproject.toml`：`[project] name="papertrace" requires-python=">=3.11" dependencies=["jsonschema>=4.20"]`；`[project.optional-dependencies] dev=["pytest"]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import subprocess, sys

def test_module_version():
    import papertrace
    assert papertrace.__version__ == "0.1.0"

def test_help_exits_zero():
    r = subprocess.run([sys.executable, "-m", "papertrace", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    out = r.stdout + r.stderr
    for cmd in ("build", "dump", "serve", "eval"):
        assert cmd in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL（无 `papertrace` 包）

- [ ] **Step 3: `git init`，写 `.gitignore`（`.venv/`, `__pycache__/`, `output/`, `data/cache.db`, `node_modules/`, `.dsh/`），写 `pyproject.toml` + 最小 `cli.py` argparse**

`cli.py` 用 `argparse` 子命令。`serve` / `eval` 打印中文「本切片未实现」并以退出码 2 返回。`build` / `dump` 本任务可先同样未实现，Task 3 再接。

- [ ] **Step 4: 测试 PASS；Commit** `chore: init papertrace package and CLI help`

---

### Task 1: Schema 校验器

**Files:**
- Create: `papertrace/schema/validate.py`
- Create: `tests/test_schema.py`
- Modify: `schema/trace.schema.json` 仅当测试证明缺字段

**Interfaces:**
- Consumes: `schema/trace.schema.json`
- Produces:
  - `class TraceSchemaError(Exception): errors: list[str]`（也可放 `exceptions.py`，两处不得各写一份）
  - `validate_trace(doc: dict) -> None`
  - `minimal_trace() -> dict` 十个根键齐全，数组为空，`meta.paper.ingest_mode=="none"`，`meta.model.name=="offline"`
  - `load_trace(path: Path) -> dict` / `dump_trace(doc: dict, path: Path) -> None`

- [ ] **Step 1: Write the failing tests**（名称与断言钉死）

```python
def test_minimal_trace_passes():
    from papertrace.schema.validate import minimal_trace, validate_trace
    validate_trace(minimal_trace())

def test_missing_source_rejected():
    # 往 nodes 塞缺 source 的节点，必须 TraceSchemaError 且 errors 含 "source"

def test_empty_evidence_rejected():
    # anchors.evidence == "" 必须失败

def test_dump_roundtrip(tmp_path):
    # dump 后再 load，validate 通过
```

`minimal_trace()` 的 `meta.repo.commit` 用 `dirty-skeleton`（≥7 字符）；`meta.model.embed_model` 用 `none`。

- [ ] **Step 2: FAIL because functions missing**
- [ ] **Step 3: Implement with `jsonschema.Draft202012Validator`；收集所有 error 进 `TraceSchemaError.errors`**
- [ ] **Step 4: PASS; Commit** `feat: validate and dump minimal trace.json`

---

### Task 2: LLM Protocol + 默认 Offline

**Files:**
- Create: `papertrace/llm/client.py`, `papertrace/llm/prompts.py`
- Create: `tests/test_llm_offline.py`

**Interfaces:**
- Consumes: 环境变量 `PAPERTRACE_LLM_BACKEND`（默认 `offline`）
- Produces:

```python
class ChatResult(NamedTuple):
    text: str
    model: str
    backend: str

class LLMUnavailable(Exception): ...  # 中文 message

class LLMBackend(Protocol):
    name: str
    def chat(self, prompt: str, *, system: str | None = None) -> ChatResult: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class OfflineBackend:
    name = "offline"
    def chat(self, prompt, *, system=None) -> ChatResult:
        raise LLMUnavailable("LLM backend=offline。未安装本地模型，也未配置 PAPERTRACE_LLM_BACKEND=openai|ollama。")
    def embed(self, texts) -> list[list[float]]:
        raise LLMUnavailable("...")

def get_llm() -> LLMBackend: ...
```

- `prompts.py` 必须含 `JUDGE_PROMPT`（含「只能回答 yes / no」）与 `DRILL_PROMPT`（含「已知父节点结论」）。本切片不调用它们。
- `get_llm()` 读到 `openai` / `ollama` 时 **本切片仍返回 OfflineBackend 或抛 `LLMUnavailable`**（未实现），禁止偷偷打网。测试：`monkeypatch.setenv("PAPERTRACE_LLM_BACKEND","ollama")` 后 `chat()` 仍不得返回假 yes。

- [ ] **Step 1: `test_offline_chat_raises` / `test_offline_embed_raises` / `test_judge_prompt_is_yes_no`**
- [ ] **Step 2: FAIL**
- [ ] **Step 3: Implement；禁止 OfflineBackend 返回固定向量或 "yes"**
- [ ] **Step 4: PASS; Commit** `feat: offline-first LLM backend that refuses to hallucinate`

---

### Task 3: `build --skeleton` / `dump` CLI 契约

**Files:**
- Modify: `papertrace/cli.py`, `papertrace/build/trace.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `minimal_trace`, `validate_trace`, `dump_trace`
- Produces:
  - `skeleton_trace(*, repo_url: str, commit: str) -> dict`：合法 trace；`nodes==[]`；`anchors==[]`；`paper.ingest_mode=="none"`；`paper.unit_count==0`；`model.name=="offline"`
  - CLI：

```
python -m papertrace build --repo <path> --paper none --out output/ --skeleton
python -m papertrace dump --trace output/trace.json
```

- `build` 无 `--skeleton`：退出码 2，stderr 含「算子追踪尚未实现，请加 --skeleton」。
- `build --skeleton`：创建 `out/trace.json`，退出 0。不读 torch、不调 LLM。
- `dump`：打印 `nodes=0 edges=0 anchors=0` 这类计数，退出 0。
- `--paper` 不是 `none` 且本切片：退出码 2，`论文 ingest 尚未实现`。

- [ ] **Step 1: 测试 skeleton 文件通过 `validate_trace`；测试无 --skeleton 退出 2；测试 dump 计数**
- [ ] **Step 2: FAIL**
- [ ] **Step 3: Implement `build_trace.skeleton_trace`；CLI 不得 import `align` / `parse_code.fx_trace`**
- [ ] **Step 4: PASS; Commit** `feat: skeleton build writes valid empty trace.json`

---

### Task 4: 模块桩与「禁止生成对齐」守卫

**Files:**
- Create: File Structure 中列出的全部包 `__init__.py` 与模块桩
- Create: `papertrace/constants.py`（`W_RETR=0.30` 等）
- Create: `tests/test_imports.py`, `tests/test_align_no_generation.py`

**Interfaces:**
- 每个功能模块对外函数签名先写上，函数体 `raise NotImplementedError(模块名)`。本切片钉死的名字：

```python
# parse_code/fx_trace.py
def trace_module(mod, args: tuple) -> object: ...

# ingest/repo.py
def ingest_repo(src, dest) -> object: ...

# align/judge.py
def judge(term, snippet: str) -> object: ...   # 不得出现 mapping: dict 参数

# align/score.py
def confidence(s_retr: float, s_judge: float, s_struct: float) -> float: ...
```

`confidence` **本切片就实现**（纯函数，不依赖 LLM）：

`c = 1/(1+exp(-(0.30*s_retr+0.50*s_judge+0.20*s_struct)))`

并加测试：`s_retr=s_judge=s_struct=1` 时 `c>0.75`；全 0 时 `c<0.45`。

- [ ] **Step 1: `test_imports.py` 把 `papertrace` 子包全部 import 成功**
- [ ] **Step 2: `test_align_no_generation.py` 读 `papertrace/align/*.py` 文本，禁止子串 `generate_alignment` / `对应关系如下` / `自由生成`**
- [ ] **Step 3: `test_confidence_thresholds`**
- [ ] **Step 4: PASS; Commit** `feat: module stubs and frozen confidence weights`

---

### Task 5: nanoGPT 关 flash 夹具 + Vaswani 最小 TeX

**Files:**
- Create: `tests/fixtures/nanogpt/model.py`（从 karpathy/nanoGPT `model.py` 精简：保留 `GPTConfig`, `CausalSelfAttention`, `MLP`, `Block`, `GPT`；**不要** 训练循环）
- Create: `tests/fixtures/papers/vaswani2017/attention.tex`（只含 Attention 公式，能拆出 QK^T、scale、softmax、V 四项的 LaTeX 即可）
- Create: `tests/test_fixture_flash.py`

**Interfaces:**
- 源码字面量：`self.flash = False`，注释 `# PaperTrace fixture: keep QK^T/scale/mask/softmax as separate ops`
- `attention.tex` 含稳定注释 `% papertrace-id: §3.2-eq-attn`
- 测试分两档：
  1. 无条件：`model.py` 文本含 `self.flash = False`；`attention.tex` 含 `\mathrm{softmax}` 与 `QK`（或等价 LaTeX）
  2. `pytest.importorskip("torch")` 之后才实例化 `CausalSelfAttention` 断言 `m.flash is False`

本切片 **不** `pip install torch`。无 torch 时第 2 档 skip，第 1 档必须绿。

- [ ] **Step 1: 写测试**
- [ ] **Step 2: vendor 并改 flash；写入最小 tex**
- [ ] **Step 3: PASS; Commit** `test: nanogpt flash-off fixture and vaswani attention tex`

---

### Task 6: 修订既有工程文档（不是再写一篇愿景）

**Files:**
- Create: `docs/superpowers/plans/2026-11-14-papertrace-framework.md`（本计划全文）
- Modify: `docs/superpowers/plans/2026-11-14-papertrace-engineering-plan.md`
  - Global Constraints：默认 backend offline；删「Task 0 必须 ollama pull」
  - Spec Amendments 增加 S13，S1/S3/S12 改成 S1′/S3′/S12′
  - Task 0 Step 3 删除 winget Ollama 与 `ollama pull` 命令
  - 日历表上方加一句：「日历仅供参考，用户已拍板工期不管」
- Modify: `docs/ENVIRONMENT.md` 开头加 **「Ollama / 7B 为后续可选，框架阶段不要执行第 3 节」**
- 不重生成 25 页 Word（除非你明确要求）。Word 里的「现在装 7B」与本计划冲突，README 指向 markdown 计划为准。

- [ ] **Step 1: 落盘本计划**
- [ ] **Step 2: 改旧计划三处冲突（装模型 / 日历强制 / 缺 S13）**
- [ ] **Step 3: Commit** `docs: lock offline-first framework plan and S13`

---

## 本切片成功标准

1. `python -m pytest` 全绿（无 torch、无 Ollama）。
2. `python -m papertrace build --repo tests/fixtures/nanogpt --paper none --out output --skeleton` 写出通过 schema 的 `output/trace.json`，`nodes` 为空。
3. `get_llm().chat("yes?")` 抛 `LLMUnavailable`。
4. 仓库是 git repo，Task 0–5 各有一次 commit。
5. 旧工程计划不再把 `ollama pull` 当第一周必做。

## 明确不做（本切片）

- 安装 Python 3.11 / CUDA torch / Ollama / 7B / nomic-embed-text
- `torch.fx` 追踪、einops 展开、tree-sitter 降级
- 论文 ingest、判断题对齐、前端、FastAPI、L0–L3
- 重画 Word 计划书

## 假设

- 「本地模型」= Ollama 权重，不是 pip 包。jsonschema/pytest 可装。
- 框架阶段用系统 Python 3.13 可接受。
- 后续 LLM 更可能走 DeepSeek 中转（openai-compatible），Ollama 仍可选，本切片两者都不接。
- nanoGPT fixture 用精简 vendor，不 submodule 整个 karpathy/nanoGPT。

## 风险

- 3.13 以后跑 fx 可能踩 PyTorch wheel；那是下一份计划的 M1a 前置，不是现在的失败。
- 空 skeleton trace 被误当成 M1a 完成：CLI 无 `--skeleton` 必须拒绝，README 写明。
