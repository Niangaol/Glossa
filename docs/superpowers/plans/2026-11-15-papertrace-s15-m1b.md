# PaperTrace S15 + M1b + 文档修：实施计划

> **For agentic workers:** 本计划由控制器（lead）逐波次派发。波次1 的三个 Task 可**并行**（写作用域互不重叠，R111 授权）；波次2 的集成由控制器**串行独占**。每个 Task 的第一步是读自己的 brief，brief 里有逐字精确值；本计划是权威规格。步骤用 checkbox 便于跟踪。

**Goal:** 让 judge 在「结构同构没命中」时也能工作（S15 kind→op 候选回退 + 词法排序），同时把算子节点的 `loc` 从 `model.GPT` 换成真实 `file:line`（M1b），并把三处与代码行为相反的一手文档修正。

**Architecture:** 三个独立单元并行落地 —— `papertrace/align/candidates.py`（新，纯函数，零 LLM 零 torch）、`papertrace/parse_code/loc.py`（填桩，纯字符串解析）、README/docstring 文档修正。波次2 由控制器把候选回退接进 `papertrace/spine/spine.py`（helper 抽到新文件 `papertrace/spine/fallback.py`，因为 spine.py 已 198/200 行）、让 HTML 算子行显示 `basename:line`、并按要求改写 R37 守门测试。

**Tech Stack:** Python 3.13.15（系统解释器）+ pydeps（pytest 9.2.0 / jsonschema / jinja2 / sympy / torch 2.15.0+cpu）。**零新依赖（GC13）**：禁 numpy / requests / antlr4 / lark。

**Spec:** docs/superpowers/specs/2026-11-15-papertrace-s15-m1b-design.md（v2，286 行，已按独立 builder-check 6+10 条修订，用户 m06557 + 本轮拍板批准）。
**Baseline:** master = e2feca6，**719 passed**。
**Ledger:** .superpowers/sdd/2026-11-15-papertrace-s15-m1b/progress.md（gitignored，控制器维护）。

## 用户拍板记录（绑定）

| 编号 | 拍板内容 | 来源 |
|---|---|---|
| m06557 ① | S15 机制 = **kind→op 决定资格，词法只排序**（词法无一票否决权） | 用户选「推荐」 |
| m06557 ② | judge 预算 = **每项最多 3 个** | 用户选「推荐」 |
| m06557 ③ | 切片范围 = **S15 + M1b + parked 文档修，三块并行** | 用户选「推荐」 |
| 本轮 ① | **R112 成立：回退候选产出的 anchor，tier 上限锁 yellow** | 用户选「锁黄线（推荐）」 |
| 本轮 ② | **R115 授权：改写 R37 守门测试，且必须是加强**（保留「满分检索 + 全 yes → 黄不是绿」断言） | 用户选「授权改写，且必须是加强」 |
| 本轮 ③ | **先写实施计划，然后并行施工** | 用户选「推荐」 |

## Global Constraints（12 条，逐字有效，每个 implementer 的 brief 都要原样带上）

1. **单文件 ≤200 行**，口径 `len(pathlib.Path(f).read_text(encoding='utf-8').splitlines())`（Get-Content .Count 少算）。当前贴线：code_table.py 200、latex_safe.py 200、openai_backend.py 199、**spine.py 198**、split_terms.py 196、cli.py 193。**spine.py 的去处已指定为 spine/fallback.py，不许硬塞、不许现场发明别的文件。**
2. 禁 mock 填产品输出；测试注入的假后端必须**单实例跨调用保持状态**，且**必须断言被测路径真被走到**（计数器 +1）。
3. 默认 offline；judge 禁自由生成；JUDGE_PROMPT / DRILL_PROMPT 正文一字不许改（sha256 钉扎在 tests/test_spine_judge.py）。
4. 公式写死：`c = sigmoid(4·(0.30·s_retr + 0.50·s_judge + 0.20·s_struct − 0.5))`；绿线 0.75 + **s_struct ≥ 0.5 门**；黄线 0.45。**R112 只封 tier，绝不改 signals / confidence / s_struct**（R69）。
5. **GC8：不带 --paper 时逐项不变** nodes=128（module34/param18/input1/op75）、edges=101、counts{operators75, degraded2, fused0, orphan0, shape_broken0, shape_unchecked0}。M1b 改 loc 不在冻结项里，但必须真跑核对七项一个不动。
6. **零新依赖（GC13）**：禁 numpy / requests / antlr4 / lark；禁 `sympy.parsing.latex.parse_latex`。可用：标准库 + sympy / jinja2 / jsonschema / torch 2.15.0+cpu。
7. 测试环境：PYTHONPATH 含仓库根 + pydeps；**不用 pytest tmp_path**，用 `tests/_tmp.py::scratch_dir`。跑 torch.export 前必须先 `from papertrace.parse_code.fx_trace import _ensure_export_cache; _ensure_export_cache()`（否则 dynamo 在缓存目录上炸）。
8. 每 Task 一次提交；变异探针还原锚点必须**先验唯一**；还原后 sha256 逐字节比对。
9. 只捕预期不可用（LLMUnavailable / IngestError），**禁裸 `except Exception`**（R56）。
10. 判据尺子：**静默错误事实 > 静默省略 > 响亮崩溃**。六次升级先例 R27/R36/R54/R76/R85/R96-98。builder-check M2 就是按这把尺子否掉了控制器自己的 R114 原修法。
11. 扫「有没有某种代码」必须**按行或 AST**，不能对全文跑正则（docstring 会冒充代码）。
12. 探针必须**打真产物**，不要自己编简化版再指控。

### 测试命令（每个 implementer 照抄，不要自创）

```powershell
$env:PYTHONPATH='D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps'
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
& 'C:\Users\niangao\AppData\Local\Programs\Python\Python313\python.exe' -m pytest -q
```

### 控制器裁决（本轮新增，波次2 消费）

- **R112**：回退候选产出的 anchor，`level = "yellow" if level == "green" else level`，降级原因拼进 evidence。**只封 tier**。
- **R113（修正版）**：`code_expr_range` **保持 R68 纯 node_id 格式，一个字不改**（改格式会静默砸掉 HTML 彩线）。真实行号走 `node["loc"]`。
- **R114 → R117**：**不**按 `..` 拆区间画线（builder-check M2：区间含 35 个真实节点、实际候审 3 个 → 会画 35 条假线）。**回退路径的 anchor 只指认 judge 确认的那一个节点**（`_judge_pairs` 返回三元组），单节点 → HTML 天然画得出线。结构路径完全不动（仍 first..last），既有测试 :285/:288/:290 保持绿。**既有结构多节点彩线缺失 deferred 到 M4**，正确修法写进文档（anchor 加可选 `code_node_ids` 精确列表，不靠拆 range 猜）。
- **R115**：改写 `tests/test_spine_end_to_end.py:383-416`，必须是加强（见 Task D Step 2）。
- **R116**：`loc` 存绝对路径（诚实、机器相关写进已知局限）；**HTML 只显示 `basename:line`**，完整路径进 `title` 属性；trace.json 相对化归 M4。
- **R118（本轮新增）**：`_judge_pairs` 签名改为返回 `(score: float, evidence: str, confirmed_node_id: str | None)`。**结构路径**（pairs 非空）保持既有行为，confirmed 仅用于回退路径的 range 解析。

## Review Focus（波次3 的评审按这五类找问题）

| 类 | 触发条件 | 归属 |
|---|---|---|
| RF1 | `candidate_pairs` 的资格/排序/截断不是**确定性的**（两个实现者会产出不同 trace.json），或排序让 embedding 一词有否决权 | Task A |
| RF2 | 回退候选**瞎凑**：没有 kind 命中却产出 pairs，或把权重/输入 placeholder 当算子 | Task A / D |
| RF3 | 回退 anchor **能出绿线**（R112 失效），或 R112 顺手改了 signals/confidence/s_struct（破坏 R69） | Task D |
| RF4 | `loc_from_stack_trace` 在拿不到用户帧时**编了行号**，或返回 torch 内部帧 | Task B |
| RF5 | 改写后的 R37 测试**比原来弱**（丢了 unresolved/ref 断言，或「绝不绿」断言不可失败） | Task D |

---

## 波次 1（三个 Task 并行，写作用域互不重叠）

### Task A: S15 候选生成器（papertrace/align/candidates.py）

**Files:**
- 新建 `papertrace/align/candidates.py`（≤200 行）
- 新建 `tests/test_spine_candidates.py`
- 改 `papertrace/align/struct_signal.py` **只改 docstring**：:27-28「不引入词法候选生成器（S15 未批）」→ 如实写明 S15 已批、候选由 `papertrace.align.candidates` 产出、pairs 仍是 struct_signal 的唯一产出；:29-30 的 R38 措辞「会作为 evidence 展示在 HTML」对 StructSignal 本身已过期 → 改成「供测试与调试，spine 只消费 score 与 pairs」；:31-32 的 loc 句改成「loc 是 file:line（M1b 后）或模块路径（回落时），判据只看算子名与组内顺序」。
- 改 `tests/test_spine_struct.py` **只改 :16 docstring**（loc 那句）。

**Consumes:** `papertrace.align.struct_signal.KIND_TO_OPS`（冻结映射，**直接 import，不许抄一份**）、`papertrace.parse_paper.split_terms.KINDS`（只读，用于同步测试）。

**Produces（波次2 消费，签名冻结）:**
```python
class Candidates(NamedTuple):
    pairs: list[tuple[int, str]]   # (term.index, node_id)，与 StructSignal.pairs 同形
    hits: list[str]                # 中文短句
    misses: list[str]              # 中文短句

def candidate_pairs(terms: list, nodes: list[dict], *,
                    per_term_limit: int = 3, total_limit: int = 12) -> Candidates
def lexical_rank(text: str, node: dict) -> float   # 只排序，不过滤
```

**行为约定（逐条有测试）:**
1. 候选池 = `nodes` 里 `level == "op" and kind == "op"` 的节点（与 S5/R25a 同口径）。18 个权重与 1 个输入是 `kind == "param"/"input"`，**永不进候选**。
2. 资格 = `node["op"] in KIND_TO_OPS.get(term.kind, ())`。**用 `.get` 不用下标**：未知 kind → 零候选 + 一条 miss，绝不 KeyError。
3. `lexical_rank` 的**确定性定义**（两个实现者必须产出同一份 trace.json）:
   ```
   tokens(s) = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", s.lower()))
   a = tokens(text); b = tokens(f"{node['op']} {node['label']}")
   if not a or not b: return 0.0
   return len(a & b) / max(len(a), len(b))
   ```
4. 排序 = `lexical_rank(term.latex, node)` 降序，**同分按 `node["id"]` 升序**。
5. 截断 = 每项最多 `per_term_limit` 个；全部合计最多 `total_limit` 个，**按 `term.index` 升序分配预算**；被截断的 term **记一条 miss**（不是每个被砍候选记一条），文案含「term N 有 K 个资格候选，按上限截断，丢弃 K−3 个」。
6. `hits`：每个有候选的 term 一条，文案含 term index、kind、候选数与算子名列表。`misses`：零候选的 term（未知 kind / 该 kind 没有对应算子）+ 被截断的 term。
7. `terms` 为空 / `nodes` 为空 / 全部 kind 不命中 → `pairs == []`，`misses` 写清原因，**绝不瞎凑**。
8. **不做跨 term 唯一性约束**：term0（`QK^{T}`, matmul）与 term3（`V`, matmul）候选集相同是**正确行为**（同一算子可服务两个公式项）。docstring 写明。
9. 不联网、不调 LLM、不 import torch、不 import papertrace.parse_code。**hits/misses 不被 spine 消费**，docstring 写明它们供测试/调试/将来 evidence。

**Steps:**

- [x] **Step 1**: 写 RED 测试 `tests/test_spine_candidates.py`，十条具名测试（名字即契约，不许改名）:
  1. `test_only_kind_compatible_operators_are_candidates`
  2. `test_softmax_term_ranks_real_softmax_first`（用真实夹具 terms：term2 kind=norm 必须排第一）
  3. `test_matmul_terms_share_the_same_candidate_set`（term0/term3 候选集相同 —— 诚实性）
  4. `test_ranking_is_deterministic_on_ties`（分数全 0 时按 id 升序，两次调用结果一致）
  5. `test_per_term_limit_truncates_and_records_one_miss`
  6. `test_total_limit_truncates_by_term_index_order`（**必须手工构造超预算输入**：per_term_limit=3、total_limit=4、三个 term 各 3 个候选 → 只有 term0 拿 3、term1 拿 1、term2 拿 0 并各记 miss。黄金夹具 10≤12 走不到这条路径）
  7. `test_unknown_kind_yields_no_candidates`（伪造 `term.kind = "frobnicate"` → pairs 空 + 一条 miss，不抛异常）
  8. `test_every_split_kind_has_an_operator_mapping`（`set(split_terms.KINDS) <= set(KIND_TO_OPS)`，钉住两个名单同步）
  9. `test_weight_and_input_placeholders_are_never_candidates`（真实 trace 的 18 个 param + 1 个 input 一个都不出现）
  10. `test_empty_inputs_yield_empty_pairs_with_reason`
- [x] **Step 2**: 跑测试确认 RED（ImportError 也算，但**优先让断言级红**：先写一个最小 stub 抛 NotImplementedError 再填）。
- [x] **Step 3**: 实现 `candidates.py` 到全绿。**只 import `re` 与 `typing.NamedTuple` + KIND_TO_OPS**（AST 自检：不许出现 difflib / torch / numpy / requests）。
- [x] **Step 4**: 跑全量（基线 719，本 Task 新增 10 条 → 预期 729 passed，零回归）。
- [x] **Step 5**: 变异探针（锚串先验唯一，改前 grep 确认出现 1 次）:
  - 把资格判据 `node["op"] in KIND_TO_OPS.get(term.kind, ())` 改成 `True`（不过滤）→ 测试 1 与 9 必红 → 还原 + sha256 逐字节比对。
  - 把同分规则 `node["id"]` 升序改成降序 → 测试 4 必红 → 还原 + sha256。
- [x] **Step 6**: 一次提交 `feat: propose kind-filtered judge candidates without any model`。

**Acceptance:** 十条测试全绿；全量 729 passed；行数 census 全 ≤200；GC8 七项不变（本 Task 不碰 parse_code，只需确认未触碰）；`git diff --stat` 只含四个授权文件。

---

### Task B: M1b 真实 file:line（papertrace/parse_code/loc.py）

**Files:**
- 改 `papertrace/parse_code/loc.py`（7 行桩 → 实现，签名**不变**）
- 改 `papertrace/parse_code/fx_nodes.py`：**:169 一处 + 必要 import**
- 新建 `tests/test_m1b_loc.py`

**Consumes:** `node.meta["stack_trace"]`（字符串，可能缺失）。

**Produces:**
```python
def loc_from_stack_trace(stack_trace: str) -> str
```

**行为约定:**
1. 解析 `File "<path>", line <N>, in <func>` 帧（正则 `r'File "([^"]+)", line (\d+), in (\S+)'`）。
2. 返回**第一个不属于库**的帧，格式 `"<path>:<N>"`（绝对路径，R116）。
3. 库帧黑名单（冻结，零依赖）：路径含 `site-packages` / `pydeps` / `\torch\` / `/torch/`。
4. `""` / `None` / 无帧 / 全是库帧 → 返回 `""`（空串）。**绝不编行号、绝不返回猜测值。**
5. **不 import torch**（meta 是 dict）。
6. docstring 必须写明两条已知局限：① 黑名单是**路径子串**判定而非「仓库外」判定，用户仓库路径含 `torch`/`site-packages` 字样会被误杀 → 全帧被排除 → 回落 `root_loc`（诚实降级）；② 同一行可能有多个算子（夹具里 68 个挤在 `model.py:147`），行号只定位行、不区分行内算子，行内判别靠 node id。
7. `fx_nodes.py:169` 改成：`"loc": loc_from_stack_trace(n.meta.get("stack_trace")) or root_loc`（**`or` 而非 `or ""`**，保证空串回落）。import 加在既有 `from papertrace.parse_code.fx_shapes import ...` 附近。

**Steps:**

- [x] **Step 1**: 写 RED 测试 `tests/test_m1b_loc.py`，十条具名测试:
  1. `test_returns_first_user_frame_with_line`
  2. `test_skips_torch_internal_frames`（第一帧 pydeps/torch → 返回第二帧用户）
  3. `test_skips_site_packages_and_pydeps`
  4. `test_empty_string_returns_empty`
  5. `test_none_returns_empty`
  6. `test_no_frames_return_empty`
  7. `test_all_library_frames_return_empty`
  8. `test_real_trace_gives_real_locations`（集成：`_ensure_export_cache()` + `build_trace(tests/fixtures/nanogpt, entry="model:build_model")` → **75 个 kind=='op' 节点全部** loc 含 `".py:"`、文件存在、行号在文件行范围内、该行非空；且 `"model.GPT"` 一个都不剩）
  9. `test_placeholder_nodes_fall_back_to_root_loc`（4 个 placeholder 无 stack_trace → loc == root_loc）
  10. `test_loc_module_does_not_import_torch`（**AST** 扫 loc.py 的 import，不许出现 torch —— 按 AST 不按全文正则，GC11）
- [x] **Step 2**: 确认 RED。
- [x] **Step 3**: 实现到全绿。
- [x] **Step 4**: 跑全量（基线 719 + 10 = 729 passed，**特别确认没有既有测试因 loc 变化而红** —— 已实测 grep loc 等值断言 = 0）。
- [x] **Step 5**: **GC8 逐项真跑**（这一 Task 唯一会动 trace 的地方）:
  ```powershell
  & $py -m papertrace build --repo tests/fixtures/nanogpt --out output/m1b-gc8 --force
  ```
  核对 nodes=128（module34/param18/input1/op75）、edges=101、degraded=2、fused=0、orphan=0、shape_broken=0、shape_unchecked=0、EXIT=0。
- [x] **Step 6**: 变异探针：删掉黑名单判据（所有帧都接受）→ 测试 2 与 8 必红（会返回 torch 内部帧）→ 还原 + sha256。
- [x] **Step 7**: 一次提交 `feat: locate operators at their real source line`。

**Acceptance:** 十条测试全绿；全量 729 passed；GC8 七项逐字不变；loc.py ≤200 行（预期 ~60）；fx_nodes.py ≤200（现 144，**只许多 1-2 行**）；diff 只含三个授权文件。

---

### Task C: parked 文档修（零行为风险）

**Files:**
- 改 `papertrace/parse_paper/units.py` **只改模块 docstring :1-22**
- 改 `README.md` **只改 :332-336 那一段**
- 改 `.superpowers/sdd/2026-11-14-papertrace-spine/final-fix-report.md` §8 数字

**Consumes:** 无。

**Produces:** 文档与代码行为一致。**零代码行为改动**。

**必须改对的三处:**

1. `papertrace/parse_paper/units.py:11-12` 现在写「逐字环境与行内逐字段两个视图均挖空」，与实现相反，而且同句括号里又写「代码字符虽未置空」——**同一句自相矛盾**。按 R109 的真相改写：**两个视图等长**；**code 视图保留原文**（含 `\verb|%|` 里的 `%`）；**comment 视图**把注释与逐字环境内容替换掉（用于找 marker），但**保留决定逐字环境边界的定界符**（否则 `\verb|%|` 的 `%` 会吃掉行内后半段）。附一句为什么：LaTeX 的 `%` 只在注释里是注释，在 `\verb` 里是字面字符。
2. `README.md:334-336` 现在写「没有逐算子源码行号，编一个出来就是对账造假。逐算子源码定位属 **M1b**，届时换成真实 `file:line`」——**两句都过期**：
   - M1b 已落地 → 算子节点的 `loc` **是**真实 `file:line`（绝对路径，R116）。
   - 但 `code_expr_range` **仍是纯 node_id 区间，不换成 file:line**（R113 修正版：换格式会静默砸掉 HTML 彩线）。真实行号在 `nodes[].loc` 上，HTML 的算子行显示 `basename:line`（完整路径在 `title` 里）。
   - 另写明两条局限：`loc` 是绝对路径（trace.json 机器相关，相对化归 M4）；op 节点 `loc` 是 `file:line` 而 module 节点 `loc` 仍是模块路径（同一字段两种语义，既有设计）。
   - **不许重构 README 其他部分**，只替换这一段。
3. `final-fix-report.md` §8 写「code_table 净 0 行」，实测 `+13`（fixer 自己在 concerns 里也记了这件事）→ 改成实测值并注明是事后更正。**这是 gitignored 的账本类文件，改它是为了不留错误记录。**

**Steps:**

- [x] **Step 1**: 逐句核现状（读 units.py:1-22、README:332-336、report §8），把「现在写什么 / 实际是什么」列进报告。
- [x] **Step 2**: 改三处。
- [x] **Step 3**: 跑全量，**必须仍是 719 passed**（文档改动不许影响任何测试；若红了说明误改了代码）。
- [x] **Step 4**: 自检：`git diff` 里出现任何 `def `/`return`/`if ` 的新增行都是越界，必须撤回。
- [x] **Step 5**: 一次提交 `docs: tell the truth about masking, loc, and code_expr_range`。

**Acceptance:** 全量仍 719 passed；diff 只含三个授权文件；units.py 的类与函数体零改动（`git diff -U0 | grep '^[-+].*def '` 无输出）。

---

## 波次 2（控制器独占，串行）

### Task D: 集成（spine/fallback.py + spine.py + render_html + 测试改写）

**Files（全部控制器独占，波次1 的子智能体禁碰）:**
- 新建 `papertrace/spine/fallback.py`（≤200）
- 改 `papertrace/spine/spine.py`（198 → **净增尽量为 0**，分组块搬走）
- 改 `papertrace/render/html.py`（176/200）
- 改 `papertrace/templates/spine.html.j2`
- 改 `tests/test_imports.py`（MODULES 加 `papertrace.align.candidates`、`papertrace.spine.fallback`）
- 改 `tests/test_spine_end_to_end.py`（**R115 改写**）
- 改 `tests/test_spine_html.py`
- 新建 `tests/test_spine_fallback.py`
- 若需 `papertrace/constants.py` / `schema/trace.schema.json`

**Produces:**
```python
# papertrace/spine/fallback.py
def pairs_or_fallback(signal, terms, nodes, *, per_term_limit=3, total_limit=12) -> tuple[dict, bool]
def resolve_code_range(node_ids: list[str], confirmed_id: str | None, fallback: bool) -> str
def cap_tier(level: str, fallback: bool) -> str
```

**Steps:**

- [x] **Step 1（TDD 红）**: 写 `tests/test_spine_fallback.py` 五条:
  1. `test_pairs_win_over_fallback`（signal.pairs 非空 → 原样分组 + `fallback=False`，**候选池一次都不调用**：用打桩的 candidates 计数=0 证明）
  2. `test_empty_pairs_fall_back_to_kind_candidates`（pairs 空 → 分组来自 candidate_pairs，`fallback=True`）
  3. `test_resolve_range_uses_confirmed_node_on_fallback`（fallback + confirmed=`root/@043` → 返回 `root/@043` 单节点）
  4. `test_resolve_range_keeps_first_last_on_structure_path`（非 fallback → `root/@037..root/@045`，**既有行为逐字不变**）
  5. `test_cap_tier_turns_green_into_yellow_only_on_fallback`（fallback+green→yellow；fallback+yellow→yellow；fallback+none→none；非 fallback+green→green。**且断言 signals/confidence 未被改** —— R112 只封 tier）
- [x] **Step 2**: 写 `tests/test_spine_end_to_end.py` 的 **R115 改写**（名字与断言都是契约）:
  - 改名 `test_structural_miss_falls_back_to_kind_candidates_but_never_green`。
  - 保留原注入（`_no_isomorphism` 返回 `StructSignal(0.6, [], [...], [])`）+ `_YesBackend` + `_SameVectorsBackend`（**单实例**，断言 `embedder.calls == 2`）。
  - **R112 守门断言**：`anchors` 非空（4 条）**且每条 `tier == "yellow"`**，**没有一条 green**；`confidence` 仍 ≥0.75（证明是 R112 压的黄，不是分数不够）。
  - `backend.calls >= 1`（证明 judge 真被问了 —— 这与原测试相反，是 S15 的目的）。
  - **另立** `test_offline_structural_miss_stays_honestly_empty`：offline（无注入后端）+ 结构不命中 → `anchors == []`、`backend.calls == 0`、4 条 unresolved 的 ref 恰为 `S3.2-eq-attn-t0..t3`、reason 仍含「结构同构未命中，没有可判断的候选对」且含 `s_struct=0.60`。**原测试的这几条断言一条不许丢，全部迁到这里。**
- [x] **Step 3**: 确认 RED（新文件/改写处未实现时必红）。
- [x] **Step 4**: 实现 `spine/fallback.py` + 改 `spine.py`:
  - `spine.py:121-126` 的 `if not node_ids:` 分支 → `grouped, fallback = pairs_or_fallback(signal, terms, doc["nodes"])`（分组块搬进 helper），空则仍走 `_record_unresolved`。
  - `_judge_pairs` 返回三元组（R118）；回退路径把 confirmed id 传给 `resolve_code_range`，非回退路径传 `None`。
  - `level` 过一遍 `cap_tier(level, fallback)`，降级时把「结构同构未命中，候选来自算子类型回退，不出绿线」拼进 evidence。
  - **绝不改 signals / confidence / s_struct**。
- [x] **Step 5**: 改 `render/html.py` + 模板：算子行补 `<span class="loc" title="<完整路径>"><basename>:<line></span>`；`loc` 为空或不是 `file:line`（module 节点/回落 `model.GPT`）→ 不渲染该 span（**不编**）。
- [x] **Step 6**: `tests/test_imports.py` 的 MODULES 加两个模块。
- [x] **Step 7**: 全量 + GC8 + 四输入 + 行数 census:
  ```powershell
  & $py -m papertrace build --repo tests/fixtures/nanogpt --out output/w2-a --force
  & $py -m papertrace build --repo tests/fixtures/nanogpt --paper tests/fixtures/papers/vaswani2017/attention.tex --out output/w2-b --force
  & $py -m papertrace build --repo tests/fixtures/nanogpt --paper tests/fixtures/papers/vaswani2017/attention.tex --skeleton --out output/w2-c --force
  & $py -m papertrace build --repo tests/fixtures/nanogpt --skeleton --out output/w2-d --force
  ```
  四者 EXIT=0、无 Traceback、HTML 外链 0；GC8 七项逐字；**HTML 里能搜到 model.py:147**（M1b 收益可见）。
- [x] **Step 8**: 变异探针三组（锚串先验唯一）:
  - `cap_tier` 直接 `return level` → R112 守门断言必红。
  - `resolve_code_range` 回退时仍返回 first..last → `test_resolve_range_uses_confirmed_node_on_fallback` 必红。
  - 模板里把 `loc` 用 `|` 拼成完整路径显示 → 「HTML 只显示 basename」测试必红。
- [x] **Step 9**: 一次提交 `feat: let a structural miss fall back to kind candidates without ever going green`。

**Acceptance:** 全量 ≥739 passed（719 + 10A + 10B + 5D + 改写净增 ≈ 4）；GC8 七项不变；四输入 EXIT=0；HTML 显示 `basename:line`；行数 census 全 ≤200；R112 守门断言可被变异打红。

---

## 波次 3（三个只读评审 fan-out）

按 Task 派三个**全新**只读评审，各自看自己的 diff（**不重跑整套测试**，不做视觉目检，不派子智能体）：

| 评审 | 看什么 | 报告 |
|---|---|---|
| `s15-reviewer` | Task A 的 diff + brief + report + GC 全 12 条 | `task-A-review.md` |
| `m1b-reviewer` | Task B 的 diff + brief + report + GC 全 12 条 | `task-B-review.md` |
| `docs-reviewer` | Task C 的 diff + brief + report + GC 全 12 条 | `task-C-review.md` |

**纪律（写进每个派发书）:** 不给控制器的复核结论（避免预判 findings）；「Declined to judge」必须写不许空；只读；有权挑战任何裁决；按 RF1–RF5 找问题。

## 波次 4（一个 fix subagent + 恰好一次定向复审）

- 收齐三份评审 → 汇总成**一份**清单 → 派**一个** fix subagent（不派三个）。
- 修完 → **恰好一次** scoped re-review（只看 fix diff 与 findings 是否关闭）。
- 残留按 fix-loop breaker：**只有 Critical/Important 才开第二轮**；Minor parked 到 M4 第 0 步。
- 之后：合并到 master（若用户要）、更新 goal、向用户交付。

---

## 自审（写完计划后逐条核过）

1. **每个 Task 的「Files」与「Steps」自洽**：Task A 只碰 align/ 与 tests/；Task B 只碰 parse_code/ 与 tests/；Task C 只碰三个文档位；无交叠。
2. **波次2 没有「现场发明文件」**：spine/fallback.py、tests/test_spine_fallback.py 都写进了 Files 与 MODULES。
3. **精确值只出现在本计划与 brief 里**，派发书不复述整份计划。
4. **每条裁决都能回指用户拍板或 builder-check 证据**（R112/R115 有用户原话，R117 有 M2 的 35-vs-3 实测）。
5. **验收两段**：波次1 只到函数级，端到端收益在波次2（builder-check S8）。
6. **两条既有测试的改写都点名了**：R37 那条（R115）与 tests/test_imports.py 的 MODULES（加两个模块）。没有第三条。
7. **计划里没有一处要求写死 ollama / 本地模型**（用户 m00731 拍板不装本地模型）。
8. **GC8 逐字抄了七项**，且 M1b 明确「loc 不在冻结项里但要真跑核对」。

---

## 施工结果（控制器记账，2026-11-15）

| Task | 提交 | 结果 | 修循环 |
|---|---|---|---|
| 波次1 A（S15 候选） | `bd8aef7` | 10 测试，四组变异全 RED | 无 |
| 波次1 B（M1b loc） | `6442b26` | 10 测试，75 个算子全部真实 `file:line`（7 个不同行） | 无 |
| 波次1 C（文档修） | `02811bc` | 全量仍 719，纯文档 | 无 |
| 波次2 D（控制器集成） | `e75260b` | 全量 **754 passed**；GC8 四输入 EXIT=0；四条变异全 RED | 无 |

**R132（计划文本与实现的偏差，记账）**：本计划 Step 2 写「offline 的 reason 仍含『结构同构
未命中，没有可判断的候选对』」——S15 落地后这句不再成立：offline 下**确实试过**回退候选，
只是拿不到 yes，所以诚实的原因变成 `回退候选没拿到判断题 yes（结构同构未命中，候选来自
算子类型+词法排序）`。实际断言：仍含「结构同构未命中」，另含「回退候选没拿到判断题 yes」
与 `s_struct=0.60`。改对了方向（多报一层不确定性），没有放宽任何断言。

---

## 波次3（四份独立评审）与波次4（一次修复 + 一次定向复审）

四份评审**并行 fan-out**（各一个全新只读 agent，互不共享上下文）：
`s15-reviewer`(A)、`m1b-reviewer`(B)、`docs-reviewer`(C)、`spine-d-reviewer`(D)。

| 评审 | 结论 | 计数 |
|---|---|---|
| A：S15 候选生成器 | Approved | Critical 0 / Important 0 / Minor 3 |
| B：M1b 逐算子行号 | Approved | Critical 0 / Important 0 / Minor 3 |
| C：三处文档真话 | Approved | Critical 0 / Important 0 / Minor 5 |
| D：控制器集成（Task D） | With fixes | Critical 0 / **Important 1** / Minor 4 |

D 的 Important 是真问题：符号表 `where` 列把 5 条绝对路径写进 `index.html` 正文（`_symbol_rows` 未
basename 化、模板无 `title`），顶掉了本计划的「正文无绝对路径」验收。虽然非本轮引入，但在本轮允许
改的文件里、且无任何测试覆盖。D 还给出 R117 的**可达性证明**（回退路径 s_struct 上限 0.6、s_retr 封顶
1.0 → score=sigmoid(−0.32)=0.4207 < 0.45 必落 unresolved，故回退 anchor 只可能由 s_judge>0 产出，
而 `_judge_pairs` 只在 judge_score>0 时返回 confirmed → 永远只写一个节点，不是运气）。

按 fix-loop 派**一个** fix agent 带完整九条清单（不是每条一个），提交 **`621ccfc`**（10 文件 +187/−18，
全量 **757 passed**，GC8 七项逐字不变，四条变异探针各 RED 并 sha256 逐字节还原）：

1. F1 符号表正文只显 `basename:line`、完整路径进 `<td title>`（同一 `_where_texts` 口径）。
2. F2 `test_module_rows_do_not_show_module_path_as_a_line` 从空转改成真承重（钉 SVG 算子行数/集合 == level=="op" 的 94）。
3. F3 e2e 的 R117 断言从 `":" not in range` 改成单节点三句断言（无 `..`、∈ node_ids、等于期望首候选）。
4. F4 `_attach_term` 补回 `node_ids: list` / `by_id: dict` / `fallback: bool`，spine.py 仍 200 行。
5. F5 限流默认值 3/12 与行为双重钉住。
6. F6 零候选 miss 文案拆「kind 无映射」/「有映射但无节点」两因。
7. F7 README 过期行号 `:82 → :98`（FIX-1 新增 3 行把目标行推后，照抄 `:95` 会更错）。
8. F8 `loc.py` docstring 补「绝对路径/机器相关/相对化归 M4」。
9. F9 `lexical_rank` docstring 注明与 `node[...]` 的等价条件。

**定向复审（恰好一次）`s15-rereviewer`：All addressed，9/9，残留 0；新破损 Critical 0 / Important 0 / Minor 1。**
它独立判定修复者两处改判**均成立**（`:95` 会当天过期；`--repo` 传相对路径时 `meta.repo.url` 本就相对，
「两条都保持绝对路径」是事实错误）。

**R134（复审后的一条文档 Minor，控制器自修）**：复审指出 README「分享 `trace.json` 会一并带上本机目录」
在传相对路径时不成立，建议改「可能」。改成「**可能**一并带上（`--repo`/`--paper` 传相对路径时记的就是
相对路径）」送进 `469e9b2`（`docs:` 单行 2+/1−，纯文档、零行为、无测试读取 README 内容）。
这条不进第二波复审：一行措辞、控制器自己 grep 验证、且改完重跑全量仍 757 passed。
错了的代价：若措辞仍不准，下一个人读到会多问一句——远小于再开一轮派发+复审的成本。

