# PaperTrace 重构 + 工作区精简 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 1324 项测试持续全绿的前提下，删掉 22 个空壳模块、把 `papertrace` 根下 17 个散模块收进子包、把 `glossa` 的 30 处跨包 import 收成单一门面、把 103 个测试文件按包分组。

**Architecture:** 四个阶段串行，每个阶段结束时整套测试必须仍然是 1324 passed。所有代码 import 都是绝对形式（`from papertrace.X import ...`，实测 110 处，零相对 import），因此搬家是纯机械的模块路径重写；测试的作用是characterization suite，用来证明行为没变。

> **执行结果更正（2026-11-20 核验）**：实际收口是 **1299 passed**，不是 1324。差的 25 项不是丢了测试，也不是放宽了断言——`tests/papertrace/test_imports.py` 按**模块名**参数化，删掉 22 个空壳模块后它们的 import 用例自然消失（27 条消失，其中 `papertrace.spine.claims` / `papertrace.spine.fallback` 2 条以新路径回补），`def test_` 函数数改前改后都是 **1036**。所以本文里「数字必须一点不差」这条口径与 Task 1 自相矛盾：**真正的硬约束是零丢用例、零放宽断言、零行为改动**，不是那个总数；读这份计划时以这条为准。

**Tech Stack:** Python 3.13、pytest 9.2、jinja2、jsonschema；无构建步骤，`python -m papertrace` / `python -m glossa` 直接跑。

**Spec:** `docs/superpowers/specs/2026-11-19-papertrace-refactor-design.md`

## Global Constraints

- **验证命令固定这一条**（`python -m` 才把仓库根放进 `sys.path`，`tests.common` 才 import 得到）：
  ```
  PYTHONPATH="D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps" PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "C:/Users/niangao/AppData/Local/Programs/Python/Python313/python.exe" -m pytest -q
  ```
- **每个阶段都必须 `1324 passed`**。数字变了就是失败，不是「可以接受」。
  > 这条按**文首执行结果更正**读：删模块必然少参数化用例，最终 1299 passed / 1036 个 `def test_` 不变才是硬指标。
- **不 commit、不 stash、不 git add**。改动只留在工作区，用户没让提交。
- **零写入区**：`docs/studio/`、`docs/superpowers/specs/2026-11-17-glossa-studio-design.md`、`pydeps/`、`PaperTrace_工程落地计划书.docx`、`scripts/build_plan_docx.py`、`scripts/check_plan_docx.py`。
- **不改运行时行为**：不删函数逻辑、不改 CLI 参数、不改模板输出、不改常量值。
- **检查只许加严**：任何一处为了「让测试过」而放宽断言，都算失败。
- 搬家用 `mv`（**不要用 `git mv`**：它会自动把改动放进暂存区，与「不暂存」约束冲突；git 提交时按内容自动识别重命名）。
- 路径重写规则：把 `papertrace.<旧路径>` 按**词边界**替换为 `papertrace.<新路径>`，正则用 `(?<![A-Za-z0-9_.])papertrace\.spine(?![A-Za-z0-9_])` 这种带边界的形式，否则 `papertrace.spine.spine` 会误伤 `papertrace.spine.anchor`。

## Review Focus

- **`papertrace.schema` 新包名**：`jsonschema` 的 import 与 `schema/` 包同名不同物，确认 `from jsonschema import ...` 未被污染、`papertrace/schema/` 内部不会误 import 到三方库。
- **`pyproject.toml` 的 `package-data`**：`"papertrace" = ["templates/*.j2"]` 与 `"glossa" = [...]` 是按包名钉的；`render/html.py` 若搬进 `render/`，模板仍在 `papertrace/templates/`，要确认 `importlib.resources` 的锚点包没变成 `papertrace.render`。
- **`tests/test_glossa_packaging.py`**：它 rglob 检查 package-data 覆盖面，搬家后要确认它数的是文件而不是模块路径。
- **`tests/test_align_no_generation.py`**：它 rglob 扫描 `papertrace/align` 与 `papertrace/llm` 找禁用调用，这两个目录不动，但重写 import 后要确认没把字符串形式的模块名改坏。
- **循环 import**：`build/` → `schema/` → `render/` 的依赖方向若出现反向，`python -m papertrace` 启动即炸，比测试更早暴露。

---

### Task 1: 拔掉 22 个空壳模块（阶段 A）

**Files:**
- Delete: `papertrace/detail/`（`__init__.py annotations.py cache.py closure.py l0.py l1.py l2.py l3.py stale.py`）
- Delete: `papertrace/diff/`（`__init__.py dim.py missing.py reverse.py struct.py`）
- Delete: `papertrace/trace_runtime/`（`__init__.py discover.py probe.py profile.py`）
- Delete: `papertrace/ingest/arxiv.py`、`papertrace/ingest/repo.py`
- Delete: `papertrace/parse_code/einops_expand.py`、`export_try.py`、`loop_fold.py`、`treesitter_fallback.py`
- Delete: `papertrace/symbols/shape_prop.py`
- Create: `docs/未实现能力.md`

**Interfaces:**
- Consumes: 无
- Produces: 无代码接口；`docs/未实现能力.md` 供以后重建能力时查阅

- [ ] **Step 1: 确认这 22 个文件确实零引用**

```bash
cd /d/AgentPrograms/PaperTrace
grep -rn "detail\.l0\|detail\.l1\|detail\.l2\|detail\.l3\|detail\.annotations\|detail\.cache\|detail\.closure\|detail\.stale\|diff\.dim\|diff\.missing\|diff\.reverse\|diff\.struct\|trace_runtime\.\|ingest\.arxiv\|ingest\.repo\|einops_expand\|export_try\|loop_fold\|treesitter_fallback\|shape_prop" --include=*.py papertrace glossa tests scripts
```
Expected: 无输出（只有这些文件自己内部的字符串可能出现）

- [ ] **Step 2: 把三个整包和 7 个单文件删掉**

用 `git rm -r --cached` 不合适（不提交），直接用 `git rm -r` 会让文件进入暂存区 —— 改为 `rm -r` 删除文件，让改动留在工作区未暂存：

```bash
cd /d/AgentPrograms/PaperTrace
rm -rf papertrace/detail papertrace/diff papertrace/trace_runtime
rm -f papertrace/ingest/arxiv.py papertrace/ingest/repo.py
rm -f papertrace/parse_code/einops_expand.py papertrace/parse_code/export_try.py
rm -f papertrace/parse_code/loop_fold.py papertrace/parse_code/treesitter_fallback.py
rm -f papertrace/symbols/shape_prop.py
find papertrace -name '__pycache__' -prune -exec rm -rf {} +
```

- [ ] **Step 3: 写 `docs/未实现能力.md`**

逐条记录被删的 23 个函数：原模块路径、函数签名、docstring 原文（设计意图）、删除日期。格式：

```markdown
# 未实现能力清单

2026-11-19 从代码树移出。这些模块只有 `raise NotImplementedError` 的实现、零引用，
占着目录但不生效。设计意图保留在这里，将来要做时照此重建；不要因为「文件没了」就重新发明。

| 原路径 | 签名 | 设计意图（原 docstring） |
|---|---|---|
| `papertrace/detail/l0.py` | `render_l0(node) -> object` | L0：纯模板。零 LLM 调用——能由元数据填出来的东西不该烧 token。 |
| ... | ... | ... |
```

23 行必须一条不少，内容从每个被删文件的 docstring 与签名**原样抄出**。

- [ ] **Step 4: 跑全量测试**

Run: 上面 Global Constraints 里的 pytest 命令
Expected: `1324 passed`（数字必须与基线一致）

- [ ] **Step 5: 确认没有残留空壳**

```bash
cd /d/AgentPrograms/PaperTrace
grep -rn "NotImplementedError" --include=*.py papertrace glossa
```
Expected: 只剩 `parse_code/fx_trace.py` 之类里 `_require_torch` 抛 `RuntimeUnavailable` 的合法位置，或完全无输出；不得再出现「尚未实现」。

- [ ] **Step 6: 记录改动**

```bash
cd /d/AgentPrograms/PaperTrace && git status --porcelain | head -40
```

---

### Task 2: `build/` 与 `analyze/` 收拢（阶段 B1 之一）

**Files:**
- Move: `papertrace/build/trace.py` → `papertrace/build/trace.py`
- Move: `papertrace/build/analysis.py` → `papertrace/build/analysis.py`
- Move: `papertrace/analyze/metrics.py` → `papertrace/analyze/metrics.py`
- Move: `papertrace/analyze/roles.py` → `papertrace/analyze/roles.py`
- Create: `papertrace/build/__init__.py`、`papertrace/analyze/__init__.py`（各一行 docstring，照现有子包风格）
- Modify: 全仓库 import 与文档引用

**Interfaces:**
- Consumes: Task 1 完成后的代码树
- Produces: `papertrace.build.trace`（导出 `BuildError build_trace load_entry repo_commit skeleton_trace`）、`papertrace.build.analysis`（`analyze_code empty_analysis`）、`papertrace.analyze.metrics`、`papertrace.analyze.roles`

- [ ] **Step 1: 先跑一次测试确认起点是绿的**

Run: Global Constraints 里的 pytest 命令
Expected: `1324 passed`

- [ ] **Step 2: 搬家**

```bash
cd /d/AgentPrograms/PaperTrace
mkdir -p papertrace/build papertrace/analyze
mv papertrace/build/trace.py papertrace/build/trace.py
mv papertrace/build/analysis.py papertrace/build/analysis.py
mv papertrace/analyze/metrics.py papertrace/analyze/metrics.py
mv papertrace/analyze/roles.py papertrace/analyze/roles.py
```

两行 `__init__.py` 用一句中文 docstring，与 `parse_code/__init__.py` 同风格（如 `"""构建侧：把仓库变成算子级 trace。"""`、`"""分析侧：参数/算力/角色三张表。"""`）。

- [ ] **Step 3: 按词边界重写全部 import**

替换表（旧的 → 新的）：

| 旧 | 新 |
|---|---|
| `papertrace.build.trace` | `papertrace.build.trace` |
| `papertrace.build.analysis` | `papertrace.build.analysis` |
| `papertrace.analyze.metrics` | `papertrace.analyze.metrics` |
| `papertrace.analyze.roles` | `papertrace.analyze.roles` |

对 `papertrace/ glossa/ tests/ scripts/` 下所有 `.py` 逐一重写；必须在替换后紧跟一个 `(?![A-Za-z0-9_])` 边界断言，否则 `papertrace.build.trace` 之类会前缀误伤。

- [ ] **Step 4: 重写文档与 docstring 里的路径引用**

`README.md`、`docs/*.md`、`docs/superpowers/plans/*.md`、`docs/superpowers/specs/*.md` 里出现的 `papertrace/build/trace.py`、`papertrace/build/analysis.py`、`papertrace/analyze/metrics.py`、`papertrace/analyze/roles.py` 路径同步改为新路径。同一替换表，只是把 `.` 换成 `/`、末尾补 `.py`。

- [ ] **Step 5: 跑全量测试**

Run: Global Constraints 里的 pytest 命令
Expected: `1324 passed`

- [ ] **Step 6: 冒烟两条命令**

```bash
cd /d/AgentPrograms/PaperTrace
PYTHONPATH="D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps" python -m papertrace --help
PYTHONPATH="D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps" python -m glossa --help
```
Expected: 两个都打印用法，退出码 0

---

### Task 3: `render/` 收拢（阶段 B1 之二）

**Files:**
- Move: `render/analysis.py` → `render/analysis.py`；`render/html.py` → `render/html.py`；`render/symbols.py` → `render/symbols.py`；`render/terms.py` → `render/terms.py`；`render/report.py` → `render/report.py`；`render/dump.py` → `render/dump.py`
- Create: `papertrace/render/__init__.py`
- Modify: 全仓库 import 与文档引用；`pyproject.toml` 的 `package-data`

**Interfaces:**
- Consumes: Task 2 结果
- Produces: `papertrace.render.{analysis,html,symbols,terms,report,dump}`

- [ ] **Step 1: 搬家**

```bash
cd /d/AgentPrograms/PaperTrace
mkdir -p papertrace/render
mv papertrace/render/analysis.py papertrace/render/analysis.py
mv papertrace/render/html.py papertrace/render/html.py
mv papertrace/render/symbols.py papertrace/render/symbols.py
mv papertrace/render/terms.py papertrace/render/terms.py
mv papertrace/render/report.py papertrace/render/report.py
mv papertrace/render/dump.py papertrace/render/dump.py
```

- [ ] **Step 2: 重写 import**（替换表见 Task 2 同款手法）

| 旧 | 新 |
|---|---|
| `papertrace.render.analysis` | `papertrace.render.analysis` |
| `papertrace.render.html` | `papertrace.render.html` |
| `papertrace.render.symbols` | `papertrace.render.symbols` |
| `papertrace.render.terms` | `papertrace.render.terms` |
| `papertrace.render.dump` | `papertrace.render.dump` |
| `papertrace.render.report` | `papertrace.render.report` |

**顺序要求**：先替换 `report_dump` 再替换 `report`，否则 `papertrace.render.dump` 会被 `papertrace.render.report` 规则吃掉半截。

- [ ] **Step 3: 核对模板定位点**

`render/html.py` 用 `papertrace/templates/spine.html.j2`。打开文件确认它取模板的方式（`importlib.resources` / `Path(__file__).parent` / jinja2 `PackageLoader`）：
- 若是 `Path(__file__).parent`，`__file__` 已变成 `papertrace/render/html.py`，`parent` 是 `papertrace/render`，必须改成 `parent.parent / "templates"` 或改用 `importlib.resources.files("papertrace")`；
- 若是按包名 `"papertrace"` 取，则无需改动。

改完 `pyproject.toml` 无需变（模板仍在 `papertrace/templates`）。

- [ ] **Step 4: 跑全量测试**

Run: Global Constraints 里的 pytest 命令
Expected: `1324 passed`

- [ ] **Step 5: 端到端产出一个 HTML，和改动前比对**

```bash
cd /d/AgentPrograms/PaperTrace
rm -rf output/refactor-smoke
PYTHONPATH="D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps" python -m papertrace build --repo tests/fixtures/nanogpt --out output/refactor-smoke
ls -R output/refactor-smoke | head -20
```
Expected: 产出 `trace.json` 与 `*.html`，命令退出码 0。HTML 大小与 Task 2 前一次产出的同命令结果相差不超过 1%（时间戳/随机 id 除外）。

---

### Task 4: `schema/` 与 `spine/` 收拢（阶段 B1 之三）

**Files:**
- Move: `schema/anchor.py` → `schema/anchor.py`；`schema/structure.py` → `schema/structure.py`；`schema/validate.py` → `schema/validate.py`
- Move: `spine.py` → `spine/spine.py`；`spine/anchor.py` → `spine/anchor.py`；`spine/claims.py` → `spine/claims.py`；`spine/fallback.py` → `spine/fallback.py`
- Create: `papertrace/schema/__init__.py`、`papertrace/spine/__init__.py`

**Interfaces:**
- Consumes: Task 3 结果
- Produces: `papertrace.schema.{anchor,structure,validate}`、`papertrace.spine.{spine,anchor,claims,fallback}`

- [ ] **Step 1: 搬家**

```bash
cd /d/AgentPrograms/PaperTrace
mkdir -p papertrace/schema papertrace/spine
mv papertrace/schema/anchor.py papertrace/schema/anchor.py
mv papertrace/schema/structure.py papertrace/schema/structure.py
mv papertrace/schema/validate.py papertrace/schema/validate.py
mv papertrace/spine/spine.py papertrace/spine/spine.py
mv papertrace/spine/anchor.py papertrace/spine/anchor.py
mv papertrace/spine/claims.py papertrace/spine/claims.py
mv papertrace/spine/fallback.py papertrace/spine/fallback.py
```

- [ ] **Step 2: 重写 import**

| 旧 | 新 |
|---|---|
| `papertrace.schema.anchor` | `papertrace.schema.anchor` |
| `papertrace.schema.structure` | `papertrace.schema.structure` |
| `papertrace.schema.validate` | `papertrace.schema.validate` |
| `papertrace.spine.anchor` | `papertrace.spine.anchor` |
| `papertrace.spine.claims` | `papertrace.spine.claims` |
| `papertrace.spine.fallback` | `papertrace.spine.fallback` |
| `papertrace.spine.spine` | `papertrace.spine.spine` |

**顺序要求**：`spine_*` 三条先替换，最后才是 `papertrace.spine.spine`（带词边界，避免把 `papertrace.spine.anchor` 再改成 `papertrace.spine.spine.anchor`）。

- [ ] **Step 3: 检查 `jsonschema` 未被污染**

```bash
cd /d/AgentPrograms/PaperTrace
grep -rn "^import jsonschema\|^from jsonschema" --include=*.py papertrace | head
PYTHONPATH="D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps" python -c "from papertrace.schema.validate import dump_trace; import jsonschema; print(jsonschema.__version__)"
```
Expected: 两条都正常，`jsonschema` 打印版本号

- [ ] **Step 4: 跑全量测试**

Run: Global Constraints 里的 pytest 命令
Expected: `1324 passed`

- [ ] **Step 5: 确认根下只剩 7 个文件**

```bash
cd /d/AgentPrograms/PaperTrace && ls papertrace/*.py | sed 's#.*/##'
```
Expected: 恰好 7 个 —— `__init__.py __main__.py cli.py constants.py exceptions.py exit_codes.py paths.py`

---

### Task 5: `papertrace.api` 门面，`glossa` 只认一个入口（阶段 B2）

**Files:**
- Create: `papertrace/api.py`
- Modify: `glossa/` 下 19 个文件的 30 处 `from papertrace.* import ...`

**Interfaces:**
- Consumes: Task 4 的最终模块路径
- Produces: `papertrace.api` 导出 —— `BuildError` `LLMUnavailable` `TraceSchemaError` `RuntimeUnavailable` `TraceUnsupported` `IngestError`、`MISSING_RUNTIME` `UNIMPLEMENTED` `UNTRACEABLE`、`HTML_MAX_BYTES`、`dump_trace` `minimal_trace`、`get_llm`

- [ ] **Step 1: 列出 glossa 真正用到的全部符号**

```bash
cd /d/AgentPrograms/PaperTrace
grep -rhn "^from papertrace\." glossa --include=*.py | sed 's/^.*import //' | tr ',' '\n' | sed 's/ //g' | sort -u
```
把结果全部纳入门面。**不允许**有遗漏，否则 Step 3 会因为少导出而炸。

- [ ] **Step 2: 写 `papertrace/api.py`**

只做 re-export，不写逻辑；每行 `from .x.y import a, b` 后配 `__all__` 列表。文件头 docstring 写明：「`glossa` 唯一允许依赖的 papertrace 面；新增跨包依赖先改这里」。

- [ ] **Step 3: 改 glossa 的 import**

`glossa/**/*.py` 里所有 `from papertrace.<任意> import ...` 统一改成 `from papertrace.api import ...`。同文件内多行合并可一起改，但**不要**改动 import 顺序以外的东西。

- [ ] **Step 4: 验证零漏网**

```bash
cd /d/AgentPrograms/PaperTrace
grep -rn "from papertrace" glossa --include=*.py | grep -v "from papertrace.api import" | wc -l
```
Expected: `0`

- [ ] **Step 5: 跑全量测试**

Run: Global Constraints 里的 pytest 命令
Expected: `1324 passed`

- [ ] **Step 6: 冒烟 `python -m glossa --help`**

Expected: 打印用法，退出码 0

---

### Task 6: 测试目录分组（阶段 C）

**Files:**
- Create: `tests/common.py`、`tests/papertrace/__init__.py`?（**不建**，见下）、`tests/glossa/`、`tests/review/`
- Move: 103 个 `test_*.py` 按规则分流
- Modify: 65 处 `Path(__file__).resolve().parents[1]`

**Interfaces:**
- Consumes: Task 5 结果
- Produces: `tests.common.ROOT`（`Path`，仓库根）、`tests.common.FIXTURES`（`Path`，`tests/fixtures`）

- [ ] **Step 1: 建 `tests/common.py`**

```python
"""测试公共常量：仓库根只在这里定义一次。

之前 65 个测试各自写 Path(__file__).resolve().parents[1]，测试文件一挪目录就
静默指错地方。所有路径都从这里取。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
```

不建 `tests/__init__.py`：`tests/_tmp.py` 已经靠 `python -m pytest` 把仓库根放进 `sys.path` 才能 `from tests._tmp import`，加了 `__init__.py` 反而会改变 pytest 的 rootdir 判定。

- [ ] **Step 2: 按规则分流 103 个测试文件**

```bash
cd /d/AgentPrograms/PaperTrace
mkdir -p tests/papertrace tests/glossa tests/review
```
- `test_glossa_*.py` → `tests/glossa/`
- `test_*_review.py`（first…fifteenth）→ `tests/review/`
- 其余全部（含 `test_cli.py`、`test_spine_*.py`、`test_build_real.py` 等）→ `tests/papertrace/`

用 `mv` 搬运（理由同上：不污染暂存区）。

- [ ] **Step 3: 把 65 处 `parents[1]` 换成 `tests.common.ROOT`**

替换两类表达式：
- `Path(__file__).resolve().parents[1]` → `ROOT`，并在 import 区加 `from tests.common import ROOT`
- `ROOT = Path(__file__).resolve().parents[1]` 这种先赋值再用的，直接删掉赋值行，改用公共 `ROOT`
- `... / "tests" / "fixtures" / "nanogpt"` 这类，改成 `FIXTURES / "nanogpt"`（若该文件只需要 fixtures，就只 import `FIXTURES`）

`tests/_tmp.py` 里的 `_ROOT = pathlib.Path(__file__).resolve().parents[1] / "output" / "test-tmp"` **保持不动**（它仍在 `tests/` 下，`parents[1]` 依然正确）。

- [ ] **Step 4: 验证没有残留**

```bash
cd /d/AgentPrograms/PaperTrace
grep -rn "parents\[1\]" tests/ | grep -v "_tmp.py" | wc -l
```
Expected: `0`

- [ ] **Step 5: 跑全量测试**

Run: Global Constraints 里的 pytest 命令
Expected: `1324 passed`

- [ ] **Step 6: 确认收集数量没变**

```bash
cd /d/AgentPrograms/PaperTrace
PYTHONPATH="D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps" python -m pytest -q --collect-only 2>&1 | tail -3
```
Expected: 收集到的用例数与重构前一致（1324 项）

---

### Task 7: 收尾核验与文档对齐

**Files:**
- Modify: `README.md`（若仍有旧路径）、`docs/ENVIRONMENT.md`（依赖版本表已补，确认无误）

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 无

- [ ] **Step 1: 全仓搜旧路径残留**

```bash
cd /d/AgentPrograms/PaperTrace
grep -rn "papertrace\.\(build_trace\|code_analysis\|analyze_metrics\|analyze_roles\|render_analysis\|render_html\|render_symbols\|render_terms\|report\|report_dump\|schema_anchor\|schema_structure\|schema_validate\|spine_anchor\|spine_claims\|spine_fallback\)\b" --include=*.py . | grep -v "^./pydeps/" | wc -l
```
Expected: `0`

- [ ] **Step 2: 搜文档里的旧文件路径**

```bash
cd /d/AgentPrograms/PaperTrace
grep -rn "papertrace/build_trace\.py\|papertrace/code_analysis\.py\|papertrace/render_html\.py\|papertrace/schema_validate\.py\|papertrace/spine\.py\|papertrace/report\.py" README.md docs/*.md docs/superpowers/**/*.md 2>/dev/null | wc -l
```
Expected: `0`。历史计划文档（`docs/superpowers/plans/`）**也要改**——它们会被后来的 agent 当现状读。

- [ ] **Step 3: 最终全量测试**

Run: Global Constraints 里的 pytest 命令
Expected: `1324 passed`

- [ ] **Step 4: 汇总改动**

```bash
cd /d/AgentPrograms/PaperTrace && git status --porcelain | awk '{print $1}' | sort | uniq -c && git status --porcelain | wc -l
```

- [ ] **Step 5: 报数给用户**

汇报内容固定五项：测试数、删除模块数、搬家模块数、glossa 跨包 import 数（应为 0）、工作区体积。
