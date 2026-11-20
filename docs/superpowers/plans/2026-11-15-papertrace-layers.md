# PaperTrace 逐层对齐（M4a）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让结构同构路径在**每一层**各出一条 anchor（夹具上 4 项 × 2 层 = 8 条），并把为此需要腾出的 200 行满额文件先拆开。

**Architecture:** `struct_signal` 从「只返回首匹配组」扩成「返回全部命中组 + 首组 pairs 保持不变」；`spine` 按组各跑一遍逐项循环，认领集合按「单元 × 组」隔离；anchor 新增可选 `code_group`；HTML 公式项表一行一条 anchor 并显示层。

**Tech Stack:** Python 3.13、pytest、jsonschema、jinja2（全部已在 pydeps，零新依赖）。

**Spec:** `docs/superpowers/specs/2026-11-15-papertrace-layers-design.md`

## Global Constraints

1. **单源文件 ≤200 行**，口径 `len(pathlib.Path(f).read_text(encoding='utf-8').splitlines())`（`Get-Content .Count` 少算，不许用）。测试文件不受限。
2. **零新依赖**：不许引 numpy / requests / parse_latex / lark / antlr4 / KaTeX。
3. **禁 mock 填产品输出**：假后端只能注入在测试里，且必须断言被测路径真被走到（计数器 ≥1）。注入式假后端必须**单实例**（每次调用新建会让计数器重置，曾造成误判）。
4. **默认 offline 诚实**：offline 下不产 anchor、只产 unresolved；不许兜底成假分数。
5. **公式与权重写死**：`sigmoid(4·(a−0.5))`、0.75/0.45、`GREEN_STRUCT_MIN=0.5`、结构信号四条权重（0.5/0.1/0.2）不得改。
6. **GC8 逐项不变**：不带 `--paper` 时 nodes=128（module 34 / param 18 / input 1 / op 75）、edges=101、counts={operators:75,degraded:2,fused:0,orphan:0,shape_broken:0,shape_unchecked:0}、anchors=[]、unresolved=[]。
7. **测试环境**：`$env:PYTHONPATH='D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; & 'C:\Users\niangao\AppData\Local\Programs\Python\Python313\python.exe' -m pytest -q`。不用 pytest `tmp_path`，用 `tests/_tmp.py::scratch_dir`。
8. **每 Task 一次提交**；提交信息用计划里给的那行。
9. **变异探针**：每 Task 至少一组，改坏 → 指定测试必红 → 还原并核对 sha256；锚串先验唯一。
10. **既有断言只能改期望值，不许删**（R168 清单）；改动逐条写进报告。

## Review Focus

- **层数 > 2 的模型**：夹具只有 2 层，容易写成「只有 h.0/h.1」的特例。任何依据层数写死的分支都是缺陷。
- **回退路径**：结构不命中时**不该**逐层展开（回退候选没有层的概念）；写错会让回退 anchor 数从 4 变 8。
- **认领集合的作用域**：`claimed` 提到单元外或提到组外，会让第二个层/第二个单元的错误项拿不到候选（R135/R162）。
- **judge 调用数**：分路径算（R178）——结构路径每层每项恰好一次（每组每个项只 1 个候选节点），
  回退路径每项最多 3 次、全局最多 12 次（`papertrace/align/candidates.py` 的 `per_term_limit` /
  `total_limit`）；早退（同一项命中第一个 yes）与跨层复用是两回事，跨层复用会让人看到「h.1 的证据其实来自 h.0」。
- **HTML 行数与连线**：公式项表行数 = anchor 数；图上两个 attn 组都该有连线。写成只画首组会让用户以为 h.1 没对上。

---

## Task L1: 拆 spine.py（纯重构，行为零变化）

**Files:**
- Create: `papertrace/spine/anchor.py`
- Modify: `papertrace/spine/spine.py`（200 → 约 135 行）
- Test: `tests/test_spine_tier.py:169`（import 改指新模块）、`tests/test_spine_end_to_end.py`（不改）

**Interfaces:**
- Produces（`spine/anchor.py`）：
  - `attach_term(doc: dict, unit, term, signal, retrieval, node_ids: list[str], by_id: dict, fallback: bool, claimed: set[str]) -> None`
  - `record_unresolved(doc: dict, term_id: str, cause: str, retrieval: dict, signals: dict) -> None`
  - 常量 `FALLBACK_EVIDENCE`、`ALTERNATIVE_LIMIT`、`EVIDENCE_LIMIT`
- 保持：`spine.attach_paper(doc, paper_src, model) -> dict`、`spine._attach_unit`、`spine._model_meta`、`spine.UNSPLITTABLE_REASON`、`spine.NO_CANDIDATE_REASON`、`spine.FALLBACK_PAIR_NOTE`

- [x] **Step 1** 把 `_attach_term`（spine.py:121-174）、`_record_unresolved`（:177-187）与常量 `FALLBACK_EVIDENCE/ALTERNATIVE_LIMIT/EVIDENCE_LIMIT` 整体搬到新文件，去掉前导下划线，模块 docstring 写清「这是 S9 的单公式项落盘逻辑，逐层展开由调用方循环」。
- [x] **Step 2** `spine.py` 改成 `from papertrace.spine.anchor import (ALTERNATIVE_LIMIT, FALLBACK_EVIDENCE, EVIDENCE_LIMIT, attach_term, record_unresolved)`，调用点改名。
- [x] **Step 3** `tests/test_spine_tier.py:169` 的 import 改成 `from papertrace.spine.anchor import record_unresolved`，:177 的调用同步改名。**断言一字不改。**
- [x] **Step 4** 跑全量：**787 passed，零改动**；census 两个文件都 ≤200。
- [x] **Step 5** 变异探针：把 `record_unresolved` 里的 `< {CONF_YELLOW:.2f}` 改成 `<= {CONF_YELLOW:.2f}` → `tests/test_spine_tier.py` 的边界用例必红 → 还原 + sha256。
- [x] **Step 6** 提交 `refactor: split the single-term anchor writer out of spine`

---

## Task L2: struct_signal 返回全部同构组

**Files:**
- Modify: `papertrace/align/struct_signal.py`（170 → 约 185）
- Test: `tests/test_spine_struct.py`（新增 5 条，既有 12 条不动）

**Interfaces:**
- Produces:
```python
class StructMatch(NamedTuple):
    group: str                                  # "root/transformer.h.0.attn"
    pairs: list[tuple[int, str]]                # [(term.index, node_id)]

class StructSignal(NamedTuple):
    score: float
    hits: list[str]
    misses: list[str]
    pairs: list[tuple[int, str]]                # 首组，语义不变
    groups: tuple[StructMatch, ...] = ()        # 全部命中组，nodes 顺序
```
- `struct_signal(nodes, terms, config) -> StructSignal` 签名不变。
- **不变**：`pairs` 仍取第一个命中组；`score` 仍只加一次 +0.2；`hits`/`misses` 文案一字不改。

- [x] **Step 1 写失败测试**（`tests/test_spine_struct.py`，沿用夹具 `fixture`）：

```python
def test_every_attention_layer_is_reported(fixture):
    """B 方案：两层都同构时，groups 要如实给出两个组，不许只报首层。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], terms, mod.config)
    assert [m.group for m in sig.groups] == [
        "root/transformer.h.0.attn", "root/transformer.h.1.attn"]

def test_pairs_still_come_from_the_first_group(fixture):
    """pairs 是 S7 的候选来源，逐层展开不许改变它的语义（R25a 首匹配）。"""
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], terms, mod.config)
    assert sig.groups[0].pairs == sig.pairs

def test_score_does_not_grow_with_more_layers(fixture):
    """两组同构也只加一次 +0.2：0.5+0.1+0.2=0.8，不许变成 1.0。"""
    mod, doc, terms = fixture
    assert struct_signal(doc["nodes"], terms, mod.config).score == pytest.approx(0.8)

def test_no_isomorphism_means_no_groups(fixture):
    mod, doc, terms = fixture
    sig = struct_signal(doc["nodes"], list(reversed(terms)), mod.config)
    assert sig.groups == ()

def test_single_group_reports_exactly_one():
    """单组夹具：groups 恰好一组，且它就是 pairs 的来源。"""
    sig = struct_signal(_fake_nodes(), _fake_terms(), None)
    assert len(sig.groups) == 1
    assert [nid for _, nid in sig.groups[0].pairs] == ["n0", "n1", "n2", "n3"]
```

- [x] **Step 2 跑测试确认失败**：`AttributeError: 'StructSignal' object has no attribute 'groups'`。
- [x] **Step 3 实现**：新增 `StructMatch`；`StructSignal` 末尾加 `groups: tuple[StructMatch, ...] = ()`；`_first_isomorphic_group` → `_isomorphic_groups(nodes, terms) -> list[StructMatch]`（现有循环收集所有命中组，不再 `return` 首个）；`struct_signal` 用 `matches = _isomorphic_groups(...)`，`pairs = matches[0].pairs if matches else []`，命中仍只加分一次，返回 `StructSignal(..., pairs, tuple(matches))`。
- [x] **Step 4 跑 `tests/test_spine_struct.py`**：17 passed（12 旧 + 5 新），且既有 `test_pairs_has_exactly_four_entries_for_vaswani` 一字未改仍然绿。
- [x] **Step 5** 全量 **792 passed**（787+5）。
- [x] **Step 6** 变异探针：把 `_isomorphic_groups` 的收集循环改回「命中就 return 一个」→ `test_every_attention_layer_is_reported` 必红（只报 1 组）→ 还原 + sha256。
- [x] **Step 7** 提交 `feat: report every isomorphic layer, keep pairs on the first`

---

## Task L3: spine 逐层出 anchor（认领按层隔离）

**Files:**
- Modify: `papertrace/spine/anchor.py`（+ `code_group` 参数与落盘）
- Modify: `papertrace/spine/spine.py`（结构路径按组循环；回退路径不变）
- Modify: `schema/trace.schema.json`（anchor 加可选 `code_group`）
- Test: `tests/test_spine_end_to_end.py`（新增 6 条 + 按 R168 改期望值）、`tests/test_spine_struct.py`（不动）

**Interfaces:**
- `attach_term(..., code_group: str | None)`：非 None 时 anchor 写 `"code_group": code_group`；None 时**不写这个键**。
- 结构路径：`for match in signal.groups:` 每组一个独立 `claimed: set[str] = set()`，`node_ids = [nid for i, nid in match.pairs if i == term.index]`，`dups = duplicate_claims({i: [n for i2, n in match.pairs if i2 == i] for i in ...})` 按组守门（R144 逐组）。
- 回退路径：完全保持今天的行为（`pairs_or_fallback` → `fallback=True`），只产一条 anchor，`code_group=None`。

- [x] **Step 1 写失败测试**（`tests/test_spine_end_to_end.py`，复用已有假后端 `_YesBackend` 单实例）：

```python
def test_structural_path_anchors_cover_every_layer(...):
    # 假 yes 后端 + 真夹具 → 8 条 anchor，code_group 恰好两个组
    assert len(doc["anchors"]) == 8
    assert {a["code_group"] for a in doc["anchors"]} == {
        "root/transformer.h.0.attn", "root/transformer.h.1.attn"}

def test_each_layer_gets_its_own_judge_call(...):
    # 同一 term 的两层各自问一次；calls == 8，且两层 anchor 的 code_expr_range 不同
    assert backend.calls == 8

def test_claims_are_isolated_per_layer(...):
    # 同组内四个 term 的节点互不相同；跨组的值也不相同（不同节点）

def test_offline_reports_every_layer_as_unresolved(...):
    # 真 offline：0 条 anchor，8 条 unresolved（4 项 × 2 层）

def test_fallback_path_stays_single_layer(...):
    # 结构不命中：仍是 4 条 anchor，且 "code_group" not in anchor

def test_code_group_is_declared_in_schema(...):
    # schema/trace.schema.json 的 $defs.anchor.properties 里有 code_group，且不在 required
```

- [x] **Step 2 跑测试确认失败**（anchor 只有 4 条 / 没有 code_group 键）。
- [x] **Step 3 实现**（`spine.py` 的 `_attach_unit` 结构路径改按 `signal.groups` 循环；`spine_anchor.attach_term` 加参数与新键；schema 加 `"code_group": {"type": "string"}`）。
- [x] **Step 4 按 R168 改既有期望**（`tests/test_spine_end_to_end.py`，逐处、只改值不求删）：
  `:294 len(yellow)==4` → 按层统计；`:302/:303/:332/:367/:652 backend.calls==4` → 8；`:321 len(doc["anchors"])==4` → 8；`:871 len(ranges)==4` → 8；`:478/:1053` 是回退路径 → **保持 4/2 不变**（跑一遍确认，如果变了说明 R161 被违反）。每处改动写进报告。
- [x] **Step 5** 全量 **798 passed**（792+6）；GC8 逐项重建比对。
- [x] **Step 6** 变异探针：删掉每组的 `claimed = set()` 让 claimed 跨组共享 → `test_claims_are_isolated_per_layer`（或 h.1 的项被判「候选全被认领」）必红 → 还原 + sha256。
- [x] **Step 7** 提交 `feat: emit one anchor per isomorphic layer`

---

## Task L4: HTML 显示层

**Files:**
- Create: `papertrace/render/terms.py`
- Modify: `papertrace/render/html.py`（199 → 约 150）、`papertrace/templates/spine.html.j2`
- Test: `tests/test_spine_html.py`（新增 3 条）

**Interfaces:**
- `render_terms.term_rows(doc: dict) -> list[dict]`：每行含 `term_id / tier / confidence / aten_ops / evidence / layer`（`layer` 去掉顶层模块前缀（`root/`）后的组路径，无 code_group 时 `"—"`）。
- 模板 ③ 表头加 `<th>层</th>`，行里输出 `{{ t.layer }}`。

- [x] **Step 1 写失败测试**：`test_terms_table_has_one_row_per_layer`（8 行）、`test_layer_column_shows_group_tail`（含 `transformer.h.0.attn` 与 `transformer.h.1.attn`）、`test_ops_graph_draws_links_in_both_layers`（`lnk-` 路径数 == anchor 数，且两个组的 opbox 里都有 lnklabel）。
- [x] **Step 2 跑确认失败**。
- [x] **Step 3 实现**（拆 `render/terms.py`、模板加列、StrictUndefined 下新变量必须有值）。
- [x] **Step 4** 全量 **801 passed**；四种真实输入（无--paper / 带--paper / skeleton+paper / 纯 skeleton）全部 EXIT=0，HTML <8MB。
- [x] **Step 5** 变异探针：把 `layer` 恒定为 `"—"` → `test_layer_column_shows_group_tail` 必红 → 还原 + sha256。
  **L5-I3 复盘（当时勾的 [x] 是假记录）**：这一步在 L4 落地时并没有真红——旧断言是整页子串 `"h.0.attn" in block`，被 terms 段说明散文里的「（h.0.attn / h.1.attn）」满足，`_layer_of` 恒 `"—"` 测试仍全绿（L4-I2，即 R175：守门必须解析表格行逐字断言）。波次 6 的 F2 已把该测试改成正则抓每行 「层」单元格逐字比，并补 `_layer_cells()` 助手；同款变异复跑 `1 failed in 5.76s`（RED 原文见 .superpowers/sdd/2026-11-15-papertrace-layers/wave6-fix-report.md F2 段），还原后 sha256 复核一致。 教训：变异探针的 RED 输出必须贴进报告才算做过，不能凭「想必会红」勾 [x]。
- [x] **Step 6** 提交 `feat: show which layer each anchor lands in`

---

## Task L5: 文档、演示与账本

**Files:**
- Modify: `README.md`、`docs/superpowers/plans/2026-11-15-papertrace-layers.md`（本文件执行记录段）
- 重生成 `output/demo/*`

- [x] **Step 1** README 补：逐层展开语义（B 方案）、`code_group` 字段、s_retr/s_struct 单元级而 s_judge 逐层、offline 下 unresolved 数 = 项数 × 层数。
- [x] **Step 2** 重生成三份演示（复用 `output/controller-probes/regen_demo2.py / regen_demo3.py` 的口径）：with-paper offline 的 unresolved 变 8。
- [x] **Step 3** 全量 804 passed + GC8 + census，写进计划执行记录段。
- [x] **Step 4** 提交 `docs: record per-layer alignment in README, plan and design`（按 L5 交付契约，覆盖本步骤原信息）

---

## 自审

- **Spec 覆盖**：§3.1→L2；§3.2/3.3→L3；§3.4→L4；§3.5→L1；§7 验收 1-7 逐条对应 L3/L5 步骤。
- **类型一致**：`StructMatch(group, pairs)` 在 L2 定义、L3 消费；`code_group` 在 L3 写、L4 读；`record_unresolved` 在 L1 定义、L3 继续调用。
- **Review Focus 五条**都有测试承接：层数>2（L2 `test_every_attention_layer...` 用真实 2 组但实现按组循环）、回退路径（L3 `test_fallback_path_stays_single_layer`）、认领作用域（L3 `test_claims_are_isolated_per_layer`）、judge 数（L3 `test_each_layer_gets_its_own_judge_call`）、HTML（L4 三条）。
- **比例**：计划约 200 行，spec 约 120 行，未写成代码转录。

---

## 执行记录（2026-11-15，全部完成）

**提交链**（master，每 Task 一次提交；行数与测试数均为落地时实测）：

| Task | 提交 | 内容 | 全量测试 |
| --- | --- | --- | --- |
| 基线 | b04b046 | docs: add the per-layer alignment design plus plan | 787 passed |
| L1 | bc5affe | refactor: split the single-term anchor writer out of spine（spine.py 200→123，新建 spine/anchor.py 99，行为零变化） | 787 passed |
| L2 | 06889f2 | feat: report every isomorphic layer, keep pairs on the first（struct_signal.py 170→186，StructMatch + StructSignal.groups） | 792 passed |
| L3 | 91dde12 | feat: anchor every isomorphic layer, isolate claims per group（spine.py 123→139，schema 加可选 code_group，5 files +214/-34） | 798 passed |
| L4 | 98cfb87 | feat: show which layer each anchor lands in（新建 render/terms.py 50 行，模板加「层」列，4 files +131/-23） | 801 passed |
| L3b | 157ea99 | fix: let a conservative tier downgrade pass validation（schema/anchor.py 改判据 + 3 条新测试，3 files +113/-8） | 804 passed |
| L5 | 本提交 | docs: record per-layer alignment in README, plan and design | 804 passed（不改产品代码与测试） |

**每 Task 一行**：L1 纯重构、L2 报全部同构组、L3 逐层出 anchor 并按「单元 × 组」隔离认领、L4 HTML 一条 anchor 一行 + 层列、L3b 修 tier 复核判据、L5 文档 + 演示 + 本记录段。

**最终测试数：804 passed**（L5 复跑确认，零变化）。

**实施期裁决与偏离（计划拍板时没有，实施中定）**：

- **R169**（L3）：结构信号给了 pairs 却没给 groups → BuildError fail-closed，绝不静默降级成回退路径（papertrace/spine/spine.py:103）。产品里两者永远一致，这条守门是给回归留的闸。
- **R170**（L3）：既有只给 pairs 的测试桩必须按逐层口径补 groups（两组 / 一组两种；回退路径桩不动），否则会被 R169 炸掉；断言值按 R168 改，不减断言。
- **R171 / R172**（L3b，控制器发现）：schema_anchor 的 tier 复核原判据「必须等于 signals 重算结果」会把 R112 回退路径**合法**的 green→yellow 封顶判成造假（实测配置：回退 + 假 yes + 真 embeddings，4 条 anchor 全中）。裁决：判据改成「不得高于重算结果」（rank none(0) < yellow(1) < green(2)），抓升格、放行保守下调；代价：手改把 green 涂成 yellow/none 不再被抓。落地范围只含 schema/anchor.py 判据 + docstring + 3 条新测试，既有 6 条 tier 测试一字不改。
- **R173**（L3b 控制器发现，deferred 到波次 6）：`papertrace/schema/structure.py:129` 的注释仍写 tier「必须与 signals 重算的门一致（RF3）」，R171 之后已过期（判据改成「不得高于重算结果」）。纯注释、零行为变化，L3b 因范围外未动；波次 6 F5 已改成 R171 秩比较口径（134→135 行）。
- **R174**（L4 评审 I-1）：层列原实现 `code_group.rsplit("/", 1)[-1]` 取末段，与规格「顶层模块前缀 + 点式单段路径」不符——`root/transformer.h.0.attn` 的末段是 `attn`，两层完全相同、层列零信息。裁决口径 = 去掉顶层模块前缀、保留组内路径（`transformer.h.0.attn`）；`root/a/b` 这类嵌套 id 也不能塌成末段。
- **R175 / R177**（L4 评审 I-2）：层列守门 `test_layer_column_shows_group_tail` 用整页子串 `"h.0.attn" in block`，被模板 terms 段散文里的「（h.0.attn / h.1.attn）」满足——`_layer_of` 恒返回 `"—"` 测试仍全绿，等于没有守门。判据：必须解析表格行取「层」单元格逐字断言，模板散文删掉具体层名。波次 6 F2 落地（新增 `_layer_cells()` 助手 + `_TERM_ROW` 正则），变异复跑 `1 failed in 5.76s`，RED 原文与 sha256 见 `.superpowers/sdd/2026-11-15-papertrace-layers/wave6-fix-report.md`。
- **R176**（控制器）：实现从 rsplit 取末段改成 `group.split("/", 1)[1]`（无 `/` 原样返回），render/terms.py 50→57 行，docstring 与 plan:181 / design:101 同步改口径。
- **控制器的错（R168 清单，记账）**：R168 清单把 base :367（`test_code_expr_range` 的 `backend.calls`）误列入「→8」，该处是**回退路径**的桩、必须保持 4；L3 implementer 顶住没改，是对的（执行记录 ⑤ 已记）。规约：**清单与实测冲突时，以实测为准**。
- **R178 / R179 / R180**（L5 评审 I-1 / I-2 / I-3+I-4，波次 6 F3 / F4 / F5+F6 落地）：judge 调用口径改成分路径如实说（README + design + plan 三处）；「>2 层有单测覆盖」是假话，补三组同构合成用例并把文案改成「端到端与 HTML 仍未覆盖」；plan:188 的变异探针假 [x] 已改写成真实记录。
- **L3 implementer 自曝的 controller-brief 漏项五处**（均已按实施口径纠正，不是缺陷）：① offline 期望 unresolved 4→8（逐层报）；② tests/test_spine_html.py 的 [green]*4 期望 → *8；③ duplicate-guard 测试桩从 pairs_or_fallback 换成 struct_signal；④ two-unit 分组键按「单元 × 组」取；⑤ :367 的 backend.calls==4 必须**保持 4**（该处是回退路径，控制器 R168 清单误列，implementer 纠正）。

**L5 自身的偏离（对计划 Task L5 步骤）**：

- Step 4 提交信息按交付契约用 docs: record per-layer alignment in README, plan and design（计划里写的 docs: record the per-layer alignment slice 作废）。
- Step 2 演示重生成没有复用 regen_demo2.py / regen_demo3.py 两个脚本，而是写一个 output/controller-probes/l5_regen_demo.py 一次覆盖三场景（code-only / with-paper / fallback-yellow），口径与两脚本一致；三场景落盘后重新读回 trace.json 跑 validate_trace 全过。
- Step 3 的期望测试数写的是 801，实际 804（计划成文时 L3b 尚未发生）。


---

## 波次 6：四份评审与一轮修复（结案）

上一轮按四份切分派了独立评审（L1+L2 / L3+L3b / L4 / L5），Critical 全 0：L1+L2 与 L3+L3b **Approved**（分别 0 / 0 与 0 / 0），L4 与 L5 **Needs fixes**（各 2 / 4 条 Important）。控制器逐条复核后确认六条 Important 全部成立，裁决 R174–R180，交一个 fixer 带完整清单修：

| 轮次 | 提交 | 范围 | 全量 |
|---|---|---|---|
| 波次 6 修复 | `fdf94a4` | 13 files +158/−30（render_terms / spine.html.j2 / tests / README / plan / design / 三份旧规格 / schema_structure / spine_anchor） | **807 passed** |

修复要点（对应六条 Important）：

- **F1 / R174+R176**：`_layer_of` 从「取 `code_group` 末段」改成「去掉顶层模块前缀后的组路径」。末段口径在 `root/transformer.h.0.attn` 上得到 `attn`，两层完全相同、层列零信息；`root/a/b` 这类嵌套 id 更会塌成 `b`。真实渲染现在是 `transformer.h.0.attn` / `transformer.h.1.attn`。
- **F2 / R175+R177**：层列守门改成正则抓表格每行的 (term_id, 层) 两个 `mono` 单元格逐字比。旧断言是整页子串 `"h.0.attn" in block`，被 terms 段说明散文满足——层列恒 `—` 时测试仍全绿，等于没有守门；模板散文里的具体层名同时删掉。
- **F3 / R178**：judge 调用数按路径分开写。结构路径每个「公式项 × 同构组」只有 1 个候选节点 → 恰好 1 次（夹具 4×2=8）；回退路径候选由 `align/candidates.py` 产出（`per_term_limit=3`、`total_limit=12`），每项 1..3 次、全局最多 12 次。
- **F4 / R179**：「层数 >2 有单测覆盖」是假话（全仓 `h.2`/`n_layer=3` 零命中）。补一条三组同构的合成用例，文案改成「只有结构信号层的合成用例覆盖，端到端与 HTML 仍未覆盖」。
- **F5 / R173+R180**：`schema/structure.py:129` 的过期注释改成 R171 秩比较；plan 里「变异探针必红」的假 `[x]` 改写成如实记录；三份旧规格补「M4a 已落地」注记；design 验收第 7 条改成真实值（8 条连线只在测试路径，演示产物 with-paper offline 两子图 0 条）。
- **F6**：`spine/anchor.py` 恢复两个空行；新增 `test_anchor_schema_declares_code_group`（schema 里删掉 `code_group` 声明原本没人报警）。

**定向复审（恰好一次，`layers-rer6`）**：六条 Important 全部 ADDRESSED，新破损 Critical/Important/Minor 全 0；评审自己复跑一次层列变异，RED 原文 `AssertionError: S3.2-eq-attn-t0 的两行层值不是逐层组路径：['—', '—']`，还原后 sha256 `faa6aae6…b716ccf` 一致、`git status` 干净。禁改清单（`spine.py`、`align/*`、`spine/claims.py`、`spine/fallback.py`、`paths.py`、`cli.py`、`test_spine_end_to_end.py`、`test_spine_tier.py` 既有断言）一字未动。

评审留两条先存在备案（本波不动）：`tests/test_spine_html.py` 的 `offline_doc` docstring 仍写「unresolved=4」（实际 8，L3 前遗留）；本文件 R173 行的行号括注「134→135」不精确（实际 `schema/structure.py:129-130`）。

**验收现状（波次 6 后）**：全量 **807 passed**；真夹具 + 假 yes 后端 → 8 条 anchor / judge 8 次 / HTML 8 行、层列 `transformer.h.0.attn` 与 `transformer.h.1.attn`；回退路径 4 条、层列全 `—`；真 offline → 0 anchor / 8 条 unresolved；GC8 不变（nodes=128 算子 75/权重 18/输入 1、edges=101、degraded=2、fused/orphan/shape_broken/shape_unchecked 全 0）；census 无 >200 行；三份演示产物已用当前代码重生成（`code-only` 128/101/0/0、`with-paper` 128/101/0/**8**、`fallback-yellow` 128/101/**4**/0，全部 `validate_trace` 通过、盘符 0 条）。

