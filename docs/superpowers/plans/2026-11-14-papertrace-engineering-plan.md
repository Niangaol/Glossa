# PaperTrace 工程落地计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本机（Windows + RTX 5070 Ti Laptop 12GB）落地 PaperTrace：输入 PyTorch 仓库 + 论文，输出单文件 HTML（可播放的算子级数据流图，每个节点同时锚定源码行与论文公式项）+ `trace.json`。

**Architecture:** CLI 负责 ingest / 解析 / 对齐 / 出 HTML；localhost FastAPI 只服务按需 L3 深钻的流式输出。所有模块只读写 `trace.json`。代码侧以 `torch.fx` 为主路径产出算子图（nanoGPT fixture 强制 `flash=False`）；论文侧优先 arXiv TeX；对齐强制「双向检索 Top-5 → yes/no 判断题+依据 → 结构加权」，禁止模型自由生成对应关系。

**Tech Stack:** Python 3.11 venv、PyTorch 2.x、torch.fx、sympy、tree-sitter-python、LanceDB、Ollama `qwen2.5-coder:7b` + `nomic-embed-text`、sqlite3、Vite + TypeScript + 原生 SVG + KaTeX、vite-plugin-singlefile。

**Spec:** `C:\Users\niangao\Downloads\PaperTrace_技术规格书.docx`（抽取副本 `_spec_extract.txt`）。本计划吸收规格；下方 **Spec Amendments** 优于规格原文。

**Human document:** 面向人读的正式计划书 `PaperTrace_工程落地计划书.docx`（同目录上级）。

## Global Constraints

- Python **3.11** 专用 venv，路径建议 `D:\\AgentPrograms\\PaperTrace\\.venv`。禁止用系统 Python 3.13.15 跑追踪 / 训练 / 探针。
- 默认 LLM 后端 **offline**：`PAPERTRACE_LLM_BACKEND ∈ {offline, openai, ollama}`，未设置即 offline。**框架阶段不拉任何本地权重**（S13）。
- 若真要配生成模型，默认仍是 **qwen2.5-coder:7b**（Q4_K_M）。禁止把 14B 设为默认。环境变量 `PAPERTRACE_LLM` 可覆盖。
- embedding 用 **nomic-embed-text**（或 `BAAI/bge-small-zh-v1.5` 的 CPU ONNX）。禁止用生成模型打向量。
- 不 fork、不 submodule、不 vendoring `AsyncFuncAI/deepwiki-open`。
- v1 只支持 Python + PyTorch。TF / JAX / C++ / FastAPI 类 Web 仓库全部拒绝并给出原因。
- 不修改用户代码、无账号、无云、无浏览器/IDE 插件、不跑训练、不一键复现。
- 任何结论必须带 `source ∈ {runtime, static, model}` 与 `confidence`。拿不到数据就空态 + 原因，禁止 mock 填界面。
- 对齐禁止自由生成对应。判断题依据必填、≤40 字（schema 限制 80 字符含标点）。
- `nodes[].detail` 只追加不覆盖；父节点与子结论矛盾时写 `conflicts` 且父 `stale:true`，禁止静默覆盖。
- 置信度：`w_retr=0.30, w_judge=0.50, w_struct=0.20`，`a = w·s`，**`c = sigmoid(4·(a-0.5))`**（S14；原式 `sigmoid(a)` 上限 0.731 永远达不到 0.75，见第 3 章）。`c≥0.75` 绿实线；`0.45≤c<0.75` 黄虚线 + 1–2 备选；`c<0.45` 不连线，进 `unresolved`。
- 置信度的已知副作用（**待你拍板 U1**）：`s_struct=0` 不影响进绿线（`judge=retr=1, struct=0` → 0.769 绿）；`s_judge=0` 仍可能落黄区给出备选。可选修法：绿线加 `s_struct≥0.5` 门；`s_judge==0` 直接判 `<0.45`。
- 黄金主路径：`tests/fixtures/nanogpt`（关 flash）+ Vaswani 2017（arXiv:1706.03762）Attention 公式。GPT-2 报告（Radford 2019）只作反向对账辅样例。
- 运行时探针默认 **CPU**；与 Ollama 分时使用 GPU，禁止 7B 与 `model.forward` 同时占满 12GB。
- 单源文件不超过 200 行；按目录拆模块。
- 每个 Task 结束必须能独立 `pytest` 通过，并提交一次。

## Review Focus

1. **flash 融合**：PyTorch≥2.0 默认 `scaled_dot_product_attention` 把 QKᵀ / scale / mask / softmax 融成 1 个算子。期望：fixture 强制 `CausalSelfAttention.flash=False`，图中出现独立 matmul / mul / masked_fill / softmax。
2. **export 失败**：`torch.export` 遇 Python 分支会抛。期望：M1a 以 fx 成功为验收；export 作为可选回归，失败记 `meta.runtime` 而非阻断。
3. **论文 ingest 失败**：无 TeX、marker 崩、中文公式乱。期望：`meta.paper.ingest_mode` 记录真实路径，失败单元进 `unresolved`，禁止伪造公式项。
4. **12GB 显存争用**：7B Q4 ≈4.5–5.5GB，forward 探针再要数 GB。期望：探针默认 CPU；LLM 推理时卸载大 tensor。
5. **缓存键过粗**：用整仓哈希会导致改无关文件也全失效。期望：`cache_key = sha256(commit + 闭包源码 + 论文单元 + level + 模型 + prompt_version)`，改无关函数后未受影响节点命中率 100%。
6. **自由生成对齐**：任何 `align` 代码路径若直接让模型输出「公式→行号」映射，视为失败。期望：只有 yes/no 判断题接口。
7. **L0 烧模型**：概览可由图元数据模板化。期望：L0 零 LLM 调用。
8. **空仓库 / 非 PyTorch**：期望：CLI 以非零退出 + 人类可读原因，不写残缺 HTML。

---

## Spec Amendments（相对规格书的修订，必须遵守）

规格书整体方向正确：「别人看结构，我们做对账」。下列 12 条是本计划对规格的**有依据修改**，实现时以本表为准。

| ID | 规格原文 | 修订 | 理由 |
|---|---|---|---|
| S1′ | 默认 `qwen2.5-coder:14b` | 默认后端 **offline**（不拉模型）；真要配模型时默认 **7b**，14b 仅在「只对齐、不跑探针」时可选 | 本机 RTX 5070 Ti Laptop **12227 MiB**。14B Q4 ≈9GB，与 PyTorch 探针抢显存必 OOM。7B Q4 留出 6GB+ 余量。判断题是 yes/no，7B 足够。 |
| S2 | 「deepwiki-open 是首选底座，拿它的 backend 插入论文分支」 | **禁止 fork**。只允许参考其「分块 / 缓存 / Ollama 客户端」思路，自写 `ingest/` | deepwiki-open 是仓库→wiki/Mermaid 的文档生成器，MIT 但绑 AdalFlow + `~/.adalflow/wikicache/`。它没有算子图、没有公式项、没有 shape。当底座会把产品做成「又一个 DeepWiki」。这是「一周 vs 三个月」叙事里最危险的一句。 |
| S3′ | 里程碑从 M1a 起 | 增加 **M0 骨架与夹具**；Ollama / Python 3.11 从 M0 **移除**，改为 fx 任务的前置 | 用户拍板先搭框架、不装本地模型。框架切片（`2026-11-14-papertrace-framework.md`）在系统 Python 3.13 上就能跑通，不需要 Ollama。 |
| S4 | 「默认走 export，失败再 fx」 | **M1a 主路径 fx**；export 作回归，不阻断 | nanoGPT 的 flash 分支是 Python `if self.flash`。export 对数据依赖控制流不友好。规格自己也说 fx 更宽容。先拿到可数的算子，再追求 export。 |
| S5 | A1：nanoGPT + **GPT-2 论文** | 黄金主路径改为 nanoGPT + **Vaswani 2017（arXiv:1706.03762）**；GPT-2 报告作反向对账辅样例 | GPT-2 是技术报告，Attention 公式在 Vaswani。拿 GPT-2 PDF 做项级对齐，公式项根本不在那篇里，A3 会变成「定位到一段散文」。nanoGPT 注释写明参考 GPT-2 **实现**，不是参考 GPT-2 **论文公式**。 |
| S6 | 论文 ingest：marker / MinerU / Nougat | **优先 arXiv TeX source**；无 TeX 再 marker；MinerU 仅中文；Nougat 不做 v1 | PDF→LaTeX 是本项目最大的外部脆弱点。arXiv 提供 `.tar.gz` 源码时公式是真 LaTeX，稳定 ID 才做得到。Nougat 又大又慢，12GB 上不值得。 |
| S7 | L0–L2 全量预生成（均走模型） | **L0 模板化（零 LLM）**；L1 规则+少量 LLM；L2 由图直接生成 shape 序列，LLM 只写一句人话 | 规格表 11-1 写 L0「无（静态）」。用 7B 给每个算子写「一句话职责」是烧 token 且不可复现。shape 序列是事实，不该经过模型。 |
| S8 | 复用 code2flow、repo-visualizer 作运行时依赖 | **不作为依赖**。布局用自写 Sugiyama（或 `networkx.nx_agraph` 可选）；code2flow 只允许当「调用图对照」调试脚本 | code2flow 是函数调用图，repo-visualizer 是文件气泡图，粒度都对不上算子。引入它们会多两套无关图。 |
| S9 | Mermaid 作中间表示 | Mermaid **仅调试导出**（`scripts/dump_mermaid.py`）。播放器与缩放的唯一数据是 `nodes/edges` | Mermaid 画不出逐 step 播放、shape 边标注、项级高亮。把它当中间表示会在 M2 推翻。 |
| S10 | FastAPI 作为后端框架 | FastAPI **只跑 localhost 深钻流式**；主路径是 CLI `python -m papertrace build ...` | 单文件 HTML 必须断网可开。把生成做成「必须起服务」会破坏 A6/A12。 |
| S11 | 运行时采集用 GPU hook + profiler | 探针默认 **CPU**；profiler 可选。GPU 探针与 LLM **互斥** | 见 S1。另外 nanoGPT 随机输入 forward 在 CPU 上毫秒级，没必要上 GPU。 |
| S12′ | 「第一个可用版本 2–3 周」 | 工期不管，**不排日历**。那句话只作为 **MVP-M3lite** 的范围定义（砍播放器动画、L3、批量深钻），不作为承诺 | 用户明确拍板工期不用管。保留范围定义是为了万一要提前交差时有话说，不是为了逼节奏。 |
| **S14** | `c = sigmoid(w·s)`（上限 0.731 < 0.75 绿线） | `c = sigmoid(4·(a-0.5))`：a=1→0.88 绿、a=0.5→0.50 黄、a=0.2→0.23 不连 | 规格书第 8 章自相矛盾：按原式**永远连不出绿实线**，产品最核心的视觉语义直接失效。保留用户可见的 0.75/0.45 门槛，改公式。 |
| **S13** | （规格未定义） | `PAPERTRACE_LLM_BACKEND ∈ {offline, openai, ollama}`，**默认 `offline`**；offline 下 chat/embed 必须抛 `LLMUnavailable`，禁止编造结果。框架阶段不装 Ollama、不拉权重 | 用户拍板不装本地模型。让「没有模型」成为可测试的一等状态，比留一条随时会假装成功的路径安全。 |

不改、必须守住的规格硬规则：

- trace.json 唯一契约；source 三值；低置信不连线；局部闭包重算。
- 算子级而不是函数级；einops 展开；循环数据展开 / 视图折叠 ×N。
- 三步对齐；四类对账（反向最重要）；L3 三项验证（探针 + sympy 等价 + 对抗自检）。
- 闭包五项含「N 外变量赋值」；sqlite 存 raw_response；detail 只追加。
- stale 机制；用户纠正进 annotations 并作为重算硬约束。
- 三栏 `jumpTo`；播放器 `{step,playing,speed}` + rAF；默认模块级；KaTeX `\\htmlId`；语义色 ≤3；>300 算子确认；覆盖率常驻；单文件 <8MB。

---

## 本机事实（2026-11-14 实测）

| 项 | 值 |
|---|---|
| GPU | NVIDIA GeForce RTX 5070 Ti Laptop，12227 MiB，驱动 621.01 |
| 系统 Python | 3.13.15（无 `py` launcher） |
| Ollama | **未安装** |
| 工作区 | `D:\\AgentPrograms\\PaperTrace`（空仓起步） |
| 规格书 | `C:\\Users\\niangao\\Downloads\\PaperTrace_技术规格书.docx` |

nanoGPT `CausalSelfAttention.forward` 关键结构（实现时必须对上）：

- `c_attn: Linear(n_embd, 3*n_embd)` 一次投影后 `.split(n_embd, dim=2)` 得 q,k,v
- reshape/transpose 到 `(B, n_head, T, hs)`，`hs = C // n_head`
- `self.flash = hasattr(F, 'scaled_dot_product_attention')`，PyTorch 2+ **默认为 True**
- 非 flash 路径：`att = (q @ k.T) * (1/sqrt(hs))` → `masked_fill(tril==0, -inf)` → `softmax` → `att @ v`
- MLP：`Linear(D, 4D) → GELU → Linear(4D, D)`
- Block：pre-LN，`x + attn(ln1(x))`，`x + mlp(ln2(x))`

黄金数字（GPT-2 124M 配置，nanoGPT 默认）：`n_embd=768, n_head=12, n_layer=12, block_size=1024, vocab=50304`。head_dim = 768/12 = **64**，与 Vaswani (d_k) 叙述同构。

---

## File Structure

```
papertrace/
  pyproject.toml
  README.md
  schema/trace.schema.json          # 已存在，本计划冻结
  papertrace/
    __init__.py
    cli.py                          # papertrace build|serve|dump
    schema_validate.py
    ingest/
      repo.py                       # clone / local copy, record commit
      paper.py                      # tex > marker > fail
      arxiv.py                      # download source tarball
    parse_code/
      export_try.py                 # optional torch.export
      fx_trace.py                   # 主路径
      einops_expand.py
      loop_fold.py
      treesitter_fallback.py
      loc.py                        # stack_trace → file:line
    parse_paper/
      units.py                      # stable IDs §3.2-eq3
      split_terms.py                # formula → terms
      latex_safe.py                 # latex2sympy2 容错
    symbols/
      code_table.py
      paper_table.py
      mapping.py
      shape_prop.py
    align/
      embed.py
      retrieve.py
      judge.py                      # yes/no only
      score.py                      # sigmoid 加权
    diff/
      dim.py
      struct.py
      missing.py
      reverse.py
    trace_runtime/
      discover.py
      probe.py                      # CPU forward hooks
      profile.py                    # optional
    detail/
      l0.py                         # 模板，无 LLM
      l1.py
      l2.py
      l3.py
      closure.py
      cache.py                      # sqlite3
      stale.py
    llm/
      client.py                     # OpenAI-compatible, Ollama
      prompts.py                    # 初次 / 深钻 两套，禁止混用
    build_trace.py
  frontend/
    package.json
    src/views/{Paper,Flow,Code}.ts
    src/player/machine.ts
    src/render/svg.ts
    src/panel/{detail,budget,coverage}.ts
    src/jumpTo.ts
  scripts/
    instrument.py
    dump_mermaid.py
    check_vram.py
  tests/
    fixtures/nanogpt/               # 关 flash 的 vendor 副本
    fixtures/papers/vaswani2017/    # tex + 期望公式项
    fixtures/papers/gpt2_report/    # 仅 reverse-diff
    test_schema.py
    test_fx_nanogpt.py
    ...
  data/
    cache.db
    golden/
  output/
```

职责边界：`parse_code` 不知道论文；`parse_paper` 不知道代码；`align` 只吃两侧产物；`frontend` 只吃合法 `trace.json`。`build_trace.py` 是唯一编排入口。

---

## 日历（兼职，助教可打断）

**用户已拍板：工期不管。** 下表只用于估算顺序与依赖，不是承诺，也不是验收条件；不要为了对齐日历去砍功能或用 mock 数据凑里程碑。

按每周有效开发 12–15 小时估。全日可压缩到约 0.55×。

| 里程碑 | 日历 | 必须能看到的东西 |
|---|---|---|
| M0 骨架与夹具 | D1–D2 | 系统 Python 3.13 能跑 `pytest -q` 全绿；nanoGPT flash-off 夹具 + Vaswani attention.tex 就位（**不装 Ollama**） |
| M1a 算子追踪 | D3–D8 | `output/trace.json` 仅 nodes/edges，nanoGPT 算子可数、shape 链不断 |
| M1b 符号 | D9–D12 | `n_embd=768 ↔ D`，每个维度有 `defined_at` |
| M2 图+播放器 | D13–D19 | 中栏+右栏，200 step 连播不卡 |
| M2.5 L0–L2+sqlite | D20–D23 | 改 `GELU` 一行，Attention 节点缓存 100% 命中 |
| M3 论文对齐 | D24–D33 | 点 matmul_qk，左栏亮到 Attention 公式的 QKᵀ 项 |
| M4 L3+四对账 | D34–D40 | 把 n_head 的 KV 改成 GQA，报 struct mismatch + 父 stale |
| M5 单文件+纠正 | D41–D46 | 断网打开 <8MB HTML，纠正写入 annotations 后重算遵守 |
| 缓冲 / golden | D47–D50 | 20–30 对里先做满 8 对 Attention 项 |

**MVP-M3lite（若必须 3 周交差）：** M0+M1a+M1b+「静态 SVG + 公式项锚点 + 本地 HTML」，不做播放器动画、不做 L3、不做批量深钻。A2 的流动画、A8 批量 0.6× 允许延期。不要用 mock 数据假装 M5 完成。

---

### Task 0: M0 环境、仓库骨架、夹具

**Files:**
- Create: `pyproject.toml`, `README.md`, `.python-version` (`3.11`), `.gitignore`
- Create: `papertrace/__init__.py`, `papertrace/cli.py`
- Create: `tests/test_imports.py`（导入全模块 + 桩必须抛 NotImplementedError，取代原定的 test_env.py）
- Create: `tests/fixtures/nanogpt/`（从 karpathy/nanoGPT 复制 `model.py` + 最小 `config`，**改 `self.flash = False`**）
- Create: `scripts/check_vram.py`
- Create: `docs/ENVIRONMENT.md`（可复制的 Python 侧安装命令；Ollama / 7B 移到附录，**不是 M0 步骤**）

**Interfaces:**
- Consumes: 无
- Produces:
  - `python -m papertrace --help` 退出码 0
  - `papertrace.__version__ == "0.1.0"`
  - fixture 模块 `tests.fixtures.nanogpt.model.GPT` 可 import

- [ ] **Step 1: Write the failing test**

```python
# tests/test_env.py
import sys
from pathlib import Path

def test_python_is_3_11():
    assert sys.version_info[:2] == (3, 11)

def test_schema_file_exists():
    p = Path(__file__).resolve().parents[1] / "schema" / "trace.schema.json"
    assert p.is_file() and p.stat().st_size > 1000

def test_nanogpt_flash_disabled():
    from tests.fixtures.nanogpt.model import CausalSelfAttention, GPTConfig
    cfg = GPTConfig(n_embd=768, n_head=12, n_layer=2, block_size=32, vocab_size=64, dropout=0.0, bias=False)
    m = CausalSelfAttention(cfg)
    assert m.flash is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:\\AgentPrograms\\PaperTrace\\.venv\\Scripts\\python.exe -m pytest tests/test_env.py -v`
Expected: FAIL（venv 尚不存在或 flash 仍为 True）

- [ ] **Step 3: 只装 Python 侧依赖（**不要装 Ollama，不要 pull 模型**）**

```bat
winget install Python.Python.3.11
py -3.11 -m venv .venv
.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\pip install pytest jsonschema sympy einops tree-sitter tree-sitter-python lancedb fastapi uvicorn httpx
```

CUDA 索引以本机驱动 621 能装上的官方 cu12x wheel 为准；装完用 `scripts/check_vram.py` 打印 `torch.cuda.get_device_name(0)` 与 total_memory。不要在这一步装 marker/Nougat，也不要装 Ollama（S13：默认 backend=offline）。

- [ ] **Step 4: 复制 nanoGPT fixture 并强制关 flash**

只 vendor `model.py`。把 `self.flash = hasattr(...)` 改为 `self.flash = False`，上方加注释 `# PaperTrace fixture: keep QK^T/scale/mask/softmax as separate ops`。不要 vendor 训练脚本。

- [ ] **Step 5: Run tests, expect PASS; Commit**

```bash
git add pyproject.toml papertrace tests scripts docs/ENVIRONMENT.md schema
git commit -m "chore: M0 env skeleton and nanoGPT fixture with flash off"
```

---

### Task 1: Schema 校验器（trace.json 产品化的第一天）

**Files:**
- Create: `papertrace/schema_validate.py`
- Create: `tests/test_schema.py`
- Modify: `schema/trace.schema.json` 仅当测试证明缺字段（改动必须写进本任务提交说明）

**Interfaces:**
- Consumes: `schema/trace.schema.json`
- Produces:
  - `validate_trace(doc: dict) -> None` 合法则返回，非法抛 `TraceSchemaError`（`errors: list[str]`）
  - `minimal_trace() -> dict` 返回可通过校验的空骨架（nodes/edges 为空数组）
  - `load_trace(path: Path) -> dict` / `dump_trace(doc: dict, path: Path) -> None`

- [ ] **Step 1: Write the failing test**

```python
def test_minimal_trace_passes():
    from papertrace.schema_validate import minimal_trace, validate_trace
    validate_trace(minimal_trace())

def test_missing_source_rejected():
    from papertrace.schema_validate import minimal_trace, validate_trace, TraceSchemaError
    doc = minimal_trace()
    doc["nodes"].append({
        "id": "attn.0.matmul_qk", "level": "op", "op": "aten::matmul",
        "label": "QK^T", "loc": "model.py:1-1",
        "shape_in": [["B","H","T","Dk"], ["B","H","Dk","T"]],
        "shape_out": [["B","H","T","T"]], "dtype": "float32",
        "inplace": False, "degraded": False, "repeat": 1, "stale": False
        # 缺 source
    })
    try:
        validate_trace(doc)
        assert False, "should reject"
    except TraceSchemaError as e:
        assert any("source" in x for x in e.errors)

def test_evidence_empty_rejected():
    ...  # anchors.evidence == "" 必须失败
```

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement `validate_trace` with `jsonschema.Draft202012Validator`**
- [ ] **Step 4: PASS; Commit** `feat: freeze and validate trace.json schema`

---

### Task 2: 仓库 ingest 与入口发现

**Files:**
- Create: `papertrace/ingest/repo.py`
- Create: `tests/test_ingest_repo.py`

**Interfaces:**
- Consumes: 本地路径或 git URL
- Produces:
  - `ingest_repo(src: str | Path, dest: Path) -> RepoMeta`
  - `RepoMeta(url: str, commit: str, language: Literal["python"], entry_module: str | None)`
  - `find_pytorch_modules(root: Path) -> list[Path]` 含 `nn.Module` 子类的 `.py`
  - 非 Python / 找不到 `torch` 导入 → `IngestError` 中文原因

- [ ] **Step 1: 测试本地 fixture 路径返回 7 位以上 commit（无 git 时用 `dirty-<sha256[:12]>`）**
- [ ] **Step 2: 测试空目录、纯 Django 仓库（fixture 一个假 `views.py`）抛 `IngestError`**
- [ ] **Step 3: 实现；Commit** `feat: ingest local or git python repo`

---

### Task 3: M1a 主路径 —— torch.fx 算子图

**Files:**
- Create: `papertrace/parse_code/fx_trace.py`
- Create: `papertrace/parse_code/loc.py`
- Create: `tests/test_fx_nanogpt.py`

**Interfaces:**
- Consumes: 可实例化的 `nn.Module` + 示例输入 `Tensor`
- Produces:
  - `trace_module(mod: nn.Module, args: tuple) -> FxBundle`
  - `FxBundle.nodes: list[NodeDict]` 每项已含 schema 要求的 node 字段（`source="static"`，尚无 detail）
  - `FxBundle.edges: list[EdgeDict]`
  - `count_ops(bundle) -> dict[str, int]`

验收数字（nanoGPT，`n_layer=2, block_size=8, n_embd=32, n_head=4, vocab=64` 的 **tiny** 配置，避免 124M 权重）：

- Attention 非 flash 路径至少出现：`matmul`（QK）+ `mul`（scale）+ `masked_fill` + `softmax` + `matmul`（AV）
- 全图 `shape_consistent` 全为 True，否则测试失败
- 每个 node.loc 匹配 `model.py:\d+`

- [ ] **Step 1: Write failing test `test_attention_ops_are_unfused`**

```python
def test_attention_ops_are_unfused():
    from tests.fixtures.nanogpt.model import GPT, GPTConfig
    from papertrace.parse_code.fx_trace import trace_module, count_ops
    cfg = GPTConfig(n_layer=1, n_head=4, n_embd=32, block_size=8, vocab_size=64, dropout=0.0, bias=False)
    m = GPT(cfg).eval()
    import torch
    x = torch.randint(0, 64, (1, 8))
    bundle = trace_module(m, (x,))
    ops = count_ops(bundle)
    assert ops.get("aten::matmul", 0) + ops.get("aten::mm", 0) + ops.get("call_function.matmul", 0) >= 2
    labels = [n["label"] for n in bundle.nodes]
    assert any("softmax" in (n["op"]+n["label"]).lower() for n in bundle.nodes)
```

- [ ] **Step 2: FAIL because `trace_module` missing**
- [ ] **Step 3: Implement using `torch.fx.symbolic_trace` 或 `torch.fx.Tracer` 自定义；从 `node.meta["stack_trace"]` 填 loc。tiny GPT 若 symbolic_trace 因 `if` 失败，对 `CausalSelfAttention` / `MLP` / `Block` **分别** trace 再按 Block 堆叠，禁止因此改回 flash=True。**
- [ ] **Step 4: 实现 `scripts/dump_mermaid.py` 把 bundle 打成 `flowchart LR` 便于人工看，不进入前端。**
- [ ] **Step 5: PASS; Commit** `feat: fx trace nanoGPT into unfused attention ops`

---

### Task 4: einops 展开与循环折叠

**Files:**
- Create: `papertrace/parse_code/einops_expand.py`
- Create: `papertrace/parse_code/loop_fold.py`
- Create: `tests/test_einops_expand.py`, `tests/test_loop_fold.py`

**Interfaces:**
- Consumes: FxBundle
- Produces:
  - `expand_einops(bundle) -> FxBundle`：`rearrange/reduce/repeat` 字符串走 einops 自己的 parse，展开为 reshape/transpose/expand 节点
  - `fold_repeats(bundle, n_layer: int) -> FxBundle`：trace 层保留 N 组；`repeat=N` 写在代表节点上；`view_state.collapsed` 默认折叠

- [ ] **Step 1: 测试 `'b t (h d) -> b h t d'` 展开后节点数 ≥3，且最终 shape 符号为 `[B,H,T,D]`**
- [ ] **Step 2: 测试 n_layer=12 的折叠：默认 `view_state.collapsed` 含 block 前缀，`repeat==12`**
- [ ] **Step 3: 实现（解析逻辑 import einops 内部 parse，禁止手写正则作为主路径）**
- [ ] **Step 4: PASS; Commit** `feat: expand einops and fold repeated blocks`

---

### Task 5: tree-sitter 降级

**Files:**
- Create: `papertrace/parse_code/treesitter_fallback.py`
- Create: `tests/test_degraded.py`

**Interfaces:**
- `fallback_ast(path: Path, fn_name: str) -> FxBundle` 节点全部 `degraded=True` 且 `degraded_reason` 非空
- fx 失败时 `trace_module` 捕获异常并调用 fallback，不得让 CLI 崩溃

- [ ] **Step 1: 用一段含 `if tensor.sum() > 0` 的假 Module 断言结果 `degraded is True`**
- [ ] **Step 2: 实现；Commit** `feat: tree-sitter fallback marks degraded nodes`

---

### Task 6: M1b 符号表与 shape 传播

**Files:**
- Create: `papertrace/symbols/code_table.py`, `shape_prop.py`, `mapping.py`
- Create: `tests/test_symbols_nanogpt.py`

**Interfaces:**
- `build_code_symbols(mod, bundle) -> list[CodeSymbol]`
- `propagate_shapes(bundle, symbols) -> FxBundle` 原地填 `shape_in/out`
- 符号名冻结：`B, T, D, H, Dh`（Dh = D/H）。nanoGPT：D=n_embd, H=n_head, Dh=head_dim, T=block_size

- [ ] **Step 1: 测试**

```python
def test_n_embd_maps_to_D_768_on_full_config():
    # 用 GPT-2 124M 数字但 n_layer=1 避免图过大
    ...
    assert any(s.var.endswith("n_embd") and s.symbol == "D" and s.value == 768 for s in symbols)
    assert any(s.symbol == "Dh" and s.value == 64 for s in symbols)
    assert all(s.defined_at for s in symbols)
```

- [ ] **Step 2: 任一边 shape 推不出 → 该边 `shape_consistent=False`，不得填 `None` 冒充成功**
- [ ] **Step 3: 实现；Commit** `feat: sympy shape table for nanoGPT dims`

---

### Task 7: CPU 运行时探针（runtime source）

**Files:**
- Create: `papertrace/trace_runtime/probe.py`, `discover.py`
- Create: `tests/test_probe_cpu.py`

**Interfaces:**
- `run_forward(mod, args, device="cpu") -> ProbeLog`
- `ProbeLog.by_module: dict[str, {shape_in, shape_out, dtype, amin, amax}]`
- 回填到对应 node：能匹配的 node `source="runtime"`
- 失败：`meta.runtime = {ok:false, reason, device}`，节点保持 static

- [ ] **Step 1: 测试 tiny GPT CPU forward 后 Attention 输出 shape `[1,8,32]`**
- [ ] **Step 2: 测试故意缺权重 / 错误 vocab 时不抛到 CLI，写 reason**
- [ ] **Step 3: 实现 register_forward_hook，不要默认开 profiler**
- [ ] **Step 4: Commit** `feat: cpu forward probes mark runtime source`

---

### Task 8: M2 前端 —— 图、播放器、右栏代码

**Files:**
- Create: `frontend/package.json`, `frontend/src/jumpTo.ts`, `frontend/src/player/machine.ts`, `frontend/src/render/svg.ts`, `frontend/src/views/Flow.ts`, `frontend/src/views/Code.ts`
- Create: `frontend/src/loadTrace.ts`
- Test: `frontend/src/player/machine.test.ts`（vitest）

**Interfaces:**
- `jumpTo(target: {paperUnitId?: string, symbolId?: string, stepIndex?: number}): void` 唯一滚动入口
- `PlayerState = {step: number, playing: boolean, speed: number}`
- `tick(now: number): PlayerState` 由 rAF 调用，禁止 `setTimeout` 推进 step
- 三级缩放 `zoom: "stage"|"module"|"op"`，默认 `"module"`
- 本任务**不实现左栏论文**（用空态「未接入论文」）。禁止用假公式占位。

- [ ] **Step 1: vitest `test_player_advances_monotonic`：speed=1 连播 200 step，step 从 0 到 199，无回跳**
- [ ] **Step 2: 实现 SVG 节点/边；当前 step 描边加粗；经过的边 `stroke-dashoffset`**
- [ ] **Step 3: 右栏用 `loc` 切片源码，高亮当前表达式行**
- [ ] **Step 4: 视觉：source 角标；degraded 虚线框；语义色最多 3 个（绿置信 / 黄待核 / 橙红 mismatch）。播放器控件不要渐变发光粒子。**
- [ ] **Step 5: Commit** `feat: svg player and code pane from trace.json`

---

### Task 9: M2.5 L0–L2 与 sqlite 缓存

**Files:**
- Create: `papertrace/detail/l0.py`, `l1.py`, `l2.py`, `cache.py`, `closure.py`
- Create: `papertrace/llm/client.py`, `prompts.py`
- Create: `tests/test_cache_hit.py`, `tests/test_l0_no_llm.py`

**Interfaces:**
- `render_l0(node) -> DetailLayer` **不得调用 llm.client**
- `cache_key(commit, closure_src, paper_unit, level, model, prompt_version) -> str`
- `Cache.get/set(key, raw_response, node_id, level)` sqlite 表 `(key TEXT PK, level, node_id, raw_response, created_at)`
- `closure(node_id, bundle, paper_units) -> Closure` 五项并集，缺「N 外变量赋值」视为 bug

- [ ] **Step 1: `test_l0_does_not_call_llm` 给 fake client，断言 call_count==0**
- [ ] **Step 2: `test_unrelated_edit_cache_hit`：改 MLP.GELU 为 SiLU 后重算，Attention 节点 key 不变、命中率 100%**
- [ ] **Step 3: L2 文本由算子序列模板生成（「matmul [B,H,T,Dk]×[B,H,Dk,T]→[B,H,T,T]」），LLM 只可选生成一句解释，失败则只有模板**
- [ ] **Step 4: Commit** `feat: templated L0-L2 and sqlite closure cache`

---

### Task 10: 论文 ingest（TeX 优先）

**Files:**
- Create: `papertrace/ingest/arxiv.py`, `paper.py`
- Create: `papertrace/parse_paper/units.py`, `split_terms.py`, `latex_safe.py`
- Create: `tests/fixtures/papers/vaswani2017/attention.tex`（只抽 Attention 一节的最小 tex，不要整本 15 页除非已下载）
- Create: `tests/test_split_attention_formula.py`

**Interfaces:**
- `ingest_paper(src: str) -> PaperBundle` `src` 可以是 `arxiv:1706.03762`、本地 `.tex`、本地 `.pdf`
- 优先级：本地 tex → arXiv source tarball → marker PDF。全部失败：`ingest_mode` 记原因，`unit_count=0`
- `split_formula(latex: str) -> list[Term]` 停止条件：matmul / 逐元素缩放 / 归一化 / 激活 / 转置 / concat 各算一项
- `latex_to_sympy_safe(latex) -> {ok, expr | None, raw}` 失败保留 raw，该公式不拆项并进 unresolved

Vaswani 注意力公式必须拆出至少 4 项：QKᵀ、/√d_k、softmax、×V。稳定 ID 例：`§3.2-eq-attn-t0..t3`。

- [ ] **Step 1: 测试拆项数量与 term latex 片段**
- [ ] **Step 2: 测试坏 latex `\\unknownmacro{x}` 不抛、`ok=False`**
- [ ] **Step 3: 实现；v1 不装 Nougat。marker 作为 extra optional dependency `papertrace[pdf]`**
- [ ] **Step 4: Commit** `feat: tex-first paper units and attention term split`

---

### Task 11: M3 三步对齐（禁止生成题）

**Files:**
- Create: `papertrace/align/embed.py`, `retrieve.py`, `judge.py`, `score.py`
- Create: `tests/test_align_judge_yesno.py`, `tests/test_align_no_generation.py`
- Create: `papertrace/llm/prompts.py` 中 `JUDGE_PROMPT` / `DRILL_PROMPT` 常量

**Interfaces:**
- `embed_texts(texts: list[str]) -> np.ndarray` 调 Ollama embeddings `nomic-embed-text`
- `retrieve_bidirectional(code_units, paper_terms, k=5) -> dict[id, list[Hit]]`
- `judge(term: Term, snippet: str) -> JudgeResult`
  - `JudgeResult(yes: bool, evidence: str)`
  - 解析模型输出只允许首 token 级 yes/no（大小写不敏感）；evidence 截断 40 字
  - **函数签名不得出现 `mapping: dict` 这种由模型一次生成的结构**
- `confidence(s_retr, s_judge, s_struct) -> float` 使用冻结权重
- 双向冲突：两个方向结论相反 → 两者都降为黄或 unresolved，不得取平均抬过 0.75

- [ ] **Step 1: `test_judge_prompt_is_yes_no` 断言 prompt 含「只能回答 yes / no」且不含「请列出对应关系」**
- [ ] **Step 2: 用假检索把 softmax 项与 `F.softmax(att, dim=-1)` 对上，c≥0.75；把 softmax 项与 `nn.Linear` 对上，c<0.45 进 unresolved**
- [ ] **Step 3: grep 守卫：`tests/test_align_no_generation.py` 读取 `papertrace/align/*.py` 源码，禁止出现 `generate_alignment` / `自由` / `对应关系如下` 等**
- [ ] **Step 4: 前端接左栏 KaTeX + `\\htmlId{term-...}`；`jumpTo({paperUnitId})` 三栏同步**
- [ ] **Step 5: Commit** `feat: bidirectional retrieve-judge-score alignment`

---

### Task 12: 四类对账

**Files:**
- Create: `papertrace/diff/dim.py`, `struct.py`, `missing.py`, `reverse.py`
- Create: `tests/test_diff_gqa.py`, `tests/test_diff_reverse.py`

**Interfaces:**
- `run_diff(trace) -> list[Mismatch]` type ∈ {dim, struct, missing, reverse}
- severity：影响数值 high；只影响结构 medium；可读性 low
- 反向对账规则表（v1 写死检测器，不靠 LLM）：weight tying（`wte.weight is wte` 或 `lm_head.weight is wte.weight`）、bias=False / 零初始化、pre-LN vs post-LN、causal mask 实现（tril vs 显式 -inf）、flash fusion 是否发生

- [ ] **Step 1: 把 fixture Attention 改成 GQA（`n_kv_head=2, n_head=8`）且注释仍写 Multi-Head，断言存在 `type=="struct"` 且 severity 为 high 或 medium**
- [ ] **Step 2: 对 nanoGPT 断言至少 1 条 reverse（pre-LN 或 bias 或 weight tying，以实际代码为准）**
- [ ] **Step 3: 维度：人为把 head_dim 写成 96 而论文 Dh=64，报 dim**
- [ ] **Step 4: Commit** `feat: four-way paper-code diff with GQA trap`

---

### Task 13: L3 三项验证 + stale

**Files:**
- Create: `papertrace/detail/l3.py`, `stale.py`
- Create: `tests/test_l3_required_fields.py`, `tests/test_stale_parent.py`
- Modify: `papertrace/llm/prompts.py` 追加 `DRILL_PROMPT`（必须含「已知父节点结论为 X，请核对 Y，不成立给反例」）

**Interfaces:**
- `drill_l3(node_id, question: str | None) -> DetailL3` 缺 probe / equivalent / adversarial 任一字段则抛，不得写入
- `equivalent`: 公式项 sympy 与代码片段 sympy（经 `latex_safe` + 手工 aten→sympy 表）`simplify(a-b)==0`
- `probe`: 对该算子 CPU 随机输入，记录 shape/dtype/range
- `adversarial`: LLM 二次询问；若 LLM 不可用，用规则清单（scale 位置、mask 时机、dtype 提升）填 `checked`，`conclusion="unknown"`，**不算失败**
- 与父 L0/L1 文案矛盾 → `conflicts.append` + `parent.stale=True`

- [ ] **Step 1: 构造缺 probe 的假写入，校验器或 `drill_l3` 必须拒绝**
- [ ] **Step 2: GQA 陷阱上跑 L3，父 Attention L0 若仍写「标准 MHA」则 stale**
- [ ] **Step 3: FastAPI `POST /drill` SSE 流式吐字；静态 HTML 断网仍能看已有 L0–L2**
- [ ] **Step 4: Commit** `feat: L3 probe+sympy+adversarial and stale parents`

---

### Task 14: M5 单文件导出、纠正、未定位清单

**Files:**
- Create: `frontend` singlefile 构建配置
- Create: `papertrace/detail/annotations.py`
- Create: `tests/test_annotations.py`, `tests/test_html_size.py`
- Modify: `papertrace/cli.py` `build` 写出 `output/index.html` + `output/trace.json`

**Interfaces:**
- `apply_annotation(trace, ann) -> dict` 追加 annotations；重算时注入 prompt 前置段
- 覆盖率文案：「全局仍有 N 个节点停留在 L0/L1」
- 预算条：预估 token / 秒 / 新缓存条目；算子 >300 必须确认（CLI `--yes` / 前端弹窗）
- HTML 体积 `< 8_000_000` 字节；KaTeX 只内联实际用到的字体子集；图片不内联

- [ ] **Step 1: 纠正「scale 在 softmax 后」为「scale 在 softmax 前」后，L3 文本含该纠正且说明一致性**
- [ ] **Step 2: 至少一个 unresolved 出现在 UI 清单，而不是被画成绿线**
- [ ] **Step 3: 断网复制 html 到临时目录用文件协议打开（playwright 或手工清单）**
- [ ] **Step 4: Commit** `feat: single-file html export and user corrections`

---

### Task 15: Golden set 与对照组

**Files:**
- Create: `data/golden/README.md`, `data/golden/attention_vaswani.json`
- Create: `scripts/eval_align.py`
- Create: `tests/test_golden_smoke.py`

**Interfaces:**
- 每条 golden：`{paper_term, code_range, expect: match|mismatch|unresolved}`
- v1 先做满 **8 条** Attention 项（QK、scale、mask、softmax、AV、c_attn split、c_proj、残差 add）
- 对照组：同一 8 条直接问通用模型「公式 X 对应哪一行」，脚本打分，写入 `data/golden/baseline.md`
- 工具赢不了对照组 → **不得宣称 A3 通过**，只能写 unresolved 率

- [ ] **Step 1: 落地 8 条人工标注**
- [ ] **Step 2: 评估脚本可在无 UI 下跑**
- [ ] **Step 3: Commit** `test: golden attention pairs and baseline harness`

---

## CLI 契约（一次性冻结）

```
python -m papertrace build --repo <path|url> --paper <arxiv:ID|path> --out output/
python -m papertrace dump --trace output/trace.json --mermaid output/debug.mmd
python -m papertrace serve --trace output/trace.json --host 127.0.0.1 --port 8765
python -m papertrace eval --golden data/golden
```

`build` 成功条件：写出通过 `validate_trace` 的 json；前端可缺论文（unresolved 会很多）但不得缺 nodes。失败：非零退出，stderr 中文。

环境变量：

- `PAPERTRACE_LLM` 默认 `qwen2.5-coder:7b`
- `PAPERTRACE_EMBED` 默认 `nomic-embed-text`
- `PAPERTRACE_DEVICE` 默认 `cpu`（探针）
- `PAPERTRACE_OLLAMA` 默认 `http://127.0.0.1:11434/v1`

---

## 置信度与结构信号（实现时写死，禁止让模型自己打分）

`s_retr`：双向 Top-5 的 max cosine，clip 到 [0,1]
`s_judge`：yes=1.0 / no=0.0（证据为空则强制 0）
`s_struct` 初值 0.5，加减：

- +0.2 论文「N 层」且代码 `range(n_layer)`
- +0.1 超参名在 config 出现
- +0.2 算子序列与公式项顺序同构（matmul→scale→softmax→matmul）
- -0.4 shape 与论文声明冲突
- -0.3 双向检索 top1 不是同一对

`c = 1/(1+exp(-(0.3*s_retr+0.5*s_judge+0.2*s_struct)))`

---

## 风险登记（规格表 20-1 的工程化）

| 风险 | 本计划的具体闸门 |
|---|---|
| Token 爆炸 | L0 零 LLM；检索 Top-5 不塞全文；sqlite；预算条 |
| 幻觉 | 判断题；evidence 必填；前端点开即源码；禁止生成对齐 |
| 项级天花板 | unresolved 是功能不是缺陷；golden 8 条先测天花板 |
| 局部正确整体错 | 覆盖率常驻 |
| prompt 混用 | `JUDGE_PROMPT` vs `DRILL_PROMPT` 两个常量，drill 必须带父结论 |
| fx / latex2sympy2 脆 | 三级降级；raw LaTeX 始终保留 |
| HTML 体积 | M5 测试卡 8MB |
| 无评估 | Task 15；对照组是存在理由 |
| 14B OOM | S1，默认 7B |
| deepwiki 底座跑偏 | S2 |
| 黄金论文选错 | S5 |
| 时间碎 | MVP-M3lite 可交差，禁止用假数据齐活 |

---

## 验收映射

| 规格 | 本计划 Task | 备注 |
|---|---|---|
| A1 5 分钟出 HTML | 14，依赖 0–11 | 计时从 CLI 调用起，不含首次模型下载（若启用）；框架切片下 backend=offline，下载为零 |
| A2 播放+shape | 8 + 7 | MVP 可降级为无动画仍显示当前节点 |
| A3 项级同步 | 11 + 10，论文是 Vaswani | 规格写 GPT-2 论文，见 S5 |
| A4 来源可见 | 1 + 8 | |
| A5 诚实降级 | 5 + 11 | |
| A6/A12 断网 | 14 | serve 不是验收路径 |
| A7 零外部 API 费 | 0，只走 Ollama | |
| A8 批量 0.6× | 13，可后置 | |
| A9 缓存 100% | 9 | |
| A10 GQA stale | 12 + 13 | |
| A11 纠正生效 | 14 | |
| A12 离线浏览层级 | 14 + 9 | |

---

## Self-Review（对照规格）

- 规格要算子级：Task 3 用关 flash 的 fixture 钉死，避免 SDPA 融合。
- 规格要三步对齐：Task 11 有源码 grep 守卫，防止「先写生成再重构」。
- 规格要反向对账：Task 12 写死检测器，不把最重要的差异化功能交给 LLM。
- 规格要闭包第五项：Task 9 测试必须包含 `n_embd` 定义在 `__init__` / `GPTConfig`。
- 规格要 detail 只追加：schema additionalProperties + 校验器。
- 规格目录 17 章已映射到 File Structure；FastAPI 降级为 serve。
- 规格附录 A/B 提示词不在本计划展开复制；实现时 `prompts.py` 从规格附录迁移，**初次与深钻不得共用**。
- 已知接受的缺口（规格附录 C）：项级准确率有天花板；中文公式不稳（v1 主路径英文 TeX）；非 PyTorch 无 runtime。

## 给执行者的开始命令

先不要写前端，不要装 marker。按 Task 0 → 1 → 3 的顺序。Task 3 绿之前禁止开 Task 8。论文侧 Task 10 在 M2.5 绿之前禁止合并到 main 的 `build` 默认路径。
