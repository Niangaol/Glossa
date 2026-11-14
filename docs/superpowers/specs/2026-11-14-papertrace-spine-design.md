# PaperTrace 端到端脊柱 · 设计文档

日期：2026-11-14　状态：**待年糕审批**（获批前不写产品代码）
上游规格：`PaperTrace_技术规格书.docx` → `docs/superpowers/plans/2026-11-14-papertrace-engineering-plan.md`（S1–S14 已吸收）
已完成基线：M1a，HEAD `e71d613`，448 passed，第十七轮评审「Critical 0，M1a 必修项为空」

## 1. 这份文档要解决什么

年糕的指令（m03732）：「绿栈后面加上 先跑通 然后开始施工写一个」。拆成三件事：

1. **绿线加门**（U1 已拍板，m03751）：`c ≥ 0.75` 且 `s_struct ≥ 0.5` 才连绿实线。
2. **先跑通**（已选 B 方案，m03751）：搭一条端到端脊柱，每段真跑、空的显式标空。
3. **写一个 plan**：本文档获批后产出 `docs/superpowers/plans/2026-11-14-papertrace-spine.md`。

明确**不在**本切片内：M1b 的符号 shape 传播（`symbols/shape_prop.py`）、论文 PDF/arXiv 联网 ingest、
双向检索的向量模型、L1/L2/L3 深钻、播放器动画、`serve`/`eval`。这些留给后续里程碑。

## 2. 一个必须先讲清的数学事实

权重是冻结的：`w_retr=0.30 / w_judge=0.50 / w_struct=0.20`，`c = sigmoid(4·(a−0.5))`。
`OfflineBackend.chat` 与 `.embed` 都抛 `LLMUnavailable`（S13，防假 yes／假向量）。实测：

| 场景 | s_retr | s_judge | s_struct | a | c | 旧分档 | 加门后 |
|---|---|---|---|---|---|---|---|
| 全 offline（结构满分） | 0 | 0 | 1 | 0.200 | **0.2315** | none | none |
| 词法满分但无 judge | 1 | 0 | 1 | 0.500 | 0.5000 | yellow | yellow |
| judge=yes 但无 embedding | 0 | 1 | 1 | 0.700 | **0.6900** | yellow | yellow |
| judge=yes + 弱检索 0.25 | 0.25 | 1 | 1 | 0.775 | 0.7503 | green | green |
| 三项全满 | 1 | 1 | 1 | 1.000 | 0.8808 | green | green |
| **U1 反例** | 1 | 1 | **0** | 0.800 | 0.7685 | **green** | **yellow** |

三条结论，直接决定脊柱的形状：

- **默认 offline 跑脊柱，一条线都连不出来**，四项公式全进 `unresolved`。这不是 bug，是权重决定的：
  `s_struct` 只占 0.20，满分也只到 0.2315。脊柱在 offline 下要证明的是「每一段都真跑了、空态有原因」，
  不是「画出了绿线」。这正是 Global Constraints 要求的「拿不到就空态+原因，禁止 mock 填界面」。
- **只要 judge 能答 yes，即使没有 embedding，也能连出黄虚线（0.6900）**。所以「点亮」不需要向量模型，
  一个能回答 yes/no 的生成后端就够看到线。
  - **但 judge 的 `(term, snippet)` 候选对从哪来？**（builder-check 第 2 问，原设计漏了）
    链路是 S6 retrieve → S7 judge，而 DeepSeek 无 embeddings → S6 命中为空 → judge 没有输入。
    **决定：候选对由 S5 的结构同构确定性产生**，不是由检索产生。S5 已经在做
    `matmul→scale→softmax→matmul` 的子序列匹配，匹配成功时它天然知道「t0 对应哪个 op 节点」。
    把这份对应关系作为 `StructSignal.pairs` 输出，S7 **只对这些配对**问判断题。
    Vaswani 四项 → **4 次 API 调用**，不是 4×94≈376 次全配对。
  - **这不是 S15**：S15 是词法相似度检索（TF-IDF/n-gram cosine），这里用的是已经算出来的
    结构同构，零额外依赖、零额外调用、完全确定性。
  - **诚实代价（必须写进 README）**：judge 的候选**以结构为前提**，所以 `s_judge` 与 `s_struct`
    不是完全独立的证据。结构完全对不上时没有候选 → `s_judge=0`，judge **救不回一个结构错配**。
    这是设计取舍：宁可少连线，也不花 376 次调用去猜。
- **绿线需要 s_retr ≥ 0.249**（judge=1、struct=1 时）。DeepSeek 没有 embeddings 端点，
  所以「只配 openai 后端」的现实结果是黄线，不是绿线。这一点必须写进 README，不能让人以为配了 key 就绿。

## 3. 架构：一条直线，十个可独立验收的段

```
build --repo tests/fixtures/nanogpt --paper tests/fixtures/papers/vaswani2017/attention.tex
  │
  ├─[已有 M1a] trace_module → nodes/edges（真实形状，source=runtime）
  │
  ├─ S2 ingest_paper(本地 .tex)      → PaperBundle(ingest_mode="tex", unit_count=1)
  ├─ S3 split_formula(latex)         → Term[t0..t3]（稳定 ID S3.2-eq-attn-t0..t3）
  ├─ S4 build_code_symbols/paper_table/map_symbols → symbols.{code,paper,mapping}
  ├─ S5 struct_signal(算子序列, 公式项, config) → s_struct（确定性，无 LLM）
  ├─ S6 retrieve_bidirectional(...)  → s_retr（offline → 0 + 原因）
  ├─ S7 judge(term, snippet)         → s_judge（offline → 0 + 原因）
  ├─ S1 confidence(...) + tier(c, s_struct) → green / yellow / none
  ├─ S9 组装 anchors / unresolved / mismatches → validate_trace → trace.json
  └─ S10 render_html(trace) → output/index.html（单文件、离线、<8MB）
```

**S8（openai 兼容后端）是横切开关**：不改变上面任何一段的结构，只让 S6/S7 从「抛 LLMUnavailable」
变成「真拿到回答」。默认 offline，配了环境变量才走它。

### 3.1 数据契约的唯一改动（S16 修订，需批准）

`schema/trace.schema.json` 的 `anchor` 目前**没有地方存分档结果与三个信号**。
渲染 HTML 时若只有 `confidence`，就无法执行 `s_struct ≥ 0.5` 这道门——门会长在错的地方。
所以给 `anchor` 增加两个**可选**字段：

```jsonc
"tier": { "enum": ["green", "yellow", "none"] },
"signals": {
  "type": "object",
  "required": ["s_retr", "s_judge", "s_struct"],
  "properties": {
    "s_retr":   { "type": "number", "minimum": 0, "maximum": 1 },
    "s_judge":  { "type": "number", "minimum": 0, "maximum": 1 },
    "s_struct": { "type": "number", "minimum": 0, "maximum": 1 }
  }
}
```

- **可选**，所以旧 trace 仍然合法；`schema_version` 保持 `1.0.0`（纯增量，不破坏既有 448 条测试）。
- `schema_structure.structural_errors` 增加一条不变量：**有 `tier` 就必须有 `signals`，
  且 `tier` 必须等于 `tier(confidence, signals.s_struct)` 的重算结果**。防止有人手改 trace 把黄线涂绿。
- `c < 0.45` 的项**不产生 anchor**，只进 `unresolved`（规格原文）。所以 `tier="none"` 的 anchor
  只在「备选/降级」场景出现；脊柱默认不写它。

### 3.2 绿线门的准确语义

```python
GREEN_STRUCT_MIN = 0.5   # constants.py 新增

def tier(confidence: float, s_struct: float) -> str:
    if confidence >= CONF_GREEN and s_struct >= GREEN_STRUCT_MIN:
        return "green"
    if confidence >= CONF_YELLOW:
        return "yellow"
    return "none"
```

- 门**只降不升**：它把本该绿的降成黄，绝不会把黄抬成绿。
- 被门降级的项，`evidence` 里要写明原因（例如「结构信号 0.20 < 0.50，绿线降级为黄」），
  否则用户看到黄线不知道为什么。`evidence` 上限 80 字符（schema），生成时截断到 40（规格）。
- **不采纳**工程计划书 :28 提的另一半修法「`s_judge==0` 直接判 <0.45」——年糕只批了前半。
  而且实测 `judge=0, retr=1, struct=1 → c=0.5000` 本来就是黄，不需要额外规则。

## 4. 各段的诚实边界（空就是空）

| 段 | offline 默认行为 | 写进 trace 的东西 |
|---|---|---|
| S2 ingest | 本地 `.tex` 真解析；`.pdf`/`arxiv:` 抛 **`IngestError`**（不是 NotImplementedError），由 S9 接住 | `.tex` → `ingest_mode="tex"`；其余 → **CLI exit 0** + `unit_count=0` + `ingest_mode="none"` + `unresolved{kind:paper_unit}` 带原因 |
| S3 split | Vaswani 四项真拆；坏 LaTeX → `ok=False` | 拆不出的整式进 `unresolved`，**不猜项** |
| S4 symbols | 代码侧从 nanoGPT config 真取；论文侧从 tex 真取 | `defined_at` 必填；value 冲突 → `status="value_mismatch"`，不静默取一个 |
| S5 struct | 完全确定性，offline 也能满分 | `s_struct` + 命中的规则列表（进 evidence） |
| S6 retrieve | `LLMUnavailable` → `s_retr=0` | `unresolved` 原因写「offline 后端不提供 embedding」 |
| S7 judge | `LLMUnavailable` → `s_judge=0` | 同上；**证据为空强制 0**（规格原文） |
| S9 anchors | 四项全 `c=0.2315` → **0 个 anchor** | 4 条 `unresolved{kind:paper_unit}` + 代码侧未对齐节点 |
| S10 HTML | 真渲染：代码图 + 公式项 + 未对齐清单 | 无绿线；`unresolved` 必须出现在 UI 清单里 |

**测试替身只出现在 tests/ 里**，用来钉住「后端答 yes 时分档正确」。产品代码路径上没有任何 mock：
`build` 出来的 trace 里每个结论都带 `source ∈ {runtime, static, model}`，拿不到就空态。

## 5. 依赖与接口修正

`pydeps/` 实测可用：**sympy 1.14.0 + mpmath 1.4.1**、**jinja2 3.1.6 + markupsafe**（S10 模板，零新依赖）、
jsonschema、pytest、torch 2.15.0+cpu。

**⚠️ 原文写「sympy 对 S3 的安全 LaTeX 够用」是错的，已被 builder-check 实测证伪**：
`from sympy.parsing.latex import parse_latex` 能 import，但**调用**抛
`ImportError: LaTeX parsing requires the antlr4 Python package … version 4.11`；
`parse_latex_lark` 同样缺 lark。`pydeps/` 里 **antlr4 与 lark 都不存在**。
sympy 本体在，缺的是它的 **LaTeX 前端**。

**决定：不引入 antlr4/lark，S3 改手写结构化拆项**（见 §10 第 3 条）。
`latex_to_sympy_safe` **不用 `parse_latex`**，改成「白名单宏 → sympy 可解析串」的小型显式翻译器
＋ `parse_expr(..., local_dict=…)`；超出文法一律 `ok=False, expr=None, raw=原串`。

**没有 numpy**（`pydeps/` 里；系统 site-packages 有 2.5.4 但**禁止依赖**，那是环境侥幸），
也没有 requests。两条硬约束：

- **S17 接口修正**：工程计划书 Task 11 写的 `embed_texts(texts) -> np.ndarray` 无法实现（无 numpy）。
  改为 `embed_texts(texts: list[str]) -> list[list[float]]`。cosine 用纯 Python 算，量级是几十条文本，够用。
  这是接口修正不是降级，需批准。
- **S8 用 `urllib.request`**（标准库）发 HTTP，不引入 requests。超时、非 200、JSON 解析失败
  一律翻成 `LLMUnavailable` 并带上原因，**绝不返回假 yes**。

## 6. 待批修订汇总（不静默采纳）

| 编号 | 内容 | 为什么需要 | 状态 |
|---|---|---|---|
| **U1** | 绿线加 `s_struct ≥ 0.5` 门 | 结构不符也能连绿线（0.7685） | **已批**（m03751） |
| **S16** | `anchor` 增加可选 `tier` + `signals`；结构校验钉住一致性 | 否则门没有落脚点，HTML 无法执行门 | **已批**（m03858） |
| **S17** | `embed_texts` 返回 `list[list[float]]` 而非 `np.ndarray` | 本机无 numpy | **已批**（m03858） |
| **S15** | 词法检索基线（TF-IDF/字符 n-gram cosine）作为 offline 下的 `s_retr` 来源 | 能让 offline 也出现黄线；但偏离「embedding 用 nomic-embed-text」 | **待批，本计划不含此任务** |
| **S18** | 脊柱阶段公式用等宽原始 LaTeX 文本 + 静态 SVG，**KaTeX `\htmlId` 推迟到 M2 前端** | 全仓无 KaTeX 资产（glob 实测为空），零新依赖 + 禁外链 + <8MB 三条同时成立时拿不到字体子集；vendoring 是独立前置任务 | **已批**（m03858，偏离冻结规则 :75） |
| **S19** | judge 解析按现有 `prompts.py` 的**两行格式**（`Verdict: yes\|no` / `Evidence: …`），把计划书 :547 的「首 token 级 yes/no」澄清为「**Verdict 行取值的首 token**」 | 两份冻结文本冲突：按 :547 字面解析整个响应的首 token 会拿到 `Verdict:` → 真实 DeepSeek 全判失败 → 黄线出不来；且首 token 解析拿不到 evidence，而 evidence 必填、为空强制 0 | **已批**（m03858，澄清不是违反） |

S15 我**没有**放进任务列表。它偏离冻结的 Global Constraint，必须你点头才做。
不批的话，offline 就是全 unresolved，这是诚实的结果。

**审批记录（m03858）**：年糕批准施工，S16/S17/S18/S19 **四条全批**，执行方式选 **Subagent-driven**（派子智能体逐 Task 做 + 每 Task 独立评审）。S15 仍未批、不在计划内。

## 7. 点亮路径（你只需要三个环境变量）

```powershell
$env:PAPERTRACE_LLM_BACKEND = 'openai'
$env:PAPERTRACE_OPENAI_BASE_URL = 'https://api.deepseek.com'
$env:PAPERTRACE_OPENAI_API_KEY = '<你的 key>'
$env:PAPERTRACE_LLM = 'deepseek-chat'
```

配好后重跑同一条 build 命令：S5 结构同构给出 4 个候选对 → judge 真答 yes/no（4 次调用）
→ `s_judge=1` → `c=0.6900` → **黄虚线**。
要绿线还需要 `s_retr ≥ 0.249`，即 S15 或一个真的 embedding 端点。
**不配 key 也能跑通**，只是全 unresolved——这是设计，不是失败。

前提：S5 的结构同构必须命中（夹具已实测命中，`masked_fill` 作为多余算子被允许）。
结构对不上就没有候选对，judge 不会被调用，`s_judge=0`——见 §2 的诚实代价。

## 8. 验收标准（脊柱「跑通」的定义）

1. `python -m papertrace build --repo tests/fixtures/nanogpt --paper tests/fixtures/papers/vaswani2017/attention.tex --out output/spine --force` → **exit 0**
2. `output/spine/trace.json` 通过 `validate_trace`；`symbols.code` 含 B/T/D/H/Dh 且每个有 `defined_at`；
   `meta.paper.ingest_mode == "tex"`、`unit_count == 1`
3. offline 下：`anchors == []`，`unresolved` 含 4 条 `paper_unit`（t0..t3）且每条 `reason` 非空
4. `output/spine/index.html` 单文件、**无任何 http(s) 外链**、`< 8_000_000` 字节、`file://` 打开可用；
   未对齐清单在 UI 里可见
5. 注入一个实现 `LLMBackend` 协议的测试后端答 yes → 出现 `tier="yellow"` 的 anchor（`c=0.6900`）；
   令 `s_struct=0` 且 `c=0.7685` → `tier="yellow"` 而非 green（U1 守门）
6. **更新后全量测试全绿**，新增测试全绿；单源文件 ≤200 行；每个 Task 一次提交。
   「448 条一字不动」是**不可达**的：既有测试里有 3 处专门钉住桩行为，实现后必然打破
   （`tests/test_imports.py:72-84`、`tests/test_llm_offline.py:30-36`、`tests/test_cli.py:101-111`）。
   这 3 处**按新事实改写，不是删掉**，改写清单见实施计划 S11。
7. `build` 不带 `--paper` 时行为与 M1a **逐项一致**（nodes=128/edges=101/counts 全同）

## 9. 留给 builder 的决定

- 各文件内部的具体切分与命名（只要 ≤200 行、职责单一）
- jinja2 模板的具体排版与配色（绿实线/黄虚线/灰不连的视觉区分必须清楚）
- 测试夹具的组织方式（沿用 `tests/_tmp.py::scratch_dir`，不用 `tmp_path`）
- S5 结构信号各条规则的实现细节（规则本身与权重已在工程计划书 :663-669 冻结）

## 10. builder-check 的五个问题与我的决定（2026-11-14，独立子智能体只读审查）

派 `spine-builder-check` 按 brainstorming 技能要求审这份设计。它报了 5 个「还得猜且猜错会影响计划」的问题，
**我逐条自己实测复核，5 条全部成立**。这不是措辞 nitpick，是会让施工卡死或验收不可达的缺口。

| # | 问题 | 我的复核证据 | 决定 |
|---|---|---|---|
| 1 | 验收「448 条全绿」与实现范围矛盾；§4 的 S2 行自相矛盾 | `tests/test_imports.py:72-84` 断言 judge/retrieve/embed 抛 `NotImplementedError`；`tests/test_cli.py:101-111` 断言 `--paper arxiv:` → exit 2 +「论文 ingest 尚未实现」；`tests/test_llm_offline.py:30-36` 断言 openai 也返回 offline | **允许改写这 3 处**，验收改成「更新后全绿」；S2 行统一为 `IngestError` → CLI exit 0 + 诚实空态（函数内响亮拒绝，CLI 落成带原因的空态，与全项目一致） |
| 2 | 无 embedding 时 judge 的候选对从哪来 | 链路 S6→S7，DeepSeek 无 embeddings → S6 空 → judge 无输入；全配对是 4×94≈376 次调用 | **S5 结构同构产出 `pairs`，S7 只判这些对**（4 次调用）。不是 S15。代价：judge 以结构为前提，救不回结构错配——写进 README |
| 3 | 「sympy 够用」被证伪 | `parse_latex` 调用抛 `ImportError: … antlr4 … version 4.11`；antlr4/lark 均不在 pydeps | **手写结构化拆项 + 显式宏翻译器**，不用 `parse_latex`，零新依赖；超出文法 `ok=False` |
| 4 | KaTeX 是硬要求还是可推迟 | 全仓 glob `**/katex*` 为空；冻结规则 :75 要求 KaTeX `\htmlId` | **推迟到 M2，记为 S18 待批**（偏离冻结规则必须你点头，不静默采纳） |
| 5 | judge 输出格式两份冻结文本冲突 | `prompts.py:18-20` 要求两行 `Verdict:`/`Evidence:`；计划书 :547 要求首 token yes/no | **按两行格式解析**，:547 澄清为「Verdict 行取值的首 token」，记为 S19 待批。理由：首 token 解析拿不到 evidence，而 evidence 必填且为空强制 0 |

另外它核实了验收第 7 条的数字正确（实测 nodes=128 / edges=101，op=94、module=34，validate_trace 通过），
并确认 S16/S17 的待批状态是显式列出的、不算隐藏缺口。

**我自己另外实测到的两个坑**（已写进实施计划 S3）：
- sympy 全局命名空间撞符号：`E/I/N/O/Q/S` 都被占用。裸 `parse_expr('Q*K')` 响亮地炸，
  但 **`parse_expr('I*V')` 静默成功且语义全错**（`I` 变虚数单位，free_symbols 里 `I` 消失）。必须传 `local_dict`。
- `import numpy` 本机成功（系统 site-packages 2.5.4）但**不在 pydeps**——依赖它就是重犯框架切片第二轮评审的 C2。
