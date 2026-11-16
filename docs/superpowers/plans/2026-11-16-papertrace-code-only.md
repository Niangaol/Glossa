# 无论文模式（代码侧分析）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `papertrace build --repo` 在没有论文的情况下也产出有价值的东西：代码侧符号与超参台账、每个模块在干什么、参数量与算力粗估，并在单文件 HTML 里看见。

**Architecture:** 三层。① 纯函数层：`analyze_roles.module_roles(nodes)` 与 `analyze_metrics.module_metrics(nodes)` 只吃 trace 的 nodes 列表，不 import torch / 不读源码。② 组装层：`code_analysis.analyze_code(doc, model)` 填 `symbols.code`（复用既有 `build_code_symbols`）与新增的可选顶层键 `analysis`。③ 呈现层：`render_analysis.py` 造行，jinja 模板新增第 ⑥ 块「代码体检」。

**Tech Stack:** Python 3.13 / pytest / jinja2 / jsonschema。零新依赖。

**Spec:** docs/superpowers/specs/2026-11-16-papertrace-code-only-design.md（已获年糕批准，2026-11-16）

## Global Constraints

**仓库铁律（一直在用，逐条适用）：**

1. **单文件 ≤200 行**（Python 产品源码，口径 `len(pathlib.Path(f).read_text(encoding="utf-8").splitlines())`；测试文件不受此限）。
2. **零新依赖**（GC13）：只用标准库 + 已装好的 torch / sympy / jinja2 / jsonschema。禁 numpy / requests / parse_latex / lark / antlr4 / KaTeX。
3. **不许用 mock 填产品输出**：宁可报「认不出来」，绝不编造角色、编造参数量、编造 FLOPs。假对象只能注入在测试里，单实例，且必须断言被测路径真被走到（计数器 ≥1）。
4. **默认 offline**：不配 `PAPERTRACE_LLM_BACKEND` 时不得发起任何网络调用；本切片的代码侧分析**完全不碰 LLM**。
5. **公式写死**：confidence 的权重与增益不许漂移（0.30/0.50/0.20、增益 4、中心 0.5、绿线 0.75、黄线 0.45、GREEN_STRUCT_MIN=0.5）——本切片不改这些。
6. **GC8 不变式**：不带 `--paper` 时 nodes=128（算子 75 / 权重 18 / 输入 1 / module 34）、edges=101、counts={operators:75, degraded:2, fused:0, orphan:0, shape_broken:0, shape_unchecked:0}、anchors=[]、unresolved=[]。**新增只允许出现在 `symbols.code` 与 `analysis`。**
7. **测试环境**：PYTHONPATH 含仓库根 + pydeps；**不用 pytest 的 tmp_path**（沙箱递归删除 WinError 5），临时目录走 `tests/_tmp.py::scratch_dir`；走 CLI 的测试必须把 cwd 钉在仓库根。
8. **本机 bash 不可用**（WSL E_ACCESSDENIED / Git bash signal pipe Win32 error 5）→ 一律 pwsh。
9. **每 Task 一次提交**；既有断言只能改期望值不许删；本切片**不需要**改任何既有断言的期望值。
10. **改既有文件后先核行尾**（`core.autocrlf=true` 会把 edit 写回成 CRLF，造成整文件噪声）；提交用 `git -c core.autocrlf=false commit`。

**本切片新增（GC19–GC23）：**

- **GC19（诚实边界）**：所有估算字段名必须带 `est_`，且方法说明文本必须同时出现在 `analysis.method` 与 HTML 里；禁止出现「精确计算量」「实测 FLOPs」这类说法。
- **GC20（角色只看直接子节点）**：角色判定只用模块的直接子节点（op-level 与子模块各算各的），**禁止跨子树聚合冒充自身角色**；容器一律 `stage`。
- **GC21（认不出来就写 unknown）**：`unknown` 是合法输出，**不许**为了「看起来全都认出来了」而放宽判据或隐藏 unknown。
- **GC22（`analysis` 可选 + 生产者总写）**：schema 里不进 `required`，`schema_version` 保持 `1.0.0`；但 CLI 每条路径（含 `--skeleton`）都必须写出 `analysis`（骨架写空 modules）。
- **GC23（渲染兜底用 default 不用 or）**：模板里 `StrictUndefined` 下 `X or "兜底"` 会抛，必须用 `X | default("…", true)`；`{% if %}` 裸属性必须用 `and` 短路（参考 `spine.html.j2:54`）。

## Review Focus

1. **角色判据会不会说假话**：`root` 的 `add` 只有一个输入（位置 id），`Block` 的两个 `add` 输入等形状（残差）——把两者混为一谈，或者靠模块名/类名判定，就是本切片最可能被写坏的地方。
2. **估算冒充实测**：`est_flops` 只算 matmul/linear、忽略转置语义与逐元素算子；一旦页面或 README 写成「计算量」，用户会拿它当精确值。
3. **unknown 被静默吃掉**：为了让报告好看而在渲染层过滤 unknown，等于宣称全都认出来了。
4. **旧 trace 兼容**：`analysis` 是可选键，HTML 读没有 `analysis` 的 trace 不许崩（StrictUndefined 会抛）。
5. **GC8 漂移**：无论文路径新增符号表后，nodes/edges/counts/anchors/unresolved 必须逐项不变；`load_entry` 被提前调用后失败路径必须仍是 exit 2 + 一行错误，不冒 traceback。

## 文件结构（先定边界，再拆任务）

| 文件 | 责任 | 新建/修改 |
|---|---|---|
| `papertrace/exit_codes.py` | 退出码常量（2/4/5），cli 与 report_dump 共用 | 新建（约 15 行） |
| `papertrace/report_dump.py` | `dump` 子命令的正文（原 `cli._cmd_dump`） | 新建（约 45 行） |
| `papertrace/analyze_roles.py` | `module_roles(nodes)`：角色 + 判据 | 新建（约 130 行） |
| `papertrace/analyze_metrics.py` | `module_metrics(nodes)` / `analysis_totals(rows, nodes)` | 新建（约 90 行） |
| `papertrace/code_analysis.py` | `analyze_code(doc, model)` / `empty_analysis()` | 新建（约 70 行） |
| `papertrace/render_analysis.py` | summary_line / role_rows / role_counts / method_text / symbols_note | 新建（约 80 行） |
| `papertrace/cli.py` | 无论文也 load_entry + analyze_code；dump 改调 report_dump | 修改（197 → 约 190） |
| `papertrace/report.py` | `print_build_summary` 增一行代码分析摘要 | 修改（165 → 约 172） |
| `papertrace/templates/spine.html.j2` | 新增第 ⑥ 块 + 符号表说明 | 修改 |
| `schema/trace.schema.json` | 可选顶层 `analysis` + 两个 `$defs` | 修改 |
| `tests/test_code_roles.py` | 角色判据 8 条 | 新建 |
| `tests/test_code_metrics.py` | 指标 6 条 | 新建 |
| `tests/test_code_analysis.py` | 组装 + schema 6 条 | 新建 |
| `tests/test_code_only_cli.py` | CLI 端到端 5 条 | 新建 |
| `tests/test_code_html.py` | HTML 5 条 | 新建 |
| `README.md` / 演示产物 / 本计划 | 文档与记录 | 修改 |

## Task C1：把 dump 子命令搬出 cli.py（纯重构，零行为变化）

**Files:**
- Create: `papertrace/exit_codes.py`、`papertrace/report_dump.py`
- Modify: `papertrace/cli.py`（删掉 `_cmd_dump` 与三个常量定义，改 import）

**Consumes:** `papertrace/cli.py:37-41` 的三个常量、`:162-183` 的 `_cmd_dump`、`papertrace/report.py` 的 `print_ops/print_edges/print_overview`。
**Produces:** `report_dump.run_dump(trace_path: str) -> int`，行为与旧 `cli._cmd_dump` **逐字节相同**（退出码 0 / 2 / 2）。

**为什么先做这个：** `cli.py` 现在 197/200 行，C5 还要往里加代码；先搬走 22 行，给后面留余量。

**Steps:**
- [ ] 1. 新建 `papertrace/exit_codes.py`：`UNIMPLEMENTED = 2`、`MISSING_RUNTIME = 4`、`UNTRACEABLE = 5`，每条带一行中文注释（语义照抄 cli.py:37-41 的注释）。
- [ ] 2. 新建 `papertrace/report_dump.py`：`from papertrace.exit_codes import UNIMPLEMENTED`；把 `cli._cmd_dump` 的正文**逐字**搬成 `run_dump(trace_path: str) -> int`（参数从 `args.trace` 变成 `trace_path`，其余不动，含两处 `return 2`/一处 `return UNIMPLEMENTED` 与全部中文错误文案）。
- [ ] 3. `cli.py`：删掉三个常量定义与 `_cmd_dump`，改 `from papertrace.exit_codes import MISSING_RUNTIME, UNIMPLEMENTED, UNTRACEABLE` 与 `from papertrace.report_dump import run_dump`；`main()` 里 `return _cmd_dump(args)` → `return run_dump(args.trace)`；`print_ops/print_edges/print_overview/load_trace` 若在 cli 里已无其他用处就一并删掉 import（保留仍被 `_cmd_build` 用的）。
- [ ] 4. **对拍验证**：改动前先在 HEAD 上跑一次 `python -m papertrace dump --trace output/demo/code-only/trace.json --ops` 存 stdout 到 `output/c1-before.txt`；改动后再跑一次存 `output/c1-after.txt`；用 python 读字节比较必须完全相同（`--edges` 与无 flag 两种也各对拍一次）。
- [ ] 5. 跑全量：**807 passed**（一条不少、一条不多）。
- [ ] 6. 行数 census：`cli.py` 必须比改前少 ≥15 行；`report_dump.py`、`exit_codes.py` 各自 ≤200。
- [ ] 7. 提交：`refactor: move the dump command out of cli`（`git -c core.autocrlf=false commit`）。

**变异探针：** 把 `run_dump` 里 `--ops` 分支的 `print_ops(doc)` 换成 `print_overview(doc)` → 步骤 4 的字节对拍必须不等。还原后 sha256 与改前一致。

**Acceptance:** 807 passed；dump 三种调用的 stdout 逐字节相同；`cli.py` ≤182 行。

---

## Task C2：模块角色识别（纯函数）

**Files:**
- Create: `papertrace/analyze_roles.py`（约 130 行）、`tests/test_code_roles.py`

**Consumes:** trace 的 `nodes` 列表。节点事实（已实测）：模块节点 `level != "op"`、`op` 字段是类名、`shape_*` 恒空；算子节点 `level == "op"`，`kind` ∈ {op, param, input, const}。
**Produces:** `module_roles(nodes: list[dict]) -> list[dict]`，按 `module_id` 升序，每条 **恰好** 5 个键：`module_id` / `class` / `role` / `evidence` / `op_count`。`op_count` = 直接子节点里 `level=="op" and kind=="op"` 的个数（param/input/const 不算）。

**冻结枚举（10 个）：** `attention / mlp / layernorm / embedding / linear / activation / dropout / residual / stage / unknown`。

**判据（顺序即优先级，只看直接子节点，GC20）：**

| 顺序 | role | 判据 |
|---|---|---|
| 1 | attention | 直接算子序列里存在 `matmul … softmax … matmul`（softmax 之前至少 1 个 matmul，之后至少 1 个 matmul） |
| 2 | layernorm | 直接算子含 `layer_norm` |
| 3 | embedding | 直接算子含 `embedding` |
| 4 | residual | 直接算子含 `add`，且该 add 的 `inputs` ≥2 项、各项形状相同、且等于该 add 的 `shape_out` |
| 5 | dropout | 直接算子非空且全是 `dropout` |
| 6 | activation | 直接算子非空且全在 `ACTIVATION_OPS = {gelu, relu, silu, sigmoid, tanh, mish}` |
| 7 | linear | 直接算子非空且全在 `{linear, matmul}` |
| 8 | mlp | 直接子模块里含 `linear`/`matmul` 的 ≥2 个、且含激活算子的 ≥1 个，且本模块直接算子不含 `softmax`/`layer_norm`/`embedding` |
| 9 | stage | 有直接子模块，以上都不成立 |
| 10 | unknown | 其余（无法归类） |

**evidence 必须点名判据与命中数**，中文短句，例如 attention 写「自身 22 个算子里有 matmul→…→softmax→…→matmul 子序列」；residual 写「2 个 add 都有 2 个等形状输入」；mlp 写「直接子节点里 2 个含 linear、1 个含 gelu」；stage 写「3 个直接子模块，自身只有 arange/add，未命中任何结构判据」；unknown 写「直接算子 foo/bar 不在冻结的激活/线性/归一化名单里，按约定不猜」。**不许空串、不许只写规则 id。**

**Steps:**
- [ ] 1. 写失败测试 `tests/test_code_roles.py`（8 条，见下）。
- [ ] 2. 跑 `pytest -q tests/test_code_roles.py`，确认收集期因模块不存在而红。
- [ ] 3. 实现 `analyze_roles.py`（`_direct_ops` / `_child_modules` / `_has_residual_add` / `_subtree_ops` 等私有 helper）。
- [ ] 4. `pytest -q tests/test_code_roles.py` → 8 passed；全量 → **815 passed**（807+8）。
- [ ] 5. 真夹具打印 34 条角色，逐条与 Acceptance 的统计对齐。
- [ ] 6. 提交：`feat: recognize what each module is doing`。

**测试（8 条，冻结名）：**
1. `test_attention_role_comes_from_the_matmul_softmax_matmul_pattern` —— `root/transformer.h.0.attn` 与 `h.1.attn` 都是 `attention`、`op_count == 22`，evidence 含 `matmul` 与 `softmax`。
2. `test_block_is_not_an_mlp` —— `root/transformer.h.0` 与 `root/transformer.h.1` 的 role **不是** `mlp`；`root` 与 `root/transformer` **不是** `mlp`。
3. `test_residual_requires_two_equal_inputs` —— `h.0`/`h.1` = `residual`；`root` 的 add 只有 1 个输入 → `root` = `stage`。
4. `test_mlp_container_is_recognized` —— `h.0.mlp`/`h.1.mlp` = `mlp`，evidence 同时含 `linear` 与 `gelu`。
5. `test_unknown_is_reported_not_guessed` —— 合成 nodes：一个模块直接算子 `foo`、`bar`（无子模块）→ `unknown`；evidence 非空且含 `不猜`。
6. `test_roles_cover_every_module_exactly_once` —— 真夹具返回 **34** 条、`module_id` 集合与 `[n["id"] for n in nodes if n["level"]!="op"]` 完全相等、按 id 升序。
7. `test_role_summary_for_the_fixture` —— 统计出 `attention 2 / mlp 2 / layernorm 5 / embedding 2 / linear 9 / dropout 7 / activation 2 / residual 2 / stage 3 / unknown 0`（合计 34）。
8. `test_roles_do_not_depend_on_class_names` —— 把真夹具所有模块节点的 `op`（类名）改成 `"Foo"` 后重算，角色**逐条不变**。

**变异探针：** 把 `residual` 判据的「≥2 个输入」删掉（只判有 add）→ 测试 3 必红（`root` 变 residual）。还原后 sha256 一致。

**Acceptance:** 8 passed；全量 815 passed；34 条角色与测试 7 的统计逐项相同。

---

## Task C3：参数 / 峰值激活 / 粗估 FLOPs（纯函数）

**Files:**
- Create: `papertrace/analyze_metrics.py`（约 90 行）、`tests/test_code_metrics.py`

**Consumes:** trace 的 `nodes`。实测事实：18 个 param 节点、`shape_out` 是 int 列表；`matmul` 的 `shape_in` 是第一个输入的形状；`linear` 的 `shape_in=[2,8,32]`、`shape_out=[2,8,96]`。
**Produces:** 两个函数：
- `module_metrics(nodes) -> list[dict]`：按 `module_id` 升序，每条 4 个键 `module_id` / `params` / `max_activation` / `est_flops`（都是 int，缺数据时 0，不是 None）。
- `analysis_totals(rows, nodes) -> dict`：`modules` / `params` / `max_activation` / `est_flops` / `degraded` / `degraded_reasons`（去重后升序）。

**口径（写死在 docstring 里，GC19）：**
- `params`：子树内 `kind=="param"` 节点 `shape_out` 乘积求和。**精确**。
- `max_activation`：子树内 `kind=="op"` 节点 `shape_out` 乘积最大值，**元素数不是字节**，param 节点不计。
- `est_flops`：子树内 `op in ("matmul","linear")` 的 `2 * prod(shape_out) * shape_in[-1]` 求和；其余算子计 0。**粗估**。
- `degraded`：子树内 `degraded == True` 的节点数；`degraded_reasons` 取它们的 `degraded_reason`（去重、升序、跳过空串）。
- 子树 = 自身 + 所有后代（`parent_id` 是父节点 id 的层级树；`root` 的 parent 是 `None`）。

**Steps:**
- [ ] 1. 写失败测试（6 条，见下）。
- [ ] 2. `pytest -q tests/test_code_metrics.py` → 收集期 ImportError 红。
- [ ] 3. 实现（`_prod` / `_subtree` / `_est_flops` 私有 helper；**不要 import torch**）。
- [ ] 4. `pytest -q tests/test_code_metrics.py` → 6 passed；全量 → **821 passed**。
- [ ] 5. 提交：`feat: measure parameters, activations and rough FLOPs`。

**测试（6 条，冻结名）：**
1. `test_params_are_exact_for_the_fixture` —— `root` 的 params == **29856**；`h.0.attn.c_attn` == **3072**；`h.0.ln_1` == **32**。
2. `test_max_activation_counts_elements_not_bytes` —— `root` 的 max_activation == **2048**（= 2×8×128 的 c_fc 输出），并断言它**不是** 8192（若是字节数会 ×4）。
3. `test_est_flops_only_counts_matmul_and_linear` —— `root` 的 est_flops == **884736**；`h.0.attn.c_attn` == **98304**（2×1536×32）。
4. `test_module_without_metrics_is_zero_not_none` —— 一个只有 dropout 算子的模块：params 0、est_flops 0，类型都是 `int`。
5. `test_degraded_nodes_are_reported` —— `root` 的 `degraded` == 2；`degraded_reasons` 长度 ≥1 且每条含 `split`。
6. `test_totals_sum_the_root_subtree` —— totals 的 params/max_activation/est_flops 与 `root` 那行相同；`modules` == 34。

**变异探针：** 把 `est_flops` 的 `2 *` 去掉 → 测试 3 必红（884736 → 442368）。还原后 sha256 一致。

**Acceptance:** 6 passed；全量 821 passed。

---

## Task C4：组装层 + schema 可选 `analysis`

**Files:**
- Create: `papertrace/code_analysis.py`（约 70 行）、`tests/test_code_analysis.py`
- Modify: `schema/trace.schema.json`

**Consumes:** `analyze_roles.module_roles`、`analyze_metrics.module_metrics/analysis_totals`、`symbols.code_table.build_code_symbols(mod, bundle)`（既有）、trace dict。
**Produces:** `analyze_code(doc: dict, model) -> dict`（原地填 `doc["symbols"]["code"]` 与 `doc["analysis"]`，返回同一个 doc）与 `empty_analysis() -> dict`。

**`analysis` 形状（GC22：可选、生产者总写）：**
`§json
{"modules": [{"module_id": "...", "class": "Block", "role": "residual", "evidence": "...",
              "op_count": 2, "params": 12608, "max_activation": 2048, "est_flops": 409600}],
 "totals": {"modules": 34, "params": 29856, "max_activation": 2048,
            "est_flops": 884736, "degraded": 2, "degraded_reasons": ["..."]},
 "roles": {"attention": 2, "mlp": 2},
 "method": "参数量按权重张量元素数精确统计；FLOPs 只对 matmul/linear 估算（2×输出元素数×输入最后一维），未考虑转置语义与逐元素算子，属于粗估，并随 batch/序列长度线性变化。"}
`§
- `roles` 只列**出现过的**角色，key 是角色名、value 是整数。
- `empty_analysis()` = 与上同结构但 modules 空、totals 全 0、roles 空、method 同一段文本。
- `method` 的文本定义成 `code_analysis.METHOD_TEXT` 一个模块级常量，**trace 与 HTML 共用同一份**（render_analysis 引用它），不许两处手抄。

**schema 改动（精确）：**
- 顶层 `properties` 增加 `"analysis": {"$ref": "#/$defs/analysis"}`（**不进 required**）。
- `$defs` 增加三个定义：
  - `analysis`：`type object`、`additionalProperties: false`、`required: [modules, totals, roles, method]`；`modules` 数组 items → `$ref analysisModule`；`totals` → `$ref analysisTotals`；`roles` = `{"type":"object","additionalProperties":{"type":"integer","minimum":0}}`；`method` = `{"type":"string","minLength":1}`。
  - `analysisModule`：`additionalProperties: false`、`required: [module_id, class, role, evidence, op_count, params, max_activation, est_flops]`，`role` 用 `enum` 十个角色名，数字字段 `{"type":"integer","minimum":0}`，`evidence` `minLength: 1`。
  - `analysisTotals`：`additionalProperties: false`、`required: [modules, params, max_activation, est_flops, degraded]`，`degraded_reasons` 可选数组 items string。
- `schema_version` **不动**（保持 `"1.0.0"` 的 const）。

**Steps:**
- [ ] 1. 写失败测试（6 条，见下）。
- [ ] 2. `pytest -q tests/test_code_analysis.py` → ImportError 红。
- [ ] 3. 改 schema；实现 `code_analysis.py`（`METHOD_TEXT` 常量；`analyze_code` 先填 symbols 再组装 analysis；角色与指标按 `module_id` 合并成一条）。
- [ ] 4. `pytest -q tests/test_code_analysis.py` → 6 passed；全量 → **827 passed**。
- [ ] 5. 真夹具跑一遍：`validate_trace(doc)` 通过；`analysis.modules` 34 条；`symbols.code` 5 条。
- [ ] 6. 提交：`feat: assemble the code-only analysis into trace.json`。

**测试（6 条，冻结名）：**
1. `test_analysis_has_every_module_once` —— 34 条、`module_id` 唯一、每条 8 个键齐全。
2. `test_symbols_code_is_filled_without_a_paper` —— `symbols.code` 的 symbol 集合 == `{"B","T","D","H","Dh"}`。
3. `test_symbols_paper_and_mapping_stay_empty_without_a_paper` —— `symbols.paper == []` 且 `symbols.mapping == []`。
4. `test_analysis_is_optional_in_the_schema` —— `minimal_trace()`（不含 analysis）仍然 `validate_trace` 通过。
5. `test_analysis_shape_passes_validation` —— 真夹具 doc 带 analysis **通过** `validate_trace`；再把 `roles` 里塞一个负数 → `TraceSchemaError`。
6. `test_method_text_says_it_is_an_estimate` —— `analysis["method"]` 含 `"粗估"` 且与 `code_analysis.METHOD_TEXT` 逐字相等。

**变异探针：** 把 `analyze_code` 里写 `doc["analysis"]` 的那行改成只写 `modules` 不写 `totals` → 测试 5 必红。还原后 sha256 一致。

**Acceptance:** 6 passed；全量 827 passed；真夹具 validate_trace 通过。

---

## Task C5：CLI 接线（无论文也分析）

**Files:**
- Modify: `papertrace/cli.py`、`papertrace/report.py`
- Create: `tests/test_code_only_cli.py`

**Consumes:** `code_analysis.analyze_code / empty_analysis`、`build_trace.load_entry`。
**Produces:** `build --repo X`（不带 `--paper`）产出的 trace 里 `symbols.code` 与 `analysis` 都非空；`--skeleton` 也有 `analysis`（空 modules）；stdout 多一行代码分析摘要。

**接线形状（cli._cmd_build）：**
`§python
    model = None
    if not args.skeleton:
        try:
            model = load_entry(args.repo, args.entry)
        except BuildError as exc:
            print(f"papertrace build：{exc}", file=sys.stderr)
            return UNIMPLEMENTED
    if model is None:
        doc["analysis"] = empty_analysis()
    else:
        analyze_code(doc, model)      # 无论文也填 symbols.code + analysis
`§
- 位置：`build_trace` 成功之后、`--paper` 分支之前；`--paper` 分支复用这个 `model`，**不许再 load 一次**。
- `report.print_build_summary` 末尾加一行（只在 `analysis` 存在且 modules 非空时打）：`代码分析：34 个模块 · 参数量 29,856 · 峰值激活 2,048 元素 · 粗估 FLOPs 884,736`（千位分隔用 `f"{n:,}"`）。

**Steps:**
- [ ] 1. 写失败测试（5 条，见下）。
- [ ] 2. `pytest -q tests/test_code_only_cli.py` → 断言级红（symbols 空 / analysis 缺）。
- [ ] 3. 改 cli + report（`cli.py` 必须仍 ≤200；改完实测行数并写进报告）。
- [ ] 4. `pytest -q tests/test_code_only_cli.py` → 5 passed；全量 → **832 passed**。
- [ ] 5. **GC8 复核**：`tests/test_spine_end_to_end.py::test_no_paper_flag_is_unchanged` 单条必须绿；再手工真跑一次 CLI，逐项核对 nodes=128 / edges=101 / counts / anchors=[] / unresolved=[]。
- [ ] 6. 提交：`feat: analyze a repository without any paper`。

**测试（5 条，冻结名）：**
1. `test_build_without_paper_writes_symbols_and_analysis` —— 真跑 CLI（`scratch_dir`），exit 0；`symbols.code` 5 条；`analysis.totals.params == 29856`；`analysis.method` 非空。
2. `test_gc8_numbers_are_untouched` —— 同上产物：nodes 128 / edges 101 / counts 六项 / anchors `[]` / unresolved `[]` / `meta.paper == {"source":"none","unit_count":0,"ingest_mode":"none"}`。
3. `test_skeleton_still_writes_empty_analysis` —— `--skeleton`：exit 0、nodes 0、`analysis.modules == []`、`analysis.totals.params == 0`、`symbols.code == []`。
4. `test_paper_path_still_fills_paper_symbols` —— 带 `--paper`（offline）：`symbols.paper` 非空、`symbols.mapping` 非空、`analysis` 仍在（回归：别把论文路径搞坏）。
5. `test_build_summary_mentions_the_analysis` —— stdout 含 `代码分析` 与 `粗估 FLOPs`。

**变异探针：** 把 `analyze_code(doc, model)` 改回只在 `--paper` 分支里调用 → 测试 1 必红（symbols.code 空）。还原后 sha256 一致。

**Acceptance:** 5 passed；全量 832 passed；GC8 单测绿；`cli.py` ≤200 行。

---

## Task C6：HTML 第 ⑥ 块「代码体检」

**Files:**
- Create: `papertrace/render_analysis.py`（约 80 行）、`tests/test_code_html.py`
- Modify: `papertrace/render_html.py`、`papertrace/templates/spine.html.j2`

**Consumes:** `doc["analysis"]`、`code_analysis.METHOD_TEXT`、`doc["symbols"]`、`meta.runtime.counts`。
**Produces:** 模板里 `<section id="analysis">`，含 5 件东西：总量行 / 角色分布（**unknown 必须列出**）/ 模块角色表 / 降级与形状异常 / 方法说明原文；以及 ⑤ 符号表在无论文时的说明句。

**实现约束：**
- `render_html.py` 现在 183 行，只允许加 ≤8 行（把 `render_analysis` 造好的行传给模板）。
- 模板读 `doc.analysis` 一律走 `| default(none, true)` 与 `{% if %}` 短路，**不许裸访问**（GC23；旧 trace 没有 analysis 时不能崩）。
- 模块表列：模块 id / 类名 / 角色 / 参数量 / 峰值激活 / 估算 FLOPs / 判据（evidence）。按 `module_id` 排序，**不折叠 unknown**。
- 数字用 `f"{n:,}"` 千位分隔；`est_flops` 列头写「粗估 FLOPs」，不许写「计算量」。

**Steps:**
- [ ] 1. 写失败测试（5 条，见下）。
- [ ] 2. `pytest -q tests/test_code_html.py` → 红（无 analysis section）。
- [ ] 3. 写 `render_analysis.py`；改模板与 `render_html.py`。
- [ ] 4. `pytest -q tests/test_code_html.py` → 5 passed；全量 → **837 passed**。
- [ ] 5. 真跑一次 CLI 生成 HTML，核对第 ⑥ 块内容（写进报告，不做或声称做浏览器视觉目检之外的判断）。
- [ ] 6. 提交：`feat: show the code health section in the HTML`。

**测试（5 条，冻结名）：**
1. `test_html_has_a_code_health_section` —— `<section id="analysis">` 存在；含 `代码体检`；含 `29,856` 与 `884,736`。
2. `test_html_lists_unknown_and_degraded` —— 合成一个带 `unknown` 角色的 doc：页面里 `unknown` 字样出现，且 `degraded` 计数可见。
3. `test_html_shows_the_method_text` —— 页面含 `code_analysis.METHOD_TEXT` 的原文（逐字 in）。
4. `test_symbols_table_says_there_is_no_paper` —— 无论文 doc：⑤ 块非空（有 code 行），且有一句含 `没有论文` 的说明。
5. `test_html_survives_a_trace_without_analysis` —— 把 `doc.pop("analysis")` 后 `render_html` **不抛**（旧 trace 兼容），且页面里没有 `Traceback`。

**变异探针：** 在 `render_analysis.role_counts` 里过滤掉 `unknown` → 测试 2 必红。还原后 sha256 一致。

**Acceptance:** 5 passed；全量 837 passed；`render_html.py` ≤200、`render_analysis.py` ≤200。

---

## Task C7：文档、演示产物与执行记录

**Files:**
- Modify: `README.md`（新增「## 无论文也能分析」段 + 已知局限补 4 条）、`docs/superpowers/plans/2026-11-16-papertrace-code-only.md`（追加执行记录）
- 重新生成 `output/demo/code-only`、`output/demo/with-paper`、`output/demo/fallback-yellow`

**Steps:**
- [ ] 1. README 新段必须写清：无论文时能看到什么（符号台账 / 模块角色 / 参数与粗估 FLOPs）、看不到什么（没有论文侧符号与映射、没有 anchor）、`est_flops` 是粗估且随 batch/seq 线性变化、`unknown` 是合法输出。
- [ ] 2. 已知局限补 4 条：角色是结构识别（自定义算子名会落 unknown）、FLOPs 粗估、共享权重按节点计数可能偏大、跨模块数据流图没做。
- [ ] 3. 重生成三份演示（脚本可抄 `output/controller-probes/l5_regen_demo.py`），记录三份的 nodes/edges/anchors/unresolved/analysis.totals/HTML 字节数。
- [ ] 4. 本计划末尾追加「执行记录」段：每个 Task 的提交、修循环轮数、被评审拦下的问题。
- [ ] 5. 全量跑一次 **837 passed**；census 无 >200；提交：`docs: record the code-only analysis slice`。

**Acceptance:** 三份演示都含 `analysis`；README 段落与已知局限都在；全量 837 passed。

---

## 自审（写完计划后逐项核过）

1. **每个 Task 都有独立可测的交付物？** C1 重构（807 不变）、C2 角色（8 测试）、C3 指标（6）、C4 组装+schema（6）、C5 CLI（5）、C6 HTML（5）、C7 文档。✅
2. **接口与签名在计划里是逐字的？** `module_roles(nodes)`、`module_metrics(nodes)`、`analysis_totals(rows, nodes)`、`analyze_code(doc, model)`、`empty_analysis()`、`run_dump(trace_path)`、render_analysis 五个函数名、`METHOD_TEXT` 常量、analysis 的 4 个顶层键与 module 条目 8 个键。✅
3. **期望值是实测过的数字？** 29856 / 2048 / 884736 / 98304 / 34 / 角色分布——全部来自本机原型探针 `output/controller-probes/_roles.py`。✅
4. **有没有把「猜」写成「测」？** 角色判据全部可从 trace 字段验证；`est_flops` 明确自称粗估；`unknown` 是合法输出。✅
5. **既有测试会不会被打破？** 只有 C5 改变「无论文 build 的 trace 内容」，而 `test_no_paper_flag_is_unchanged` 断言的是 nodes/edges/counts/anchors/unresolved/meta.paper——都不受影响；`analysis` 在 schema 里可选，`minimal_trace` 不变。C6 让 `render_html` 能读没有 analysis 的 doc，旧 fixture 不会崩。✅

## 执行记录

> 计划写时的全量预估（C6 / C7 都写「837 passed」）偏低：实际链路里 C2 与 C3+C4 两个修复轮共新增 7 条测试，所以 C6 落地是 844、C6 修复轮后 847。下表条数全部是当轮实测，不是计划预估值。

| Task | 提交 | 修复轮 | 全量实测 | 评审拦下的问题（含修复情况） |
| --- | --- | --- | --- | --- |
| C1 | `375bd97` | — | 807（基线 807，一条不多一条不少） | Approved（0/0/2）：Minor 2（`cli.py` import 行等），不阻塞 |
| C2 | `c0f3882` | `7c7da5c`（只补 `tests/test_code_roles.py` 79 行，产品码一行未动） | 815 → 830 | 首轮 Important 1（三条判据删掉后没有测试会红）+ Minor 2；修复轮后复审 Approved，另留 3 个边角子条件无守卫的 Minor |
| C3 | `55a732d` | 并入 C3+C4 合并轮 | 821 | Important 2 + Minor 2 |
| C4 | `fabb7aa` | 同上 | 827 | Approved 但 Important 1（重复 `module_id` 静默覆盖，合法 trace 不可达）+ Minor 4 |
| C3+C4 合并修复轮 | `70d2cab` | — | 834 | 复审 Approved（0/0/1）；那条 Minor 就是 `tests/test_code_metrics.py:301-303` 的 1/4 概率写错，C7 批处理修掉 |
| C5 | `e503444` | — | 839 | Approved（0/0/3）；3 条 Minor 里 2 条进 C7 批处理（cli.py 陈旧 docstring、测试 2 的 `meta.paper` 全字典断言），第 3 条 flake 证据链按「未根因」留账 |
| C6 | `57784b4` | `c78e37e` | 844 → 847 | Important 1：`analysis` 有 modules 缺 totals 时摘要伪造「0 个模块 · 参数量 0」与 34 行表自相矛盾；另有 F-C6-1 排序钉子（`role_counts` 降序与「缺席角色不补 0」零守卫，评审三条变异全绿）+ 六条 Minor，全部在修复轮修掉，复审确认 |
| C7 | 本提交 | — | 847 | 四条 Minor 批处理：① cli.py docstring 与行为不再矛盾；② `test_code_metrics.py` 1/4 → 1/2；③ 测试 2 补 `meta.paper` 全字典断言；④ R221（第 ⑥ 块排页面末尾）记进 README 已知局限，不开新切片 |
| C6 修复轮 2 | `b4d12ec` | — | 851 | Important 1：`analysis.modules` 缺口径时 ⑥ 块把「模块行缺失」归因成「骨架模式」（假归因），摘要与 34 行表自相矛盾；修法 4 文件 +148/−54（`render_analysis.py` 三态渲染、`render_symbols.py` 抽出符号表说明句、`spine.html.j2` 4 行、`tests/test_code_html.py` 69 行），另补 R223 tie-break 与两处空表/行数守卫，复审确认 |
| 收尾评审 | — | `b8d93a3` | 854 | Changes required 1 条 Important（README 与 `analyze_roles.py:14` 把枚举顺序说成判据优先级）+ 4 条 Minor：修法 7 文件 +93/−5，只动一行注释与一句模板文案，产品逻辑零改动；同一提交补 residual `inputs[0]==shape_out`、mlp 闸的 `layer_norm`/`embedding` 两个名字、totals 逐键与 bool 三类守卫（+3 条测试）。定向复审 Approved with minor notes，剩两条 Minor：旧 trace 空态文案无钉子、census 基准点标注过期（均由控制器本提交补上：一条断言 + 本行记录） |

### C7 交付明细

- **README**：新增顶层小节「## 无论文也能分析」（起始行 467，位于「## 已知局限」之前）；「现在是什么状态」加一句指向新小节；已知局限补 5 条（角色结构识别落 `unknown`、`est_flops` 粗估随 batch/seq 线性、共享权重按节点计数可能偏大、跨模块数据流没做、R221 第 ⑥ 块在页面末尾）。
- **三份演示重生成**（`output/demo/`，不被 git 跟踪；脚本 `output/controller-probes/c7_regen_demo.py` 照抄 `cli.py` 链路）：

  | 场景 | nodes | edges | anchors | unresolved | analysis.totals | trace.json | index.html |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | code-only | 128 | 101 | 0 | 0 | modules 34 · params 29,856 · max_activation 2,048 · est_flops 884,736 · degraded 2 | 137,956 B | 52,492 B |
  | with-paper | 128 | 101 | 0 | 8 | 同上 | 144,188 B | 61,572 B |
  | fallback-yellow | 128 | 101 | 4（全 yellow） | 0 | 同上 | 141,271 B | 55,491 B |

  三份 `index.html` 都含 `<section id="analysis">`；三份 `trace.json` 都过 `validate_trace` 且 `leaked_absolute` 为 0。
- **census**（收尾修复轮之后实测，HEAD `b8d93a3`；`b8d93a3` 只改一行注释与一句模板文案，行数不变）：`papertrace/` 递归 86 个 `.py`（b4d12ec 新增 `render_symbols.py`，28 行），无 >200 行；正好 200 行的三个文件（`parse_paper/latex_safe.py`、`render_analysis.py`、`symbols/code_table.py`）都顶格，下次改它们要腾行。`cli.py` 182 行（HEAD 177 + docstring 5 行）；C6 修复轮 2 后全量 **851 passed**，收尾修复轮后 **854 passed**。
- **全量**：847 passed in 139.29s，与 C6 修复轮基线一条不多一条不少（本 Task 只加断言、不加测试条数）。
