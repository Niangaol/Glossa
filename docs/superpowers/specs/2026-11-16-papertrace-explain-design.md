# PaperTrace 讲解页（explain.html）+ MCP 讲解 Agent 设计

日期：2026-11-16 · 分支：master · BASE：e5aaa2d（全量 854 passed）
状态：**待年糕批准**。批准后进入 writing-plans 写逐任务实施计划。

## 0. 一句话

程序出事实、模型写文字、程序管排版与图。新增一个**独立的纯讲解页 `explain.html`**，
原 `index.html` 一个字不改，继续当事实档案。讲解员通过**零依赖手写的 MCP server**拿事实、
交回「组件 + 文字」的讲解脚本，程序校验溯源后渲染成单文件离线 HTML。

## 1. 为什么要做（实测，不是感觉）

年糕 m12564：「读起来看不懂😵‍💫 …做代码仓库的解析和讲解为主，这部分做甜头吧」。
控制器把 `output/demo/code-only/index.html` 拆开量过（`read_bytes` 口径）：

| 事实 | 数字 |
|---|---|
| 整页 | 52,492 字节 / 50,167 字符 |
| ② 代码算子图一块 | 37,854 字符 = **全页 72%**，128 个节点平铺 |
| 全页人话叙述句数 | **0** |
| ③ 论文公式项 / ④ 未对齐 | 无论文时是空态，却排第 3、4 位 |
| ⑥ 代码体检（唯一有汇总价值的块） | 排在**最末尾** |
| 模块名 | 原始路径 `root/transformer.h.0.attn.c_proj`，不是人话 |
| 术语解释（tier/anchor/unresolved/shape tuple） | **0 条** |

结论：现在这页是**体检报告原始数据**，不是讲解。缺的正是「主线」那一层。

## 2. 已拍板的事（不再重开）

| 来源 | 决定 |
|---|---|
| m11636 / m12564 | 主线＝代码仓库解析与讲解；**论文降为「甜头」**，默认不参与 |
| m11668 / m11673 | 三层分工：程序出事实、AI 写文字、程序管排版与图；**先做 MCP server**，后续再应用化；通用 OpenAI 兼容接口；无 key 降级为纯事实叙述并明示 |
| m11687 | **废弃槽位化**：模型全向放大，程序只提供 fact 支持 |
| m11692 | 自由度＝**组件库 + 一个 custom 块写任意 HTML**；守卫＝**宽松**，查不到出处的数字打可见「未溯源」标记但**照常渲染** |
| m12564 | 形态 A（MCP server + 讲解技能包）+ 传输 A（**手写 stdio JSON-RPC，零依赖**） |
| m12582（本轮选择题） | **方案三：另做一个纯讲解页 `explain.html`**，原页保持事实档案 |

## 3. 本轮三个问题超时未答 → 我的默认裁决（可推翻）

控制器用提问工具问了三件事，600 秒未收到回答。按技能规矩不重复问、不当成许可，
改为**我的裁决**写在这里，年糕一句话就能改：

| # | 问题 | 我的默认 | 理由 | 推翻的代价 |
|---|---|---|---|---|
| D-A | 怎么触发讲解 | **两条都要**：MCP（我当讲解员）+ `papertrace explain` 命令 | MCP 质量最好；CLI 让这件事离开 DSH 也能跑、能重复 | 只要 MCP 可省 1 个任务；只要 CLI 可省技能包 |
| D-B | 讲给谁听 | **教学口吻**（给年糕自己读懂）：术语先解释再用、带类比、讲「为什么这么写」 | 他自评 vibe coding 入门、要细致讲解；门面版可以后加 | 改口吻只改 prompt 与降级模板，不动架构 |
| D-C | 讲解范围 | **只讲模型这条链**：入口 → 各模块 → 数据流 | 现有 128 节点 / 101 边 / 34 模块事实足够讲透；仓库文件树是另一片 | 加文件树要新增扫描与职责判定，范围翻倍且容易变成猜测 |

另两条我自己裁的小口径：
- **D-D**：`explain.html` 末尾放一个**相对链接**指回同目录 `index.html`（事实档案）。
  这不是外链（不引外部资源），且 `index.html` 不存在时不显示该链接。
- **D-E**：两页**同源**——都从同一份 `trace.json` 渲染，讲解页显示该 trace 的
  `meta.repo.commit` 与 `created_at`，避免「讲解与事实对不上」却看不出是谁旧了。

## 4. 目标 / 非目标 / 反目标

**目标**
1. 一个读得懂的 `explain.html`：开头就知道「这项目干什么、数据怎么流、先看哪三个模块」。
2. 讲解文字由模型写，**每个数字都能点开看出处**；查不到出处的打「未溯源」标记但照常显示。
3. 零新依赖、单文件离线、零外链；原 `index.html` 字节级不变。
4. 没配 key 也能出一版**如实的**讲解页（程序按事实模板写），并在页面顶部明说「未使用模型」。
5. MCP server 可被任意 MCP 客户端（DSH / Claude Desktop / 其它）挂上用。

**非目标（本片不做）**
- 仓库文件树 / 每个文件干什么 / 训练循环 / 数据管线（D-C）。
- 改 `index.html` 的排版（方案三的直接含义）。
- 官方 `mcp` SDK、Node 运行时、任何 pip 安装（本机 pip 一律 `PermissionError [Errno 13]`）。
- 讲解页的交互（折叠/搜索/切换口吻）——本片只出静态页，`<details>` 折叠算排版不算交互。
- 论文对账的任何改动（甜头块只**读**已有 anchors）。

**反目标（做出来就算失败）**
- 模型编一个数字、页面照样当事实显示且没有任何标记。
- 为了「看起来讲全了」而放宽角色判据、隐藏 unknown、或把估算说成实测。
- 讲解页引了外部 CSS/JS/字体/图片（离线打不开）。
- 没配 key 时静默产出一版「看起来像模型写的」页面。
- 动 `spine.html.j2` / `render/html.py` / `render/analysis.py` / `analyze_*.py` / `schema/trace.json`。

## 5. 架构

```
事实层（已有，不改）：build_trace → trace.json
  nodes 128（op 75 / param 18 / input 1 / module 34）
  edges 101（src/dst/shape/producer_shape/checked）
  analysis：34 模块角色 + 判据 + 指标 + method
  symbols.code：B/T/D/H/Dh + defined_at
        │ 只读
        ▼
MCP server（新，零依赖）  ◄──►  讲解员（模型 / DSH 里的我）
  stdio JSON-RPC 2.0             拿事实 → 决定讲什么怎么排
  6 个工具                       交回 blocks（组件 + 文字）
        │ blocks
        ▼
渲染层（新）：校验 → 组件取数生成 HTML/SVG → 溯源标记
  → explain.html.j2 → 单文件离线 explain.html
```

**模型手里没有「写文件」的能力**：它只能交回一个 blocks JSON，由程序落盘。
它能写任意 HTML 的地方只有 `custom` 块，且过守卫（§8）。

## 6. MCP server（传输 A：手写，零依赖）

### 6.1 协议
- **换行分隔的 JSON-RPC 2.0 over stdio**：`sys.stdin` 逐行读，一行一个请求；
  响应一行一个 JSON 写 `sys.stdout`（`ensure_ascii=False`），日志一律走 `sys.stderr`。
  **stdout 不许出现任何非 JSON 字符**（否则客户端解析炸）。
- 实现 `initialize` / `notifications/initialized`（通知，不回响应）/ `tools/list` / `tools/call` / `ping`。
  `initialize` 回 `protocolVersion: 2024-11-05`、`capabilities: {tools: {}}`、
  `serverInfo: {name: papertrace, version: 0.1.0}`。
- 未知方法 → JSON-RPC 错误 `-32601`；参数不合法 → `-32602`；内部异常 → `-32603`（消息如实，不冒 traceback 到 stdout）。
- 工具执行失败（如模块 id 不存在）→ **`result.isError = true` + 文本原因**，不是 JSON-RPC 错误
  （MCP 惯例：工具级失败要让模型看见并自己改正）。
- 只用标准库：`sys / json / pathlib / traceback / typing`。**禁 anyio/httpx/pydantic/uvicorn/mcp**。
- 入口：`python -m papertrace.mcp`（`papertrace/mcp/__main__.py`）。不占 `cli.py` 行数。

### 6.2 六个工具

| 工具 | 入参 | 返回 | 备注 |
|---|---|---|---|
| `analyze_repo` | `repo`(必), `entry?`, `batch?`, `seq_len?`, `out?` | trace 路径 + 计数摘要 + fact 目录 | 内部调 `build_trace` + `analyze_code`；**不接论文**（甜头要论文时另走 build --paper） |
| `get_facts` | `trace`(必), `kind`(必: overview/modules/module/ops/edges/symbols/totals), `module_id?`, `limit?`, `offset?` | 事实条目数组，**每条带 `fact_id`** + `total`/`next_offset` | 分页防一次吐 128 节点撑爆上下文；默认 limit=40 |
| `read_source` | `trace`(必), `path`(必), `start`(必), `end`(必) | 带行号的源码行 + 真实路径 | **只许读 trace.meta.repo.url 之下**；越界/不存在 → isError；单次 ≤200 行 |
| `list_components` | 无 | 组件清单：名字 / 参数 / 每个参数从哪取事实 / 一个最小示例 | 讲解员的「菜单」，含 custom 与 text 的规则 |
| `explain_outline` | `trace`(必) | 程序算好的事实骨架：主链、按角色分组的模块、指标、建议讲解顺序 | **与无 key 降级版共用同一份数据**（单一真源） |
| `render_explain` | `trace`(必), `blocks`(必), `out`(必), `title?` | explain.html 路径 + 字节数 + 未溯源标记数 + 被剥离构造数 + 校验问题清单 | 校验不过 → isError 且**不写文件** |

### 6.3 讲解技能包（形态 A 的另一半）
`docs/explain-agent.md`：给讲解员（我 / 任何 MCP 客户端里的模型）的操作手册——
先 `analyze_repo` 或拿现成 trace → `explain_outline` 看骨架 → `get_facts` 分页取细节 →
`read_source` 核关键行 → 组 blocks → `render_explain` → 看返回的未溯源数并回头补 cites。
含**口吻规范（D-B 教学口吻）**、**禁止编数字**、**custom 块规则**、一个完整 blocks 示例。

## 7. 讲解脚本（blocks）与组件库

### 7.1 blocks 形状
```json
{"title": "nanoGPT 是怎么把一串 token 变成下一串的",
 "blocks": [
   {"component": "text", "args": {"markdown": "## 这个项目在干什么…"}, "cites": ["fact:overview"]},
   {"component": "metrics", "args": {"keys": ["params", "max_activation", "est_flops"]}, "cites": ["fact:totals"]},
   {"component": "flow_chain", "args": {}, "cites": ["fact:chain"]},
   {"component": "module_card", "args": {"module_id": "root/transformer.h.0.attn"}, "cites": ["fact:module/root/transformer.h.0.attn"]},
   {"component": "custom", "args": {"html": "<div>…</div>"}, "cites": []}
 ]}
```
- 顺序＝讲解顺序，**模型全权决定**（m11687）。程序不重排、不删块（除守卫剥离）。
- 每块可带 `cites`（fact id 列表）。`cites` 缺失不报错，但该块里的数字全部会被判未溯源。
- 未知组件名 / 参数不合法 → **响亮拒绝整个 render**（isError + 指出第几块、错在哪），不静默跳过。
- `cites` 里出现**不存在的 fact id** → 同样响亮拒绝：引用一个不存在的事实是伪造出处，
  比数字未溯源更严重（未溯源是「没给出处」，假 cites 是「给了假出处」）。

### 7.2 组件清单（13 个，全部从 facts 取数）

| 组件 | 参数 | 产出 | 事实来源 |
|---|---|---|---|
| `text` | `markdown` | 受限 markdown 子集渲染（§7.3） | 模型文字 + cites |
| `custom` | `html` | 任意 HTML（过守卫 §8） | 模型 |
| `overview` | 无 | 项目名 / 入口 / commit / 生成时间 / 规模计数 | meta + nodes/edges 计数 |
| `metrics` | `keys?` | 大数字块（默认四项） | analysis.totals |
| `flow_chain` | `max_steps?` | **主链**：input → … → 输出，逐步标形状变化 | nodes + edges（程序算路径） |
| `module_card` | `module_id` | 人话名 + 类名 + 角色 + 判据原文 + op_count + 三项指标 | analysis.modules + nodes |
| `ops_graph` | `module_id` | 该模块的算子 SVG（**复用 `render_html._groups` 的口径**） | nodes |
| `flow_edges` | `module_id` 或 `edge_ids` | 谁喂谁表：src → dst / label / shape / producer_shape / 是否一致 | edges |
| `callchain` | `root?` | 模块树时序（入口往下串，标层号） | nodes(level=module) |
| `symbol_table` | 无 | B/T/D/H/Dh 台账：值 + 定义位置（basename:line，悬停看全路径） | symbols.code |
| `code` | `path`, `start`, `end` | 带行号等宽源码块 | 只读 repo 内文件 |
| `table` | `kind`, `columns?`, `module_id?` | 任何 facts 表 | get_facts 同源 |
| `paper_bonus` | 无 | **甜头**：有 anchors 才渲染论文对账小结；无论文**整块不出现** | anchors/unresolved |

### 7.3 受限 markdown 子集（零依赖手写）
支持：`##`/`###` 小标题、空行分段、`- ` 无序列表、`1. ` 有序列表、`**粗体**`、行内代码（单反引号）。
**不支持**：链接、图片、裸 HTML、表格、脚注（要这些走 `custom` 或 `table` 组件）。
遇到不支持的构造 → 原样当纯文本显示（不静默丢字），并在 render 返回里记一条提示。
理由：讲解需要小标题与列表，但引入完整 markdown 库违反零新依赖。

### 7.4 人话名（`explain/names.py`）
`root/transformer.h.0.attn.c_proj` + class `Linear` + role `linear`
→ 「第 1 层 · 注意力 · 输出投影（Linear）」。
规则：层号从 id 里的 `h.<n>` 取（**事实**），部件名从 id 末段 + 角色映射表取，
映射表里没有的末段 → **原样显示 id 末段**，不猜。每个名字旁边保留原始 id（悬停/小字）。

## 8. 守卫与溯源（宽松口径的具体实现）

### 8.1 fact id 体系（`explain/facts.py`）
| fact id | 指向 | 数值集合（用于溯源比对） |
|---|---|---|
| `fact:overview` | meta + 计数 | nodes/edges 数、batch、seq |
| `fact:totals` | analysis.totals | modules/params/max_activation/est_flops/degraded |
| `fact:totals/<key>` | 单个指标 | 该值 |
| `fact:module/<module_id>` | 一条模块分析 | op_count/params/max_activation/est_flops + 层号 |
| `fact:node/<node_id>` | 一个节点 | shape_in/shape_out/outputs 里的所有整数 |
| `fact:edge/<edge_id>` | 一条边 | shape/producer_shape 里的整数 |
| `fact:symbol/<var>` | 一条符号 | value |
| `fact:chain` | 主链 | 链上所有节点的形状整数 |
| `fact:source/<path>:<a>-<b>` | 一段源码 | 该段里出现的所有整数 |

### 8.2 未溯源标记（宽松，m11692）
- 从**模型写的文字**（`text` 的 markdown、`custom` 的可见文本）里正则提取数字
  （含千分位 29,856、小数、百分号；忽略行内代码与 HTML 属性里的数字）。
- 与该块 `cites` 指向的 fact 数值集合比对：**命中 → 正常显示**；
  **未命中 → 包 `<mark class=untraced title=未在引用的事实里找到这个数字>29,857</mark>`**，
  **照常渲染，不删不改数字**（删改就是替模型圆谎）。
- 页面顶部汇总「本页有 N 处数字未溯源」，并给一个「只看未溯源」的锚点列表。
- 组件自己产出的数字**不标记**（它们直接来自 facts，构造上就有出处）。
- 程序降级版（§9）预期未溯源数 = **0**，这是一条验收断言。

### 8.3 custom HTML 守卫（`explain/guard.py`）
允许：任意标签、内联 `style`、`class`、`<details>/<summary>`、内联 SVG（`xmlns` 是命名空间标识符，沿用 R75）。
禁止并**剥离**：`<script>`、`on*` 事件属性、远程 `src=/href=`（http/https/协议相对）、
`<link>/<iframe>/<object>/<embed>`、CSS 里的远程 `url(...)` 与 `import`、`<base>`、`<meta http-equiv=refresh>`。
**处置＝剥离 + 当面明示**：页面上该块顶部显示「本块已移除 N 处不允许的构造（脚本/外链/事件属性）」，
MCP 返回里逐条列出被移除的构造。理由：宽松口径要「照常渲染」，但零外链是产品铁律，
剥离并明示既满足两者，又不是静默。
相对链接 `index.html`（D-D）与页内锚点 `#…` **允许**。

## 9. 无 key 降级（`explain/narrate.py`）

- 触发：`PAPERTRACE_LLM_BACKEND` 未设/offline，或显式 `--no-llm`。
- 产出：用 `explain_outline` 的同一份事实骨架 + **如实模板句**组成 blocks，走同一条渲染路径。
  模板句例：「CausalSelfAttention（第 1 层注意力）：判定为 attention，判据原文『…』；
  本模块 22 个算子，参数量 4,352，峰值激活 1,536 元素，粗估 FLOPs 147,456。」
  ——**每个数字都来自 facts，不编一个形容词性的结论**（不许写「这是模型的核心」这类无出处判断）。
- 页面顶部横幅：「**本页未使用模型**：文字由程序按事实模板生成。配好中转后可得模型撰写的讲解。」
- 有 key 时：`explain/llm_explain.py` 复用 `papertrace/llm/openai_backend.py`（可注入 transport，测试不联网），
  prompt 里给 outline + 组件菜单 + 口吻规范，要求返回 blocks JSON；
  解析失败/模型不返回合法 JSON → **不静默兜底成降级版**，而是报错并提示可用 `--no-llm`（响亮）。
  `LLMUnavailable` → 自动降级并明示（这是唯一允许自动降级的分支）。

## 10. CLI

```
python -m papertrace explain --repo tests/fixtures/nanogpt --out output/demo-explain --no-llm
python -m papertrace explain --trace output/demo/code-only/trace.json --out output/demo-explain
python -m papertrace.mcp            # MCP server（stdio）
```
- `--repo` 与 `--trace` 二选一（都给 → 报错；都不给 → 报错）。`--repo` 内部先 build 再讲解。
- `--no-llm` 强制降级；不给则按后端分派（§9）。
- 退出码沿用既有口径（实测 `papertrace/exit_codes.py`：UNIMPLEMENTED=2 / MISSING_RUNTIME=4 / UNTRACEABLE=5，**没有 6**）：
  渲染失败 exit 2（与 `cli.py:166` 同口径）、trace 不合法 exit 1（`cli.py:147`）、缺 torch exit 4、追不动 exit 5、
  参数二选一错由 argparse 自己处理（exit 2）。
- **`cli.py` 现 182 行**，加子命令会破 200 → 新增 `papertrace/cli_explain.py` 承载
  `add_parser(sub)` 与 `run(args) -> int`，`cli.py` 只加 import + 两行分派（≤190 行）。

## 11. 页面长什么样（草图）

```
nanoGPT 是怎么把一串 token 变成下一串的
[横幅] 本页由模型撰写（deepseek-chat）· 事实来自 trace.json（commit dirty-subdir, 2026-11-16 05:04）
       本页有 2 处数字未溯源 → 查看

目录：这个项目在干什么 · 数据怎么流 · 先看这三个模块 · 逐层拆解 · 代码体检 · 甜头

## 这个项目在干什么
一个 GPT 语言模型实现。它把一串 token 变成「下一个 token 的概率分布」…

[大数字块] 34 个模块 | 参数量 29,856 | 峰值激活 2,048 元素 | 粗估 FLOPs 884,736
           （口径：kind==param 元素数求和，含 weight tying 重复与 buffer；FLOPs 只对 matmul/linear 粗估）

## 数据怎么流
token ids (2,8) → 词嵌入 (2,8,32) + 位置嵌入 (8,32) → 4 层 Transformer → 末归一化 → lm_head → logits (2,8,32)
[SVG：主链，每步标形状]

## 先看这三个模块
[模块卡] 第 1 层 · 注意力（CausalSelfAttention）  角色 attention  判据原文…  6 算子 / 4,352 / 1,536 / 147,456
         人话：把 Q/K/V 一次算出来再拆开，因果掩码防偷看未来。 [展开算子图] [看源码 model.py:120-140]
…

## 代码体检
[table: 34 模块，可折叠]

## 甜头：与论文对账（有 --paper 才出现）
[paper_bonus]

—— 事实档案：index.html（128 节点 / 101 边的原始平铺，给对账用）
```

## 12. 文件结构（每个产品文件 ≤200 行）

```
papertrace/mcp/__init__.py          包声明
papertrace/mcp/__main__.py          python -m papertrace.mcp 入口（~15 行）
papertrace/mcp/server.py            stdio 循环 + JSON-RPC 分派 + 错误码（~150）
papertrace/mcp/tools.py             6 个工具的 schema 声明 + 参数校验（~180）
papertrace/mcp/handlers.py          工具实现（analyze/get_facts/read_source/outline/render）（~190）
papertrace/explain/__init__.py      包声明
papertrace/explain/facts.py         fact id 索引 + 数值集合 + 分页取事实（~190）
papertrace/explain/outline.py       主链计算 + 角色分组 + 建议顺序（~150）
papertrace/explain/names.py         module_id → 人话名（~90）
papertrace/explain/blocks.py        blocks 校验（组件名/参数/cites）（~150）
papertrace/explain/guard.py         custom HTML 剥离 + 未溯源数字标记（~190）
papertrace/explain/markdown.py      受限 markdown 子集（~130）
papertrace/explain/components.py    组件注册表 + 分派（~120）
papertrace/explain/comp_facts.py    overview/metrics/module_card/symbol_table/table（~190）
papertrace/explain/comp_graph.py    flow_chain/ops_graph/flow_edges/callchain（~190）
papertrace/explain/comp_code.py     code/paper_bonus（~120）
papertrace/explain/render.py        组装 + 模板渲染 + 体积上限 + 写盘（~150）
papertrace/explain/narrate.py       无 key 降级：事实模板叙述（~150）
papertrace/explain/llm_explain.py   有 key：调模型产 blocks + 解析（~140）
papertrace/templates/explain.html.j2  讲解页模板（内联 CSS，零外链）
papertrace/cli_explain.py           explain 子命令 parser + run（~120）
papertrace/cli.py                   +import +2 行分派（182 → ~190）
docs/explain-agent.md               讲解技能包（给模型的操作手册）
```
**禁改**：`render/html.py` / `render/analysis.py` / `render/symbols.py` / `render/terms.py` /
`spine.html.j2` / `analyze/roles.py` / `analyze/metrics.py` / `build/analysis.py` / `schema/trace.json` /
`build/trace.py` / `spine*.py` / `align/*` / `parse_*/*`。
`ops_graph` 复用 `render_html._groups`：**只 import 调用，不改它**（它是私有函数，
在 `comp_graph.py` 里 import 使用，不改名不动实现；需要复用口径时抄口径并注明来源）。
**preflight 实测**：`_groups(doc)` 返回 **30 组布局字典**（键 `parent/width/height/nodes`，
节点键 `box_w/label/link/loc_full/loc_short/loc_x/shape_in/shape_out/y`），**不是原始节点**；
SVG 的 markup 在 `spine.html.j2:68-81`，要抄那段口径并注明来源，不许改原模板。
34 个模块里有 **4 个没有算子组**（`root/transformer`、`root/transformer.h`、
`root/transformer.h.0.mlp`、`root/transformer.h.1.mlp`——算子挂在子模块下），
`ops_graph` 遇到它们必须如实说「该模块没有直接算子，算子挂在子模块下」，不许画空图也不许崩。

## 13. 测试策略（TDD，每任务先红后绿）

- 新测试文件：`tests/test_mcp_server.py` / `test_mcp_tools.py` / `test_explain_facts.py` /
  `test_explain_outline.py` / `test_explain_names.py` / `test_explain_blocks.py` /
  `test_explain_guard.py` / `test_explain_markdown.py` / `test_explain_components.py` /
  `test_explain_render.py` / `test_explain_narrate.py` / `test_explain_cli.py`。
- MCP server 测试用 `io.StringIO` 假 stdin/stdout 跑循环（**不起子进程、不联网**）；
  另有一条端到端用 `sys.executable -m papertrace.mcp` 真起一次子进程（stdio 管道）。
- 模型调用测试一律注入假 transport（单实例 + 断言被测路径真被走到，计数器 ≥1）。
- 真事实来自夹具真跑一次 build（module 级 fixture，`tests/_tmp.py::scratch_dir`，**禁 tmp_path**）。
- **每任务 ≥1 条变异探针**：改产品代码一处 → 指定测试必红 → 还原（`git show HEAD:<file>` + `write_bytes`，
  **禁 `git checkout --`**，`core.autocrlf=true` 会改行尾）→ 核 sha256 全等。
- 关键钉子（必须有）：
  1. 原 `index.html` 字节级不变（同 trace 渲染两次比对）。
  2. `explain.html` 零外链（扫 http/https/协议相对/src=/import，`xmlns` 例外）。
  3. 未溯源数字：文字里写 29,857（真值 29,856）→ 出现 `<mark class=untraced>29,857</mark>` 且数字原样。
  4. 溯源命中：写 29,856 且 cites 含 `fact:totals` → **不**出现 mark。
  5. custom 里塞 `<script>` / `onclick` / 远程 `src` → 被剥离 + 页面明示 + 返回里逐条列出。
  6. 未知组件名 / 缺必填参数 → isError 且**不写文件**。
  7. 无 key 降级页：横幅含「未使用模型」、未溯源数 = 0。
  8. `read_source` 越界（../../）→ isError，不读到 repo 外。
  9. `get_facts` 分页：limit/offset 正确、total 正确、不重不漏。
  10. 无论文时 `paper_bonus` **整块不出现**（不是空态）。
  11. stdout 纯净：server 跑一轮后 stdout 每行都是合法 JSON。
  12. GC8 六项不变（nodes=128 / edges=101 / modules=34 / params=29,856 / degraded=2 / est_flops=884,736）。

## 14. 全局约束（继承 + 新增）

继承 `.superpowers/sdd/2026-11-16-papertrace-code-only/global-constraints.md` 的 GC1–GC23 全部
（≤200 行 / 零新依赖 / 禁 mock 填产品输出 / 默认 offline / 公式写死 / GC8 不变式 /
scratch_dir / 一律 pwsh / 每任务一次提交 / 行尾核对 / GC19 诚实边界 / GC20 只看直接子节点 /
GC21 unknown 合法 / GC22 analysis 可选 / GC23 模板兜底用 default）。

本片新增：
- **GC24（两页同源、原页不动）**：`explain.html` 与 `index.html` 从同一份 trace 渲染；
  本切片**不许改**原页任何渲染文件，验收含「原页字节级不变」。
- **GC25（stdout 纯净）**：MCP server 的 stdout 只许出现 JSON-RPC 响应，一行一个；日志走 stderr。
- **GC26（数字要么有出处要么被标记）**：模型文字里的数字未命中 cites 的 fact 数值集合 →
  必须打 `untraced` 标记且**原样保留数字**；禁止删改数字、禁止静默通过。
- **GC27（剥离必须明示）**：custom 块被守卫移除的构造，必须同时在页面与工具返回里可见。
- **GC28（降级必须自报）**：无模型参与生成的页面，顶部横幅必须明说「未使用模型」；
  有模型参与时必须写出模型名与 trace 的 commit/created_at。

## 15. 风险与取舍

| 风险 | 处置 |
|---|---|
| 模型编数字 | GC26 标记 + 顶部汇总 + 技能包要求回头补 cites；**不拦截渲染**（宽松口径是用户拍板） |
| custom HTML 破坏离线 | GC27 剥离 + 明示；测试钉四类注入 |
| 讲解页与事实档案不一致 | D-E 同源 + 页面显示 commit/created_at |
| 组件参数错 | 响亮拒绝整个 render，指出第几块；不静默跳过 |
| 128 节点撑爆模型上下文 | `get_facts` 分页（默认 40）+ `explain_outline` 先给骨架 |
| 范围膨胀（仓库文件树/训练循环） | D-C 明确非目标，写进反目标 |
| `cli.py` 破 200 行 | 拆 `cli_explain.py`（§10） |
| 手写 JSON-RPC 与真实客户端不兼容 | 端到端真起子进程测一轮；协议版本钉 2024-11-05；DSH 里真挂一次验收 |
| 受限 markdown 表达力不够 | 不支持的构造原样显示 + 返回提示；要复杂排版走 custom |

## 16. 任务拆分概览（详细计划另写）

| Task | 交付 | 独立可测 |
|---|---|---|
| E1 | `explain/facts.py` + `outline.py` + `names.py`：fact 索引、主链、人话名 | 纯函数测试 |
| E2 | `explain/markdown.py` + `guard.py`：受限 markdown + 剥离 + 未溯源标记 | 纯函数测试 + 注入探针 |
| E3 | `explain/blocks.py` + `components.py` + `comp_facts.py`：校验与事实类组件 | 真 trace 渲染片段 |
| E4 | `comp_graph.py` + `comp_code.py`：图/边/调用链/源码/甜头 | SVG 与表格断言 |
| E5 | `explain/render.py` + `explain.html.j2`：整页渲染 + 体积上限 + 零外链 | 整页断言 + 原页不变 |
| E6 | `explain/narrate.py` + `cli_explain.py`：降级版 + CLI | 真跑命令 + 横幅 + 未溯源 0 |
| E7 | `mcp/server.py` + `tools.py` + `handlers.py` + `__main__.py` | 假 stdio + 真子进程端到端 |
| E8 | `explain/llm_explain.py` + `docs/explain-agent.md` + README + 演示 | 假 transport + 真挂 DSH 验收 |

每任务：先写红测试 → 实现 → 绿 → 变异探针 → 一次提交 → 独立评审 → 修复循环。

## 17. 验收标准（交付时必须全中）

1. `python -m papertrace explain --repo tests/fixtures/nanogpt --out output/demo-explain --no-llm`
   → exit 0，`explain.html` 存在、零外链、横幅含「未使用模型」、未溯源数 0、含主链/模块卡/指标/体检。
2. MCP 端到端：`initialize` → `tools/list`（6 个）→ `get_facts` 分页 → `render_explain`（讲解员 blocks）
   → 文件写出，返回字节数/未溯源数/剥离数；stdout 每行合法 JSON。
3. 在 DSH 里真挂一次这个 MCP server，由我当讲解员产出一版**模型撰写**的 `explain.html`，
   年糕读得懂（这是主观验收，交付时请他看）。
4. 原 `index.html` 字节级不变；GC8 六项不变；全量 pytest 绿（854 + 新增）。
5. 三份演示目录都有 `explain.html`（code-only / with-paper / fallback-yellow），
   其中 with-paper 那份出现甜头块、另两份不出现。
6. README 新增「讲解页」小节 + `docs/explain-agent.md` 技能包；已知局限如实更新。

## 18. 待年糕确认

- §3 的 D-A / D-B / D-C 三条默认裁决（两条都要 / 教学口吻 / 只讲模型链）——不改就按这个做。
- §7.2 的 13 个组件够不够？有没有你特别想看的块（例如「训练时怎么用这个模型」——那属 D-C 范围外）。
- §11 的页面草图是不是你要的「读得懂」。
