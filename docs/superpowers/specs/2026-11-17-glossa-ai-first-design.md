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
- 真实 key 的接入方式（`GLOSSA_LLM_BACKEND=openai` + `GLOSSA_LLM_BASE_URL/API_KEY/MODEL`）保持不变，用户自己填即可。