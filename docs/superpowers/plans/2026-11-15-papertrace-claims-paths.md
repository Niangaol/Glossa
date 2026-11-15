# S20 认领唯一性 + S21 路径便携化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development（并行波次）或
> superpowers:executing-plans。Step 用 `- [ ]` 勾选跟踪。

**Goal:** 让「一个公式项 ↔ 一个算子节点」的归属在同一公式单元内唯一，并把 trace.json 里的本机绝对路径改成
可分享的相对路径。

**Architecture:** 两块新逻辑各自独立成模块（`papertrace/spine_claims.py`、`papertrace/paths.py`），
只在控制器独占的波次里接线到 `papertrace/spine.py` 与 `papertrace/cli.py`。三个实现 Task 写作用域互不重叠，
可一次并行派发；集成与既有测试改写由控制器串行完成。

**Tech Stack:** Python 3.13（无新依赖）、pytest、torch.fx（既有）、jinja2（既有）。

**Spec:** docs/superpowers/specs/2026-11-15-papertrace-claims-paths-design.md（本计划从它推导；执行者两份都读）

## Global Constraints

1. **单文件 ≤200 行**，口径 `len(pathlib.Path(f).read_text(encoding='utf-8').splitlines())`；`Get-Content .Count` 不作数。
2. **零新依赖**：不许 import numpy / requests / parse_latex / lark / antlr4；新增 import 只能来自标准库。
3. **GC8**：不带 `--paper` 的 build 逐项不变 —— `nodes=128（算子 75 / 权重 18 / 输入 1）`、`edges=101`、
   `degraded=2 fused=0 orphan=0 shape_broken=0 shape_unchecked=0`、EXIT=0。
4. **GC14**：`relativize_doc` 生效后，`meta.repo.url` / `meta.paper.source` / 每个 op `loc` / 每个
   `symbols.code[*].defined_at` 都不含 `[A-Za-z]:\\`，也不以 `/` 开头的绝对形态（输入在 cwd 之下时）。
5. **GC15**：认领唯一性不增加 judge 调用上限（每项 ≤3，合计 ≤12），实测调用数 ≤ 现状。
6. **GC16**：同一公式单元内所有 anchor 的 `code_expr_range` 指认的节点集合互不相交。
7. **offline 诚实空态**：offline 下 anchors=0、unresolved 自报原因；绝不为了好看造 anchor。
8. **测试不许用 `pytest tmp_path`**（沙箱递归删除 WinError 5），一律 `tests/_tmp.py::scratch_dir`。
9. **每个 Task 一次提交**；提交信息用英文 `feat:` / `fix:` / `docs:` 前缀。
10. **变异探针**：改产品代码让某条测试红 → 还原并核对 sha256；锚串先验证全仓唯一。
11. 不许把 `papertrace/spine.py` 超到 200 行以上：本片要求它接完线后 **≤200**（搬出 `_judge_pairs`/`_node_text` 腾出空间）。
12. 不许改 `papertrace/align/struct_signal.py` 的 `KIND_TO_OPS`；不许改 `schema/trace.schema.json`（本片不需要）。

## Review Focus

1. **候选被占尽的公式项**：用户期望看到「被前面的公式项占用了」而不是「没有候选」；两种成因文案必须分开。
2. **结构路径的重复认领**：子序列匹配理论上 1:1，一旦回归要响亮 `BuildError`，不许静默连两条线。
3. **相对路径的失效面**：从 A 目录构建、到 B 目录打开时相对路径指错；`--repo` / `--paper` 传相对路径时不能再
   二次相对化（也不能变成空串）。
4. **`portable_loc` 误伤**：module 节点的 `loc` 是模块路径（`model.GPT`），绝不能被当成文件路径改写。
5. **judge 预算**：独占不应把调用数推过 12；候选被跳过时不许「补问」别的项。

## File Structure

| 文件 | 职责 | 谁写 |
|---|---|---|
| `papertrace/spine_claims.py`（新） | 认领唯一性：`node_text` / `unclaimed` / `judge_first_yes` / `duplicate_claims` / `CLAIMED_REASON` | Task A |
| `tests/test_spine_claims.py`（新） | 上述函数的函数级测试 | Task A |
| `papertrace/paths.py`（新） | 路径便携化：`portable_path` / `portable_loc` / `relativize_doc` | Task B |
| `tests/test_paths.py`（新） | 上述函数的函数级测试 + 四字段覆盖 | Task B |
| `README.md`、`papertrace/align/candidates.py`（仅 docstring） | 说真话：唯一性已做、路径已相对化 | Task C |
| `papertrace/spine.py`、`papertrace/cli.py`、`tests/test_imports.py`、`tests/test_spine_end_to_end.py` | 接线与端到端 | 控制器（波次2） |

---

### Task A: 认领唯一性模块（`papertrace/spine_claims.py`）

**Files:**
- Create: `papertrace/spine_claims.py`（目标 ≤120 行）
- Test: `tests/test_spine_claims.py`

**Interfaces:**
- Consumes: `papertrace.align.judge.judge(term_text, snippet) -> JudgeResult`、
  `papertrace.align.judge.judge_score(result) -> float`（既有，不要改签名）。
- Produces（D 波次按这些签名接线，逐字不许改）:
  ```python
  CLAIMED_REASON: str  # 中文一句话，必须含「认领」二字与「同一」二字
  def node_text(node: dict) -> str
  def unclaimed(node_ids: list[str], claimed: set[str]) -> list[str]
  def judge_first_yes(term_text: str, node_ids: list[str], by_id: dict,
                      claimed: set[str]) -> tuple[float, str, str | None]
  def duplicate_claims(grouped: dict[int, list[str]]) -> list[str]
  ```

**行为约定（冻结）:**
1. `node_text` 与 `papertrace/spine.py:184-187` **逐字等价**（`op label loc in=shape_in out=shape_out`，`.strip()`）。
2. `unclaimed` 保序返回，不改入参。
3. `judge_first_yes`：按 `node_ids` 顺序跳过 `claimed` 里的 id、以及 `by_id` 里没有的 id；
   对剩下的逐个 `judge(term_text, node_text(node))`；第一个 `judge_score > 0` 的返回
   `(1.0, result.evidence.strip(), node_id)` **并把 node_id 加入 `claimed`**（有副作用，docstring 写明）；
   都不中返回 `(0.0, "", None)`。**不许**改 `judge` / `judge_score` 的行为。
4. `duplicate_claims`：输入 `{term_index: [node_id, ...]}`，返回在同一单元内出现 2 次以上的 node_id（升序去重）；
   空输入返回 `[]`。**只报告，不抛异常**（是否抛由调用方决定）。
5. 纯函数以外只允许调 `judge`；不许读环境变量、不许联网、不许 import torch。

- [ ] **Step 1: 写失败测试**（`tests/test_spine_claims.py`，具名测试名冻结）
  - `test_node_text_matches_spine_exactly`：与 `spine._node_text`（临时 import 后对比）输出逐字相等，
    用一个真实 trace 节点（`level=op, kind=op`）与一个缺字段的畸形节点各测一次。
  - `test_unclaimed_keeps_order_and_does_not_mutate`：`unclaimed(['a','b','c'], {'b'}) == ['a','c']`，入参集合仍只有 `b`。
  - `test_claimed_candidate_is_skipped`：两个候选，第一个已在 `claimed` → 只对第二个调 judge（用计数假后端断言 calls==1）。
  - `test_confirmed_node_id_is_added_to_claimed`：确认后 `claimed` 含该 id、返回值三元组正确。
  - `test_all_candidates_claimed_asks_no_judge`：全被占 → `(0.0, "", None)` 且后端 `calls == 0`。
  - `test_duplicate_claims_reports_repeated_ids`：`{0:['a','b'], 1:['b','a']}` → `['a','b']`。
  - `test_claimed_reason_mentions_claim_and_same_unit`：`CLAIMED_REASON` 同时含「认领」「同一」。
  - 假后端纪律：**单实例跨调用**，且断言被测路径真被走到（`calls`）。
- [ ] **Step 2: 跑测试确认红**（`ModuleNotFoundError: papertrace.spine_claims` 或 AttributeError）。
- [ ] **Step 3: 实现** 上述五个名字；`node_text` 直接从 spine 搬。
- [ ] **Step 4: 跑测试确认绿**；再跑全量确认零回归（基线 **757 passed**）。
- [ ] **Step 5: 变异探针**：把 `judge_first_yes` 里跳过 `claimed` 的那行删掉 → `test_claimed_candidate_is_skipped` 必红；还原并核 sha256。
- [ ] **Step 6: 提交** `feat: claim each operator for at most one term`。

---

### Task B: 路径便携化模块（`papertrace/paths.py`）

**Files:**
- Create: `papertrace/paths.py`（目标 ≤90 行）
- Test: `tests/test_paths.py`

**Interfaces:**
- Produces（D 波次逐字按此接线）:
  ```python
  def portable_path(p: str, base: str | pathlib.Path | None = None) -> str
  def portable_loc(loc: str, base: str | pathlib.Path | None = None) -> str
  def relativize_doc(doc: dict, base: str | pathlib.Path | None = None) -> int
  ```

**行为约定（冻结）:**
1. `portable_path`：`base` 默认 `pathlib.Path.cwd()`。空串 → 空串。相对路径 → 只把 `\` 换成 `/` 返回（已经是便携的）。
   绝对路径且**在 base 之下** → `PurePosix` 风格相对路径（`os.path.relpath` 后 `Path(...).as_posix()`）；
   绝对路径但**不在 base 之下**（含 `ValueError` / 不同盘符）→ 原样返回。
   实现建议 `pathlib.Path(p).resolve()` + `Path.relative_to(base_resolved)` + `try/except ValueError`；不许 `os.chdir`。
2. `portable_loc`：`loc.rpartition(':')` 的尾段是**纯数字**且 head 非空时，只对 head 调 `portable_path` 再拼回 `:line`；
   否则原样返回（模块路径 `model.GPT`、空串、`model.GPT:3` 之外的怪形态都不动）。
3. `relativize_doc`：**原地**改写、返回改写条数；覆盖且只覆盖四处：
   `doc['meta']['repo']['url']`、`doc['meta']['paper']['source']`、每个 `doc['nodes'][*]['loc']`（走 `portable_loc`）、
   每个 `doc['symbols']['code'][*]['defined_at']`（走 `portable_loc`）。
   缺键/类型不对一律跳过不抛（trace 可能是 minimal）。
4. 不许改 `meta.repo.commit`、`meta.runtime`、`nodes[*].id`、`paper_unit_id`、module 节点的 loc 语义。

- [ ] **Step 1: 写失败测试**（`tests/test_paths.py`，测试名冻结）
  - `test_portable_path_makes_paths_under_base_relative`（`C:\\w\\proj\\a.py` + base `C:\\w\\proj` → `a.py`）。
  - `test_portable_path_keeps_paths_outside_base`（`D:\\other\\a.py` → 原样）。
  - `test_portable_path_converts_separators_for_relative_input`（`sub\\a.py` → `sub/a.py`）。
  - `test_portable_path_passes_empty_string_through`。
  - `test_portable_loc_rewrites_file_line_only`：`C:\\w\\proj\\m.py:147` → `m.py:147`；`model.GPT` → `model.GPT`；`""` → `""`。
  - `test_relativize_doc_covers_all_four_fields`：手工 doc（四字段各一条绝对路径）→ 四条全变相对，返回 4。
  - `test_relativize_doc_tolerates_minimal_doc`：`{}` / 缺 `symbols` / `loc` 非字符串 → 不抛，返回 0 或实际条数。
  - `test_relativize_doc_leaves_module_paths_alone`。
  - 测试里的临时目录用 `tests/_tmp.py::scratch_dir`；Windows 盘符用 `pathlib.Path.cwd().anchor` 之类**动态取**，
    不要硬编码 `D:`（换机器就红）。
- [ ] **Step 2: 跑测试确认红**。
- [ ] **Step 3: 实现**。
- [ ] **Step 4: 跑测试确认绿**；全量零回归（基线 757）。
- [ ] **Step 5: 变异探针**：把 `relative_to` 的 `try/except ValueError` 去掉/改成无条件拼接 → 对应测试必红；还原并核 sha256。
- [ ] **Step 6: 提交** `feat: keep local absolute paths out of trace.json`。

---

### Task C: 文档说真话（README + candidates.py docstring）

**Files:**
- Modify: `README.md`（新增「认领唯一性」与「路径便携化」两小节；不改其他结构）
- Modify: `papertrace/align/candidates.py:16-19`（**只改 docstring**，代码零改动）
- Modify: `tests/test_align_no_generation.py`？**不许改**（它扫的是禁自由生成串）

**Interfaces:** 无（纯文档）。

- [ ] **Step 1: 改 `candidates.py` docstring**：把「**不做跨 term 唯一性约束**……去重等于编造『唯一归属』」
  改成如实描述：候选生成器本身**仍然**不做跨 term 去重（它是纯函数、不知道谁被认领），
  唯一性由 `papertrace/spine_claims.py` 在编排层执行；并写清 R135 的理由与「跨单元允许共享」。
- [ ] **Step 2: README 新增「一个算子只归一个公式项」小节**：说明同单元独占、跨单元可共享、被占尽的项落 unresolved、
  以及贪心而非最大匹配的已知局限（引设计文档 §6）。
- [ ] **Step 3: README 新增/改写「路径是相对 cwd 的」小节**：四类字段、`/` 分隔符、跨目录打开会指错、
  `trace.json` 里不再有本机绝对路径。同时**删掉**旧的「相对化归 M4」那句并改写成「已做」。
- [ ] **Step 4: 自查**：`git grep -n '归 M4' README.md` 必须零命中；两份新增小节里的行号引用必须指向真实行（自己核）。
- [ ] **Step 5: 提交** `docs: say the claim is unique per unit and paths are portable`。

---

### Task D（控制器独占，串行）: 接线 + 既有测试改写

**Files:**
- Modify: `papertrace/spine.py`（搬出 `_judge_pairs`/`_node_text` 到 `spine_claims`，`_attach_unit` 持 `claimed`，
  结构路径重复 → `BuildError`；接完线 **≤200 行**）
- Modify: `papertrace/cli.py`（`dump_trace` 之前调 `relativize_doc`，打印改写条数可省）
- Modify: `tests/test_imports.py`（MODULES 加 `papertrace.spine_claims`、`papertrace.paths`）
- Modify: `tests/test_spine_end_to_end.py`（新增端到端断言）

**Interfaces:** 消费 Task A 的四个名字与 Task B 的三个名字（签名见上，逐字）。

- [ ] **Step 1**: `spine.py` 改用 `from papertrace.spine_claims import CLAIMED_REASON, judge_first_yes, node_text, unclaimed`；
  删除本地 `_judge_pairs`/`_node_text`；`_attach_unit` 建 `claimed: set[str] = set()` 顺序传参。
- [ ] **Step 2**: `_attach_term` 里 `available = unclaimed(node_ids, claimed)`；`available` 空但 `node_ids` 非空 →
  记 unresolved（cause = `CLAIMED_REASON`）；否则 `judge_first_yes(...)`。
- [ ] **Step 3**: 结构路径守门：`duplicate_claims(grouped)` 非空 → `BuildError`（文案点明「同一公式单元内一个算子只归一个公式项」）。
- [ ] **Step 4**: `cli.py` 在 `dump_trace` 前 `relativize_doc(doc)`。
- [ ] **Step 5**: 新测试（具名）：`test_two_terms_never_claim_the_same_node`（假 yes 后端 + 回退路径 → 两个 matmul 项分别指
  `root/@037`/`root/@045`，且与结构真值一致）、`test_exhausted_candidates_report_claim_not_absence`（构造只剩一个 matmul 节点
  → 第二项 unresolved 原因含「认领」）、`test_structural_duplicate_is_a_build_error`（直接喂重复 grouped，monkeypatch）、
  `test_cli_trace_has_no_drive_letters`（CLI 真跑，读 trace.json，四类字段无盘符）、`test_gc16_anchors_do_not_share_nodes`。
- [ ] **Step 6**: 全量 + GC8 四输入复核（控制器自跑，不转引）。
- [ ] **Step 7**: 提交 `feat: wire unique claims and portable paths into build`。

---

### Task D 修订（builder-check 走后，逐条覆盖上面的 Step 1–7）

裁决 R144–R153 见设计文档 §8。接线时必须照做：

- **Step 1（改）**：`spine.py` 的 `_judge_pairs`/`_node_text` 删掉，改 import `spine_claims`。
  **`_record_unresolved` 必须留在 spine.py**（`tests/test_spine_tier.py:169` 直接 import 它）。
  行数账：删 16 行 / 加 ≤14 行，改完必须 **≤200**（`splitlines` 口径）。
- **Step 2（改）**：`available = unclaimed(node_ids, claimed)`；`available` 空而 `node_ids` 非空 →
  **裸 append** `{"kind": "paper_unit", "ref": term_id, "reason": CLAIMED_REASON}`（R146），**不走** `_record_unresolved`。
- **Step 3（改）**：守门**只在 `fallback=False` 时**跑（R144）：`if not fallback and duplicate_claims(grouped): raise BuildError(...)`。
  回退路径的跨 term 重复是正常输入，绝不拦。
- **Step 4（补）**：产出 anchor 之后，把 `code_expr_range` 覆盖的节点**全部**加进 `claimed`（R147）——
  结构路径就是那个节点，回退无确认时是 first..last 覆盖的全部节点。
- **Step 5（补）**：黄线 `alternatives` 过滤掉 `claimed` 里的 id（R151）。
- **Step 6（补）**：`cli.py` 用 `try/except BuildError` 包住 `attach_paper`，打印一行 + 返回 2（R148）；
  `dump_trace` 之前调 `relativize_doc(doc)`；cli.py 改完 ≤200 行。
- **Step 7（补）**：`papertrace/spine_fallback.py:11` 的 `spine._judge_pairs` 改指 `spine_claims.judge_first_yes`（R152）。

**既有测试的改动清单（分栏，R145）**：

| 类别 | 文件:行 | 改什么 |
|---|---|---|
| 修改 | `tests/test_spine_end_to_end.py:199-204` `test_meta_paper_is_tex` | `paper["source"]` 期望改成 `"tests/fixtures/papers/vaswani2017/attention.tex"`（相对 cwd，`/` 分隔） |
| 修改 | `tests/test_spine_end_to_end.py:390-442` 回退认领测试 | t3 的 `code_range` 期望改成 `"root/@045"`（该 term 候选组里第一个未被认领的节点），注释写明这是 S20 的结果 |
| 修改 | `tests/test_spine_end_to_end.py:390-442` 回退认领测试的**输入** pairs | 被 R144 守门逼出的输入调整：旧 pairs 让 @038 同时属 t0 与 t1 → 新产品直接抛 BuildError，故 t1 候选 @038→@039（t0 期望一字未动） |
| 新增 | `tests/test_imports.py` MODULES | 加 `papertrace.spine_claims`、`papertrace.paths` |
| 新增 | `tests/test_spine_end_to_end.py` | `test_two_terms_never_claim_the_same_node`、`test_exhausted_candidates_report_claim_not_absence`、`test_structural_duplicate_is_a_build_error`、`test_cli_trace_has_no_drive_letters`、`test_gc16_anchors_do_not_share_nodes` |

**新测试的 cwd 纪律（R150）**：所有走 CLI 的新测试必须 `subprocess.run(..., cwd=REPO_ROOT)`，不要继承 pytest 启动目录。

---
## 波次与并行

| 波次 | 谁 | 写作用域 | 依赖 |
|---|---|---|---|
| 1 | Task A、Task B、Task C **并行三派** | `spine_claims.py`+`tests/test_spine_claims.py` / `paths.py`+`tests/test_paths.py` / `README.md`+`candidates.py` | 无 |
| 2 | 控制器 | `spine.py`、`cli.py`、`test_imports.py`、`test_spine_end_to_end.py` | 波次1 三个提交 |
| 3 | 三份独立评审 **并行 fan-out** | 只读 | 波次2 |
| 4 | 一个 fix agent 带完整清单 → 恰好一次定向复审 | 按 review 清单 | 波次3 |

## 自审（写完后自查）

1. 三个 Task 的文件清单**互不交叠**？是（A 与 B 各自新文件；C 只碰 README 与 candidates 的 docstring）。
2. 每个 Task 的「测试」都能在**没有**其它 Task 的情况下写出来？是（A/B 都是纯函数级；C 无测试）。
3. 精确值（`CLAIMED_REASON` 必须含哪两词、`portable_loc` 的三类输入、GC14 的四字段）都写成了可断言的形式？是。
4. 既有测试里会被打破的都点名了？`test_imports.py` MODULES（新模块），除它之外还有 3 处授权改写，见上表；其余靠 cli 层相对化避开。
5. 有没有要求执行者「自己发挥」的地方？`portable_path` 的异常处理写到了 `try/except ValueError` 级别。

---

## 执行记录（波次 1–5，已完成）

| 波次 | 内容 | 结果 |
|---|---|---|
| 1 | 三路并行实现：Task A 认领唯一性、Task B 路径便携化、Task C 文档 | `8987b57`（spine_claims.py 70 行 + 7 测试）、`681a29b`（paths.py 83 行 + 8 测试）、`048ada1`（README 两节 + candidates.py docstring） |
| 2 | 控制器接线：spine.py / cli.py / spine_fallback.py，并按 R145 改写三处既有测试 | 全量 780 passed |
| 3 | 三路独立评审并行（路径 / 认领 / 集成） | Critical 0，Important 6（路径 2、认领 1、集成 3），Minor 14 |
| 4 | 一个 fixer 带 F1–F6 清单一次修完 + 恰好一次定向复审 | `a490da9`（9 files +479/−31），全量 **787 passed**；复审 **ALL ADDRESSED / 0 open**，新破损 0 |

### 波次4 落的六件事

- **F1**：`papertrace/paths.py` 新增 `leaked_absolute(doc, base=None)`（只诊断 GC14 的四处字段；`://` 前置豁免；`<path>:<line>` 用 `rpartition` 只判 head）；`papertrace/cli.py` 在相对化之后写一行 stderr 提示「N 条路径不在构建目录 X 之下，按 GC14 原样保留（仍含盘符）」，**不动 exit code、不动 stdout**。同时把两处多行 `print` 压成单行，cli.py 199 → 197 行。
- **F2**：补 `test_two_units_may_share_a_node`（两个公式单元的夹具），把 R136「跨单元可以共享」从注释变成有牙的测试；产品零改动。
- **F3**（R158）：`resolve_code_range` 的**回退分支一律单节点** `str(confirmed_id or node_ids[0])`，于是结构路径（每项恰好 1 节点）+ 回退路径全部单节点 ⇒「认领集合 == 区间覆盖」自动成立，GC16 的「区间内部节点」第三态从根上消失。GC16 文案改认领集口径并写唤醒条件。
- **F4**：R145 的授权改写拆成 R145-1/2/3 补登（第三处是 @038 同属 t0/t1 逼出的**输入**调整，t0 期望一字未动），plan 自审句同步改口。
- **F5**：补 `test_yellow_alternatives_exclude_claimed`——R151 的黄线 alternatives 过滤此前零测试（offline / DeepSeek 下 forward 恒空，是可达配置下的死代码）。
- **F6**：七条 Minor 全修（docstring 五类行为、盘根假设假失败、README 两处措辞、期望值改手算常量、`GOLD_PAIRS` 派生、注释落点）。

### 波次5 定向复审的判定

六条 finding 全部 ADDRESSED，**New breakage Critical 0 / Important 0 / Minor 0**，裁决「放行」。复审额外用变异探针独立确认了三件事有牙：F2（把 `claimed` 提到单元循环外 → 红）、F5（删掉 `and code_id not in claimed` → 红）、F3（回退改回 `if fallback and confirmed_id` → 两条红）。报告 `.superpowers/sdd/2026-11-15-papertrace-claims-paths/wave5-rereview.md`。

### 留待后续（已记账，不在本切片）

- `_attach_term` 9 个位置参数 → 小对象重构（`papertrace/spine.py` 正好 200 行零余量，须与 M4 第 0 步的拆文件一起做）。
- `relativize_doc` 与 `leaked_absolute` 与提示文案三处都吃默认 `base=Path.cwd()`：今天同源但没有测试钉住（复审判为可推迟，最坏后果是提示报错基准、不影响产物）。
- `CLAIMED_REASON` 不点名「占位者」是谁（文案 R146 冻结，可读性 Minor）。
- 子目录 cwd 构建（如 `cd tests && papertrace build`）产物路径相对子目录——GC14 允许，但用户可能意外；暂无提示。
