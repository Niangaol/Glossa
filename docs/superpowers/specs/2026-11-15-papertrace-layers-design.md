# PaperTrace 逐层对齐（M4a）设计

日期：2026-11-15　状态：**已获年糕拍板（m10968：选 B「每层一条 anchor，全部展开」）**

## 0. 为什么现在做

S20/S21 交付后剩下的第一条已知局限是「只对齐第一层」：`papertrace/align/struct_signal.py:25-26`
（R25a）明写「h.0.attn 与 h.1.attn 完全同构且都能匹配，首匹配规则选 h.0.attn」。
真 GPT-2 有 12 层、GPT-3 级有 96 层，同一份 attention 公式在每一层都重复出现，
只认首层会让用户以为「只有第一层对上了」。

年糕选了 **B：每层一条 anchor，全部展开** —— 每层各出一条线、各问一次判断题。
代价（API 调用 ×层数、anchor 数与 HTML 行数 ×层数）已知并接受。

## 1. 实测现状

| 事实 | 值 | 出处 |
|---|---|---|
| 夹具 n_layer | 2 | `tests/fixtures/nanogpt/model.py` GPTConfig |
| 两个注意力组 | `root/transformer.h.0.attn` / `root/transformer.h.1.attn`，各 22 个真算子（23 个 op-level 节点） | 控制器探针 s5_nodes.py |
| 组内算子序列 | split, getitem×3, view, transpose…, **matmul, mul**, slice×2, eq, masked_fill, **softmax**, **matmul**, transpose, contiguous, view | 同上 |
| 同构命中 | Vaswani 四项 `matmul→scale→norm→matmul` 在两组的子序列匹配都成立 | 同上 |
| 当前 pairs | 只由首组产出 4 对 | struct_signal.py:128-135 |
| 结构路径 anchor 数 | 4（4 项 × 1 层） | tests:321 等 |
| 满额文件 | spine.py 200 / latex_safe.py 200 / symbols/code_table.py 200 / render/html.py 199 / openai_backend.py 199 | 控制器 census |
| anchor schema | 7 个 required，`evidence` maxLength 80，**未设 additionalProperties**（可加字段）；顶层 trace 是封闭的 | schema/trace.schema.json |

## 2. 三个方案与取舍

- **A 一条 anchor + 同构层清单**：anchor 指首层，另加可选字段列出其余同构层。零 API 成本、anchor 不膨胀；但「h.1 到底对没对上、证据是什么」只能靠清单断言，没有逐层证据。
- **B 每层一条 anchor（选用）**：每层各自出 anchor、各自问 judge、各自算 confidence。最接近事实；代价是调用数与行数 ×层数，且 12 层时 terms 表会很长的。
- **C 只写进 evidence**：零 schema 改动，但 evidence 上限 80 字，已承载「回退说明 + 分档理由 + 兜底证据」，塞不进层信息，下游也读不到。

选 B 的理由：用户看到的应当是「h.0 对上了、h.1 也对上了（各自有证据）」，而不是一条 anchor 加一句附录。

## 3. 设计

### 3.1 struct_signal 产出全部同构组

`papertrace/align/struct_signal.py`：

```python
class StructMatch(NamedTuple):
    group: str                                  # 组 id，如 "root/transformer.h.1.attn"
    pairs: list[tuple[int, str]]                # [(term.index, node_id)]

class StructSignal(NamedTuple):
    score: float
    hits: list[str]
    misses: list[str]
    pairs: list[tuple[int, str]]                # 首组，**保持不变**（S7 与既有测试的契约）
    groups: tuple[StructMatch, ...] = ()        # 全部命中组，nodes 顺序
```

`_first_isomorphic_group` 改名为 `_isomorphic_groups`，返回所有命中组；
`pairs` 仍取第一个命中组（R25a 的「首匹配」语义不变，S7 的候选来源不变）。
score 仍只加一次 +0.2（多层同构不是多次加分）。
hits/misses 文案**一字不改**（R38 的 ≤80 字预算与既有断言）。

### 3.2 spine 逐层出 anchor

结构路径（`signal.groups` 非空）：对**每个组**各跑一遍逐项循环，于是
4 项 × 2 层 = 8 条 anchor；每层的 `claimed` 集合独立（同组内独占、跨组互不影响）。
回退路径（结构未命中）：**保持现状**，每个 term 一条 anchor —— 回退本来就没有层可言。

anchor 新增可选字段 `code_group: str`（组 id）。结构路径必填，回退路径省略
（回退时 anchor 落在哪个组取决于候选算子，语义上不是「层」）。

s_retr 与 s_struct 是**公式单元级**信号，逐层相同；s_judge 是逐层各自的。
所以同一 term 的两条 anchor 的 confidence 只可能因 s_judge 不同而不同 —— 如实写进
docstring 与 README，不假装逐层独立。

### 3.3 认领唯一性

R135 的「一个算子至多归一个公式项」按 **公式单元 × 同构组** 隔离：
同组内独占（一个算子在这一层只归一个项），跨组共享是必然的（h.0 与 h.1 是不同节点）。
R144 的重复守门同样按组跑。

### 3.4 HTML

- ③ 公式项表：一行一条 anchor（8 行），新增「层」列显示 `code_group` 去掉顶层 `root/` 前缀后的组路径（如 `transformer.h.1.attn`）。
- ② 算子图：现有「节点 → 连线 + lnklabel」机制天然支持多层 —— 8 条 anchor 落在 8 个节点上，
  两个注意力组都会画出 t0..t3 的连线，无需新逻辑。
- ④ 未对齐清单：offline 下 8 条（每层每项一条），文案不变。

### 3.5 拆文件（本片必须先做，否则改不动）

| 文件 | 现状 | 做法 |
|---|---|---|
| `papertrace/spine/spine.py` | 200 | 拆出 `papertrace/spine/anchor.py`：`attach_term` + `record_unresolved` + 证据常量；spine.py 只留编排 |
| `papertrace/render/html.py` | 199 | 拆出 `papertrace/render/terms.py`：公式项行的构造（锚点 → 行 dict） |
| `latex_safe.py` / `symbols/code_table.py` / `llm/openai_backend.py` | 200/200/199 | **本片不动**（本片不触碰；无价值重构，等真正要改它们的那片再拆） |

## 4. 裁决

- **R161**（已实现，L3 91dde12）逐层展开只发生在结构同构路径；回退路径每个 term 一条 anchor（无层可言）。
- **R162**（已实现，L3 91dde12）认领唯一性按「单元 × 同构组」隔离；R144 重复守门同样按组。
- **R163**（已实现，L3 91dde12）anchor 新增可选 `code_group`：结构路径必填、回退路径省略；schema 里声明但不进 required。
- **R164**（已实现，L3 91dde12）s_retr / s_struct 是单元级、逐层相同；只有 s_judge 逐层。docstring 与 README 如实写（README 字段契约段 + 已知局限段，L5 补）。
- **R165**（已实现，L1 bc5affe）拆 `spine.py` → `spine/anchor.py`；`tests/test_spine_tier.py:169` 的 `from papertrace.spine.spine import _record_unresolved` 改指新模块（断言一字不改，属重命名不是削弱）。
- **R166**（已实现，L4 98cfb87）拆 `render/html.py` 的公式项行构造 → `render/terms.py`；公式项表改成一条 anchor 一行，「层」列显示 `code_group` 去掉顶层模块前缀后的组路径（R176：不取末段——嵌套 id 下末段会塌成同一个词，层列信息全丢）。
- **R167**（已实现：三文件一字未动，行数仍 200/200/199）`latex_safe.py` / `symbols/code_table.py` / `llm/openai_backend.py` 本片不动。
- **R168**（已实现，L3 91dde12）既有测试里「结构路径 4 条 anchor / judge 4 次」的期望按逐层改成 8，逐处列进计划（授权改写，不许删断言）。

**实施期新裁决（L3 / L3b，均已实现并落在测试里）**：

- **R169**（L3 91dde12）结构信号给了 `pairs` 却没给 `groups` → `BuildError` fail-closed，绝不把结构路径静默降级成回退路径（`papertrace/spine/spine.py:103`；测试 `tests/test_spine_end_to_end.py` 的 pairs-无-groups 用例）。产品里 `pairs` 与 `groups` 永远一致，这条守门是给未来的回归留的闸。
- **R170**（L3 91dde12）测试桩补 `groups`：既有只给 `pairs` 的测试桩按逐层口径补同构组（两组 / 一组两种），回退路径的桩不动；断言值按 R168 改，不减断言。
- **R171**（L3b 157ea99）`schema_anchor` 的 tier 复核判据从「必须等于重算结果」改成「**不得高于重算结果**」（rank `none`(0) < `yellow`(1) < `green`(2)）：抓升格（手涂绿）、放行保守下调。缺口成因：R112 回退路径会把 green 封顶成 yellow，旧判据把这个**合法行为**判成造假。代价：手改把 green 涂成 yellow/none 不再被抓。
- **R172**（L3b 157ea99）Task L3b 立项范围：只改 `schema/anchor.py` 判据与 docstring，加 3 条测试（下调放行 / 升级拒绝 / 回退端到端过校验），既有 6 条 tier 测试一字不改。

## 5. 全局约束（追加）

- **GC17** 结构路径 anchor 数 = 公式项数 × 同构组数；回退路径 = 公式项数。
- **GC18** 同一组内两个 anchor 不得共用算子节点（既有 GC16 的逐组版本）。
- **GC8** 不变：不带 `--paper` 时 nodes=128 / edges=101 / 六计数不变、anchors=[] / unresolved=[]。

## 6. 已知局限（本片结束仍然存在）

- 逐层展开只对「结构同构」有效的组；同构判定按**组内子序列**做，跨组混合结构（如残差在不同层插入位置不同）仍可能只命中一部分层。
- 层数 >2 的规模化只有结构信号层的合成用例覆盖（`tests/test_spine_struct.py` 的三组同构图，R179）；夹具本身只有 2 层，>2 层的端到端 anchor 生成与 HTML 渲染仍未覆盖。
- s_struct 上限仍是 0.8（论文侧「N 层」与形状声明两条规则要靠 M4b 读论文正文）。
- 配 DeepSeek 仍然出不了绿线（无 embeddings → s_retr=0）。
- HTML 公式项表在 12 层模型下会变成 4×12=48 行；折叠/筛选留给后续。
- **R171 之后 schema 只抓升格**：手改把 tier 从 green 涂成 yellow / none 不再被 `validate_trace` 抓到——这是让 R112 回退路径的合法封顶过校验而主动让出的一小步（换来的是合法构建不再崩），不是放进假事实。
- **默认 offline 后端下逐层口径不可见**：offline 是默认后端，一条 anchor 都不产，演示产物 `index.html` 公式项表的「层」列全是「—」（L5 实测三个演示场景的层名个数均为 0）；逐层显示路径由 `tests/test_spine_html.py` 覆盖，不在演示里。

## 7. 验收

1. 全量测试全绿（基线 787），既有断言只按 R168 清单改期望值。
2. 夹具 + 假 yes 后端：**8 条 anchor**，分属两个组，组内四个 term 各一条，judge 调用 **8 次**
   （结构路径每个「公式项 × 同构组」候选只有 1 个节点，恰好 1 次；回退路径每项最多 3 次、
   全局最多 12 次，R178）。
3. 真 offline：**0 条 anchor、8 条 unresolved**。
4. 回退路径（结构不命中）：仍是 **4 条**，且不带 `code_group`。
5. GC8 逐项不变。
6. 产品源文件 ≤200 行（census）。
7. 演示产物重生成：`output/demo/with-paper` 的 unresolved 从 4 变 8；HTML 里 ② 两张 attn 图各有 4 条连线
   （如实说：这 8 条连线只出现在「结构命中 + 判断题后端」的测试路径里，即
   `tests/test_spine_html.py` 的假 yes 路径；演示产物里没有这条路径——with-paper offline
   两子图 0 条，fallback-yellow 是 h.0=4 / h.1=0）。

**验收结论（L5 落地时核对）**：1–7 全部达成。全量测试 787 → **804 passed**；演示三场景重生成后 `validate_trace` 全过，with-paper offline 实测 unresolved=8（4 项 × 2 层），逐场景数字与提交链见 plan 文档执行记录段。
  **L5-I4 复盘（波次 6 更正）**：第 7 条里「两张 attn 图各有 4 条连线」在演示产物里并不成立——
  8 条连线只在测试路径（结构命中 + 假 yes 后端）里出现；演示产物实测 with-paper offline
  两子图 0 条、fallback-yellow h.0=4 / h.1=0。第 7 条已按此如实口径重写，其余条目结论不变。
