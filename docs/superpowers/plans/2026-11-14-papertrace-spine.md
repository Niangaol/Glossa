# PaperTrace 端到端脊柱 · 实施计划

> **For agentic workers**: 按 Task 顺序执行，每个 Task 内部严格 TDD（先写失败测试 → 跑红 → 最小实现 → 跑绿 → 提交）。
> 不要跳步，不要把多个 Task 合成一次提交。每个 Task 结束时全量 pytest 必须绿。

- **Goal**：让 `build --repo … --paper …` 真跑通一条端到端脊柱（论文 → 公式项 → 符号 → 信号 → 分档 → trace.json → 单文件 HTML），并落地 U1 绿线门 `s_struct ≥ 0.5`。offline 下诚实空态，配了 openai 兼容后端就点亮。
- **Architecture**：一条直线十段。代码侧沿用 M1a 的 `trace_module`（不改）；新增 `papertrace/spine.py` 做编排；`cli.py` 只负责把 `--paper` 接上去。所有跨模块数据只走 `schema/trace.schema.json`。
- **Tech Stack**：Python 3.13.15（本机唯一可用）、torch 2.15.0+cpu、sympy 1.14.0、jinja2 3.1.6、jsonschema 4.26.0、pytest 9.2.0，全部已在 `pydeps/` 且实测 import 成功。**`pydeps/` 里没有 numpy、没有 requests**：向量用 `list[list[float]]`，HTTP 用 `urllib.request`。
  - ⚠️ 实测 `import numpy` 在本机**能成功**（2.5.4，来自系统 site-packages，不在 `pydeps/`）。**仍然禁止依赖它**——框架切片第二轮评审的 C2 就是「顶层 import numpy 但依赖里没有，干净机器上全炸，本机全绿只是环境侥幸」。同理任何不在 `pydeps/` 的包都不许 import。
- **Spec**：`docs/superpowers/specs/2026-11-14-papertrace-spine-design.md`（**已批 m03858**）；上游 `docs/superpowers/plans/2026-11-14-papertrace-engineering-plan.md`。
- **执行方式**：Subagent-driven（年糕选定）——每个 Task 派一个全新 implementer 子智能体，完成后派独立 task reviewer，全部 Task 完成后做一次 whole-branch 评审。账本在 `.superpowers/sdd/2026-11-14-papertrace-spine/progress.md`。分支 `spine`（从 master e71d613 切出）。

## Global Constraints（每个 Task 都受这些约束，违反即返工）

1. **单源文件 ≤ 200 行**，口径是 `len(pathlib.Path(f).read_text(encoding='utf-8').splitlines())`。**不要用 `Get-Content .Count`**——本机实测它少算（fx_nodes 报 159 真值 175）。
2. **禁止 mock 填产品输出**。trace 里每个结论必须带 `source ∈ {runtime, static, model}`；拿不到就空态 + 原因。测试替身只允许出现在 `tests/` 下。
3. **默认 offline**。`OfflineBackend.chat` / `.embed` 必须继续抛 `LLMUnavailable`，禁止返回固定 yes 或假向量（S13）。
4. **对齐禁止自由生成**。judge 只问「是同一件事吗」，依据必填且 ≤40 字符（schema 上限 80）。`judge()` 签名不得出现 `mapping: dict`。
   - **S19 输出格式澄清（待批）**：按现有 `papertrace/llm/prompts.py:18-20` 的**严格两行**格式解析——`Verdict: yes|no` 与 `Evidence: <≤40字>`。工程计划书 :547 的「首 token 级 yes/no」指的是 **Verdict 行取值的首 token**，不是整个响应的首 token（整个响应的首 token 是 `Verdict:`，按字面解析会让真实 DeepSeek 全判失败）。大小写不敏感；`Verdict:` 行缺失或值不是 yes/no → **不是 yes**。
5. **置信度公式写死**：`a = 0.30·s_retr + 0.50·s_judge + 0.20·s_struct`，`c = sigmoid(4·(a−0.5))`。`c≥0.75` 绿实线 / `0.45≤c<0.75` 黄虚线 / `c<0.45` 不连线进 unresolved。**新增 U1 门：绿线还要求 `s_struct ≥ 0.5`**。
6. **不改用户代码**、不联网下载论文（本切片只吃本地 `.tex`）、不训练、无账号、无云、无插件。
7. **黄金主路径**：`tests/fixtures/nanogpt`（flash 已写死 False）+ `tests/fixtures/papers/vaswani2017/attention.tex`。探针默认 CPU。
8. **`build` 不带 `--paper` 时行为必须与 M1a 逐项一致**：nodes=128（module 34 / param 18 / input 1 / op 75）、edges=101、counts={operators 75, degraded 2, fused 0, orphan 0, shape_broken 0, shape_unchecked 0}。每个 Task 结束都要核这一条。
9. **测试环境**：`$env:PYTHONPATH='D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps'`；`$env:PYTHONIOENCODING='utf-8'`；`$env:PYTHONUTF8='1'`；解释器 `C:\Users\niangao\AppData\Local\Programs\Python\Python313\python.exe`。**不用 `tmp_path`/`--basetemp`**（沙箱下 WinError 5），用 `tests/_tmp.py::scratch_dir()`。`pyproject.toml` 已有 `addopts = "-p no:cacheprovider"`。
10. **每个 Task 一次提交**，提交信息用英文祈使句；文档同步（README / 本计划 / 账本）单独一次提交。git 身份 `niangao <niangaol@qq.com>`。
11. **变异探针**：每个 Task 至少做一次「把新判据关掉 → 确认测试变红 → 还原 → 确认 restored」。还原锚点必须唯一，**不要用单字符或空串做 `old_string`**（历史上踩过：`'}'` 匹配 5 次导致半变异态）。
12. **修订审批状态**：S16（anchor 加 tier/signals）、S17（embed 返回 list）、S18（KaTeX 推迟到 M2）、S19（judge 两行格式解析）**四条已于 m03858 全部批准**，按批准内容施工。**S15（词法检索基线）仍未批、不在本计划内**，不做。
13. **零新依赖**：只许 import `pydeps/` 里有的包与标准库。**`sympy.parsing.latex.parse_latex` 不可用**（实测调用抛 `ImportError: LaTeX parsing requires the antlr4 Python package … version 4.11`，antlr4/lark 都不在 pydeps）；`numpy` 虽能从系统 site-packages import 成功但**不在 pydeps，禁止依赖**。

## Review Focus（五类最可能咬人的输入，每类都在 owning Task 里有测试）

| # | 输入类 | 为什么危险 | owning Task | 必须的测试 |
|---|---|---|---|---|
| RF1 | 坏 LaTeX / 缺 marker / 空 tex / 非 UTF-8 | 拆项器最容易在这种输入上「猜」出项，或抛裸 traceback | S2, S3 | `test_unknown_macro_is_not_split`、`test_missing_marker_derives_stable_id`、`test_empty_tex_yields_zero_units` |
| RF2 | 后端抛 LLMUnavailable / 答非 yes-no / 证据为空 | 一旦兜底成 yes 或 0.5，整条对齐就是幻觉 | S6, S7, S8 | `test_offline_judge_scores_zero_with_reason`、`test_non_yes_no_answer_is_not_yes`、`test_empty_evidence_forces_zero` |
| RF3 | 手改过的 trace.json（tier 涂绿 / signals 缺项 / 与 confidence 不符） | 门若只在生成时执行，手改就能绕过 | S1 | `test_tier_must_match_recomputed_gate`、`test_tier_without_signals_is_rejected` |
| RF4 | config 缺字段 / 派生符号 / 非 dataclass / 整除不成立 | fixture **没有 head_dim 字段**，Dh 必须派生；猜一个值就是假数据 | S4 | `test_head_dim_is_derived_not_invented`、`test_missing_config_field_is_unresolved`、`test_non_divisible_heads_is_value_mismatch` |
| RF5 | HTML 超 8MB / 含外链 / 空 anchors / unresolved 被画成绿线 | 交付物必须离线单文件可用，且不能把未对齐伪装成已对齐 | S10 | `test_html_has_no_external_refs`、`test_html_under_size_cap`、`test_unresolved_list_is_visible`、`test_empty_anchors_renders` |

---

## Task S1：分档函数 + 绿线门 + anchor 契约（U1 / S16）

**Files**
- 改 `papertrace/constants.py`（26 行 → 约 30 行）：新增 `GREEN_STRUCT_MIN = 0.5`
- 新 `papertrace/align/tier.py`（约 45 行）
- 改 `schema/trace.schema.json`：`$defs.anchor.properties` 增加可选 `tier` 与 `signals`
- 新 `papertrace/schema_anchor.py`（约 55 行）：anchor 的跨字段不变量
- 改 `papertrace/schema_structure.py`（129 行 → 约 135 行）：在 `structural_errors` 末尾调用 `anchor_errors(doc)`
- 新 `tests/test_spine_tier.py`

**Interfaces**
- Consumes：`papertrace.constants.CONF_GREEN / CONF_YELLOW`；`papertrace.align.score.confidence`
- Produces：
  - `papertrace.align.tier.tier(confidence: float, s_struct: float) -> str`（返回 `"green"|"yellow"|"none"`）
  - `papertrace.align.tier.tier_reason(confidence: float, s_struct: float) -> str`（降级原因，≤40 字符，供 evidence）
  - `papertrace.schema_anchor.anchor_errors(doc: dict) -> list[str]`
  - schema `$defs.anchor.properties.tier: {"enum":["green","yellow","none"]}`
  - schema `$defs.anchor.properties.signals: {type:object, required:[s_retr,s_judge,s_struct], 每项 number 0..1}`

**Steps**
1. 写 `tests/test_spine_tier.py`，先只写测试不写实现。必须包含：
   - `test_green_requires_both_thresholds`：参数化 `(c, s_struct, expected)`，至少覆盖 `(0.8808, 1.0, 'green')`、`(0.7685, 0.0, 'yellow')`（**U1 反例**）、`(0.7685, 0.49, 'yellow')`、`(0.7685, 0.5, 'green')`、`(0.6900, 1.0, 'yellow')`、`(0.45, 1.0, 'yellow')`、`(0.4499, 1.0, 'none')`、`(0.2315, 1.0, 'none')`
   - `test_gate_only_downgrades`：对 100 个 `(c, s)` 网格断言 `tier(c,s)` 的档位序号 ≤ 无门时的档位序号（门只降不升）
   - `test_tier_matches_confidence_formula`：用 `confidence(1,1,0)` 算出 c，断言 `tier(c, 0.0) == 'yellow'` 且 `c >= CONF_GREEN`（证明门确实拦下了一个本该绿的）
   - `test_tier_reason_mentions_struct`：`tier_reason(0.7685, 0.0)` 含「结构」与「0.50」，且 `len <= 40`
   - `test_tier_reason_empty_when_not_downgraded`：`tier_reason(0.8808, 1.0) == ""`
   - RF3：`test_tier_must_match_recomputed_gate`（手改 anchor 把 yellow 涂成 green → `anchor_errors` 非空）、`test_tier_without_signals_is_rejected`、`test_signals_out_of_range_is_rejected`、`test_anchor_without_tier_still_valid`（旧 trace 兼容）
2. 跑 `python -m pytest tests/test_spine_tier.py -q` → **必须红**（`ModuleNotFoundError: papertrace.align.tier`）。把红的原因记进账本。
3. 在 `constants.py` 加 `GREEN_STRUCT_MIN = 0.5`，注释写明这是 U1（年糕 m03751 拍板），门只降不升。
4. 写 `papertrace/align/tier.py`：`tier()` 与 `tier_reason()`。docstring 要写清「为什么门长在这里而不是 HTML 里」——因为渲染时只有 confidence 无法执行门。
5. 改 schema 加两个可选字段；写 `papertrace/schema_anchor.py::anchor_errors`，在 `schema_structure.structural_errors` 末尾 `errors.extend(anchor_errors(doc))`。
6. 跑 `python -m pytest tests/test_spine_tier.py -q` → 绿。
7. 跑全量 `python -m pytest -q` → **448 + 新增 全绿**。若旧测试因 schema 变化红，说明改动不是纯增量，回头修。
8. 变异探针：把 `tier()` 里的 `and s_struct >= GREEN_STRUCT_MIN` 删掉 → 确认 U1 反例用例红 → 还原 → 确认 restored。
9. 核 Global Constraint 8（不带 --paper 的 build 逐项不变）+ 行数 census（OVER200 必须为空）。
10. 提交：`feat: gate the green tier on a minimum structural signal`。

---

## Task S2：论文 ingest（只吃本地 .tex）

**Files**
- 改 `papertrace/ingest/paper.py`（17 行桩 → 约 90 行）
- 改 `papertrace/parse_paper/units.py`（7 行桩 → 约 85 行）
- `papertrace/ingest/arxiv.py` **保持桩**（本切片不联网）
- 新 `tests/test_spine_ingest.py`

**Interfaces**
- Consumes：`tests/fixtures/papers/vaswani2017/attention.tex`；`papertrace.exceptions.IngestError`
- Produces：
  - `papertrace.parse_paper.units.PaperUnit(NamedTuple)`：`unit_id: str`、`latex: str`、`label: str | None`
  - `papertrace.parse_paper.units.extract_units(text: str) -> list[PaperUnit]`
  - `papertrace.ingest.paper.PaperBundle` **增加一个字段** `units: list[PaperUnit] = []`（放在末尾带默认值，保持既有四字段兼容）；`unit_count == len(units)`
  - `papertrace.ingest.paper.ingest_paper(src: str | Path) -> PaperBundle`

**行为约定**
- `src` 是本地 `.tex` 且存在 → 读 UTF-8 → `extract_units` → `PaperBundle(source=str(src), ingest_mode="tex", unit_count=len(units), title=<第一行注释里的标题或 None>, units=units)`
- `unit_id` 优先取 `% papertrace-id: <id>` 注释；**没有 marker 时**按 `eq-<序号>` 派生稳定 ID（同一文件重复解析必须得到同一 ID），不抛错
- 只识别 `\begin{equation}…\end{equation}`（含 `equation*`）；`\label{…}` 抽出来放 `label` 并从 latex 里剔除
- `src` 是 `.pdf` / `arxiv:…` / 不存在的路径 → 抛 `IngestError`（**不是 NotImplementedError**），消息写明为什么不支持。由 S9 的编排层捕获并写成 `unresolved{kind:"paper_unit", ref:src, reason:…}`。**原因落在 trace 里，不落在异常里**——CLI 不该因为论文读不了就吐 traceback。`title` 字段只放论文标题，绝不拿来装错误信息。
- 空文件 / 只有注释 → `units=[]`、`unit_count=0`、`ingest_mode="tex"`（真的解析了，只是没有公式）

**Steps**
1. 写 `tests/test_spine_ingest.py`：`test_fixture_tex_yields_one_unit`（unit_id == `S3.2-eq-attn`、label == `eq:attention`、latex 含 `\mathrm{softmax}` 且**不含** `\label`）、`test_missing_marker_derives_stable_id`（同一文本解析两次 ID 相同）、RF1 三条（`test_empty_tex_yields_zero_units`、`test_non_utf8_tex_raises_ingest_error`、`test_pdf_source_raises_ingest_error_with_reason`）、`test_arxiv_source_raises_ingest_error`、`test_unit_count_equals_len_units`。
2. 跑 → 红（`NotImplementedError`）。记录。
3. 实现 `extract_units`（纯正则 + 字符串处理，不引第三方）。
4. 实现 `ingest_paper`，给 `PaperBundle` 加 `units` 字段。
5. 跑 → 绿；跑全量 → 绿（注意 `PaperBundle` 加字段可能影响既有构造点，grep 确认）。
6. 变异探针：把 marker 优先级去掉（永远用派生 ID）→ 确认 `test_fixture_tex_yields_one_unit` 红 → 还原。
7. 核行数 + Constraint 8。提交：`feat: ingest a local tex paper into stable equation units`。

---

## Task S3：公式拆项 + 安全 LaTeX

**Files**
- 改 `papertrace/parse_paper/split_terms.py`（7 行桩 → 约 110 行）
- 改 `papertrace/parse_paper/latex_safe.py`（7 行桩 → 约 70 行）
- 新 `tests/test_spine_split.py`

**Interfaces**
- Consumes：`sympy.Symbol` / `sympy.parsing.sympy_parser.parse_expr`（**不是 `parse_latex`**，见 Constraint 13）；`re`（标准库）；S2 的 `PaperUnit`
- Produces：
  - `papertrace.parse_paper.split_terms.Term(NamedTuple)`：`index: int`、`latex: str`、`kind: str`
    `kind ∈ {"matmul","scale","norm","act","transpose","concat"}`
  - `papertrace.parse_paper.split_terms.split_formula(latex: str) -> list[Term]`（**签名不变**，返回类型从 `list[object]` 收紧为 `list[Term]`）
  - `papertrace.parse_paper.latex_safe.latex_to_sympy_safe(latex: str) -> dict`：`{"ok": bool, "expr": sympy.Expr | None, "raw": str}`
  - 项 ID 由编排层拼：`f"{unit_id}-t{term.index}"`（split_formula 本身不知道 unit_id，保持纯函数）

**行为约定**
- **拆项是手写的结构化扫描，不依赖任何 LaTeX 解析器**（builder-check 第 3 问，已实测证伪「sympy 够用」）：
  `split_formula` 用正则/括号配平在**已知文法**上定位结构——`\frac{A}{B}`、`\sqrt{A}`、
  `\mathrm{softmax}` / `\operatorname{softmax}`、`\left(…\right)`、`^{T}`、尾随的 `V`。
  只覆盖夹具这类公式文法；**超出文法不猜**，返回 `[]` 让编排层整条进 unresolved。
- **`latex_to_sympy_safe` 不调用 `parse_latex`**，改成两步：①白名单宏 → sympy 可解析串的显式翻译
  （`\frac{A}{B}`→`(A)/(B)`、`\sqrt{A}`→`sqrt(A)`、`\mathrm{softmax}`→`softmax`、`\cdot`→`*`、
  `\left(`/`\right)`→`(`/`)`、相邻字母补 `*`、`^{T}`→`**T`）；②`parse_expr(串, local_dict=…)`。
  出现白名单外的宏（如 `\unknownmacro`）→ 直接 `{"ok": False, "expr": None, "raw": 原串}`，**不抛异常**。
  必须有测试 `test_no_latex_frontend_is_used`：grep 本 Task 两个源文件，断言不含 `parse_latex`。
- **必须给 `parse_expr` 传显式 `local_dict`（已实测的坑，不是理论风险）**：sympy 的全局命名空间里 `E=Exp1`、`I=ImaginaryUnit`、`N=function`、`O=type`、`Q=AssumptionKeys`、`S=SingletonRegistry`。裸 `parse_expr('Q*K')` 抛 `TypeError: unsupported operand type(s) for *: 'AssumptionKeys' and 'Symbol'`；更危险的是 **`parse_expr('I*V')` 与 `parse_expr('E*x')` 会静默成功但语义全错**——`I` 变成虚数单位、`E` 变成自然常数，`free_symbols` 里那个符号直接消失（实测 `I*V` 的 free_symbols 只有 `{V}`）。Attention 的 `Q` 会响亮地炸，但任何用 `E`/`I`/`N`/`S` 当符号的论文会**静默算错**。
  - 做法：`local_dict = {name: sympy.Symbol(name) for name in 本式出现的符号名}`，实测 `parse_expr('softmax(Q*K/sqrt(d_k))*V', local_dict=…)` 正确得到 `V*softmax(K*Q/sqrt(d_k))`、free_symbols 为 `{K,Q,V,d_k}`。
  - 必须有测试 `test_single_letter_symbols_do_not_collide_with_sympy_globals`：参数化 `Q*K`、`I*V`、`E*x`、`N*x`、`S*x`，断言 `ok=True` 且 `free_symbols` 含那个字母本身（**不是只断言不抛异常**——`I*V` 裸解析就不抛）。
- Vaswani 那条公式必须拆出**恰好 4 项**，顺序与 kind 为：`t0 matmul (QK^{T})`、`t1 scale (1/\sqrt{d_k})`、`t2 norm (softmax)`、`t3 matmul ((\cdot)V)`
- 拆项停止条件：matmul / 逐元素缩放 / 归一化 / 激活 / 转置 / concat 各算一项（规格 Task 10）
- `latex_to_sympy_safe` 遇到 `\unknownmacro{x}` → `{"ok": False, "expr": None, "raw": <原串>}`，**不抛异常**
- `ok=False` 的整式**不拆项**，由编排层整条进 `unresolved`（不猜项）

**Steps**
1. 写 `tests/test_spine_split.py`：`test_vaswani_splits_into_exactly_four_terms`（断言 `len==4` 且 `[(t.index,t.kind) for t in terms] == [(0,'matmul'),(1,'scale'),(2,'norm'),(3,'matmul')]`）、`test_term_latex_preserves_original_substring`（每项 latex 是原串的子串，证明没重写公式）、**`test_single_letter_symbols_do_not_collide_with_sympy_globals`**（见上面行为约定，参数化 Q/I/E/N/S，断言 free_symbols 含该字母）、RF1 `test_unknown_macro_is_not_split`（`ok=False` 且 `split_formula` 返回 `[]`）、`test_safe_parse_never_raises`（参数化 10 条坏串）、`test_empty_latex_yields_no_terms`。
2. 跑 → 红。记录。
3. 实现 `latex_to_sympy_safe`：白名单宏翻译器 + `parse_expr(local_dict=…)`；任何异常都吞成 `ok=False`（**只吞解析异常，不吞 KeyboardInterrupt/SystemExit**）。**不 import `sympy.parsing.latex`**。
4. 实现 `split_formula`：手写结构化扫描（括号配平 + 白名单宏定位），先 safe parse，`ok=False` 直接返回 `[]`；再按结构拆项。
5. 跑 → 绿；全量 → 绿。
6. 变异探针：把 `ok=False` 时的早退删掉 → 确认 `test_unknown_macro_is_not_split` 红 → 还原。
7. 核行数 + Constraint 8。提交：`feat: split the attention formula into four ordered terms`。

---

## Task S4：符号码表（代码侧 / 论文侧 / 映射）

**Files**
- 改 `papertrace/symbols/code_table.py`（7 行桩 → 约 120 行）
- 改 `papertrace/symbols/paper_table.py`（7 行桩 → 约 70 行）
- 改 `papertrace/symbols/mapping.py`（7 行桩 → 约 80 行）
- **`papertrace/symbols/shape_prop.py` 保持桩**（符号 shape 传播属 M1b，本切片不做）
- 新 `tests/test_spine_symbols.py`

**Interfaces**
- Consumes：S2 的 `PaperBundle`；`build_trace()` 产出的 trace dict（取 `meta.runtime.batch`）；`inspect` / `ast`（标准库）
- Produces：
  - `papertrace.symbols.code_table.build_code_symbols(mod, bundle) -> list[dict]`（每项符合 schema `codeSymbol`：`var/symbol/defined_at` 必填，`value/used_by` 可选）
  - `papertrace.symbols.paper_table.build_paper_symbols(bundle: PaperBundle) -> list[dict]`（符合 `paperSymbol`：`symbol/first_seen` 必填）
  - `papertrace.symbols.mapping.map_symbols(code_symbols: list, paper_symbols: list) -> list[dict]`（符合 `symbolMapping`：`paper_symbol/code_var/status` 必填，`status ∈ {matched,value_mismatch,code_only,paper_only}`）

**夹具的真实事实（已实测，不要凭印象写）**
- `tests/fixtures/nanogpt/model.py:158-169` 的 `build_model()` 用 `GPTConfig(block_size=16, vocab_size=64, n_layer=2, n_head=4, n_embd=32, dropout=0.0, bias=False)`
- **`GPTConfig` 没有 `head_dim` 字段**（`model.py:19-26` 只有 block_size/vocab_size/n_layer/n_head/n_embd/dropout/bias）。`Dh` 必须**派生**：`D // H`，`defined_at` 指向真正算它的地方 `model.py:65`（`C // self.n_head`）。工程计划书 Task 6 写的「Dh=head_dim」在这个夹具上不成立，按派生处理并记进账本。
- 符号名冻结 `B,T,D,H,Dh`（`Dh=D/H`）。映射：`n_embd→D`、`n_head→H`、`block_size→T`、派生→`Dh`、运行时 batch→`B`
- `B` 不是 config 字段：`value` 取 `bundle["meta"]["runtime"]["batch"]`，`defined_at` 指向 `papertrace/build_trace.py:20`（`DEFAULT_BATCH = 2`）
- **`T` 记声明值 `block_size=16`，而运行时实际序列长度是 8**（`example_inputs_for` 取 `min(block_size, DEFAULT_SEQ_LEN=8)`）。符号表记的是**声明超参**，运行时形状在 nodes 里；两者对账属 M4，本切片不做，但必须在 README 写清这个区别，不能让人以为 T=16 就是跑出来的形状。
- `defined_at` 必须是真实的 `文件:行号`：用 `inspect.getsourcefile(type(mod))` + 读 config 类源码，正则匹配 `^\s*{var}\s*[:=]` 定位行。找不到就**不写这个符号**，改成 `unresolved{kind:"symbol"}`，绝不编一个行号。

**Steps**
1. 写 `tests/test_spine_symbols.py`：`test_five_frozen_symbols_present`（`{s['symbol'] for s in code} == {'B','T','D','H','Dh'}`）、`test_values_match_the_fixture`（D=32,H=4,Dh=8,T=16,B=2）、`test_all_symbols_have_real_defined_at`（每个 `defined_at` 形如 `path:line`，且该行真的存在、真的含对应变量名或表达式）、RF4 `test_head_dim_is_derived_not_invented`（断言 config 里**没有** head_dim，而 Dh 仍等于 D//H 且 defined_at 指向 `C // self.n_head` 那行）、`test_default_config_gives_768`（用默认 `GPTConfig()` 构造，D=768）、`test_missing_config_field_is_unresolved`、`test_non_divisible_heads_is_value_mismatch`、`test_paper_symbols_extract_d_k`（`d_k` 在列，`first_seen == 'S3.2-eq-attn'`）、`test_mapping_marks_value_mismatch_explicitly`、`test_mapping_never_silently_picks_one_value`。
2. 跑 → 红。记录。
3. 实现 `build_code_symbols`（含派生 Dh 与真实行号定位）。
4. 实现 `build_paper_symbols`（从 tex 抽 `d_k` 这类下标符号）。
5. 实现 `map_symbols`：`d_k ↔ Dh` 按语义表配对；值不同 → `status="value_mismatch"` 且 `value` 写**代码侧的值**，同时论文侧值保留在 `paperSymbol.value`（两边都留痕，不静默取一个）。
6. 跑 → 绿；全量 → 绿。
7. 变异探针：把 Dh 改成从 config 读 `head_dim`（getattr 默认 64）→ 确认 RF4 用例红 → 还原。
8. 核行数 + Constraint 8。提交：`feat: build code and paper symbol tables with real definition sites`。

---

## Task S5：结构信号 s_struct（确定性，offline 也能算）

**Files**
- 新 `papertrace/align/struct_signal.py`（约 120 行）
- **`papertrace/diff/struct.py` 保持桩**：它产的是 `mismatch{type:"struct"}` 记录（M4），与这里的 `s_struct` 信号是两件事，不要混
- 新 `tests/test_spine_struct.py`

**Interfaces**
- Consumes：trace dict 的 `nodes`（取 `level=="op"` 的 `op` 名与 `parent_id`）；S3 的 `list[Term]`；`mod.config`
- Produces：
  - `papertrace.align.struct_signal.StructSignal(NamedTuple)`：`score: float`、`hits: list[str]`、`misses: list[str]`、**`pairs: list[tuple[int, str]]`**
  - `papertrace.align.struct_signal.struct_signal(nodes: list[dict], terms: list, config) -> StructSignal`
  - **`pairs` 是 judge 的唯一候选来源（builder-check 第 2 问的决定）**：`[(term.index, node_id), …]`，
    由「算子序列与公式项顺序同构」那条规则的子序列匹配**顺带产出**——匹配成功时天然知道 t0 对应哪个 op 节点。
    同构不命中 → `pairs == []` → S7 不被调用 → `s_judge=0`。**不做全配对**（4×94≈376 次 API 调用不可接受），
    **不引入词法候选生成器**（那是 S15，未批）。Vaswani 夹具应产出恰好 4 对。

**规则（工程计划书 :663-669 冻结，不得改权重）**
- 初值 `0.5`
- `+0.2` 论文说「N 层」且代码有 `range(n_layer)`
- `+0.1` 超参名在 config 出现
- `+0.2` 算子序列与公式项顺序同构（`matmul→scale→softmax→matmul`）
- `−0.4` shape 与论文声明冲突
- `−0.3` 双向检索 top1 不是同一对（**本切片 offline 无检索结果 → 这条不触发，记进 misses 而不是当成命中**）
- 结果 clamp 到 `[0,1]`

**夹具的真实算子序列（已实测）**：`CausalSelfAttention.forward` 是 `matmul`(model.py:68) → `mul`(68) → `masked_fill`(69) → `softmax`(70) → `matmul`(72)。`masked_fill` 是因果掩码，公式里没有对应项——**同构判定必须允许代码侧多出掩码算子**，否则永远命中不了。这是本 Task 最容易写错的地方，要有专门测试。

**Steps**
1. 写 `tests/test_spine_struct.py`：`test_attention_sequence_is_isomorphic`（用夹具真 nodes + 四 terms，断言 `+0.2` 那条在 hits 里）、`test_extra_mask_op_does_not_break_isomorphism`（RF：`masked_fill` 插在中间仍命中）、`test_wrong_order_is_not_isomorphic`（把 terms 顺序打乱 → 不命中）、`test_score_starts_at_half`（空 terms + 空 nodes → 0.5）、`test_score_is_clamped`、`test_no_retrieval_means_rule_not_fired`（offline 下 −0.3 那条在 misses 里且**没有**被扣分）、`test_hits_are_human_readable`（每条 hit 是能在 evidence 里展示的短句）、**`test_pairs_has_exactly_four_entries_for_vaswani`**（`len(pairs)==4` 且 `[i for i,_ in pairs]==[0,1,2,3]`，每个 node_id 真的在 nodes 里且 `op` 名与 term.kind 对应）、**`test_no_isomorphism_means_no_pairs`**（打乱 terms 顺序 → `pairs==[]`，证明 judge 不会拿到瞎凑的候选）。
2. 跑 → 红。记录。
3. 实现 `struct_signal`：子序列匹配（允许代码侧多余算子），逐条规则累加，clamp。
4. 跑 → 绿；全量 → 绿。
5. 变异探针：把子序列匹配改成严格相等 → 确认 `test_extra_mask_op_does_not_break_isomorphism` 红 → 还原。
6. 核行数 + Constraint 8。提交：`feat: score structural agreement without any model`。

---

## Task S6：双向检索 + embed 接口（offline 诚实归零）

**Files**
- 改 `papertrace/align/embed.py`（12 行桩 → 约 55 行）
- 改 `papertrace/align/retrieve.py`（7 行桩 → 约 110 行）
- 新 `tests/test_spine_retrieve.py`

**Interfaces**
- Consumes：`papertrace.llm.client.get_llm()`；`papertrace.exceptions.LLMUnavailable`
- Produces：
  - `papertrace.align.embed.embed_texts(texts: list[str]) -> list[list[float]]`（**S17：不是 np.ndarray**，本机无 numpy。注意 `LLMBackend.embed` 协议在 `client.py:35` 已经是 `list[list[float]]`，所以这条只是把工程计划书 Task 11 的措辞改对，协议本身不用动）
  - `papertrace.align.retrieve.retrieve_bidirectional(code_units: list, paper_terms: list, k: int = 5) -> dict`
    返回 `{"forward": {term_id: [{"code_id":…, "score":…}, …]}, "backward": {code_id: [{"term_id":…, "score":…}, …]}, "s_retr": float, "conflicts": list, "reason": str | None}`
  - `papertrace.align.retrieve.cosine(a: list[float], b: list[float]) -> float`（纯 Python，零向量返回 0.0 不抛）

**行为约定**
- `get_llm().embed(...)` 抛 `LLMUnavailable` → `s_retr = 0.0`、`forward/backward` 为空 dict、`reason` 写明「offline 后端不提供 embedding」。**不兜底成 0.5，不返回假向量。**
- `s_retr` = 双向 Top-5 的 max cosine，clip 到 `[0,1]`
- 双向 top1 不是同一对 → 记进 `conflicts`，**不得取平均把 confidence 抬过 0.75**（规格 Task 11）
- **S15 词法基线不在本 Task 内**，未批不做

**Steps**
1. 写 `tests/test_spine_retrieve.py`：RF2 `test_offline_retrieve_scores_zero_with_reason`（断言 `s_retr==0.0`、`reason` 非空、`forward=={}`）、`test_cosine_of_identical_vectors_is_one`、`test_cosine_of_zero_vector_is_zero`、`test_cosine_is_clamped`、`test_bidirectional_conflict_is_recorded`（用一个实现 `LLMBackend` 协议的**测试后端**注入可控向量，断言 conflicts 非空）、`test_conflict_does_not_raise_confidence`（断言冲突时 `s_retr` 不被平均抬高）、`test_embed_returns_list_not_ndarray`（断言 `isinstance(out, list)` 且 `isinstance(out[0], list)`）。
2. 跑 → 红。记录。
3. 实现 `cosine` 与 `embed_texts`（后者只是转调 `get_llm().embed`，异常原样上抛给 retrieve 处理）。
4. 实现 `retrieve_bidirectional`：捕获 `LLMUnavailable` → 归零 + reason；有向量时算双向 top-k。
5. 跑 → 绿；全量 → 绿。
6. 变异探针：把 `except LLMUnavailable` 的归零改成 `s_retr = 0.5` → 确认 RF2 用例红 → 还原。
7. 核行数 + Constraint 8。提交：`feat: retrieve bidirectionally, score zero when offline`。

---

## Task S7：判断题 judge（yes/no + 依据）

**Files**
- 改 `papertrace/align/judge.py`（17 行桩 → 约 95 行）
- **改** `papertrace/llm/prompts.py`（**已存在，32 行**，含 `JUDGE_PROMPT` 与 `DRILL_PROMPT`；不是新建）：保留两行输出格式，新增 `JUDGE_PROMPT_VERSION` 与 `judge_prompt(term_text, snippet)`。**`DRILL_PROMPT` 不动**（L3 深钻属后续里程碑，铁律：初次与深钻必须是两个常量，禁止混用）
- 新 `tests/test_spine_judge.py`、新 `tests/test_align_no_generation.py`

**Interfaces**
- Consumes：`papertrace.llm.client.get_llm()`；`papertrace.constants.EVIDENCE_MAX_CHARS=40`
- Produces：
  - `papertrace.align.judge.JudgeResult(NamedTuple)`：`yes: bool`、`evidence: str`（**已存在，不改**）
  - `papertrace.align.judge.judge(term, snippet: str) -> JudgeResult`（**签名不变，不得出现 mapping: dict**）
  - `papertrace.align.judge.judge_score(result: JudgeResult) -> float`（yes→1.0，no→0.0，**evidence 为空强制 0.0**）
  - `papertrace.llm.prompts.JUDGE_PROMPT_VERSION: str`、`judge_prompt(term_text: str, snippet: str) -> str`

**行为约定**
- prompt 必须含「只能回答 yes / no」，**不得含**「请列出对应关系」这类自由生成诱导
- **按两行格式解析（S19）**：找 `Verdict:` 行 → 取其值的**首 token**，大小写不敏感；找 `Evidence:` 行 → 取其余文本。
  `Verdict: Yes` → yes；`Verdict: maybe` / `Verdict:` 行缺失 / 空串 → **不是 yes**。
  **不要**对整个响应取首 token（那是 `Verdict:`，会让真实后端全判失败）。
  容错：允许 `Verdict：`（全角冒号）与行首空白；但**不允许**从自由文本里搜 `yes`（那就退回自由生成了）
- evidence 截断到 40 字符；模型没给依据 → `evidence=""` → `judge_score` 强制 0
- `LLMUnavailable` → `JudgeResult(yes=False, evidence="")`，由编排层写 reason

**Steps**
1. 写 `tests/test_spine_judge.py`：`test_judge_prompt_is_yes_no`（含「只能回答 yes / no」、不含「请列出对应关系」）、RF2 `test_non_yes_no_answer_is_not_yes`（参数化 `Verdict: maybe` / `Verdict: I think` / 空串 / 缺 Verdict 行 / `Verdict: no way`，注意 `no way` 首 token 是 no → 不是 yes）、**`test_two_line_format_is_parsed`**（`"Verdict: yes\nEvidence: 第 68 行的 QK^T 矩乘"` → yes 且 evidence 正确）、**`test_verdict_value_takes_first_token`**（`"Verdict: Yes, because…"` → yes）、**`test_free_text_yes_is_not_accepted`**（`"我觉得 yes 是对的"` 无 Verdict 行 → 不是 yes）、`test_empty_evidence_forces_zero`、`test_evidence_truncated_to_40`、`test_offline_judge_scores_zero_with_reason`、`test_judge_signature_has_no_mapping_param`（用 `inspect.signature` 断言参数名里没有 mapping）。
2. 写 `tests/test_align_no_generation.py`：**递归**读 `papertrace/align/*.py` 与 `papertrace/llm/*.py`，断言不含 `generate_alignment` / `对应关系如下` / `请列出`。
3. 跑 → 红。记录。
4. 实现 `prompts.py` 与 `judge.py`。
5. 跑 → 绿；全量 → 绿。
6. 变异探针：把 Verdict 行解析改成 `"yes" in text.lower()` → 确认 `test_free_text_yes_is_not_accepted` 红 → 还原。
7. 核行数 + Constraint 8。提交：`feat: ask a yes/no question, never a generation task`。

---

## Task S8：openai 兼容后端（点亮开关，默认仍 offline）

**Files**
- 新 `papertrace/llm/openai_backend.py`（约 140 行）
- 改 `papertrace/llm/client.py`（89 行 → 约 110 行）：`get_llm()` 按 `configured_backend()` 分派；`_offline_hint` 改成如实描述（openai 已实现）
- 新 `tests/test_spine_openai.py`

**Interfaces**
- Consumes：环境变量 `PAPERTRACE_LLM_BACKEND` / `PAPERTRACE_OPENAI_BASE_URL` / `PAPERTRACE_OPENAI_API_KEY` / `PAPERTRACE_LLM`；`urllib.request`（标准库）
- Produces：
  - `papertrace.llm.openai_backend.OpenAICompatBackend`：实现 `LLMBackend` 协议（`name`、`chat(prompt, *, system=None) -> ChatResult`、`embed(texts) -> list[list[float]]`）
  - `papertrace.llm.client.get_llm() -> LLMBackend`（offline → OfflineBackend；openai → OpenAICompatBackend；ollama → 仍抛/仍 offline 并如实说明）

**行为约定**
- **测试绝不联网**：把传输层做成可注入的 `transport(payload: dict) -> dict`，测试注入假传输；产品默认用 `urllib.request`
- 缺 base_url / api_key / model → `LLMUnavailable`，消息写明缺哪个环境变量
- 超时、非 200、JSON 解析失败、 choices 为空 → 一律 `LLMUnavailable` 带原因，**绝不返回假 yes**
- `embed()`：POST `/embeddings`；端点不存在（404）或返回不含 data → `LLMUnavailable`。**DeepSeek 没有 embeddings 端点，所以只配 openai 时 `s_retr` 仍然是 0**，这一点必须写进 README
- `ChatResult.model` 写服务端返回的真实 model 名，`backend="openai"`

**Steps**
1. 写 `tests/test_spine_openai.py`：`test_missing_env_raises_llm_unavailable`（参数化缺 base_url/key/model 三种，断言消息含对应变量名）、`test_chat_parses_first_choice`（注入假传输）、`test_non_200_raises`、`test_timeout_raises`、`test_malformed_json_raises`、`test_empty_choices_raises`、`test_embed_404_raises_llm_unavailable`、`test_backend_satisfies_protocol`（`isinstance(b, LLMBackend)`，协议是 runtime_checkable）、`test_get_llm_dispatches_on_env`（monkeypatch 环境变量，断言返回类型）、`test_offline_is_still_the_default`（清空环境变量 → OfflineBackend）、`test_no_network_in_tests`（monkeypatch `urllib.request.urlopen` 使其抛 AssertionError，确认所有用例都不触发它）。
2. 跑 → 红。记录。
3. 实现 `OpenAICompatBackend`（transport 可注入）。
4. 改 `get_llm()` 分派 + `_offline_hint` 文案。
5. 跑 → 绿；全量 → 绿。**已定位会被打破的既有用例**：`tests/test_llm_offline.py:30-33` 参数化 `["ollama", "openai", "openai:deepseek"]` 断言 `get_llm()` 返回 offline；`tests/test_llm_hint.py:19-24` 断言配 ollama 时报「backend=ollama 尚未实现」。openai 那条语义变了，必须**按新事实改写**（openai → 真后端；ollama → 仍如实报未实现），不是删掉测试。
6. 变异探针：把非 200 的分支改成返回 `ChatResult("yes", …)` → 确认 `test_non_200_raises` 红 → 还原。
7. 核行数 + Constraint 8。提交：`feat: add an openai-compatible backend, offline stays the default`。

---

## Task S9：编排 spine + 打通 --paper

**Files**
- 新 `papertrace/spine.py`（约 180 行，**贴着 200 行上限，写之前先算**）
- 改 `papertrace/cli.py`（157 行 → 约 170 行）：删掉 `:79-81` 的硬拒绝，接上 spine
- 改 `papertrace/build_trace.py`：**不改**（181 行，加编排会破 200；编排放在 spine.py）
- 新 `tests/test_spine_end_to_end.py`

**Interfaces**
- Consumes：S2–S8 全部；`papertrace.build_trace.build_trace`；`papertrace.schema_validate.validate_trace / dump_trace`
- Produces：
  - `papertrace.spine.attach_paper(doc: dict, paper_src: str, model) -> dict`（**原地填充并返回同一个 doc**：`meta.paper`、`meta.model`、`symbols.{code,paper,mapping}`、`anchors`、`unresolved`）
  - CLI：`build --paper <本地.tex>` 不再 exit 2

**行为约定**
- `meta.paper` = `{source, unit_count, ingest_mode, title?}`；`meta.model` = `{name: <后端名>, prompt_version: JUDGE_PROMPT_VERSION, embed_model: <真实模型名或 "none">}`
- 每个公式项：算 `s_struct`（S5）、`s_retr`（S6）、`s_judge`（S7）→ `confidence` → `tier`
  - **judge 只对 `StructSignal.pairs` 里的配对调用**（S5 产出，见该 Task）。`pairs` 为空 → 不调用 judge、`s_judge=0`、reason 写「结构同构未命中，没有可判断的候选对」。**不做全配对、不做词法候选**
  - `tier == "none"` → **不产生 anchor**，写 `unresolved{kind:"paper_unit", ref:term_id, reason:<为什么>}`
  - `tier == "yellow"` → anchor 带 `alternatives`（1–2 个备选）、`direction`、`signals`、`tier`
  - `tier == "green"` → anchor 带 `signals`、`tier`
  - `evidence` 必填 ≥1 字符 ≤80；被门降级时把 `tier_reason` 拼进去
- `IngestError` / `LLMUnavailable` 都要落成 `unresolved` 的 reason，**不让异常冒到 CLI 变成 traceback**
- 拆不出的整式（S3 `ok=False`）→ 整条进 unresolved，不猜项
- **不带 `--paper` 时 spine 完全不被调用**，M1a 行为逐项不变

**Steps**
1. 写 `tests/test_spine_end_to_end.py`：`test_offline_build_exits_zero`（真跑 CLI，断言 exit 0）、`test_offline_trace_is_schema_valid`、`test_offline_has_no_anchors`（`anchors == []`）、`test_offline_has_four_unresolved_terms`（t0..t3 各一条且 reason 非空）、`test_meta_paper_is_tex`（`ingest_mode=="tex"`、`unit_count==1`）、`test_symbols_are_filled`（code 含 B/T/D/H/Dh）、`test_yes_backend_produces_yellow_anchor`（注入答 yes 的测试后端 + 无 embedding → 断言出现 `tier=="yellow"` 且 `0.45 <= confidence < 0.75`）、`test_green_gate_downgrades_in_real_trace`（构造 `s_struct=0` 且 c≥0.75 → anchor 的 tier 是 yellow）、`test_no_paper_flag_is_unchanged`（**Constraint 8 的逐项断言**：nodes=128/edges=101/counts 全同）、`test_ingest_error_becomes_unresolved_not_traceback`。
2. 跑 → 红。记录。
3. 实现 `spine.attach_paper`。
4. 改 `cli.py`：删硬拒绝，`build_trace` 之后调 `attach_paper`，再 `validate_trace` → `dump_trace`。
5. 跑 → 绿；全量 → 绿。
6. 真跑一次命令并把输出贴进账本：`python -m papertrace build --repo tests/fixtures/nanogpt --paper tests/fixtures/papers/vaswani2017/attention.tex --out output/spine --force`
7. 变异探针：把 `tier=="none"` 也写成 anchor → 确认 `test_offline_has_no_anchors` 红 → 还原。
8. 核行数（spine.py 必须 ≤200）+ Constraint 8。提交：`feat: wire the paper spine into build --paper`。

---

## Task S10：单文件离线 HTML

**Files**
- 新 `papertrace/render_html.py`（约 150 行）
- 新 `papertrace/templates/spine.html.j2`（jinja2 模板，**不算源文件行数**，但要保持可读）
- 改 `papertrace/cli.py`：build 成功后写 `output/index.html`
- 新 `tests/test_spine_html.py`

**Interfaces**
- Consumes：`jinja2`（已在 pydeps）；合法的 trace dict；`papertrace.constants.HTML_MAX_BYTES=8_000_000`
- Produces：`papertrace.render_html.render_html(doc: dict) -> str`（返回完整 HTML 文本）；CLI 写 `<out>/index.html`

**行为约定**
- **零外链**：不得出现 `http://` / `https://` / `//cdn` 形式的资源引用（CSS/JS/字体/图片全部内联或不使用）。
  **S18（待批）：本切片不引 KaTeX**，公式用等宽原始 LaTeX 文本 + 静态 SVG 展示。
  理由：全仓 glob `**/katex*` 实测为空，而冻结规则（工程计划书 :75）要求 KaTeX `\htmlId`、:611 要求只内联用到的字体子集——
  在「零新依赖 + 禁外链 + <8MB」三条同时成立时拿不到这些资产，离线 vendoring JS + 字体子集是一个**独立前置任务**。
  这是对冻结规则的偏离，**必须年糕点头**，不静默采纳；批了就把 KaTeX 留给 M2 前端里程碑。
- 三块内容：① 代码算子图（静态 SVG，按 parent_id 分组，标真实形状）② 论文公式项清单（t0..t3，标 kind）③ **未对齐清单**（unresolved 的 ref + reason，必须可见）
- anchor 按 tier 上色：绿实线 / 黄虚线 / 不连线。**`tier=="none"` 绝不能被画成绿线**
- `anchors == []` 时也要正常渲染（这是 offline 的默认结果，不是错误）
- 超过 `HTML_MAX_BYTES` → 抛 `BuildError`，不静默截断

**Steps**
1. 写 `tests/test_spine_html.py`：RF5 四条（`test_html_has_no_external_refs` 用正则扫 `https?://` 与 `src=`/`href=` 外链、`test_html_under_size_cap`、`test_unresolved_list_is_visible`（断言每条 unresolved 的 ref 与 reason 都出现在 HTML 里）、`test_empty_anchors_renders`）、`test_green_and_yellow_are_visually_distinct`（断言两种 tier 的 stroke-dasharray 或 class 不同）、`test_no_none_tier_is_drawn_as_green`、`test_formula_terms_are_listed`（t0..t3 都在）、`test_real_shapes_appear`（夹具的 `(2, 4, 8, 8)` 这类形状出现在 SVG 标签里）、`test_cli_writes_index_html`（真跑 CLI 后文件存在）。
2. 跑 → 红。记录。
3. 写模板 + `render_html`（jinja2 `Environment(autoescape=True)`，**必须开 autoescape**，论文文本里的 `<` 不能变成标签）。
4. 改 CLI 写 index.html。
5. 跑 → 绿；全量 → 绿。
6. **人工验收**：用 `file://` 打开 `output/spine/index.html`，确认离线可用、未对齐清单可见、没有绿线假象。把截图或目检结论记进账本。
7. 变异探针：把 unresolved 清单那段模板删掉 → 确认 `test_unresolved_list_is_visible` 红 → 还原。
8. 核行数 + Constraint 8。提交：`feat: render a single offline html with an honest unresolved list`。

---

## 收尾 Task S11：文档同步 + 交付

1. README 增补：脊柱怎么跑（可复制的完整命令）、offline 为什么全 unresolved（附 §2 那张数学表）、点亮需要的四个环境变量、**只配 openai 是黄线不是绿线**（DeepSeek 无 embeddings）、符号表记声明值而运行时形状在 nodes、S16/S17 修订说明。
2. 本计划补每个 Task 的真实提交哈希与实测数字；账本 `.superpowers/sdd/2026-11-14-papertrace-framework/progress.md` 追加脊柱段。
3. 全量 pytest + 端到端 + 行数 census（OVER200 必须为空）+ 不带 --paper 的逐项对照。
   **既有测试改写清单（builder-check 第 1 问；按新事实改写，不是删掉）**：
   - `tests/test_imports.py:72-84` `test_align_stubs_raise_not_implemented`：原断言 judge/retrieve/embed 抛 `NotImplementedError`。改成断言 **offline 下抛 `LLMUnavailable`**（S6/S7 实现后的真实行为），并保留原 docstring 的意图「不许返回假 yes/假向量」——再加一条断言 `judge_score(JudgeResult(True, "")) == 0.0` 把「假绿线」这个失败模式钉得更死。
   - `tests/test_llm_offline.py:30-36`：参数化 `["ollama","openai","openai:deepseek"]` 断言返回 offline。改成 **openai/openai:deepseek → `OpenAICompatBackend`；ollama → 仍 offline 并如实报未实现**；另留一条「清空环境变量 → offline」。
   - `tests/test_cli.py:101-111` `test_build_with_paper_refuses`：原断言 `--paper arxiv:…` → exit 2 +「论文 ingest 尚未实现」。改成 **exit 0 + `meta.paper.unit_count==0` + `ingest_mode=="none"` + `unresolved` 里有 `kind=="paper_unit"` 且 reason 说明 arXiv 未实现**，函数名改成 `test_build_with_unsupported_paper_is_honest_empty`。
   - `tests/test_llm_hint.py:19-24`：ollama 文案不变（仍未实现），只需确认 openai 的 hint 不再说「尚未实现」。
4. 派独立评审子智能体复审脊柱（沿用 M1a 的做法：只读、快照、变异探针、五个自问点）。
5. 向年糕交付：trace.json + index.html + 评审结论 + 仍待批的 S15/S16/S17/S18/S19。

## 自审（writing-plans 技能要求的五项）

- **规格覆盖**：U1 门 → S1；论文 ingest → S2；拆项 → S3；符号表 → S4；结构信号 → S5；检索 → S6；judge → S7；后端 → S8；编排与 --paper → S9；HTML → S10。M1b 的 shape_prop、PDF/arXiv ingest、L1/L2/L3、serve/eval **明确不在本切片**，桩保持原样。
- **步骤扫描**：每个 Task 都是「写测试 → 跑红 → 实现 → 跑绿 → 变异探针 → 核约束 → 提交」，每步一个可检查结果，没有「然后把它做好」这种空话。
- **类型一致**：`Term(index,latex,kind)` 不含 term_id（由编排层拼）；`PaperBundle` 加字段带默认值保持兼容；`embed_texts` 与既有 `LLMBackend.embed` 协议一致（都是 `list[list[float]]`）；`judge()` 签名不变；`build_code_symbols(mod,bundle)` 签名不变；`StructSignal` 新增 `pairs` 字段（NamedTuple 加字段会影响既有构造点，S5 里 grep 确认）。
- **builder-check 五个缺口已闭合**：①验收改「更新后全绿」+ S11 列出 3 处改写清单；②judge 候选由 S5 `pairs` 确定性产出（4 次调用，非 376）；③S3 改手写拆项 + 显式宏翻译，不用 `parse_latex`（Constraint 13）；④KaTeX 推迟记为 S18 待批；⑤judge 两行格式解析记为 S19 待批。详见设计文档 §10。
- **Review Focus**：RF1→S2/S3、RF2→S6/S7/S8、RF3→S1、RF4→S4、RF5→S10，每条都有具名测试。
- **篇幅比例**：11 个 Task，最重的是 S9（编排）与 S4（符号表），各约 10 步；其余 7–8 步。没有哪个 Task 大到需要再拆。
