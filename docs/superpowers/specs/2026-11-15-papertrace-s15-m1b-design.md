# PaperTrace 下一切片设计：S15 候选回退 + M1b 真实行号 + parked 文档修

> 状态：**已批（2026-11-15）**：用户拍板 R112 = 锁黄线、R115 = 授权改写 R37 守门测试（必须是加强）、下一步 = 先写实施计划再并行施工；m06557 三项（kind→op 过滤 + 词法只排序 / 每项最多 3 个 / 三块并行）继续有效。实施计划：docs/superpowers/plans/2026-11-15-papertrace-s15-m1b.md。用户已在 m06557 拍板三项：S15 用 kind→op 过滤 + 词法只排序；每项最多 3 个候选；本切片三块并行。
> 基线：master = e2feca6（脊柱切片 S1–S11 已合并，719 passed）。
> 本文档的每个数字都是控制器或 builder-check 在 e2feca6 上真跑出来的，探针在 output/controller-probes/ 与 output/builder-check/。
> v2 变更：独立设计审查（.superpowers/sdd/2026-11-15-papertrace-s15-m1b/builder-check.md）报了 6 条必须补 + 10 条建议补，全部已处理，见 §7。**其中 M1 需要你额外点头一次**（§0.2）。

## 0. 需要你点头的两件事（其余都是已批事项的实现细节）

### 0.1 绿线张力（拟 R112）

**S15 会不会让「结构没命中」的项混上绿线？** 实测（真实 confidence()/tier()，builder-check 独立复算吻合）：

| 场景 | s_retr | s_judge | s_struct | c | tier |
|---|---|---|---|---|---|
| 结构不命中 + 无 judge（现状） | 0 | 0 | 0.6 | 0.179 | none |
| 结构不命中 + judge 全 yes（S15 后，offline/DeepSeek） | 0 | 1 | 0.6 | 0.618 | **yellow** |
| **结构不命中 + judge 全 yes + 检索也满分** | 1 | 1 | 0.6 | **0.843** | **green** ⚠️ |
| 同上但把 s_struct 压到 0.49 | 1 | 1 | 0.49 | 0.831 | **green** ⚠️ |

最后一行说明**没有更简单的等价做法**：绿线门是 s_struct≥0.5，而「结构不命中」时 s_struct 仍是 0.5（基础分）或 0.6（+config 加成），门拦不住；把基础分压到 0.49 也照样绿。只要后端有 embeddings（DeepSeek 没有，OpenAI 正版/ollama 有），S15 就能在结构同构失败时连出绿线。

**我的建议（拟 R112）：回退候选产出的 anchor，tier 上限锁 yellow。** 理由：绿线门（U1/S1）是用户可见承诺「绿＝结构对上了」，结构没对上就该说黄线＋人工复核，与全项目「宁可报对不上也绝不编造对齐」同一把尺子。
**只封 tier，不动 signals / confidence**（R69 要求同一份 signals 既喂 confidence() 又写进 anchor.signals，顺手改 s_struct 会破坏它）。降级原因拼进 evidence，用户看得见为什么被压成黄。
**错了的代价**：将来接了带 embeddings 的后端，本来能绿的项被压成黄，用户多点一次人工复核。
**备选（如果你要绿）**：不锁，接受上表第三行，并在 README 写明「绿线不再保证结构同构命中」。我不推荐，因为它悄悄改了 U1 的语义。

### 0.2 R37 的硬边界测试必须改写（拟 R115，builder-check M1 挖出来的）

**tests/test_spine_end_to_end.py:383-416 有一条测试，名字就叫 `test_no_structural_pairs_never_asks_judge_even_with_embeddings`**，docstring 原文：「R37 的硬边界：pairs 空 → 一个 judge 都不问，哪怕检索有候选、哪怕问了就能绿」。它断言 anchors==[]、backend.calls==0、4 条 unresolved。

**S15 与它直接冲突，不能同时为真。** builder-check 把 S15 回退接进真实 attach_paper 实测：anchors=4、backend.calls=4、unresolved=0、4 条全 green（conf=0.8429）。

这不是 bug，是**你批准的语义反转**：R37 当初禁止非结构候选，S15 就是要放开它。但「改写既有测试」必须你点头，不能由实现者现场决定是削弱测试还是改设计。

**我的建议（拟 R115）：按 D1 授权改写这一条，且必须是加强不是削弱。** 具体：
- 改名为 `test_structural_miss_falls_back_to_kind_candidates_but_never_green`（名字如实描述新语义）。
- **保留 R37 防的那个具体攻击**：注入「检索满分 + judge 全 yes」，断言 tier **必须是 yellow 不是 green**（这正是 R112 的守门测试，比原来的 anchors==[] 更强——原来只测「不出线」，现在测「出线但绝不绿」）。
- 断言候选来自 **kind→op 映射**而不是 embedding top1（把 embedding 后端换成返回乱序向量的假后端，候选集不变）。
- 另立一条 offline 用例：结构不命中 + offline → 仍 anchors==[]、backend.calls==0（诚实空态不变）。
- 原测试的其余断言（unresolved 的 ref 列表、reason 含 s_struct）迁到 offline 那条里，一条不丢。

**错了的代价**：如果 R112 实现有漏洞，这条改写后的测试是唯一的守门人；写弱了就等于把绿线承诺悄悄放弃。所以验收里明确要求「注入满分检索 + 全 yes 必须 yellow」这一条断言存在且能红。
**备选（如果你要保 R37 字面）**：不做 S15 回退，judge 永远只吃结构 pairs。那你 m06557 批准的「judge 在结构不命中时也能工作」就落空了。

## 1. 三块工作与实测依据

### 1.1 M1b：真实 file:line（比预想便宜——桩早就预留好了）

papertrace/parse_code/loc.py 是个 7 行桩，docstring 原文「把 stack_trace 变成人读的 file:line，供右栏代码视图定位」，签名 `loc_from_stack_trace(stack_trace: str) -> str` 已冻结。**当初接口设计对了，只是没填。**

实测（output/controller-probes/m1b_feasibility2.py、m1b_s15_probe.py）：

- 75 个 call_function 节点，**75 个都带 meta['stack_trace']**，0 个洞。meta key census：nn_module_stack 75 / stack_trace 75 / torch_fn 75 / val 75 / tensor_meta 73；source_fn_stack 全为 None（不可用）。
- stack_trace 是真实源码行，例：`File "D:\...\tests\fixtures\nanogpt\model.py", line 142, in forward` + 源码行。
- 多帧时**第一帧就是用户代码**，后续帧是 torch 内部（pydeps/torch/nn/modules/sparse.py:189 等）。实测「第一帧是 torch 但后续帧是用户」的节点 = **0**。
- 命中 **7 个不同源码行**，直方图 {142:1, 143:1, 144:1, 145:2, **147:68**, 148:1, 149:1}。

**关键局限：68 个算子挤在 model.py:147 同一行。** 行号能定位「哪一行」，不能区分「行内哪个算子」。所以 code_expr_range 仍用节点 id（见 §3 R113）。

**唯一改动点**：papertrace/parse_code/fx_nodes.py:169 的 `"loc": root_loc`（全仓只有这一处给 op 节点写 loc）。改成先试 loc_from_stack_trace(n.meta.get("stack_trace"))，拿不到就回落 root_loc（fail-closed，绝不编行号）。

**没有测试钉住 loc 的值**（grep loc 等值断言 = 0 处；builder-check N2/N5 独立复核：产品调用方仅 fx_trace.py:149-152，6 个测试调用方全传 root_loc="root" 且无 loc 值断言，judge prompt 测试用合成 _SNIPPET）→ **M1b 本身不需要改写任何既有测试**。

**loc 存绝对路径（拟 R116，builder-check S5）**：实测 loc 会是 `D:\AgentPrograms\PaperTrace\tests\fixtures\nanogpt\model.py:147`。后果：trace.json 立即机器相关、分享 HTML 会带本地目录。**本切片不改**，理由：相对化要把 repo 根穿过 fx_nodes → fx_trace → loc 三处签名并波及 6 个测试调用方，超出「填一个桩」的范围；而绝对路径是**诚实的**（它确实是那个文件），不是编造。
**呈现层解决**：波次2 的 HTML 只显示 `basename:line`，完整路径放 title 属性（悬停才见）。**trace.json 的相对化归 M4**，写进已知局限。
**另注**：模块节点的 loc 仍是 'model.GPT'（fx_modules.py:49/:53/:72），**同一字段两种语义**——op 节点是 file:line、module 节点是模块路径。这是既有设计（module 节点本来就没有单一源码行），写进 docstring 与 README，不许为了「统一」去编模块行号。

### 1.2 S15：纯词法实测不行，kind→op 行

用户原话批准的是「词法候选生成器」。我用 difflib.SequenceMatcher + token 重叠实测（output/controller-probes/s15_decide.py），把每个公式项的 LaTeX 与 75 个算子的 label/op 名算相似度，看真值排第几：

| 公式项 | kind | 词法 top1 配到 | 真值排名（共75） |
|---|---|---|---|
| QK^{T} | matmul | eq ❌ | 7 |
| \sqrt{d_k} | scale | add ❌ | 50 |
| \mathrm{softmax} | norm | softmax ✅ | 1 |
| V | matmul | view ❌ | 51 |

**4 项错 3 项。** 原因：LaTeX 符号名与 aten 算子名不在一个词汇表里，QK^{T} 与 matmul 零共同字符，V 与 view 反而共享 v。词法在这里是噪声。

改用 S5 已冻结的 KIND_TO_OPS（实测值）：
```
matmul→(matmul,)  scale→(mul,div)  norm→(softmax,)
act→(gelu,relu,sigmoid,tanh)  transpose→(transpose,)  concat→(cat,)
```
当候选过滤器：**4/4 项的真值全部落在候选集里**。

**候选数与 judge 调用数（builder-check M4 澄清，三个数不要混）**：
- **资格候选 12 个**：term0→4、term1→2、term2→2、term3→4（全配对是 4×75=300）。
- **每项截到 3 之后 10 个**：3/2/2/3。
- **judge 最坏调用 10 次**（builder-check 用 no 后端实测就是 10）；**12 是 4项×3 的理论上界**，本夹具到不了。
- 首个 yes 即早退，所以实际通常远少于 10。

**所以 S15 = kind→op 决定「谁有资格」，词法只决定「先问谁」。** 词法没有一票否决权，只影响顺序（进而影响早退与调用数）。

### 1.3 parked 文档修（R110 遗留，零行为风险）

- papertrace/parse_paper/units.py:11-12 docstring 写「逐字环境与行内逐字段两个视图均挖空」，与实现相反（R109：code 视图保留原文、只挖 comment 视图），且同句括号里又写「代码字符虽未置空」——**同一句自相矛盾**。
- **README.md:335-336 两句都要改**（builder-check M6）：:335「没有逐算子源码行号，编一个出来就是对账造假」M1b 后过期；:336「届时换成真实 file:line」在 R113 撤回后也过期——真实行号走 node["loc"]，code_expr_range 保持 node_id。
- .superpowers/sdd/2026-11-14-papertrace-spine/final-fix-report.md §8「code_table 净 0 行」与实测 +13 不符（报告卫生）。
- OBS-1：.4f 之外再比原值（观察级，本切片只做记录不改代码）。

## 2. 并行波次与写作用域（R111 的落地）

用户明确要效率。三块写作用域**实测不重叠**：

| 波次 | 子智能体 | 独占写作用域 | 显式禁改 |
|---|---|---|---|
| 1A | s15-implementer | papertrace/align/candidates.py（新）、papertrace/align/struct_signal.py（**只改 docstring :27-28 与 :31-32**）、tests/test_spine_candidates.py（新）、tests/test_spine_struct.py（**只改 :16 docstring**） | spine.py、cli.py、constants.py、schema/、parse_code/、parse_paper/、judge.py、retrieve.py、embed.py、score.py、tier.py、prompts.py、client.py、test_imports.py、test_spine_end_to_end.py |
| 1B | m1b-implementer | papertrace/parse_code/loc.py（填桩）、papertrace/parse_code/fx_nodes.py（**只改 :169 一处 + 必要 import**）、tests/test_m1b_loc.py（新） | align/、spine.py、cli.py、constants.py、schema/、parse_paper/、fx_trace.py、fx_graph.py、fx_edges.py、fx_modules.py、fx_signature.py、test_imports.py |
| 1C | docs-implementer | papertrace/parse_paper/units.py（**只改 docstring**）、README.md、.superpowers/sdd/.../final-fix-report.md | 任何 .py 的行为代码、align/、parse_code/、spine.py、cli.py、schema/ |
| 2 | **控制器独占** | papertrace/spine.py、**papertrace/spine_fallback.py（新 helper，见 §3 M5）**、papertrace/render_html.py、papertrace/templates/spine.html.j2、tests/test_imports.py、tests/test_spine_end_to_end.py、tests/test_spine_html.py、**tests/test_spine_fallback.py（新）**、constants.py（若需）、schema/（若需） | — |
| 3 | 三个只读评审 fan-out | 无写权限 | 全部 |
| 4 | 一个 fix subagent + 恰好一次定向复审 | 按 findings | — |

**为什么集成必须串行独占**：papertrace/spine.py 同时消费 S15 的候选与 M1b 的 loc（_node_text 在 :184 把 loc 拼进喂给 judge/检索的文本）。两个 implementer 都改它必然互相覆盖。tests/test_imports.py 的 MODULES 列表（:19-56）要加 candidates.py 与 spine_fallback.py，也是共享文件。

**跨波次语义交互（不是写冲突，但必须知道）**：M1b 把 loc 从 'model.GPT' 换成真实 file:line → spine.py:184 的 _node_text 变了 → **喂给 judge 与检索的文本变了**。offline 下无影响（judge 恒归零）。波次2 必须真跑四输入确认。

**测试分层（builder-check S8，免得波次1 被当成没干活）**：
- **波次1A 的验收只到函数级**：candidate_pairs 的资格/排序/截断/空态/未知 kind，全部用手工 nodes 与 terms，**不碰 attach_paper、不碰 HTML**。
- **「回退候选进 anchor + R112 封顶 + HTML 看得见」全部归波次2**，因为 spine.py / render_html.py 不在 1A 的写作用域里。
- 所以 §6 的验收分两段：波次1 结束时只要求函数级测试 + 全量不回归；S15 的端到端收益在波次2 结束时才验收。

**import 守卫窗口（builder-check S9）**：candidates.py 在波次1 落盘，但 test_imports.py 的 MODULES 到波次2 才加。**这个窗口期可接受**——该测试遍历硬编码列表而非自动发现，窗口期内只是「新模块还没被守卫覆盖」，不会红。波次2 必须补齐两个新模块。

**每波结束控制器核对**：git diff --stat 列出实际触碰文件，与上表逐项比对；越界即回滚该文件并重派。

## 3. 接口契约（波次2 集成时消费）

### S15
```python
# papertrace/align/candidates.py（新，≤200 行，零新依赖：只用 re）
class Candidates(NamedTuple):
    pairs: list[tuple[int, str]]   # (term.index, node_id)，与 StructSignal.pairs 同形
    hits: list[str]                # 中文短句
    misses: list[str]              # 中文短句

def candidate_pairs(terms: list, nodes: list[dict], *,
                    per_term_limit: int = 3, total_limit: int = 12) -> Candidates
def lexical_rank(text: str, node: dict) -> float   # 只排序，不过滤
```
- 只取 level=='op' 且 kind=='op' 的节点（与 S5/R25a 同口径，排除 18 权重 + 1 输入的 placeholder）。
- 候选资格 = `node['op'] in KIND_TO_OPS.get(term.kind, ())`；**直接 import S5 的 KIND_TO_OPS，不许抄一份**（抄一份就会漂移）。**用 .get 不用下标**（builder-check S4）：未知 kind → 空候选 + 一条 miss，绝不 KeyError。另加一条测试钉 `split_terms.KINDS` 的每个 kind 都在 KIND_TO_OPS 里（两个名单今天一一对应但无人看守）。
- **lexical_rank 的确定性定义（builder-check S1，两个实现者必须产出同一份 trace.json）**：
  ```
  tokens(s) = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", s.lower()))
  a = tokens(term.latex);  b = tokens(f"{node['op']} {node['label']}")
  score = len(a & b) / max(len(a), len(b))   # 任一侧为空 → 0.0
  ```
  排序 = score 降序，**同分按 node id 升序**。实测效果：\mathrm{softmax} 与 softmax 算子共享 token → 0.5 排第一；QK^{T} 与 matmul 零共享 → 全 0 分 → 按 id 升序（确定性，不靠运气）。
- **hits / misses 语义（builder-check S2）**：都是给人看的中文短句。**hits** 每个有候选的 term 一条，写明「term N（kind=X）有 K 个资格候选，算子名 …」；**misses** 写零候选的 term（未知 kind / 没有该算子）与被截断的 term。**spine 不消费 hits/misses，只消费 pairs**（实测 spine.py:120 只用 signal.score）——它们供测试、调试与将来 evidence 展示。附带修 struct_signal.py:29-30 的 R38 措辞：「会作为 evidence 展示在 HTML」对 StructSignal 本身已过期，改成如实描述。
- **截断粒度（builder-check S3）**：每项最多 per_term_limit 个；全部项合计最多 total_limit 个，按 term.index 升序分配预算。**超预算时每个被截断的 term 记一条 miss**（不是每个被砍候选记一条），写明「term N 有 K 个资格候选，按上限截断，丢弃 K−3 个」。黄金夹具 10≤12 走不到 total_limit 这条路径，**必须用手工构造的超预算输入测它**，否则永不被纠正。
- terms 为空 / nodes 为空 / 没有 kind 命中 → pairs==[]，misses 写清原因，**绝不瞎凑**。
- **不做跨 term 唯一性约束（builder-check S7）**：term0（QK^{T}）与 term3（V）都是 matmul kind，候选集相同是**正确行为**——两个公式项都对应矩乘算子，具体是哪个由 judge 判定。若 judge 对两者都 yes 到同一节点，两个 anchor 指向同一节点是诚实的（同一算子服务两个公式项）。写进 docstring。
- 不联网、不调 LLM、不 import torch。

### M1b
```python
# papertrace/parse_code/loc.py（填桩，签名不变）
def loc_from_stack_trace(stack_trace: str) -> str
```
- 解析 `File "<path>", line <N>, in <func>` 帧，返回**第一个属于用户仓库的帧**的 "<path>:<N>"（绝对路径，见 §1.1 R116）。
- 排除库帧的判据（冻结黑名单，零依赖）：路径含 site-packages / pydeps / \\torch\\ / /torch/。
- 空串 / None / 无帧 / 全是库帧 → 返回 ""（空串），由调用方回落 root_loc。**绝不编行号、绝不返回猜测值。**
- 不 import torch（meta 是 dict，不需要 torch）。
- **已知局限写进 docstring（builder-check S10）**：黑名单是**路径子串**判定而不是「仓库外」判定——用户仓库路径本身若含 torch / site-packages 字样会被误杀 → 全帧被排除 → 回落 root_loc。这是**诚实降级**（宁可没有行号也不给错行号），可接受，但必须写明。

### code_expr_range：**不改格式**（R113 已被控制器自己的预检推翻）

我原本提议把 code_expr_range 改成 `<file>:<line>#<node_id>`。**预检实测证明这个提议会静默砸掉 HTML 的彩线，撤回。**

证据（output/controller-probes/r113_html_check.py，真跑 render_html）：
- papertrace/render_html.py:82 把 `code_expr_range` **当节点 id 用**：`style_of[code_id] = ...`，:95-100 再用 `node["id"]` 去查 `style_of`。
- 格式里只要多出 `file:line#` 前缀，**没有任何节点 id 能匹配上** → 所有 anchor 的彩线全部消失，而 trace.json 看起来完全正常。这正是本项目尺子最重的那一档「静默错误事实」。
- tests/test_spine_end_to_end.py:288 明写 `assert ":" not in anchor["code_expr_range"]`，:285/:290 钉死纯 node_id 格式，测试名就叫 `test_code_expr_range_uses_node_ids_not_source_lines`，是 R68 的守门测试。builder-check N3 独立复核：schema:226 是 {"type":"string"} 无 pattern，守门仍成立。

**R113（修正版）：code_expr_range 保持 R68 的纯 node_id 格式，一个字不改。** 真实行号走 **node["loc"]**（M1b），HTML 在算子行里显示 loc。schema 不动、R68 守门测试不动。
**错了的代价**：行号与 anchor 分处两个字段，用户要看「这条线对应哪一行」得在算子行里找。可接受。

### R114 撤回原修法，改为「回退 anchor 只指认被确认的那一个节点」（builder-check M2/M3）

**我原来的修法是错的。** 原提议：render_html 把 code_expr_range 按 `..` 拆开，对区间内每个真实节点 id 都画线。builder-check 实测推翻：
- S15 回退时 spine.py:136 会产出 `root/@037..root/@071`（候选首尾），而**该区间含 35 个真实节点 id，实际候审只有 3 个**。
- 照原修法会画 **35 条线谎称对齐 35 个算子**——比「不画线」更严重，是诚实性倒退（尺子最重档）。

**新修法（拟 R117）：回退路径的 anchor 只指认 judge 真的说了 yes 的那一个节点。**
- `_judge_pairs` 改成返回 `(score, evidence, confirmed_node_id)`（现在只返回前两个，spine.py:170-179）。
- **回退路径**：code_expr_range = confirmed_node_id（单节点）→ HTML 天然画得出线（单节点路径实测 lnk-green=1 ✅），**不需要改 render_html**，M3 的「波次1 用户零感知」也随之消失。
- **结构路径完全不动**：仍用 first..last，既有测试 :285/`:290` 保持绿。
- 其余候审但没被确认的候选进 `alternatives`（schema 已有，maxItems 2），用户看得见「还考虑过谁」。
- **R112 封顶**在这条路径上生效：level == "green" → "yellow"，降级原因拼进 evidence。

**既有的多节点结构 anchor 彩线缺失（S10 就存在的静默省略）本切片不修，deferred 到 M4。** 正确修法已想清：给 anchor 加一个可选 `code_node_ids: list[str]` 精确列出真正对上的节点，render_html 优先用它、回落拆 range。**不能靠拆 range 猜**，因为区间里的节点大多数根本没被对齐。
**错了的代价**：M4 之前，一项对多个算子的结构 anchor 在 HTML 上仍看不见线（trace.json 里是对的）。这是既有缺陷不是本切片引入的，且本切片的回退路径不受影响。

### M5：spine.py 装不下，helper 去处已指定（builder-check M5）

spine.py **198/200，只剩 2 行**。最小增量 4-6 行（import + 回退触发 + R112 封顶 + _judge_pairs 三元组）→ 202-204，**必然超线**。

**指定去处：新建 `papertrace/spine_fallback.py`（波次2 控制器独占）**，承载：
- `pairs_or_fallback(signal, terms, nodes, *, per_term_limit, total_limit)` → `(grouped, fallback_flag)`：pairs 非空就直接用；空则调 candidates.candidate_pairs 并按 term.index 分组。**把 spine.py 现有的分组块整段搬过来**，spine.py 净增行数因此可能为负。
- `resolve_code_range(node_ids, confirmed_id, fallback)` → str：回退且有 confirmed → 单节点；否则既有 first..last 逻辑。
- `cap_tier(level, fallback)` → str：R112 封顶，**只改 tier 不改 signals**。
- 三个函数各带 docstring 写明裁决编号与「错了的代价」。

**配套义务**：≤200 行；进 tests/test_imports.py 的 MODULES；新建 tests/test_spine_fallback.py 覆盖三个函数（含「回退 + 满分检索 + 全 yes → yellow」这条 R112 守门断言）。**这些都在波次2 scope 里，不是排期外工作。**

### HTML 显示 loc（波次2，配合 M1b）
papertrace/render_html.py:50-54 的 _node_label 现在只返回 op 名，**全页没有任何源码位置**（探针实测 "model.py" in html == False）。M1b 之后 node["loc"] 是真实 file:line，波次2 在算子行补显示 **basename:line**，完整路径放 title 属性（R116 的呈现层处理）。
**约束**：不许 import report（report 顶层 import build_trace 会把 torch 拖进纯渲染器）；autoescape 与 StrictUndefined 纪律不变（兜底一律 `| default(x, true)`，不用 `or`）；零外链不变；HTML_MAX_BYTES=8_000_000 实测当前 31934 字节，无风险（builder-check N6）。

## 4. Global Constraints（沿用脊柱切片，逐字有效）

1. 单文件 ≤200 行，口径 `len(pathlib.Path(f).read_text(encoding='utf-8').splitlines())`（Get-Content .Count 少算）。**当前贴线文件**：code_table.py 200、latex_safe.py 200、openai_backend.py 199、spine.py 198、split_terms.py 196、cli.py 193。spine.py 的去处已指定为 spine_fallback.py（§3 M5），**不许硬塞、不许现场发明别的文件**。
2. 禁 mock 填产品输出；测试注入的假后端必须**单实例跨调用保持状态**，且**必须断言被测路径真被走到**（计数器 +1）。
3. 默认 offline；judge 禁自由生成；JUDGE_PROMPT / DRILL_PROMPT 正文一字不许改（sha256 钉扎已在 tests/test_spine_judge.py）。
4. 公式写死：c = sigmoid(4·(0.30·s_retr + 0.50·s_judge + 0.20·s_struct − 0.5))；绿线 0.75 + s_struct≥0.5 门；黄线 0.45。**R112 只封 tier，绝不改 signals/confidence/s_struct**（R69）。
5. **GC8：不带 --paper 时逐项不变** nodes=128（module34/param18/input1/op75）、edges=101、counts{operators75, degraded2, fused0, orphan0, shape_broken0, shape_unchecked0}。builder-check N4 已实测七项全中、且无测试比对 trace.json 字节。**M1b 改 loc 不在冻结项里，但必须真跑核对这七项一个不动。**
6. 零新依赖（GC13）：禁 numpy / requests / antlr4 / lark；禁 sympy.parsing.latex.parse_latex。可用：标准库 + sympy / jinja2 / jsonschema / torch 2.15.0+cpu。
7. 测试环境：PYTHONPATH 含仓库根 + pydeps；不用 pytest tmp_path，用 tests/_tmp.py::scratch_dir。跑 torch.export 前必须先 `_ensure_export_cache()`（否则 dynamo 在缓存目录上炸）。
8. 每 Task 一次提交；变异探针还原锚点必须**先验唯一**；还原后 sha256 逐字节比对。
9. 只捕预期不可用（LLMUnavailable / IngestError），**禁裸 except Exception**（R56）。
10. 静默错误事实 > 静默省略 > 响亮崩溃。六次升级先例：R27/R36/R54/R76/R85/R96-98。**builder-check M2 就是按这把尺子否掉了我自己的 R114 原修法。**
11. 扫「有没有某种代码」必须按行或 AST，**不能对全文跑正则**（docstring 会冒充代码，控制器已犯 5 次）。
12. 探针必须打真产物，不要自己编简化版再指控（控制器已犯 16 次）。

## 5. 已知局限（本切片不解决，写进 README）

- 只对齐第一层 h.0.attn（逐层属 M4）。
- s_struct 上限 0.8（论文层数/形状/双向检索三条规则本切片不可判定，R23）。
- 68 个算子共享一行 → 行号不能区分行内算子（code_expr_range 用 node_id 补）。
- **loc 是绝对路径** → trace.json 机器相关；HTML 只显示 basename:line，相对化归 M4（R116）。
- **op 节点 loc 是 file:line，module 节点 loc 仍是模块路径**（同一字段两种语义，既有设计）。
- loc 黑名单是路径子串启发式，仓库路径含 torch/site-packages 字样会被误杀 → 回落 root_loc。
- 配 DeepSeek 永远出不了绿线（无 embeddings → s_retr 恒 0）。
- **回退候选的 anchor 永远出不了绿线**（R112，这是有意的）。
- S15 回退候选的 judge 以 kind 为前提，kind 标错则候选全错（kind 由 S3 拆项决定，已冻结）。
- **跨 term 候选可重复**：同一算子可被两个公式项认领（S7，诚实行为）。
- **多节点结构 anchor 的 HTML 彩线仍缺失**（既有缺陷，R114 正确修法归 M4）。
- 浏览器视觉目检没做（R94：不因此判未完成）。

## 6. 验收（分两段，builder-check S8）

### 波次1 结束（三块并行完成时）
- 全量测试全绿（基线 719 passed，只增不减）。**此时 R37 那条既有测试仍应绿**——因为回退还没接进 spine.py。
- 1A：candidate_pairs 函数级测试全绿（资格/排序确定性/截断/超预算/空态/未知 kind/KINDS 同步）。
- 1B：75/75 op 节点 loc 是真实 file:line，行号在文件范围内、该行非空；空串回落 root_loc 有用例。
- 1C：三处文档与代码行为一致（人工逐句核）。
- GC8 七项逐字不变；行数 census 所有产品 .py ≤200；三块写作用域无越界（git diff --stat 核对）。

### 波次2 结束（集成完成时）
- 全量测试全绿，**R37 那条按 R115 改写后仍绿且是加强**（必须含「满分检索 + 全 yes → yellow 不是 green」的断言，且该断言能被变异探针打红）。
- 四输入真跑全 EXIT=0：①无 --paper ②带 --paper ③--skeleton --paper ④纯 --skeleton。
- **S15 收益可复现**：构造结构不命中场景，offline 下仍 tier=none（诚实空态），注入 yes 后端后 tier=yellow，**且 HTML 上看得见那条黄线**（单节点 confirmed → lnk-yellow ≥1）。
- **M1b 收益可复现**：HTML 算子行显示 basename:line，title 里是完整路径。
- 两个新模块（candidates.py、spine_fallback.py）都进了 test_imports.py 的 MODULES。
- GC8 七项仍逐字不变；行数 census 仍全 ≤200。

## 7. builder-check 的 6 条必须补 + 10 条建议补：我的处理

独立设计审查（只读，探针落 output/builder-check/，报告 178 行）报了 6 条必须补、10 条建议补、8 条「已验证不是缺口」。**我全部认账，没有一条驳回。**

| # | 它说什么 | 我怎么处理 |
|---|---|---|
| M1 | R37 硬边界测试与 S15 直接冲突，设计全文未点名 | **新增 §0.2 拟 R115**，明确请求改写授权，且规定改写必须是加强（保留「绝不绿」断言）。这是 v2 唯一新增的需用户点头项 |
| M2 | R114 按 .. 展开会画 35 条线谎称对齐 35 个算子 | **撤回原修法**，改 R117：回退 anchor 只指认 judge 确认的那一个节点；既有结构多节点缺陷 deferred 到 M4 并写明正确修法（code_node_ids 精确列表） |
| M3 | S15 回退 anchor 多节点 → HTML 零显示，而修复在波次2 | R117 让回退 anchor 变成单节点 → **HTML 天然画得出，不需要改 render_html**；另加 §2 测试分层与 §6 两段验收 |
| M4 | 候选总数 12 与 per_term_limit=3 自相矛盾 | §1.2 拆成三个数：资格 12 / 截断后 10 / judge 最坏 10（理论上界 12） |
| M5 | spine.py 装不下且 helper 去处未指定 | §3 指定 **papertrace/spine_fallback.py**，三个函数名与职责写死，配套 MODULES 与新测试文件都列进波次2 scope |
| M6 | 两句文档变假且无主 | struct_signal.py 的授权范围扩到 **:27-28 与 :31-32**；README 扩到 **:335-336** |
| S1 | lexical_rank 算法未定义 | §3 给确定性最小定义（token 集合交集 / 两侧最大值，同分按 id 升序），并说明实测效果 |
| S2 | hits/misses 语义未定义 | §3 定义两者内容，明写 **spine 不消费**；附带修 struct_signal.py:29-30 的过期 R38 措辞 |
| S3 | 截断超预算时 misses 粒度 | §3 定为**每个被截断的 term 一条**，并要求用手工超预算输入测（黄金夹具走不到） |
| S4 | 未知 kind 兜底 | §3 改 `.get(kind, ())` + 一条 KINDS↔KIND_TO_OPS 同步测试 |
| S5 | loc 绝对路径后果 | §1.1 拟 R116：trace.json 存绝对（诚实、机器相关写进局限），**HTML 只显示 basename:line**，相对化归 M4；另写明 op/module 两种 loc 语义 |
| S6 | R112 只封 tier 不改 signals 的可解释性 | §0.1 与 GC4 都明写**不动 signals/confidence/s_struct**（R69） |
| S7 | 跨 term 候选重复认领 | §3 声明**不做唯一性约束**并说明为什么重复是诚实的 |
| S8 | 测试分层未拆 | §2 加测试分层段，§6 拆成波次1/波次2 两段验收 |
| S9 | 波次1→2 的 import 守卫窗口 | §2 明写窗口期可接受（硬编码列表非自动发现），波次2 必须补齐 |
| S10 | 黑名单是路径子串而非「仓库外」判定 | §3 要求写进 docstring 已知局限（诚实降级可接受） |

**它替我核实「不是缺口」的 8 条（N1–N8）我不动**：循环 import 不存在、fx_nodes:169 改动不影响其它调用方、R113 撤回后不破契约、GC8 七项实测全中、M1b 不红既有测试、HTML 体积无风险、≤200 规则存在、loc 空串回落契约成立。

**它没能验证的 8 条**（报告 §④，含未复跑全量 719、未跑 CLI 四输入、R114 修复效果未实跑、spine 行数增量为估算）→ 全部由波次2 的控制器真跑覆盖，已写进 §6。
