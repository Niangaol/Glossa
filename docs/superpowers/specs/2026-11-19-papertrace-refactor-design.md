# PaperTrace 重构 + 工作区精简（设计 v1）

日期：2026-11-19 · 状态：待批准 · 用户拍板：方案 C（A + B + 测试目录分组）、删 `wheels/` 保 `pydeps/`

## 0. 一句话

在**功能不变、1324 项测试全绿**的硬约束下，把 22 个空壳模块连根拔掉、把 `papertrace` 根下 17 个散模块按职责收进子包、把 `glossa` 对 `papertrace` 的 30 处跨包 import 收成单一门面，最后把 103 个测试文件按包分组。

## 1. 为什么做（实测依据）

| 实测项 | 数字 | 含义 |
|---|---|---|
| 空壳模块 | **22 个**，每个 7–10 行 `raise NotImplementedError` | 零引用（tokenizer 精确扫描：641 个模块级定义里只有这 23 个函数无任何引用） |
| `papertrace` 根下散模块 | **17 个**（build/analyze/render/report/schema/spine 五类混在一起） | 目录一层看不出职责，改一处要翻半天 |
| `glossa` → `papertrace` import | **30 行**，散落在 19 个文件 | 跨包耦合面大，`glossa` 实际只用到 exceptions / exit_codes / constants / schema_validate / llm.client |
| 测试文件 | **103 个**平铺在 `tests/` | 65 个文件用 `Path(__file__).resolve().parents[1]` 定位仓库根，靠目录层级隐式耦合 |

## 2. 目标 / 非目标 / 反目标

**目标**
- 删掉从未生效的代码，把它们的**设计意图**保留成文档
- `papertrace` 目录一眼看出职责分层
- `glossa` 只依赖 `papertrace` 一个明确的公开面
- 测试按被测包分组，根路径只在一处定义

**非目标**
- 不改任何运行时行为、不改 CLI 参数、不改 HTML/templates 输出
- 不做函数级算法重写（那是另一件事）
- 不提交 git、不碰 `docs/studio/`（Glossa Studio 待批准设计 + 40 张对照图）
- 不动 `pydeps/`（604MB，torch 真实导出测试要用）

**反目标（做了就算失败）**
- 测试数下降、测试被弱化或被删来「通过」
- 任何模块对外行为变化导致 golden 断言需要跟着改
- `docs/studio/`、`PaperTrace_工程落地计划书.docx` 及其生成脚本被动到

## 3. 约束

1. **验证标准**：`pytest -q` 1324 passed，数量与现在一致；清理前后各跑一次留证
   > **执行更正（2026-11-20）**：最终是 1299 passed。差额 25 项全部来自 `test_imports.py` 对**已删模块名**的参数化——删模块必然少用例，和 Task 1 自相矛盾。真正成立的口径是「`def test_` 函数数不变（1036）+ 零放宽断言 + 零行为改动」，总数会随被删模块数同步下降。
2. **环境**：`PYTHONPATH=<repo>;<repo>/pydeps`，解释器 Python 3.13，沙箱下不能用 `tmp_path`
3. **不 commit**：当前工作区已有 `docs/ENVIRONMENT.md` 修改 + 4 个 tmpinstall 删除 + 2 个未跟踪项，重构改动叠加在工作区，不暂存不提交
4. `docs/studio/` 与 `docs/superpowers/specs/2026-11-17-glossa-studio-design.md` 零写入

## 4. 方案（用户已选 C）

考虑过并否决的方案：

- **只删空壳（A 单独）**：收益只有 22 个文件、约 190 行，目录结构没改善，`glossa` 耦合照旧。→ 作为 C 的第一步保留。
- **保持扁平，只加门面**：改动最小，但「一眼看不出职责」的问题没解决，不满足用户「精简工作区」的诉求。→ 否决。
- **连 tests 一起大改（重写测试）**：违反反目标。→ 否决。

选 C 的理由：三档收益叠加且方向一致（都是减熵），每档可独立验证、独立回退。

## 5. 分阶段设计

### 阶段 A：拔空壳（22 文件 / 23 函数）

删除整个子包（里面全是空壳）：

| 包 | 文件 | 空壳函数 |
|---|---|---|
| `papertrace/detail/` | `annotations cache closure l0 l1 l2 l3 stale` + `__init__` | `apply_annotation cache_key closure render_l0 render_l1 render_l2 drill_l3 mark_stale` |
| `papertrace/diff/` | `dim missing reverse struct` + `__init__` | `diff_dim diff_missing diff_reverse diff_struct` |
| `papertrace/trace_runtime/` | `discover probe profile` + `__init__` | `discover_entry run_forward profile_forward` |

只删单文件（同包内还有真实实现）：

| 文件 | 空壳函数 |
|---|---|
| `ingest/arxiv.py` | `fetch_arxiv_source` |
| `ingest/repo.py` | `ingest_repo find_pytorch_modules` |
| `parse_code/einops_expand.py` | `expand_einops` |
| `parse_code/export_try.py` | `try_export` |
| `parse_code/loop_fold.py` | `fold_repeats` |
| `parse_code/treesitter_fallback.py` | `fallback_ast` |
| `symbols/shape_prop.py` | `propagate_shapes` |

新建 `docs/未实现能力.md`：逐条记下每个空壳的 docstring（设计意图）、原路径、签名，写明「2026-11-19 移出代码树，需要时照此重建」。删代码不删意图。

**验证**：`pytest -q` 1324 passed；`grep -r "NotImplementedError" papertrace/` 应只剩真实实现的合法用法。

### 阶段 B1：`papertrace` 根收拢（17 个模块搬家）

| 原模块 | 新模块 |
|---|---|
| `build/trace.py` | `build/trace.py` |
| `build/analysis.py` | `build/analysis.py` |
| `analyze/metrics.py` | `analyze/metrics.py` |
| `analyze/roles.py` | `analyze/roles.py` |
| `render/analysis.py` | `render/analysis.py` |
| `render/html.py` | `render/html.py` |
| `render/symbols.py` | `render/symbols.py` |
| `render/terms.py` | `render/terms.py` |
| `render/report.py` | `render/report.py` |
| `render/dump.py` | `render/dump.py` |
| `schema/anchor.py` | `schema/anchor.py` |
| `schema/structure.py` | `schema/structure.py` |
| `schema/validate.py` | `schema/validate.py` |
| `spine.py` | `spine/spine.py` |
| `spine/anchor.py` | `spine/anchor.py` |
| `spine/claims.py` | `spine/claims.py` |
| `spine/fallback.py` | `spine/fallback.py` |

根下保留 7 个：`__init__.py` `__main__.py` `cli.py` `constants.py` `exceptions.py` `exit_codes.py` `paths.py`。

搬到新位置的模块，其 `templates/` 与包数据引用必须跟着改（`pyproject.toml` 的 `package-data` 目前是 `"papertrace" = ["templates/*.j2"]`，`render/html.py` 用 `importlib.resources` 之类定位的话一并核对）。

**验证**：`pytest -q` 1324 passed；`python -m papertrace build --repo tests/fixtures/nanogpt --out output/x` 能产出与改动前同结构的 HTML（对比文件清单与字节数，不比对时间戳）。

### 阶段 B2：`glossa` 只认一个门面

新增 `papertrace/api.py`，导出 `glossa` 需要的**全部**符号：

```python
# papertrace/api.py —— glossa 唯一允许依赖的门面
from .constants import HTML_MAX_BYTES, ...
from .exceptions import BuildError, LLMUnavailable, TraceSchemaError
from .exit_codes import MISSING_RUNTIME, UNIMPLEMENTED, UNTRACEABLE
from .llm.client import get_llm
from .schema.validate import dump_trace
```

`glossa` 里 19 个文件的 30 行跨包 import 改成 `from papertrace.api import ...`。

**验证**：`grep -rn "from papertrace" glossa/ | grep -v "papertrace.api"` 必须为空；`pytest -q` 1324 passed。

### 阶段 C：测试目录分组

```
tests/
  _tmp.py                保留（62 个文件在 import）
  common.py              新增：ROOT / FIXTURES / scratch 三个常量与函数
  fixtures/              原地不动
  papertrace/            test_spine_*.py、test_fx_*.py 等非 glossa 前缀的
  glossa/                test_glossa_*.py
  review/                test_{first..fifteenth}_review.py
```

65 处 `Path(__file__).resolve().parents[1]` 全部换成 `from tests.common import ROOT`。这一处是**净收益**：仓库根只在一处定义，以后再挪目录不会静默指错。

**验证**：`pytest -q` 1324 passed；`grep -rn "parents\[1\]" tests/` 为空。

## 6. 每阶段收尾动作

1. `pytest -q` 全量：
2. `python -m papertrace --help`、`python -m glossa --help` 不报错
3. `git status` 只出现预期文件
4. 汇报改动文件数与删/增行数

## 7. 留给实现者的判断

- 阶段 B1 与新路径的循环 import 风险：`build/` 与 `render/` 之间若有互相引用，需按「render 依赖 build、不反向」的既有方向核对，别为了搬家强行造环
- 测试分组的分流规则以本文件第 5 节为准；落在规则之外的（如 `test_cli.py`）进 `tests/papertrace/`
- `tmpinstall/` 是否改名为 `scripts/deps/`：本设计**不做**，留作后续单独决定
