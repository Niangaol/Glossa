# 笺疏 M2 设计 v2：AI 写文字与图，程序给款式与抽线

日期：2026-11-17　状态：待年糕批准　作者：lead
（v2 按 m14616 重写：**CSS 不交给 AI**，AI 只写文字与图的连线；美术风格是几套预设、由用户选。）

## 0. 一句分工

> AI 决定「说什么、图里谁连谁」，程序决定「长什么样、线怎么画、页面怎么组装」。

- **程序给**：事实台账、页面外壳（目录/页头/页脚）、几套预设美术风格（用户选）、图表的渲染器与预设范式（形制）、四道闸。
- **AI 写**：每一段的文字；每张图的**结构**——选哪种图、放哪些节点、谁连到谁、连线上的字、分组与注释。
- **AI 不碰**：CSS、class、字体、颜色、间距、页面布局。提示词里**一句样式都不给**，避免它去猜版式。

## 1. 用户怎么选风格

```bash
python -m glossa explain --repo <仓库> --out <目录> --style magazine   # 默认
python -m glossa explain ... --style report      # 技术报告：紧凑、黑白灰 + 单强调色
python -m glossa explain ... --style cards       # 图鉴：卡片网格、徽章、大留白
python -m glossa explain ... --style list        # 只列出可用风格，不生成页面
```

- 风格 = 程序里的一套 CSS（`glossa/templates/styles/<name>.css`）+ 版式参数（字号阶梯、间距刻度、图例位置）。
- 同一份事实、同一份 AI 内容，换 `--style` 只换皮，**内容字节不变**（可测）。
- 风格页面上不显示「由 AI 选了 xx 风格」——风格是用户选的，页面徽章只写模型名。

## 2. AI 产出什么（协议）

AI 每段返回**严格 JSON**（不含 HTML，不含 CSS）：

```json
{
  "title": "谁依赖谁",
  "prose": [
    {"text": "全仓 485 个文件里，真正互相 import 的只有 8 个节点。", "cites": ["fact:graph"]},
    {"text": "入口 server.ts 被 2 个文件依赖，是这条链的起点。", "cites": ["fact:file:packages/a/src/server.ts"]}
  ],
  "figure": {
    "pattern": "layered",
    "caption": "依赖分层：从左到右是调用方向",
    "nodes": [
      {"id": "server", "label": "server.ts", "fact": "fact:file:packages/a/src/server.ts"},
      {"id": "circuit", "label": "circuit.ts", "fact": "fact:file:packages/a/src/circuit.ts"}
    ],
    "edges": [
      {"from": "server", "to": "circuit", "label": "import", "fact": "fact:import:packages/a/src/server.ts#./circuit.js"}
    ],
    "groups": [{"label": "@x/a", "members": ["server", "circuit"]}],
    "notes": ["circuit.ts 只被 server.ts 依赖"]
  },
  "notes": []
}
```

规则（程序强制，不是提示词里的建议）：

1. **每条连线必须有 `fact`**，且该 fact 的边（from/to）与 AI 给的 from/to 对得上；对不上**丢边**并计入「未溯源连线」。数字与边的口径一致：宁缺不编。
2. **每个 prose 的 `cites` 必须是真 fact id**；正文里出现的数字不在这些 fact 的 numbers 里 → 包黄标并计数（沿用 M1 的 `mark_untraced`）。
3. 节点必须指向 `doc.files` 里真实存在的路径（或用 `fact:pkg:*` / `fact:project:*`）。
4. 段数、段序：程序给七段骨架与每段目标（AI 可改标题文字，段数不变）。第七段「甜头」没有事实时不出现。

## 3. 图表范式（系统给的「预设」）

`glossa/templates/patterns/`（随包发布），每种一个 JSON 示例 + 允许字段列表，作为 few-shot 塞进提示词（每种 ≤600 字）：

| 范式 | 干什么 | 关键字段 |
|---|---|---|
| `layered` | 分层/拓扑图：模块上下层级与依赖方向 | nodes / edges / groups |
| `flow` | 调用链时序：从入口到出口逐步 | nodes / edges（带 step 序号） |
| `matrix` | 依赖矩阵：谁依赖谁一眼看全部 | nodes / edges（grid 位置程序算） |
| `tree` | 目录/包含树：包 → 文件 | nodes（带 parent） |
| `bars` | 指标条：文件/符号/import 这类数字对比 | bars（label + fact + 值取 facts） |
| `cards` | 文件图鉴：每个关键文件一张卡 | cards（path + fact + 一行摘要） |

- **AI 只选范式 + 填内容**；坐标、箭头、颜色、图例、SVG 全由程序画（`glossa/explain/draw.py`，纯字符串拼 SVG，零依赖）。
- 程序不认识 AI 给的新范式名 → 该图**不画**，段里留一句「模型给的图类型 <x> 不认识，已省略」并记 note（不静默吞）。
- 节点超过上限（默认 60）→ 截断并在图注写明「另有 N 个节点未画」（沿用 M1 的诚实口径）。

## 4. 素材包（喂给 AI 的东西）

每段一个 pack（JSON，≤8KB）：

```json
{
  "section": {"index": 4, "title": "谁依赖谁", "goal": "讲清谁喂谁"},
  "facts": [{"id": "fact:graph", "text": "...", "numbers": [0,2,6,8], "edges": [{"from": "...", "to": "...", "kind": "internal"}]}],
  "patterns": [{"name": "layered", "fields": ["nodes","edges","groups"], "example": {...}}],
  "sources": [{"path": "packages/a/src/server.ts", "start": 1, "end": 40, "text": "..."}]
}
```

- `sources`：程序预置 ≤6 片段 / ≤8KB；AI 可带 `need_source`（≤3 条）追问一次。
- `facts[].edges` 直接给可用的边——AI 的任务是「挑与讲」，不是「重新发现」。
- **pack 里没有任何 CSS/class/字号**（§0 的纪律）。

## 5. 渲染与四道闸

程序拿到 AI 的 JSON 后：

1. **安全闸**：AI 不产 HTML，所以没有注入面；只有 `prose.text` 经 `markdown` 子集渲染（纯文本 + 强调 + 行内代码），标签由程序生成。
2. **溯源闸**：数字（黄标计数）+ 连线（丢边计数）两把尺子，都上页头徽章。
3. **体积闸**：整页 > `HTML_MAX_BYTES`（8MB）→ BuildError，写盘前抛（沿用）。
4. **诚实闸**：页头徽章「模型：<name>」或「本页未使用 AI（仅事实底稿）」；页脚固定披露四句由模板渲染，AI 碰不到。

## 6. 回退（没配 AI）

仍出程序版七块（确定性、可复算）+ 页头红条：「本页未使用 AI（仅事实底稿）……配置 `GLOSSA_LLM_BACKEND=openai` 后重跑」。

## 7. 不做什么

- AI 不写 CSS/HTML/class/坐标；不直接读文件系统；不重新发明事实。
- 不引外链、不加 JS、不联网取字体（离线单文件）。
- 不改事实层（repo.json / facts / schema）一个字节。

## 8. 验收

1. `--style report|magazine|cards` 三套都能出页，同一 doc 换风格：**内容区文本与图节点边集合逐字相同**，只有 CSS 与版式参数变。
2. 没配 AI → 事实版 + 红条；配错 → exit 4 + 原文。
3. 假后端固定 JSON → 页面逐字节可复现。
4. 编造的边被丢弃并计数；编造的数字被黄标；两者都能在页头看到数字。
5. 真仓（SafeTrace / PokemonData / 自举）各跑一遍，逐段读，交「读不懂清单」。
6. 旧 1111 条测试零回归；新增测试全用假后端，不联网。

## 9. 切片

- **A1 配置与回退**：`GLOSSA_*` 配置、后端选择、失败语义、红条（模板条件）。
- **A2 风格与范式**：3 套 CSS + 版式参数、`--style` 选择器、6 种图表范式定义与示例。
- **A3 协议与素材包**：pack 构造、prompt、严格 JSON 解析、need_source 追问一轮。
- **A4 渲染器与闸**：`draw.py`（6 种图 → SVG/HTML）、prose 渲染、边溯源、数字溯源、体积。
- **A5 外壳与组装**：七段骨架 + 目录/锚点/页头页脚 + 风格注入 + 并发请求按序组装。
- **A6 接线与验收**：CLI（`--style`）/MCP、文档、三仓演示、可读性清单、评审。

## 10. 风险

| 风险 | 对策 |
|---|---|
| AI 编连线 | 每条边必须带 fact 且与事实边对得上，否则丢弃并计数 |
| AI 写长文但没信息 | 段落目标 + 数字必须有出处 + 每段字数上限（程序校验超长截断并记 note） |
| 图太挤/太散 | 节点上限 60、程序布局、超限截断并披露 |
| 成本 | pack ≤8KB、追问至多一次、`--jobs` 并发 |
| 风格与内容耦合 | 三套风格只动 CSS 与版式参数，内容 JSON 与风格无关（验收 1 可测） |



## 12. 决策（2026-11-17，用户选择 B）

**A6 出页演示一律使用离线桩模型，不接真实 API、不需要 key、不联网。**

- 离线桩（`FakeLLM`）按真实协议的同一套 JSON 形状返回内容：plan 返回 3–5 节，每节返回 `{title, html, figures, notes}`，其中 figures 的节点与边**全部取自 pack 里给的事实边**。
- 目的：把「程序侧」的东西（分节、画图、四道闸、体积、目录、三套风格）全部验证到位；真实模型只是把同一份 JSON 写得更好看，不改变流水线。
- 约束：离线桩不许出现在生产路径上；它只能通过 `--llm fake` 或测试注入进入，且必须在页头标注「本页由离线桩生成，未调用真实模型」，防止把桩内容误当真实 AI 产出。
- 真实 key 的接入方式保持不变，用户自己填即可：`GLOSSA_LLM_BACKEND=openai` + `GLOSSA_OPENAI_BASE_URL` + `GLOSSA_OPENAI_API_KEY` + `GLOSSA_LLM`（前三项之外，模型名变量是 `GLOSSA_LLM`，没有 `GLOSSA_MODEL`；`PAPERTRACE_*` 同名变量是兜底，慢的推理模型可用 `GLOSSA_LLM_TIMEOUT` 调大超时）。
## 13. 裁决（A4 收尾，2026-11-17）

**R498（批准）**：六种图范式以仓内真源为准 —— layered / flow / matrix / tree / bars / cards。我在 A4 派发书里写的 layers / chain / radial 是记错的名字，不许为迁就派发书另造第二套名字。未知 pattern 抛 ValueError 并列出这六种。

**R499（统一体积口径）**：页面体积只有一个真源 —— papertrace.constants.HTML_MAX_BYTES（8,000,000）。glossa/explain/gates.py 的 MAX_PAGE_BYTES 改为从该常量取（不许另写 2,000,000），render/assemble 的超限判定一律读它。

**R500（已知局限，A2b 再修）**：patterns.validate_figure 目前只保留 pattern/caption/nodes/edges/groups，所以 bars 与 cards 的数据数组到不了画图器，只能退化成单列清单/两列卡片。A5 不许为了让条形图好看去改 patterns.py；等 A6 出页后再单独开 A2b 放行这两个字段（值必须来自 facts 的 numbers）。
## 14. 裁决（A6 收尾，2026-11-17）

**R501（必修）**：`pack_for_plan` 不许只取 `facts[:60]` —— 三仓实测都只有 3 节、0 张图，因为窗口里全是 `fact:file:*`，唯一带边的 `fact:graph` 永远进不来。改为按 prefix 分组、每组至少 1 条，再轮转补齐到 60 条或 8000 字节；`fact:graph` 进包时必须带 `edges` 并标 `has_edges`。理由：不给 AI 边，它就不可能画关系图，而「图里模块关系」正是用户最想要的那件事。

**R502（必修）**：每个 fact 的 `text` 里写出来的数字必须全部在 `numbers` 里（R398-M3 只钉了反方向）。`fact:totals` 文字里有 6/11/259/302 而未入 numbers，真模型照抄就会被溯源闸标 4 处假黄 —— 这是 facts 层的假事实，按尺子该判 Critical。修法：补 numbers，不许改文字迁就数字。

**R503（批准）**：MCP `render_explain` 的 required 从 `("repo","blocks")` 改为 `("repo",)`。理由：ai 模式根本没有 blocks；program 模式缺 blocks 仍走同一句 BuildError → isError，既有 32602 测试用的是 `analyze_repo`，不受影响。

**R504（A2b 排队，仍不修）**：`bars` / `cards` 数据数组尚未放行（见 R500）。等 A7 出页后单开一片，值与边一起过闸。

## 15. 裁决：图数据的出处（A10 收尾，2026-11-17）

**R515（必修）**：`gates.gate_labels` 只看 `fig["nodes"]`，而 bars/cards 图的 `nodes` 是空的 → R508 对这两种图**完全失效**，模型写一个 `label="fact:languages"` 的条形照样印上页。裁定：一张图的 label 源 = 节点 label + `bars[].label` + `cards[].label`，任一条查不到出处就整张图丢弃（披露里不回声模型原话）。核对口径：整串出现在本节素材原文里，**或它每个词都出现过**——只看整串会把「json 文件」这种由素材里两个词拼出来的正常名字全判死（素材原文是「json 78 个文件」），图就白丢了。

**R516（必修）**：柱状图的值会以文本形式印进 SVG，而数字溯源闸只扫 html、扫不到图数据 → 模型编一个 99999，页面上就多一个零出处的数字，页头还写着「未溯源 0 处」。裁定：新增 `gates.gate_values`，柱状值必须能在本节素材 `facts[].numbers` 里核上（复用 `_numeric` 的归一化，认 `29,856` / `50%` 这类写法）；编的那一条丢掉、其余照画并披露，一条都核不上就整张图丢弃。内容闸因此是五道：`gate_html → gate_numbers → gate_edges → gate_labels → gate_values`。

**错的代价**：不修时页面能通过当时全部测试、页头自称「未溯源 0 处」，却在 SVG 里印着模型编的名字和数字——这是这个设计里最不该发生的一类错误（静默的错误事实），比缺一段正文严重得多。

## 15. 裁决（AIFINAL 评审结案，2026-11-17）

评审报告 `.superpowers/sdd/2026-11-17-glossa/task-AIFINAL-review.md`（230 行）判 Changes required：Critical 1 / 高 3 / 中 6 / 低 5，14 条变异 9 红 5 绿。下面是逐条裁定与落点。

**R517（Critical，接真模型的唯一入口从来没通）**：`papertrace.llm.client.LLMBackend` 只有 `chat(prompt, *, system=None) -> ChatResult`，而 `ai_pipeline` 要的是 `complete(prompt, system) -> str`；离线桩恰好有 `complete`，所以 1000+ 条测试全绿，而用户按文档填好 key 跑 `--ai --llm openai` 必然 AttributeError。修法：`ai_pipeline.ChatAdapter` 把 `chat()` 包成 `complete()`（空文本 / 非字符串响亮 `BuildError`，绝不把空串当正文），`as_completer()` 对已实现 `complete` 的对象原样放行，`build_llm()` 统一走它。同时把超时做成可配：`llm_config.TIMEOUT_PAIR = ("GLOSSA_LLM_TIMEOUT", "PAPERTRACE_LLM_TIMEOUT")`，`timeout_seconds()` 读不到就用默认，写错值（非数字、非正数）响亮 `ValueError`，`backend()` 显式构造 `OpenAICompatBackend(timeout=...)`——StepPlan 的 step-5-preview 真跑一节要 35.9 秒，默认 60 秒太紧。

**R518（Critical，页头那个 0 只覆盖了一半通道）**：「未溯源 N 处」只数 `<main>` 里的黄标，可图注、卡片 `text`、连线标签、节标题、模型 `notes` 这五处由程序绘制或转义输出，数字既不标黄也不计数。修法：`gates.count_plain_numbers(texts, allowed)` 只记账不加标记（SVG 里塞 `<mark>` 非法、标题会被转义），计入同一个页头总数，并在本节追加一句「图注/卡片/连线标签/标题/说明里另有 N 处数字…已计入页头」。**只查模型写的文字**：程序自己的说明（素材包预算、边被裁了几条）是程序事实，不计入。

**R519（页头自相矛盾）**：桩跑出来的页头同时写「本页由模型分节撰写」和「本页由离线桩生成，未调用真实模型」。修法：`assemble.build_page(..., mode_text=None)` 允许覆盖徽章，`ai_pipeline.mode_text()` 对桩返回「本页由离线桩分节组装，未调用真实模型」、对真后端返回 `None` 交回默认那句。

**D2/D3（文档说假话）**：README 与 docs/glossa.md 的溯源闸行补上「图注/卡片/连线标签/标题/模型说明标不了黄标，只计数并计入同一总数（R518）」；设计文档 §12 的三个变量名原来全写错，改成 `GLOSSA_LLM_BACKEND` + `GLOSSA_OPENAI_BASE_URL` + `GLOSSA_OPENAI_API_KEY` + `GLOSSA_LLM`（没有 `GLOSSA_MODEL`）。

**D4（fact:graph 自相矛盾）**：截断时原文写「120 个节点…其中 233 个因截断未画」，两个数字互相打架。改成「画出 120 个节点…另有 233 个节点被截断、没有画进图（截断只计数，清单不在页面上）」。

**D8（说明把包撑爆）**：一节的源文件大面积读不到时，每失败一条加一条说明，实测 486 条 / 42,756 字节，把 8000 字节预算吃光、facts 被 trim 到 0——模型什么都看不到。修法：`pack.MAX_NOTES = 8`，第 9 条起折成一句「另有 N 条跳过说明已略（只附前 8 条）」；缺 fact id 的名单也截到 12 个 + 「等 N 个」。说明照样计入包体积，但不再可能把 facts 挤空。

**D10（清单不全不披露）**：桩的原文片段清单只列包里那几段，页面上读起来像全部。桩的正文补一句「上面这段清单只列本节素材包里真有的原文片段，台账里其它文件没有搬进来」。这句里不许写数字——写了就会被溯源闸标成未溯源（实测把一条程序说明标成 5 处假黄）。

**错的代价**：R517 让「配好 key 跑 AI 讲解」这条唯一被用户期待的路在真模型上直接崩（而所有测试都是绿的）；R518 让页头那个数字变成半个谎；D8 让模型在最坏情况下拿到 0 条事实却照常出页。三条都属于「看起来成功、其实没发生」，按尺子都该在合并前修掉。

## 16. 裁决（第一次真跑 StepPlan，2026-11-17）

配置到位后（key 在 `~/.dsh/.credentials.yaml` 的 `refs.STEP_PLAN_API_KEY`，端点 `https://api.stepfun.com/step_plan/v1`，模型 `step-5-preview` / `step-3.7-flash`），第一次真跑 `--ai --llm openai` 暴露三件事，都有对应裁决。

**R520（推理模型必须给 token 上限）**：StepPlan 的 `step-5-preview` / `step-3.7-flash` 都是推理模型，`max_tokens=2000` 时 `content` 是空的、`finish_reason=length`——2000 个 token 全花在 `reasoning_content`（实测 4560 / 4666 字符）上。不设上限时服务端默认更慢，第一次真跑在 300 秒超时后 exit 4。修法：`papertrace.llm.openai_backend` 认 `PAPERTRACE_LLM_MAX_TOKENS`（显式入参优先），只在配置过时才把这个键写进请求体（默认请求形状一个字节都没变）；glossa 侧用 `GLOSSA_LLM_MAX_TOKENS`（`llm_config.MAX_TOKENS_PAIR`），写错值响亮 `ValueError`。实测 8000 时两个模型都在 16–21 秒稳定返回正文。

**R521（一张图不合规不许连坐整节正文）**：真模型给的 `figures` 里常常缺 `pattern`（或写成别的键），`patterns.validate_figure` 抛 `ValueError` 后整节被判「生成失败」——第一次真跑 5 节全灭，页头写「失败 5 节」，页面除了失败说明一个字都没有。修法：每张图的 `gate_edges → gate_labels → gate_values` 包在 `try/except (BuildError, ValueError)` 里，坏的那张整张丢弃并记一句「第 N 节的一张图被丢弃（原因）」，正文照常上页。SYSTEM 里补第 8 条把图的形状写死：`{"pattern":..., "caption":..., "nodes":[{"id","label"}], "edges":[{"from","to","label"}]}`，并明说「没有图就写 figures: []」。

**R522（JSON 坏了给一次补救机会，只给一次）**：真模型的一节返回被截断（`Unterminated string`），`parse_section` 直接判死。修法：`_ask_section` 只对「不是合法 JSON」这一类错误重试一次，提示词追加一句「上一轮不是合法 JSON（可能被截断），请只输出一个完整 JSON 对象」；第二次还坏就按原文披露这一节失败。

**R523（全部失败不写半张页）**：5 节全失败时 exit 0 并写出只有失败说明的页面，等于交了一份没用的东西还报成功。修法：`run_ai` 在 `failed == len(sections)` 时抛 `BuildError`（exit 2，不写盘）；部分失败照旧上页并在页头写「失败 M 节」。

**实跑结果（真模型，2026-11-17）**：ts-monorepo 夹具 → 4 节 / 6 张图 / 0 未溯源 / 0 失败 / 26,041 字节 / `<script>` 0 / 除 SVG 命名空间外零 http；正文里的数字（13 文件、10 符号、9 条 import、6 条边、2 层）全部来自台账，模型自己写的那节把 `packages/a`、`@x/b`、`serve/check/test` 讲成了人话。

## §17 R525–R526（真跑 SafeTrace 暴露的两条）

**R525（token 预算按真仓库定，别按夹具定）**：`GLOSSA_LLM_MAX_TOKENS=8000` 在 ts-monorepo 夹具上够用，在 SafeTrace 上不够——每节素材更大、思维链更长，两个模型都出现过 `content` 为空、`finish_reason=length`，`ChatAdapter` 重试一次仍空，于是 exit 4。实测同一提示：16000 token 时 step-3.7-flash 21.4 秒 / step-5-preview 10.6 秒，`finish_reason=stop` 且正文完整。裁定：文档与 README 的推荐值改成 16000；`ChatAdapter` 两次空回时的错误信息必须点名 `GLOSSA_LLM_MAX_TOKENS`（不许只说「空文本」），用户才知道该拧哪个旋钮。

**R526（提交哈希不是数字）**：真跑页头报「未溯源 11 处」，逐条看全是同一个 commit `9ca2b4f9a17f3cf190f3b604c1dff779198c25a4` 被数字正则撕成 9 / 2 / 4 / 9 / 190 / 604 / 779198 … 一串假黄标。裁定：`glossa/explain/guard.py` 的 `_NUM` 前后加 `(?<![0-9A-Za-z])` / `(?![0-9A-Za-z])`——紧贴 ASCII 字母或数字的连续数字（提交哈希、`0x1F`、`x86`）不是「数字」，不许标也不许计数；紧贴汉字的数字照旧（「共 13 个文件」）。修后同一仓库重跑：**未溯源 2 处**（都是模型在程序绘制处写的数字，页面如实计入页头），黄标 0 处、7 图、5 节、35,479 字节。
