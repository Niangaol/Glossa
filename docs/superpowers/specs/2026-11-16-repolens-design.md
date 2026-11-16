# RepoLens 重做设计：任意代码仓库的静态解析与讲解

- 日期：2026-11-16　状态：**待年糕批准**　分支：master　BASE：ad51b52
- 取代：docs/superpowers/specs/2026-11-16-papertrace-explain-design.md 与同名 plan（**E1–E8 全部作废**）
- 触发：用户 m12709「但是 很多时候这些项目都只是一些普通的代码项目 ，你可以参考本机的一些项目比如D:\AgentPrograms\safetrace」；m12720「事实上我希望你重做 这个方向已经错的有点离谱了。。。你先写计划吧」

## 0. 一句话

RepoLens 读一个**普通代码仓库**——不需要能跑、不需要装依赖、不需要有模型——静态解析出「有哪些文件、谁 import 谁、入口在哪、每个文件里有什么」，产出一页**人能读懂的单文件离线讲解页**；同一套事实通过 MCP 交给任意 AI Agent 去写讲解文字。torch 模型追踪与论文对账降为**可选甜头**。

## 1. 为什么是重做而不是继续修

错在**输入假设**，不在渲染细节：

| 证据 | 实测 |
|---|---|
| 现有入口契约 | `python -m papertrace build --repo <dir> --entry 模块:工厂函数`，靠 torch.fx 追踪一个能实例化的 nn.Module |
| SafeTrace 有没有 torch 模型 | **一个都没有**（TS monorepo，六包，43 条 npm scripts）→ 现有 build 根本分析不了它 |
| 现有页面为什么看不懂（m12564） | 全页 50,167 字符里 ② 算子图占 37,854（**72%**），128 个节点平铺，**零句人话叙述**，模块名是原始路径 |
| 旧 explain 切片（E1–E8）错在哪 | 它仍然以 trace.json（torch 算子图）为唯一事实源，只是给算子图加讲解 → 对普通仓库依旧无输入 |

所以：**换事实源**。新核心从「文件系统 + 源码文本」出发，而不是从「能跑的模型」出发。旧管线一行不改地留着当甜头。

## 2. 真项目实测（这一节决定事实模型，不是背景介绍）

### 2.1 SafeTrace（D:\AgentPrograms\safetrace）

- TypeScript ESM monorepo，npm workspaces 六包：`src/shared, src/gateway, src/ingest, src/enrich, src/qa, src/assets`；`type: module`，`engines.node >= 24`。
- 用本设计的默认排除规则实跑（探针 output/controller-probes/_scan_safetrace.py）：**保留 486 个文件**，语言分布 typescript 326 / json 78 / vue 24 / markdown 20 / javascript 15 / shell 8 / yaml 8 / python 2 / css 2 / html 1 / 只登记名的 .env 2。
- `src/` 下 ts+js **255** 个；逐包：shared 27 / gateway 26 / ingest 53 / enrich 41 / qa 90 / assets 18。
- **vendored 干扰极大**：`third_party/` 下 11,557 个 .py（open-jev / qdrant / snapshots），`Python/` 是嵌入式运行时（bin / pythoncore-3.14-64 / _cache，1,344 个 .py、283 个 .h、72 个 .pyd）。排除规则命中：node_modules 2 处、.git 1、third_party 1、bin/pythoncore-* 等；**>1MB 跳过 8 个**（含一个 11.7MB 的 zip）。
- 入口全在 npm scripts（**43 条**）：`gateway:serve → tsx src/gateway/src/server.ts`、`qa:serve → tsx src/qa/src/server.ts`、`cli:ask → tsx src/qa/src/cli.ts`、`intel:agents → node --import tsx scripts/intelligence-agents.ts`；dependencies 为空，devDependencies = @types/node / tsx / typescript。
- 真实 import 形态（决定解析口径）：`import { x } from "@safetrace/shared"`（workspace 包）、`import type { EventBus } from "@safetrace/shared"`（type-only）、`import { CircuitBreaker, type CircuitState } from "./circuit.js"`（**相对路径带 .js 后缀但真实文件是 .ts**）、`import { spawn } from "node:child_process"`（内置）、`import path from "node:path"`（默认导入）。
- 有 `.env.example` 与 `.env.local` → **必须只登记文件名，绝不读内容**。

### 2.2 PokemonData（D:\AgentPrograms\PokemonData）

- 排除 node_modules/.git/bin/obj 后扩展名分布：**.png 8,207 / .json 5,328 / 无扩展 3,264 / .dll 1,697 / .md 303 / .js 242**。
- 结论：解析器必须**按语言白名单取文件**，不能全扫；二进制与资产只计数不读内容。

### 2.3 PaperTrace 自身（本仓库）

- 86 个产品 .py + 53 个测试文件，854 passed。是**自举 smoke** 的理想对象：纯 Python、有 pyproject/requirements、有 `if __name__ == '__main__'` 入口。

### 2.4 由实测推出的五条硬需求

1. 多语言（至少 Python + TS/JS + Vue），且**精确度分级要如实标注**。
2. monorepo：包边界、workspace 包名 → 目录的映射必须解析，否则 `@safetrace/shared` 全是 unresolved。
3. 入口不只 `__main__`：npm scripts 是 SafeTrace 的唯一入口来源。
4. vendored 排除必须**显式、可解释、计数上页面**（13k 干扰文件 vs 486 真文件）。
5. 二进制/资产/超大文件必须跳过并计数，且**绝不执行任何被分析代码**。

## 3. 裁决清单（每条给理由与否决代价；年糕可逐条推翻）

| 编号 | 裁决 | 理由 | 否决的代价 |
|---|---|---|---|
| D1 | 新包 `repolens/`，CLI `python -m repolens`；旧 `papertrace/` **一行不改**保留，854 条旧测试每任务全量跑、零回归 | 旧管线是「甜头」本体且已全绿，删掉是净损失；新旧并存让重做可增量验证 | 若选「归档到 legacy/ 或删除」：要动 86 个文件与 53 个测试的 import，风险与工作量都大 |
| D2 | 语言：**Python 精确**（标准库 ast）；**TS/JS/TSX/JSX/MJS/CJS 近似**（自写词法扫描）；**.vue 切 script 块后走同一词法器**；其它语言只文件级事实 + manifest 依赖 | SafeTrace 需要 TS，PokemonData 需要 Vue；零新依赖装不了 tree-sitter | 若要 TS 精确解析：必须引入解析器依赖，本机 pip 一律 PermissionError，不可行 |
| D3 | 粒度：**文件级 import 图 + 文件内符号清单 + 入口清单**；第一版**不做函数级调用图** | 静态近似调用图会产「假精确」，违反本项目「宁可不说话也不说假话」 | 若要函数级：得先做符号解析与作用域分析，是另一个切片 |
| D4 | **绝不执行被分析仓库的代码**：不 import、不 exec、不 npm/pip install、不跑 setup.py，只读文本 | 安全 + 可分析「跑不起来的项目」 | 无（这是硬底线） |
| D5 | `.env*` 只登记文件名；`.pem/.key/id_rsa/*.pfx` 同样只登记名；页面不出现绝对路径（复用 papertrace/paths.py 的口径） | SafeTrace 真有 .env.local；讲解页会被分享 | 无（硬底线） |
| D6 | 排除规则显式：默认目录清单 + 语言白名单 + 单文件 >1MB 跳过 + 总文件上限 20,000 截断；支持仓库根 `.repolensignore`；**排除计数与逐条规则上页面** | 13k vendored vs 486 真文件；用户必须能看懂「为什么少了一半」 | 若隐藏排除：页面数字不可信 |
| D7 | 讲解文字两条路：**无 key → 程序事实叙述**（模板化但人话，全部可溯源）；**有 key → 模型只写文字**，图与排版由程序生成 | 沿用 m11687「模型全向放大、程序只提供 fact」与 m11692「组件库 + custom 块 + 宽松未溯源标记」 | 若只留模型路：没 key 时页面空白，违反「离线可用」 |
| D8 | 交付形态：**MCP server + CLI 两条都要**；MCP 用纯标准库手写换行分隔 JSON-RPC 2.0 over stdio | 沿用 m11668/m11673 拍板；本机装不了官方 mcp SDK（要拖 anyio/httpx/pydantic/uvicorn） | 若用官方 SDK：pip 在本机一律失败 |
| D9 | 甜头：旧命令 `python -m papertrace build` 原样可用；新讲解页**只有当输出目录里存在旧 trace.json 时**才显示「模型与论文」可选块，否则整块不出现 | 论文对普通仓库是噪音；有模型时才值得看 | 若强制显示：又回到「看不懂」 |
| D10 | 真项目只做**手动 smoke**：合成夹具入库；SafeTrace/PokemonData 的产物只落 `output/`（已 gitignore），**绝不把用户私有代码拷进仓库** | 隐私 + 仓库体积 + 测试可重复 | 若把真项目入库：泄漏私有代码且测试依赖本机路径 |

## 4. 目标 / 非目标 / 反目标

**目标**
1. `python -m repolens analyze D:\AgentPrograms\safetrace --out output/safetrace` → repo.json + 人话摘要，exit 0，不执行任何被分析代码。
2. `python -m repolens explain D:\AgentPrograms\safetrace --out output/safetrace` → 单文件离线 explain.html，**无 key 也能读懂**「这项目干什么、怎么跑、谁依赖谁」。
3. `python -m repolens serve` → MCP stdio server，六个工具，任意 Agent 可接。
4. 配了 OpenAI 兼容 key 时，讲解文字由模型写，数字未溯源打可见标记但照常渲染。
5. 旧 papertrace 管线与 854 条测试零回归。

**非目标（第一版明确不做）**：函数级调用图、类型推断、跨文件 re-export 链追踪、执行/构建/测试被分析仓库、语义搜索、增量缓存、Web 服务、多仓库对比、非 Python/TS 语言的符号级解析。

**反目标（做了就算错）**：为了页面好看而编造职责描述；把 unresolved 的 import 猜成某个文件；把 vendored 文件算进「项目规模」；把 .env 内容写进任何产物；在讲解页里放外链或脚本。

## 5. 架构：三层，事实与文字彻底分离

```
被分析仓库（只读文本，绝不执行）
        │
        ▼
[事实层] scan → lang/* → resolve → manifests/entries → facts → graph
        │  产出 repo.json（唯一事实源，带 fact id 台账与 degraded 清单）
        ▼
[讲解层] outline（程序定骨架）→ narrate（无 key 程序叙述 / 有 key 模型写字）
        │  组件库只从 facts 取数自己画图；custom 块过守卫
        ▼
[交付层] render → explain.html（单文件离线） / MCP tools → 任意 Agent
```

铁律：**模型 never 碰事实来源，程序 never 写叙述文字（除了有 key 时把 facts 交给模型）**。图与排版永远由程序生成。

## 6. 事实模型 repo.json（逐字段）

顶层 11 键，全部必填（空也要给空值，不许缺键）：

```json
{
  "meta": {
    "repo": {"name": "safetrace", "path": "safetrace", "commit": "…|unknown", "scanned_at": "ISO8601", "tool_version": "repolens-0.1"},
    "language_counts": {"typescript": 326, "vue": 24, "…": 0},
    "excluded": {"rules": [{"rule": "dir:node_modules", "hits": 2}], "files": 0, "bytes": 0, "oversize": [{"path": "…", "bytes": 11777947}], "truncated": false},
    "secrets_seen": [".env.example", ".env.local"],
    "limits": {"max_file_bytes": 1000000, "max_files": 20000}
  },
  "files": [{"id": "file:src/gateway/src/circuit.ts", "path": "src/gateway/src/circuit.ts", "lang": "typescript", "lines": 80, "bytes": 2568, "package": "@safetrace/gateway", "symbols": 4, "imports": 1, "doc_first_line": "…|null", "parse": "exact|approx|file-only|skipped"}],
  "symbols": [{"id": "symbol:src/gateway/src/circuit.ts#CircuitBreaker", "file": "src/gateway/src/circuit.ts", "name": "CircuitBreaker", "kind": "class|function|const|interface|type|method|enum", "line": 12, "end_line": 60, "exported": true, "doc_first_line": "…|null"}],
  "imports": [{"id": "import:000123", "file": "src/gateway/src/index.ts", "specifier": "./circuit.js", "line": 3, "type_only": false, "names": ["CircuitBreaker"], "resolved": {"kind": "internal|workspace|external|builtin|dynamic|unresolved", "target": "file:src/gateway/src/circuit.ts|null", "package": "@safetrace/shared|null"}}],
  "packages": [{"id": "pkg:@safetrace/gateway", "name": "@safetrace/gateway", "path": "src/gateway", "manifest": "src/gateway/package.json", "deps": [], "dev_deps": [], "scripts": {"serve": "tsx src/server.ts"}, "workspace": true}],
  "entries": [{"id": "entry:gateway:serve", "kind": "npm_script|py_script|main_guard|bin|makefile", "name": "gateway:serve", "command": "tsx src/gateway/src/server.ts", "target": "file:src/gateway/src/server.ts|null", "package": "@safetrace/gateway|null"}],
  "docs": [{"id": "doc:README.md", "path": "README.md", "title": "…", "headings": ["…"], "first_paragraph": "…"}],
  "graph": {"nodes": ["file:…"], "edges": [{"from": "file:…", "to": "file:…", "kind": "import"}], "cycles": [["file:a", "file:b"]], "reachable_from_entries": ["file:…"], "unreachable": ["file:…"]},
  "totals": {"files": 486, "source_files": 341, "lines": 0, "symbols": 0, "imports": 0, "internal_edges": 0, "external_deps": 0, "packages": 6, "entries": 43, "excluded_files": 0, "unresolved_imports": 0, "approx_files": 326},
  "facts": {"fact:repo.totals": {"numbers": [2, 6, 15, 20, 24, 43, 486, 326], "text": "…"}},
  "degraded": [{"what": "typescript", "why": "词法近似：不解析类型、不追 re-export 链、动态 import 记 unresolved"}]
}
```

口径裁决：
- `source_files` = lang ∈ {python, typescript, javascript, vue, csharp, go, java, rust, c, cpp} 的文件数；json/md/yaml/css/html/shell **不算源码**但算 files。
- `lines` 只统计源码文件的物理行数（含空行与注释，口径写进页面）。
- `meta.repo.path` 是**仓库目录名**，不是绝对路径；绝对路径只允许出现在 meta.repo 之外的 nowhere（沿用 GC：页面零绝对路径）。
- `parse` 四态必须逐文件如实标注：`exact`（Python ast）/`approx`（TS/JS/Vue 词法）/`file-only`（其它语言）/`skipped`（超大或二进制）。
- 任何解析不出来的东西进 `degraded` 或 `resolved.kind=unresolved`，**不许猜**。

## 7. fact id 台账（九种，一个不多一个不少）

| fact id | 覆盖 | numbers 集合 |
|---|---|---|
| `fact:repo.totals` | totals 全部整数值 | 升序去重的 int |
| `fact:file.<relpath>` | 单个文件的 lines/bytes/symbols/imports | 同上 |
| `fact:symbol.<relpath>#<name>` | 符号的 line/end_line | 同上 |
| `fact:import.<id>` | 单条 import 的 line | 同上 |
| `fact:pkg.<name>` | 包的 deps/dev_deps/scripts 计数 | 同上 |
| `fact:entry.<name>` | 入口（命令文本里的数字也收） | 同上 |
| `fact:doc.<relpath>` | 文档标题与段落（无数字则空集） | 同上 |
| `fact:graph.stats` | nodes/edges/cycles/reachable 计数 | 同上 |
| `fact:exclude.rules` | 排除计数与 oversize 字节 | 同上 |

规则（沿用旧切片已验证的口径）：numbers **只收 int、排除 bool**、float 整数值转 int、升序去重；未溯源比对是「数字 ∈ 所引用 fact 的 numbers 并集」，未命中只包 `<mark class="untraced">` 照常渲染并在页顶汇总；**引用不存在的 fact id 必须响亮拒绝**（假出处比未溯源严重）。

## 8. 扫描与排除（T1）

默认排除目录（大小写不敏感，命中即整棵子树跳过并计数）：
```
node_modules .git __pycache__ .venv venv dist build out bin obj
third_party vendor vendored site-packages .next .nuxt coverage target
.pytest_cache .mypy_cache .ruff_cache .tmp tmp var snapshots
qdrant-storage qdrant-storage .idea .vscode __MACOSX
pythoncore-*  （前缀匹配：嵌入式 Python 运行时）
```

语言白名单（扩展名 → lang）：.py→python；.ts/.tsx→typescript；.js/.jsx/.mjs/.cjs→javascript；.vue→vue；.cs→csharp；.go→go；.java→java；.rs→rust；.c/.h→c；.cpp/.cc/.hpp→cpp；.json→json；.md→markdown；.html→html；.css/.scss→css；.sh/.bat/.ps1→shell；.yml/.yaml→yaml；.toml→toml。**不在白名单的扩展名只计数不读**（PokemonData 的 8,207 个 png 因此零成本跳过）。

守卫：单文件 >1,000,000 字节 → skipped + 记 oversize；累计保留文件 >20,000 → 停止扫描 + `truncated: true` + 页面明示「只扫了前 20,000 个」；`.env*` 与密钥类扩展名 → 只登记名，**不 open**；读取一律 `errors="replace"`，解码失败不抛。

## 9. 语言解析口径（精确度必须自报）

### 9.1 Python（exact，标准库 ast）
- `ast.parse` 取：import / from-import（含相对层级 level）、def / async def / class（含嵌套，记 end_lineno）、模块 docstring 首句、`if __name__ == '__main__'` 入口。
- SyntaxError → 该文件 `parse=skipped` + degraded 记原因，**不抛**（一个坏文件不能毁掉整仓分析）。
- 不执行、不 import 被分析模块（硬底线 D4）。

### 9.2 TS/JS（approx，自写词法扫描，零依赖）
- 先做**掩码视图**：把字符串字面量、模板串、注释替换成等长占位，避免把注释里的 import 当真（这一招在旧 S2 已验证有效，直接复用思路）。
- 识别：`import … from '…'`、`import '…'`、`export … from '…'`、`require('…')`、`import('…')`（记 dynamic）、`export (default) (async) function|class|const|let|var|interface|type|enum NAME`。
- **明确不做**：类型解析、作用域分析、re-export 链追踪、装饰器语义、JSX 内部结构。全部写进 degraded。
- 词法器失败（括号不配对等）→ 退化为「只取能匹配到的行」+ degraded 记明，不抛。

### 9.3 Vue（approx）
- 用正则切 `<script …>…</script>` 块（含 setup），把块内文本交给 9.2 同一词法器；行号按块偏移还原。template/style 块只计数不解析。

### 9.4 其它语言（file-only）
- 只给 path/lang/lines/bytes/package；符号与 import 为空；degraded 记「该语言第一版只做文件级」。

## 10. import 解析规则表（T4，逐条可测）

| specifier 形态 | resolved.kind | target |
|---|---|---|
| `./circuit.js` / `../x.ts` | internal | 先按原样找；找不到则**把 .js/.jsx/.mjs/.cjs 后缀换成 .ts/.tsx 再找**；再试目录 index.{ts,js}；仍找不到 → unresolved |
| `@safetrace/shared` | workspace | 由根 package.json 的 workspaces + 各包 package.json 的 name 建映射 → 该包入口（main/exports/index.ts）|
| `node:fs/promises` / `fs` | builtin | null（Node 内置名单硬编码一份，标注「名单可能不全」）|
| `tsx` / `@types/node` | external | null + package=specifier 的包名部分 |
| `import('…')` 动态 | dynamic | 字面量可解析则同 internal，否则 unresolved |
| Python `from . import x` / `from ..pkg import y` | internal | 按文件所在目录 + level 上溯换算路径；找不到 → unresolved |
| Python `import papertrace.llm.client` | internal 或 external | 仓库内存在该路径 → internal；否则 external |

**unresolved 必须计数上页面**（`totals.unresolved_imports`），并在 import 表里逐条显示原因，不许静默丢弃。

## 11. 图与入口（T6）

- 节点 = 源码文件（file-only 语言也进图，只是没有出边）；边 = resolved.kind ∈ {internal, workspace} 的 import。
- `reachable_from_entries`：从所有 entries.target 出发 BFS；没有 target 的入口（如 `smoke` 这种复合命令）如实记「命令未指向单文件」。
- 环：Tarjan 或 DFS 找回边，列出**具体环路径**（不只是「有环」）。
- 分层：按到入口的最短距离给 layer（0 = 入口本身），用于页面排序；**标注这是启发式排序，不是架构分层**。
- 图规模守卫：节点 >400 或边 >1,500 时，页面只画**入口可达子图的前 N 个节点**并明示「已截断，完整图见 repo.json」。

## 12. 讲解页结构（七块，顺序即阅读顺序）

```
① 这是什么项目      README 首段 + manifest description + 语言构成 + 规模三个数
② 怎么跑起来        入口清单（npm scripts / py scripts / main_guard），每条给可复制命令
③ 仓库地图          目录树（前两层 + 文件数）+ 包地图（六包各自文件数与职责一句）
④ 谁依赖谁          文件级 import 图 SVG（程序画）+ 外部依赖表 + 环与 unreachable 如实列出
⑤ 逐个讲            按包/目录分组的 file_card：职责一句 + 符号表 + 关键代码片段（带行号）
⑥ 体检与局限        totals + degraded 逐条 + 排除规则与计数 + 未溯源汇总 + approx 文件数
⑦ 甜头（可选）      仅当输出目录存在旧 trace.json 时出现：模型指标 + 论文对账摘要 + 链接
```

- 每块 `<section class="blk" data-component="…">`；**空块整层不出现**（不是留个空壳）。
- 页面顶部一行「本页由程序生成事实 + <程序叙述|模型名> 生成文字；N 处数字未溯源」。
- 单文件、离线、零外链、零 `<script>`；SVG 的 xmlns 允许（沿用旧 GC）。
- 末尾相对链接指回 index.html（若存在）与 repo.json。

## 13. 讲解文字与守卫（T7/T8/T9）

- **无 key（默认）**：`narrate.program(facts)` 用确定性模板写人话，例如「这个仓库有 6 个包、341 个源码文件；入口有 43 条 npm 脚本，最常用的是 gateway:serve，它跑 src/gateway/src/server.ts」。**每个数字都来自 facts，未溯源数必须为 0**（这是验收断言）。
- **有 key**：`narrate.model(facts, outline)` 把 facts 摘要 + 组件清单 + 受限 markdown 规则交给模型，模型返回 blocks（组件名 + 参数 + 文字 + cites）；程序校验组件名/必填参/cites 的 fact id 真实存在，然后渲染。
- 受限 markdown 子集：`##/###`、空行分段、`- ` 与 `1. ` 列表、**粗体**、单反引号行内代码；链接/图片/裸 HTML/表格/脚注**不支持 → 原样当纯文本 + notes 提示**（不静默丢）。
- custom 块：允许任意 HTML + 内联 style，**禁 `<script>`、事件属性、外链、iframe/object/embed、javascript: 与 data: URL**；用 `html.parser.HTMLParser` 逐标签重建（禁正则剥标签）；被剥离的构造计数并在块顶明示「本块已移除 N 处不允许的构造」。
- 未溯源数字：用 `re.split(r'(<[^>]*>)')` 分离标签与文本，跳过 `<code>` 子树，数字正则 `r'\d[\d,]*(?:\.\d+)?%?'`；只包 mark，**数字原样保留**。

## 14. MCP 协议与六工具（T10）

- 传输：**换行分隔 JSON-RPC 2.0 over stdio**，纯标准库 `sys.stdin` 逐行读 + `json`；protocolVersion `2024-11-05`；实现 initialize / notifications/initialized / tools/list / tools/call / ping；错误码 -32601（方法不存在）/-32602（参数错）/-32603（内部错）；**工具级失败用 result.isError=true + 人话原因**，不是协议错误。
- 入口 `python -m repolens.mcp`（也提供 `python -m repolens serve`）。

| 工具 | 参数 | 返回 |
|---|---|---|
| `analyze_repo` | path, out?, excludes? | repo.json 路径 + totals + degraded 摘要 |
| `get_facts` | repo_json, scope(all/file/pkg/entry/graph), key?, page?, page_size=40 | 分页事实 + total + 下一页游标 |
| `read_source` | repo_root, path, from_line, to_line | 带行号文本；**只许仓库内、单次 ≤200 行、拒绝 .env 与密钥类** |
| `list_components` | — | 组件名 + 必填参 + 说明 + 示例 |
| `explain_outline` | repo_json | 程序建议的讲解骨架（块顺序 + 每块可用 fact id）|
| `render_explain` | repo_json, payload(blocks), out, mode?, model_name? | explain.html 路径 + report{untraced, removed, notes, bytes, blocks} |

## 15. CLI 与退出码

```
python -m repolens analyze <path> --out <dir> [--force] [--no-default-excludes] [--max-files N]
python -m repolens explain <path> --out <dir> [--force] [--llm] [--model NAME]
python -m repolens facts <repo.json> --scope file --key src/gateway/src/index.ts
python -m repolens serve            # MCP stdio
```

退出码（复用 papertrace/exit_codes.py 的既有值，不新造）：0 成功；1 产物不合法/参数错；2 渲染失败或功能未实现（UNIMPLEMENTED）；3 输出冲突未加 --force；4 缺运行时（MISSING_RUNTIME，如配了 --llm 但无 key 且要求必须用模型）；5 无法解析（UNTRACEABLE，如路径不存在或零文件）。

## 16. 文件清单与行数预算（每个 ≤200 行，零新依赖）

```
repolens/__init__.py            6    repolens/__main__.py          12
repolens/cli.py               170    repolens/scan.py             150
repolens/exclude.py            90    repolens/manifests.py        160
repolens/entries.py           120    repolens/lang/__init__.py     40
repolens/lang/python.py       150    repolens/lang/tsjs.py        190
repolens/lang/vue.py           60    repolens/lang/generic.py      30
repolens/resolve.py           170    repolens/facts.py            180
repolens/fact_ids.py           90    repolens/graph.py            150
repolens/schema/repo.json     200    repolens/explain/__init__.py   4
repolens/explain/outline.py   120    repolens/explain/narrate.py  170
repolens/explain/markdown.py  130    repolens/explain/guard.py    190
repolens/explain/components.py 90    repolens/explain/comp_repo.py 180
repolens/explain/comp_file.py 180    repolens/explain/comp_text.py 120
repolens/explain/render.py    160    repolens/explain/templates/repolens.html.j2  190
repolens/mcp/__init__.py        4    repolens/mcp/__main__.py      10
repolens/mcp/server.py        150    repolens/mcp/tools.py       120
repolens/mcp/handlers.py      190
```

约 33 个新文件。**复用不重写**：papertrace/paths.py（路径便携化）、papertrace/llm/*（OpenAI 兼容后端，可注入 transport）、papertrace/exceptions.py、papertrace/exit_codes.py、papertrace/schema_validate.py（jsonschema 已在 pydeps）。复用方式：`from papertrace import paths` 直接 import，不复制代码（避免两份真源）。

## 17. 测试策略与夹具

- 合成夹具入库：`tests/fixtures/repos/py-mini/`（3 文件，含相对 import 与 main_guard）、`ts-monorepo/`（根 package.json + 两包 + .js→.ts 相对 import + workspace import + node: 内置 + 动态 import）、`vendored-mix/`（node_modules/third_party/pythoncore-3.14-64 各放一个 .py + 一个 >1MB 文件 + 一个 .env.local + 一个 png）、`empty/`（零文件）、`broken/`（一个 SyntaxError 的 .py + 一个括号不配对的 .ts）。
- 每个任务：先写红测试 → 跑红（记录原文）→ 实现 → 跑绿 → **≥2 条变异探针**（改产品代码看对应测试是否真红，内存字节还原 + sha256 核）→ 一次提交。
- 每任务跑**全量**（基线 854 + 新增），旧 papertrace 零回归是硬门。
- 真项目 smoke 只在 T10 手动跑，产物落 output/，**不入库、不进测试断言**（避免依赖本机私有路径）。

## 18. 全局约束（继承 + 新增）

继承旧切片 GC1–GC28 中仍适用的：单文件 ≤200 行；零新依赖（stdlib + pydeps 里的 pytest/jsonschema）；TDD 红→绿；每任务一提交；独立评审；产物单文件离线零外链；数字可溯源；不静默兜底；行数用 splitlines、字节用 read_bytes；扫代码按行/AST 不按全文正则；禁 tmp_path 用 tests/_tmp.py::scratch_dir；子进程必须显式传 PYTHONPATH；core.autocrlf=true 故禁 git checkout -- 还原，一律内存字节。

新增：
- **GC29**：绝不执行被分析仓库的任何代码（不 import/exec/subprocess 跑它的脚本）。
- **GC30**：绝不读 .env* 与密钥类文件的内容；只登记文件名。
- **GC31**：排除与截断必须计数并上页面；隐藏排除等于造假规模。
- **GC32**：每个文件的 parse 精确度（exact/approx/file-only/skipped）必须如实标注并在页面汇总。
- **GC33**：unresolved import 必须计数 + 逐条给原因，不许猜 target。
- **GC34**：旧 papertrace 管线与 854 条测试零回归；新代码不得修改 papertrace/ 下任何文件（只许 import 复用）。

## 19. 风险与已知局限（第一版就写进页面，不装作支持）

| 风险 | 处置 |
|---|---|
| TS 词法近似漏掉复杂 import（多行、别名、re-export） | 标 approx + degraded；unresolved 计数上页面；第二版再补 |
| 大仓扫描慢（SafeTrace 排除后 486 文件，但 PokemonData 有 8k png） | 语言白名单 + 目录排除 + 大小守卫 + 20,000 上限；实测计时写进报告 |
| 入口命令是复合 shell（`a && b`）无法指向单文件 | 如实记「命令未指向单文件」，不猜 |
| 模型编造职责描述 | 宽松未溯源标记 + 页顶汇总；cites 假 fact id 响亮拒绝 |
| 讲解页仍然「看不懂」 | ①②③ 块必须是人话且无 key 可读；T9 验收由控制器真跑 SafeTrace 后逐块读一遍 |
| 私有代码泄漏 | D10：真项目产物只落 gitignore 的 output/；页面零绝对路径 |

## 20. 任务划分（T1–T10，三阶段）

| 阶段 | 任务 | 交付 | 依赖 |
|---|---|---|---|
| A 事实层 | T1 scan+exclude | 走树、语言识别、排除计数、安全守卫 | — |
| A | T2 manifests+entries | 包/workspace/scripts/依赖/入口 | T1 |
| A | T3 lang/python | ast 精确符号与 import | T1 |
| A | T4 lang/tsjs+vue+resolve | 词法近似 + import 解析规则表 | T1,T2 |
| A | T5 facts+schema+fact_ids | repo.json 组装与校验、台账 | T1–T4 |
| A | T6 graph | 文件级图、可达、环、分层 | T5 |
| B 讲解页 | T7 markdown+guard+outline | 受限 markdown、custom 守卫、骨架 | T5 |
| B | T8 components+render+模板 | explain.html（程序叙述版） | T6,T7 |
| B | T9 cli+narrate+README | analyze/explain/facts 命令、无 key 降级、有 key 模型路 | T8 |
| C 交付 | T10 mcp+docs+smoke | 六工具 stdio server、Agent 文档、真项目 smoke、演示产物 | T9 |

## 21. 验收标准（六条，全部要真跑证据）

1. `python -m repolens analyze D:\AgentPrograms\safetrace --out output/safetrace` exit 0；repo.json 过 schema；totals.files=486（按本设计规则）、packages=6、entries=43、approx_files=326；excluded 与 oversize 计数非零且逐条可解释。
2. `python -m repolens explain D:\AgentPrograms\safetrace --out output/safetrace` exit 0；explain.html 单文件离线、零外链零 script、七块中 ①–⑥ 非空、⑦ 不出现（无旧 trace）；**无 key 时未溯源数 = 0**；控制器逐块读一遍确认「能读懂这项目干什么、怎么跑」。
3. `python -m repolens analyze .`（自举）exit 0，Python 文件 parse=exact，入口含 main_guard。
4. MCP：initialize → tools/list 返回六工具 → tools/call analyze_repo/get_facts/read_source/render_explain 各一次成功；read_source 越界与 .env 请求被拒；假 fact id 的 render_explain 返回 isError。
5. 全量 pytest = 854 + 新增，**零失败**；旧 papertrace 产物（三份 demo）逐字节不变。
6. 每个新文件 ≤200 行；零新依赖；真项目代码未入库（git status 干净、output/ 被忽略）。
