# S20 认领唯一性 + S21 路径便携化：设计文档

> 状态：设计（待 builder-check）。用户 m10311「按照你的想法做」＝把方向决定权交给我，
> 但下面每条仍然写清「为什么这么定 / 错了的代价」，方便事后逐条推翻。

## 0. 为什么是这两件事

上一片（S15 + M1b）交付后，我自己跑演示时看到两个**用户一眼就能看出不对**的东西：

1. `output/demo/fallback-yellow/index.html` 里 4 条黄线中有两条指向**同一个算子节点** `root/@037`
   ——term0 是 `QK^{T}`、term3 是 `V`，两个不同的公式项认领了同一个 matmul。
2. `trace.json` 里 `meta.repo.url`、每个 op 的 `loc`、符号表的 `defined_at` 全是
   `D:\AgentPrograms\PaperTrace\...` 这种绝对路径，分享出去就等于把本机目录结构一起发出去。

第 1 条是**正确性**问题（归属断言自相矛盾），第 2 条是**可分享性**问题（R116/R133 当时把相对化推给 M4，
现在做掉）。三件待办里的「M4 第 0 步拆文件」不是独立价值，它是这两件事的前置，所以放在施工波次里顺手做
（见 §5 GC）。

## 1. 实测事实（全部本机真跑，不是推测）

### 1.1 候选集完全相同

探针 `output/controller-probes/s20_paths_probe.py`，黄金夹具 `tests/fixtures/nanogpt` +
`tests/fixtures/papers/vaswani2017/attention.tex`：

| 项 | kind | latex | 候选（按词法排序） |
|---|---|---|---|
| t0 | matmul | `QK^{T}` | `root/@037`, `root/@045`, `root/@071` |
| t1 | scale | `\sqrt{d_k}` | `root/@038`, `root/@072` |
| t2 | norm | `\mathrm{softmax}` | `root/@043`, `root/@077` |
| t3 | matmul | `V` | `root/@037`, `root/@045`, `root/@071` |

t0 与 t3 的候选**逐字相同**（都是三个 matmul）。而结构同构给出的真值对是
`[(0,'root/@037'), (1,'root/@038'), (2,'root/@043'), (3,'root/@045')]`——两项落在**不同**的 matmul 上。

**独占贪心模拟**（按 term.index 升序、跳过已被认领的）：t0→`@037`、t1→`@038`、t2→`@043`、t3→`@045`，
与结构真值**四项全同**。也就是说去重不是让结果变差，而是把「假后端一答 yes 就撞车」的结果拉回真值附近。

### 1.2 谁在替我们做决定

- `papertrace/align/candidates.py:16-17` 当时明文写着：**不做跨 term 唯一性约束**，理由是「同一个算子可以同时
  服务两个公式项，去重等于编造唯一归属」。这条理由的成立前提是「共享真的存在」。见 §4 R135 的反驳。
- `papertrace/spine.py:107-108` 逐项独立处理，term 之间**没有任何共享状态**；
- `papertrace/spine.py:172-181` 的 `_judge_pairs` 按候选顺序问，第一个 yes 就返回。

### 1.3 路径都出现在哪

| 字段 | 现在 | 来源 |
|---|---|---|
| `meta.repo.url` | `D:\AgentPrograms\PaperTrace\tests\fixtures\nanogpt` | `papertrace/cli.py:92` `repo_url=str(args.repo)` |
| `meta.paper.source` | `.tex` 的本机路径 | `papertrace/spine.py` 的 `meta.paper` |
| `nodes[*].loc`（op） | `D:\...\model.py:147`（7 种，68 个算子挤在 `:147`） | `loc_from_stack_trace`（M1b） |
| `nodes[*].loc`（module） | `model.GPT`（模块路径，**不是文件路径**） | `fx_modules.py` |
| `symbols.code[*].defined_at` | `D:\...\model.py:65` 等 5 条 | `papertrace/symbols/code_table.py` |

schema 对这四个字段**只要求 `type: string`**（`schema/trace.schema.json:24/34/109/146`），没有 `pattern`/`format`
→ 相对化**不需要改 schema**。

### 1.4 环境约束

- 测试里**没有任何 `os.chdir`**（`grep chdir tests/` 零命中）→ pytest 的 cwd 一直是仓库根，相对路径在测试里
  可解析（`tests/test_spine_symbols.py:82-106` 会真的去打开 `defined_at`）。
- `papertrace/spine.py` 正好 **200 行**（硬上限）→ 加逻辑必须先搬走等量代码。
- `spine_fallback.py` 66 行、`candidates.py` 110 行有空间；`paths.py`/`spine_claims.py` 是**新文件**，不占名额。

## 2. 设计 A：认领唯一性（S20）

**要断言的东西**：在一**个公式单元**内，一个算子节点最多被一个公式项认领。anchor 的语义是「这一项由这个算子
实现」（归属），不是「这一项和这个算子有关」（相关）。同一个 matmul 不能既实现 `QK^{T}` 又实现 `V`。

**做法**：

1. `papertrace/spine_claims.py` 新模块，放四样东西：
   - `node_text(node) -> str`：从 spine.py:184-187 搬来（逐字不动）；
   - `unclaimed(node_ids, claimed: set[str]) -> list[str]`：保持顺序，剔掉已认领的；
   - `judge_first_yes(term_text, node_ids, by_id, claimed: set[str]) -> tuple[float, str, str | None]`：
     从 spine.py:172-181 搬来 + 跳过已认领 + **确认时把 node_id 写进 `claimed`**；
   - `CLAIMED_REASON`：候选全被占时给用户看的一句话（中文，含「同一单元内一个算子只归一个公式项」）。
2. `_attach_unit`（spine.py:92-108）持有 `claimed: set[str]`，逐项传下去；`_attach_term` 拿到 `available = unclaimed(...)`：
   - `available` 为空但 `node_ids` 不空 → 记 unresolved + `CLAIMED_REASON`（**不是** `NO_CANDIDATE_REASON`，两者成因不同）；
   - 否则照旧问 judge，确认即占位。
3. 结构路径不变（子序列匹配天生 1:1），但加**守门**：同一单元内 `grouped` 的 node_id 出现两次 → `BuildError`。
   理论上不可达，属于防回归的断言，不是靠它出结果。

**作用域**：只限同一公式单元。跨单元（不同 equation）允许共享——不同的推导式复用同一个算子完全正常，
而且跨单元去重要求「整篇论文一个算子只归一项」，那是明显过强的断言。

## 3. 设计 B：路径便携化（S21）

**要断言的东西**：`trace.json` 在「构建时的 cwd 之下」的路径，一律存相对路径（`/` 分隔），否则保留绝对路径。
这样同一份 trace 拿到别的机器/别的目录，路径仍然指向项目内的相对位置。

**做法**：新建 `papertrace/paths.py`：

- `portable_path(p: str, base: str | Path | None = None) -> str`：`base` 默认 `Path.cwd()`；
  能把 `p` 解析成「在 base 之下」时返回 POSIX 风格的相对路径，否则原样返回；空串原样返回。
- `portable_loc(loc: str) -> str`：只处理 `path:line` 形态（`rpartition(':')` 的尾段是数字）；
  **模块路径（`model.GPT`）原样返回**，`D:\...` 与 `/home/...` 两种绝对形态都能处理。
- `relativize_doc(doc: dict, base=None) -> int`：**原地**改写并返回改写条数：
  `meta.repo.url`、`meta.paper.source`、`nodes[*].loc`（走 `portable_loc`）、`symbols.code[*].defined_at`。

**接线点只有一处**：`papertrace/cli.py` 在 `dump_trace` 之前调 `relativize_doc(doc)`。producer（parse_code / symbols /
spine）全部不动——单点、可测、不散落。

**不碰**：module 节点 `loc`（模块路径不是文件）、`paper_unit_id`/`term_id`（是标识符不是路径）、`repo.commit`、
`meta.runtime`（张量形状等）。

## 4. 裁决（R135–R143，逐条给「为什么」与「错了的代价」）

| # | 裁决 | 为什么 | 错了的代价 |
|---|---|---|---|
| R135 | **推翻** S15 的「不做跨 term 唯一性」（candidates.py:16-17），改为同单元内唯一 | 那句的理由是「共享真实存在」，但 anchor 是**归属**断言；实证：t0/t3 候选逐字相同、真值对是两个不同 matmul，独占贪心四项目标全中 | 若某论文真有「一个算子实现两个公式项」的情形，我们会少连一条线（落 unresolved 并写明原因），而不是连错 |
| R136 | 唯一性**只限同一公式单元**，跨单元不共享 `claimed` | 不同 equation 复用同一算子是常见且正确的 | 跨单元的重复仍然存在（可接受，属语义正确） |
| R137 | 候选被占尽 → unresolved，原因文案与「没有候选」分开 | 两种成因，用户要能看出是「被别人占了」还是「压根没有」 | 文案冗余一点 |
| R138 | 结构路径不变，但加 `BuildError` 守门（同单元重复 node_id） | 理论不可达；一旦回归要响亮失败而不是静默连线 | 真有合法重复时会响亮炸（更安全的方向） |
| R139 | 便携化在**落地前一次**（cli.py），producer 不动 | 单点、可测、不散落；producer 不依赖 cwd | cli 之外的调用方（测试直接调 `attach_paper`）拿到的是绝对路径 |
| R140 | 相对基准 = 构建时 cwd；只在 cwd 之下时相对化；分隔符统一 `/` | 分享者按项目根解开即可；POSIX 分隔符跨平台可读 | 从 A 目录构建、到 B 目录打开时相对路径指错（README 写清） |
| R141 | 不相对化 module loc / unit_id / commit / runtime | 它们不是文件路径，相对化会造出假路径 | 无 |
| R142 | HTML 的 `title` 显示字段原值（现在变短了），正文仍只显 `basename:line` | 保持 R133 的「正文给人读、title 给细节」 | title 没有绝对路径可看（真需要时 trace.json 里有原始输入） |
| R143 | 代码落点：新 `spine_claims.py`（spine 搬出 `_judge_pairs`/`_node_text`）+ 新 `paths.py` | spine.py 已 200 行满额；搬出后净增 ≤0 | 新模块多一层 import |

## 5. Global Constraints（本片新增 3 条，其余沿用脊柱切片）

- **GC14**：`relativize_doc` 之后，当输入都在 cwd 之下时，trace.json 的 `meta.repo.url`/`meta.paper.source`/
  所有 op `loc`/所有 `defined_at` **不含** `[A-Za-z]:\\` 与以 `/` 开头的绝对形态。
- **GC15**：认领唯一性**不增加** judge 调用次数上限（仍每项 3、合计 12），且实测 ≤ 现状。
- **GC16**：同一公式单元内，**认领（claim）集合**互不相交——一个算子至多归属一个公式项；anchor 的 `code_expr_range` 写出的节点与它覆盖的候选节点全部计入认领；跨公式单元共享是允许的。
  R157/R158 之后所有 range 都是单节点，「认领口径」与「区间口径」因此是同一件事。**唤醒条件**：若将来结构路径的一个公式项又产出多节点区间，
  必须重新裁决区间口径（内部节点算不算认领）并补测试，不许默默恢复第三态。
- 沿用：零新依赖、单文件 ≤200 行（`splitlines` 口径）、GC8 不带 `--paper` 逐项不变、offline 诚实空态、
  禁止 mock 填产品输出、测试用 `tests/_tmp.py::scratch_dir`、每次提交一次改动。

## 6. 已知局限（写进 README，不假装解决）

1. 唯一性只在**同一单元**内；跨方程仍可能两项指同一算子。
2. 独占是**贪心**（按 `term.index` 升序），不是最大匹配。极端构造下（t0 只有一个候选 、且 t3 只能用它）会牺牲 t3。
   改成最大匹配要多问 judge、且要处理平局优先级——不在本片。
3. 便携化基准是 cwd，跨目录打开会指错；`trace.json` 里不再有本机绝对路径，也就无法从 trace 反推原仓库位置。
4. 只对齐第一层 `h.0.attn`（沿用 S5 局限）。（M4a 已落地，见 specs/2026-11-15-papertrace-layers-design.md）
5. 浏览器视觉目检仍未做（自动化断言 + 抽页渲染代替）。

## 7. 验收

1. 全量测试 ≥ 757 + 新增，且零回归；GC8 四输入逐项不变（`128/101`、`degraded=2 fused=0 orphan=0 shape_broken=0 shape_unchecked=0`）。
2. 新测试（具名）：重复认领不可发生（同单元两项不得同一节点）、候选被占尽落 unresolved 且原因含「认领」、
   结构路径守门 `BuildError`、`portable_path` 的 inside/outside/分隔符、`portable_loc` 不动模块路径、
   `relativize_doc` 四字段全覆盖、CLI 端到端 trace.json 无盘符。
3. 演示对比：同一假 yes 后端下，旧产物两项指 `@037`，新产物指 `@037`/`@045`（结构真值）。
4. 独立评审 fan-out（认领 / 路径 / 文档三份）+ 一轮修复 + 恰好一次定向复审。
## 8. builder-check 的六条必须补与我的裁决（R144–R153）

独立 builder-check（`claims-paths-builder-check`，报告 `.superpowers/sdd/2026-11-15-papertrace-claims-paths/builder-check.md`）
给出 A 必须补 6 条 / B 建议补 6 条 / C 核实不是缺口 8 条 / D 与代码事实不符 3 条。我逐条复核后裁决如下
（A1、A2 是它抓到的**真**缺陷，不补会直接踩雷）。

| # | 裁决 | 为什么 | 错了的代价 |
|---|---|---|---|
| R144 | **推翻 R138 的「理论不可达」**：守门**只在结构路径（`fallback=False`）执行**；回退路径的 grouped 跨 term 重复是**正常输入**，唯一性交给 `claimed` | builder-check 探针实测回退 grouped = `{t0:[@037,@045,@071], t3:[@037,@045,@071]}`，按字面实现会让**所有结构不命中的 build** 崩 BuildError——那正是 S15 的核心场景与两条既有回归测试 | 结构路径若真出现重复会响亮失败（保留守门）；回退路径不变 |
| R145 | 两条既有测试**必然要改**，新期望值写死：`test_meta_paper_is_tex` 的 `source` → `tests/fixtures/papers/vaswani2017/attention.tex`；回退测试里 t3 的 `code_range` → `root/@045`（= 该 term 候选组里第一个未被认领的节点） | 设计 §7.1 说「零回归」却不点名，实现者跑到红会怀疑自己实现错而回滚认领 | 若把断言改成自证循环，验收就成了橡皮图章——所以期望值必须是**手算的常量** |
| R146 | `CLAIMED_REASON` 统一文案：`候选全部被同一公式单元内更早的公式项认领（一个算子只归一个公式项）`，**裸 append** 进 unresolved，**不走** `_record_unresolved` | 走 `_record_unresolved` 会包装成「置信度 x < 0.45：…」，但这里的成因是「节点被占了」不是「证据不够」，文案会误导 | unresolved 的字段形态与其它条目略不一致（仍满足 schema：kind/ref/reason 都有） |
| R147 | **GC16 的达成机制补死**：任何**产出 anchor** 的项，把它 `code_expr_range` 覆盖到的节点**全部加进 `claimed`** | builder-check 指出只认领「judge 确认的那个」时，回退路径 s_judge=0 仍可上黄线（s_retr=1 时 c≈0.46≥0.45）；当时 range 是 first..last，两项仍可重叠（R158 之后回退一律单节点，这条动机随历史保留，机制本身无条件生效）。GC16 是硬约束，必须有无条件机制 | 无 judge 确认的回退 anchor 会吞掉整段候选，同单元后面的项更早落 unresolved——方向是「少连一条线并写明原因」 |
| R148 | 守门/接线抛的 `BuildError` 由 cli **新增一个 try** 收成一行错误 + 退出码 2（与既有 BuildError 处理一致），不冒 traceback | `attach_paper` 现在不在任何 `try/except BuildError` 里，守门一炸就是裸 traceback | cli.py 193→≤198 行，仍 ≤200 |
| R149 | 演示产物**重新生成并覆盖** `output/demo/{code-only,with-paper,fallback-yellow}`；旧产物不留副本（它是 `output/`，gitignored，且新产物本身就是证据） | 旧产物里两项指 `@037` 正是要被修掉的缺陷，留副本只会让下一个人以为缺陷还在 | 失去「修复前后对比」的实物；设计 §7.3 的对比改写进交付说明（文字 + 新产物数值） |
| R150 | CLI 端到端新测试必须**显式 pin cwd = 仓库根**（`subprocess.run(..., cwd=REPO)`） | GC14 的相对基准是 cwd；从别的目录跑 pytest 期望值全漂 | 测试多一点样板 |
| R151 | 黄线的 `alternatives` 也**过滤 `claimed`** | 否则 HTML 会出现「备选指向已被别的项归属的节点」，与 R135 自相矛盾 | 备选有时为空（允许，schema 里 alternatives 非必填） |
| R152 | `papertrace/spine_fallback.py:11` docstring 里「由 `spine._judge_pairs` 返回」改成指向 `spine_claims.judge_first_yes` | 搬走后那句成了假地址 | 无 |
| R153 | 设计文档 §1.4 的 `tests/test_spine_symbols.py:82-106` 更正为 `:78-93`；§0 第 1 条的「在 index.html 里可见」改成「在 trace.json 里两条 anchor 都是 `root/@037`（index.html 走渲染通道，grep 不到字面 `@037`）」 | builder-check D1/D2：行号引尾超界、产物级引用不精确 | 无（结论不变） |

另：B2（相对输入也要 `as_posix()` 归一化）已在 Task B 的行为约定第 1 条里写死；B6（测试清单要分「修改既有 / 新增」）
已按 R145 在计划里分栏。

