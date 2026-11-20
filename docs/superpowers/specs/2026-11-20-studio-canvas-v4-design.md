# 笺疏 Studio 画布 v4：纸白技术插图 + 五类流水线角色

日期：2026-11-20 · 状态：已实现 · 原型：`docs/studio/mock/index4.html`

## 1. 为什么改

用户原话：「我觉得现在的工作流演示还是不够直观 输入输出 处理存储 转译 控制几个流程都要有明显的扎实」「把现在的画布改造一下 更专业一点」。

v3.2 的画布画的是**代码结构**：系统 → 子系统 → 文件，两套边（import 依赖、符号级数据流），力导向布局。它回答"谁依赖谁"，但不回答"数据在哪儿进、在哪儿被处理、落到哪儿去"。五个流程类别在页面上完全不存在。

同时 v3 的视觉是纸质手账风：宋体、红印章、纸纹噪点（`body::before` 一层 `mix-blend-mode: multiply`）、按 `data-role` 填充的米黄卡片。像一本装帧精致的读物，不像工程工具。

## 2. 目标与非目标

**目标**

1. 每个节点带一枚**流水线角色**徽标（输入输出 / 处理 / 存储 / 转译 / 控制 / 非代码），系统层与子系统层卡片底部画五色微条，按该类文件占比。
2. 每个标签都能追到证据：右栏列出命中的 import、路径或符号原文。
3. 左下角固定图例：五类色 + 两类边。
4. 「按流水线排布」开关：默认关（保持自由力导向），打开后按五类分带，空类只留窄槽。
5. 视觉换成纸白技术插图：白底、1px 墨线、等宽数字、去宋体/印章/纸纹。

**非目标**

- 不伪造运行时数据。Glossa 是静态分析，五类只能从 import、路径、符号名推断，页面必须写明这一点。
- 不引第三方库，仍是单文件离线 HTML。
- 不改 `data.json` 既有字段，只新增 `stage` / `stage_evidence` / `stage_score` / `stages` / `layout_bands`。

## 3. 五类怎么判定

脚本：`scripts/build_studio_v4.py`。

按**加权打分**选主类，不是"先命中算哪个"：

| 信号 | 分值 | 理由 |
|---|---|---|
| 路径命中 | 3 | 仓库作者自己放的位置，最可信 |
| import 命中 | 2 | 依赖关系是硬事实 |
| 符号命中 | 1 | 名字最容易误伤 |

| 类别 | import 关键词 | 路径关键词 | 符号关键词 |
|---|---|---|---|
| 控制 | orchestrat / statemachine / taskgraph / scheduler / worker_threads | orchestrator / daemon / runtime / scheduler / statemachine / taskgraph | orchestrat / scheduler / statemachine / queue / daemon / pipeline / worker / taskgraph |
| 转译 | parser / compiler / babel / esbuild / markdown / schema / vite / postcss | — | parse / compile / transpile / render / format / normalize / convert / markdown |
| 存储 | sqlite / better-sqlite3 / pg / mysql / redis / lancedb / leveldb | — | store / db / save / persist / backup / repository / dao / migrat |
| 输入输出 | http / ws / fetch / axios / express / fastify / hono / koa / node:net | gateway / api/ / server / client / cli / ingest / web/ / views / routes / handler | handler / route / fetch / request / response / socket / listen / stream |
| 处理 | — | — | 兜底：是源码、但四类都没命中 |

两条刻意的取舍：

- **`node:fs` 不计分**。几乎每个脚本都摸文件系统，算进去会把一半文件误判成存储/输入输出。初版就这么错过一次：存储 124、输入输出 94，全是假的。
- **非代码文件记 `none`**。md/json/yaml 不参与流程判定，徽标显示「—」，不计进占比；否则整个 docs 目录会被标成"处理"。

SafeTrace 的实际分布（485 个文件）：输入输出 150 · 处理 147 · 存储 33 · 转译 15 · 控制 30 · 非代码 110。分组主类：`src` = 处理（98 处理 / 87 输入输出 / 30 存储），`web` = 输入输出（50），`scripts` = 处理（44）。

## 4. 画布改造清单

| 项 | 做法 |
|---|---|
| 主色 | `--bg #f4f3ee`、`--panel #fff`、`--line #d8d5cc`、`--ink #1b1e23` |
| 去手账 | 删宋体（`--serif: var(--sans)`）、关 `body::before` 纸纹与 `.stage::after` 噪点、红印章换成中性墨块 |
| 卡片 | 统一白底（`g.node[data-role] rect.card`），1px 描边，去投影；角色只留左侧 3px 色条 + 徽标 |
| 徽标 | 卡片右上角，类名色底白字，宽按字数算 |
| 微条 | 卡片底边，五段宽度按该类文件占比；只有 1 类时不画 |
| 图例 | 左下固定：五类色 + import 依赖（虚线）+ 数据流（实线）+ 选中即点亮 |
| 证据 | 右栏「流水线角色」块：命中的规则原文（import / 路径 / 符号）；目录层改列占比 |
| 分带 | 列宽按内容算，空类只留 64px 窄槽；一列超过 4 个节点自动并第二列 |
| 边 | import 依赖去箭头（和数据流走同一条路径会叠成一团），数据流收细到 1.5–3.9px |
| 动画 | 关入场动画（`nodeIn` 的 CSS transform 会盖掉 SVG 的 translate，节点会堆在原点）；顶部统计不再滚动 700ms |

## 5. 实现与复现

```bash
python scripts/build_studio_v4.py      # data.json → data4.json（打标签 + 算分带坐标）
python scripts/make_studio_v4_html.py  # index3.html + data4.json → index4.html
```

两个脚本都以 `index3.html` / `data.json` 为输入，可重复跑。`index3.html` 原样保留作对照。

截图：`docs/studio/mock/shots-v4/free.png`（默认）、`pipe.png`（按流水线排布），由无头 Edge 渲染。

## 6. 验证

- `node --check` 通过（生成的 `<script>` 无语法错误）。
- 默认态：11 个节点、11 枚徽标、5 条占比微条、5 个图例色块、0 个分区带（开关关闭）。
- 分带态：6 条带（含 3 条空槽）、节点按类落列，缩放到 73% 一屏可见。
- 分带画布尺寸：组级 1648×904（初版固定列宽是 2760 宽，缩到 0.42 字看不清）。

## 7. 遗留

- 文件层（第三个层级）不分带：文件一次只显示几十个、卡片小，五列会把画布拉到 13000 宽。需要时可给单个组单独算布局。
- 角色判定是启发式，误判仍然存在（例如 `src/gateway/package.json` 会因路径含 `gateway` 落到输入输出）。页面用证据块兜住：能看到它是被哪条规则判的，不服可以改规则重跑。
- 深色主题仍可用（顶栏切换），但不是设计目标，配色未逐项调过。
