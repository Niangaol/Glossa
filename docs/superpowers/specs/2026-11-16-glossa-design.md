# 笺疏 Glossa 设计文档：任意代码仓库的静态解析与人话讲解

- 日期：2026-11-16　仓库：D:\AgentPrograms\PaperTrace　分支：master　BASE：03a6838
- 产品名：**笺疏**（英文 **Glossa**）；包名与命令：`glossa` / `python -m glossa`。仓库目录名不改（仍 PaperTrace），旧 `papertrace` 包原样保留为「甜头」。
- 配套实施计划：docs/superpowers/plans/2026-11-16-glossa.md（T1–T11，含完整红测试代码与变异锚串）。
- 本文取代 2026-11-16-papertrace-explain-design.md（旧 explain 切片 E1–E8 **全部作废**）。

## 1. 一句话定位

**给一个普通代码仓库，笺疏不运行它、不装它的依赖，只读源码，产出一页人能读懂的讲解**：这项目是干什么的、分几块、从哪进来、谁依赖谁、每个关键文件里有什么、哪些地方我没看清（如实说）。配了模型 key 就让模型写讲解文字，没配就用程序生成的事实叙述，两者都明示来源。

## 2. 为什么重做（用户原话 + 实测）

- 用户 m12564：「读起来看不懂😵‍💫 …我觉得一开始方向走错了，做代码仓库的解析和讲解为主，这部分做甜头吧」。
- 用户 m12709：「但是 很多时候这些项目都只是一些普通的代码项目，你可以参考本机的一些项目比如 D:\AgentPrograms\safetrace」。
- 用户 m12720：「事实上我希望你重做 这个方向已经错的有点离谱了。。。你先写计划吧」。
- 实测结论：旧 `python -m papertrace build` 要求「Python 模块:工厂函数 + torch.fx 追踪」，**SafeTrace 与 PokemonData 一个都分析不了**。旧页面 72% 体量是 128 个算子节点平铺，零句人话。

## 3. 三个真项目的实测事实（设计依据，全部真跑）

### 3.1 SafeTrace（D:\AgentPrograms\safetrace，TypeScript ESM monorepo）

| 项 | 实测值 |
|---|---|
| 排除后保留文件 | **486**（typescript 326 / json 78 / vue 24 / markdown 20 / javascript 15 / shell 8 / yaml 8 / python 2 / css 2 / html 1） |
| src/ 下 ts+js | **255**；逐包 shared 27 / gateway 26 / ingest 53 / enrich 41 / qa 90 / assets 18 |
| npm workspaces | 六包：src/{shared,gateway,ingest,enrich,qa,assets} |
| npm scripts | **43 条**（gateway:serve → tsx src/gateway/src/server.ts；qa:serve；cli:ask；check = typecheck && test && …） |
| 依赖 | dependencies 空；devDependencies = @types/node / tsx / typescript |
| vendored 干扰 | third_party/ **11,557 个 .py**；Python/ 是嵌入式运行时（bin、pythoncore-3.14-64、_cache，1,344 个 .py） |
| 排除命中 | node_modules 2 / .git 1 / third_party 1 / .tmp 1 / tmp 1 / var 1 / snapshots 1 / qdrant-config 1 / qdrant-storage 1 |
| >1MB 跳过 | **8 个**（含 11,777,947 字节 zip、两个 >1MB pdf） |
| 密钥类 | .env.example / .env.local → **只登记文件名，绝不读内容** |
| 真实 import 形态 | `from "@safetrace/shared"`（workspace 包名）、`from "./circuit.js"`（**后缀 .js 但实际文件是 .ts**）、`from "node:child_process"`（内置）、`import type { … }`（type-only）、`import path from "node:path"`（default） |

### 3.2 PokemonData（D:\AgentPrograms\PokemonData，.NET 8 WPF + Web + Vue）

| 项 | 实测值 |
|---|---|
| C# 源码 | **108 个 .cs，全在 src/ 下**（排除 bin/obj/.nuget-packages/publish/dataset/screenshots 等之后） |
| 项目 | 五个 csproj：src/PokemonDex.{App,Core,Core.Tests,Web,Web.Tests}；根 **PokemonDex.sln** |
| sln 陷阱 | Project 条目里有一个解决方案文件夹 `('src','src')`，**不是真项目，必须按 .csproj 后缀过滤** |
| 其它 | .xaml **7**（WPF 视图，第一版只文件级）、.vue **13** |
| 真实 C# 形态 | `using CommunityToolkit.Mvvm.ComponentModel;`（外部 NuGet）、`using System.Linq;`（内置）、**`namespace PokemonDex.App.ViewModels;`（file-scoped，C# 10）**、`public partial class MainViewModel : ObservableObject`（partial + 基类）、`[ObservableProperty]` 特性、`private readonly IHost _host;` 字段、`public ObservableCollection<MenuItemViewModel> MenuItems { get; } = new();` 属性、泛型 `ILogger<MainViewModel>` |
| csproj 形态 | SDK 风格 XML：`<TargetFramework>net8.0</TargetFramework>`、`<RootNamespace>PokemonDex.Core</RootNamespace>`、**`<ImplicitUsings>enable</ImplicitUsings>`（隐式全局 using，必须记 degraded）**、`<Nullable>enable</Nullable>`、`<PackageReference Include="Microsoft.Data.Sqlite" Version="8.0.11" />` |

### 3.3 PaperTrace 自身（自举验证用）

86 个产品 .py + 53 个测试文件；纯 Python、无 package.json；入口是 `python -m papertrace`（__main__.py）与 `if __name__ == '__main__'`。旧管线产物 nodes=128 / edges=101 / modules=34 / params=29,856 / est_flops=884,736（GC8 基线，**新代码不许动它**）。

## 4. 已拍板清单（用户明确选择的，不再问）

| 编号 | 用户决定 | 出处 |
|---|---|---|
| U1 | 主线＝代码仓库解析与讲解；torch 模型 + 论文对账降为**甜头** | m12564 / m12709 |
| U2 | **重做**，先写计划 | m12720 |
| U3 | 讲解页另做一页，旧事实页保持档案（方案三） | m12582 |
| U4 | 架构＝程序出事实、AI 写文字、程序管排版与图；**先做 MCP server**，后续应用化 | m11668 / m11673 |
| U5 | 模型自由度放大：组件库 + 一个 custom 块写任意 HTML；**宽松守卫**——查不到出处的数字打可见「未溯源」标记但照常渲染 | m11687 / m11692 |
| U6 | 旧 papertrace **原样保留当甜头，新包并存**（86 文件 / 854 测试一行不改） | 本轮答复 |
| U7 | 语言范围＝Python 精确 + TS/JS/Vue 近似 + **再加 C# 符号级** | 本轮答复 |
| U8 | 产品名 **笺疏 / Glossa**，包名 glossa | 本轮答复 |
| U9 | **计划要写得更细致**（完整红测试代码、精确签名、夹具内容、变异锚串、逐步命令） | 本轮答复 |

## 5. 控制器裁决（D1–D14，用户可否决）

- **D1 并存不迁移**：新包 `glossa/` 与旧 `papertrace/` 同级；只 import 复用旧基础设施（paths / llm / exceptions / exit_codes / schema_validate / report_dump），**不改旧文件一个字节**。理由：854 条测试是既有资产，迁移风险远大于收益。错了的代价：若用户后来想合并，需要一次专门的迁移切片。
- **D2 精确度自报**：每个文件带 `parse` ∈ {exact, approx, file_only, skipped}，页面与 repo.json 都如实显示；**不许把近似结果说成精确**。
- **D3 第一版不做函数级调用图**：只做文件级（Python/TS）与项目级（C#）依赖图。理由：无类型信息时函数级调用图必然大量猜错，违背「宁可不说话也不说假话」。
- **D4 绝不执行被分析仓库的代码**（GC29）：不 import、不 exec、不 subprocess 跑它的脚本、不 npm/pip/dotnet install。
- **D5 密钥只登记名**（GC30）：.env*、*.pem、*.key、*.pfx、id_rsa 等只记文件名与字节数，**内容一个字符都不读进内存**。
- **D6 排除显式计数**（GC31）：默认排除清单 + .glossaignore + >1MB 跳过 + 20,000 文件上限，全部计数并上页面；截断必须明示「本页只覆盖前 N 个文件」。
- **D7 无 key 也要能读**：程序生成确定性人话叙述，**未溯源数字必须 = 0**；有 key 时模型只写文字，未命中数字打 mark 照常渲染 + 页顶汇总。
- **D8 两条入口都要**：CLI（`python -m glossa`）+ MCP server（`python -m glossa.mcp`，手写换行分隔 JSON-RPC 2.0 over stdio，零依赖）。
- **D9 甜头块条件出现**：只有当输出目录或指定路径存在旧 `trace.json` 时，讲解页才出现「模型与论文」块；否则整层不渲染。
- **D10 真项目只手动 smoke**：SafeTrace / PokemonData 的产物落 output/（gitignore），**私有代码绝不入库**；自动化测试只用合成夹具。
- **D11 C# 图是项目级不是文件级**：C# 的 `using` 指向命名空间而非文件，一个命名空间可能对应几十个文件；硬画文件级边会造假。裁决：C# 画 **csproj 之间的 ProjectReference 图** + 命名空间归属表；文件级 import 图只对 Python/TS/JS 画。
- **D12 C# using 分类四态**：builtin（System.* 等框架前缀）/ external（命中 csproj 的 PackageReference 名前缀）/ namespace（命中仓库内声明的命名空间）/ unresolved（其余）。**namespace 态 target 为 null**（不猜具体文件），但记 `namespace` 字段与命中文件数。
- **D13 ImplicitUsings 记 degraded**：csproj 里 `<ImplicitUsings>enable</ImplicitUsings>` 意味着有一批隐式全局 using 看不见 → 该项目的 C# 文件 degraded 记「隐式全局 using 未展开，依赖可能少计」。
- **D14 讲解页人话优先**：① 这项目是什么 ② 从哪进来 ③ 分几块（包/项目地图）④ 谁依赖谁（图）⑤ 关键文件逐个讲 ⑥ 我没看清的地方（排除/降级/未解析）⑦ 甜头（可选）。**事实表折叠在 <details> 里，不占首屏**。

## 6. 目标 / 非目标 / 反目标

**目标**：① 任意普通仓库（Python / TS·JS·Vue / C# / 其它）零执行零安装地分析；② 产出 repo.json（过 schema）+ 单文件离线 explain.html；③ 无 key 可读、有 key 更好读；④ MCP 六工具供外部 Agent 取事实与渲染；⑤ 旧管线零回归。
**非目标（第一版明确不做）**：函数级调用图、类型推断、跨语言调用链、增量分析、watch 模式、Web UI、执行/构建被分析项目、C# 的 .xaml 解析（只文件级）、Rust/Go/Java 符号级。
**反目标（做了就是错）**：把近似说成精确；把 unresolved 猜成同名文件；把 vendored 代码当项目代码讲；读 .env 内容；为了页面好看而编数字；静默吞掉解析失败。

## 7. 三层架构

```
scan（排除/大小/语言/密钥名）
  → lang/{python,tsjs,vue,csharp,generic}（符号 + import/using + docstring 首句 + parse 精确度）
  → manifests（package.json / pyproject / requirements / csproj / sln）+ entries（npm scripts / py scripts / main_guard / dotnet）
  → resolve（import/using → internal | workspace | builtin | external | namespace | dynamic | unresolved）
  → facts（repo.json 11 顶层键 + 14 种 fact id）→ graph（文件级 / 项目级 + 环 + 可达 + 分层 + 截断）
  → outline（七块骨架，程序定）→ narrate（程序版确定性 / 模型版只写字）
  → components（14 个，程序画图与表）→ render（Jinja2 StrictUndefined，单文件离线）
  → cli（analyze / explain / facts / serve）+ mcp（stdio JSON-RPC 六工具）
```

## 8. repo.json 字段规格（11 个顶层键，一个不多一个不少）

| 键 | 形状 | 来源 |
|---|---|---|
| meta | {repo:{url,commit,language,root_name}, created_at, tool:{name:'glossa',version}, scan_opts} | scan + **只读 .git/HEAD 与 refs 文件**（绝不起 subprocess；读不到记 'unknown' + degraded） |
| totals | {files, by_lang:{}, symbols, imports, packages, projects, entries, edges, cycles, unreachable, excluded_files, excluded_bytes, oversize, degraded, unresolved} | facts 汇总 |
| files | [{path, lang, bytes, lines, parse, package_hint, project_hint, doc_first_line, symbols:[…], imports:[…], degraded:[…]}] | lang/* |
| packages | [{name, path, manifest, deps, dev_deps, scripts, workspace}] | manifests |
| projects | [{name, path, csproj, target_framework, root_namespace, implicit_usings, package_refs, project_refs, files, namespaces}] | manifests_cs |
| entries | [{kind, name, command, target, package, note}] | entries |
| imports | [{from, specifier, kind, target, package, namespace, line, type_only}] | resolve |
| graph | {nodes, edges, cycles, reachable_from_entries, unreachable, layers, level:'file'|'project', truncated, omitted_isolated}；edge 带 count（同 from/to/kind 的 import 合并条数） | graph |
| excluded | {rules:[{rule,hits}], files, bytes, oversize:[{path,bytes}], truncated, secrets_seen:[…]} | scan |
| degraded | [{scope, reason, count}] | 各层如实登记 |
| facts | {fact_id: {numbers:[int], text:str}} | fact_ids |

## 9. 语言解析口径

| 语言 | 手段 | parse | 支持 | 不支持（如实说） |
|---|---|---|---|---|
| Python | `ast.parse` | **exact** | import/from（含相对 level）、def/async def/class（含嵌套与 parent）、行号与 end_line、模块 docstring 首句、main_guard | 动态 getattr 调用、运行时 import |
| TS/JS | 掩码视图 + 正则 | **approx** | import/export（含多行、type-only、default、namespace）、动态 import()、export const/function/class/interface/type/enum、行号 | 类型推断、re-export 链追踪、JSX 内部结构 |
| Vue | 切第一个 <script> 块后转 TS/JS | **approx** | script 内的 import 与**带 export 关键字**的符号，行号按偏移还原（实测 App.vue 开标签行 4、import 行 5） | template 结构、style、组合式 API 语义、**script setup 的顶层绑定**（无 export 关键字 → 不抓，记 degraded） |
| C# | 掩码视图 + 正则 | **approx** | using（含 static/alias）、namespace（**块级与 file-scoped 两种**）、class/interface/record/struct/enum（含 partial、基类列表、泛型）、method/property/field、attribute 名、行号 | 重载解析、扩展方法归属、隐式全局 using（记 degraded）、.xaml |
| 其它（json/yaml/md/sh/css/html/xaml） | 只统计 | **file_only** | 路径、字节、行数、语言 | 一切符号 |
| 二进制/超大/解码失败 | 跳过 | **skipped** | 计数与原因 | 内容 |

## 10. import / using 解析规则表（逐条，例子来自真项目）

| 形态 | kind | target | 例 |
|---|---|---|---|
| `./circuit.js` 且存在 circuit.ts | internal | file:…/circuit.ts | SafeTrace gateway |
| `./x` 无后缀 | internal | 依次试 .ts/.tsx/.js/.jsx/.vue/index.ts | — |
| `@safetrace/shared` | workspace | package:@safetrace/shared（+ 该包入口文件若可确定） | SafeTrace |
| `node:fs/promises` | builtin | null | SafeTrace |
| `react`（在 deps 里） | external | null（记 package） | — |
| `import type { X }` | 同上 + type_only=true | — | SafeTrace |
| `import('./x.js')` | dynamic | 能解析则给 target，否则 null | — |
| `./nope.js` 不存在 | **unresolved** | **null（绝不猜）** | — |
| Python `from ..pkg import y` | internal | file:…（按 level 与包路径推） | PaperTrace 自身 |
| Python `import numpy` | external/builtin | null（标准库名单 → builtin） | — |
| C# `using System.Linq;` | builtin | null | PokemonData |
| C# `using Microsoft.Data.Sqlite;`（命中 PackageReference） | external | null（记 package） | PokemonData |
| C# `using PokemonDex.Core.Models;`（仓库内声明） | **namespace** | **null** + namespace 字段 + 命中文件数 | PokemonData |
| C# `using Foo.Bar;`（都不命中） | unresolved | null | — |
| csproj `<ProjectReference Include="..\PokemonDex.Core\…csproj" />` | internal_project | project:PokemonDex.Core | PokemonData |

## 11. manifest 与入口

- package.json：name / workspaces（数组或 {packages:[…]}）/ scripts / dependencies / devDependencies；workspace 名 → 目录映射。
- pyproject.toml：tomllib 读 [project] name/scripts；requirements.txt 只列名（不解析版本约束）。
- csproj：XML 读 TargetFramework / RootNamespace / ImplicitUsings / Nullable / PackageReference / ProjectReference；**sln 只取 .csproj 后缀的 Project 条目**（解决方案文件夹丢弃并计数）。
- 入口种类：npm_script（命令能指向单文件则给 target，复合命令 target=null + note）、py_script、main_guard、dotnet_project（csproj 的 OutputType=Exe 或 Sdk=Microsoft.NET.Sdk.Web）、module_main（__main__.py）。**绝不猜复合命令的 target**。

## 12. 排除与安全

- 默认排除目录（大小写不敏感）：node_modules、.git、bin、obj、dist、build、out、target、vendor、third_party、__pycache__、.venv、venv、.nuget-packages、publish、.tmp、tmp、var、snapshots、qdrant-config、qdrant-storage、.next、.nuxt、coverage、.pytest_cache、.mypy_cache、.ruff_cache、.idea、.vscode、.agent-teams、.chorography、.video_agent、.zcode、.test-tmp。
- 目录前缀规则：pythoncore-*、python-*（嵌入式运行时）；文件名含 -dataset-、-main 的数据集目录（PokemonData 的 pokemon-dataset-zh-main）→ 规则名 `dir:dataset`。
- 大小守卫：单文件 >1,000,000 字节 → skipped + oversize 记录；总文件 >20,000 → 截断 + truncated=true。
- 密钥名单：.env、.env.*、*.pem、*.key、*.pfx、*.p12、id_rsa、id_ed25519、*.keystore、secrets.*、credentials.* → **只登记名与字节数**。
- .glossaignore：仓库根，每行一个 glob（支持 dir/ 与 *.ext），规则名 `ignore:<行>`。
- 语言白名单之外的扩展名（png/dll/zip/pdf/pyd/h…）→ 只计数不解析。

## 13. 事实台账：14 种 fact id

`fact:totals`、`fact:files`、`fact:file:<relpath>`、`fact:pkg:<name>`、`fact:project:<name>`、`fact:entry:<name>`、`fact:import:<序号>`、`fact:symbol:<relpath>#<name>`、`fact:namespace:<ns>`、`fact:graph`、`fact:excluded`、`fact:degraded`、`fact:source:<relpath>:<起>-<止>`、`fact:bonus`。
每个 id 带 `{numbers:[int], text:str}`；numbers 只收 int、排除 bool、float 整数转 int、升序去重。**引用不存在的 id → 响亮拒绝**；数字未命中 → 只包 mark 照常渲染。

## 14. 讲解层：七块骨架 + 14 个组件

| 块 | 组件 | 内容 |
|---|---|---|
| ① 这项目是什么 | overview + metrics + text | 名字、语言分布、规模、一句话定位（来自 README 首段或 docstring，**注明来源**） |
| ② 从哪进来 | entry_list + text | 真实入口命令与目标文件；复合命令明示「未指向单文件」 |
| ③ 分几块 | package_map / project_map + dir_tree | npm 包地图或 csproj 项目地图 + 目录树（折叠） |
| ④ 谁依赖谁 | import_graph + text | 文件级（py/ts）或项目级（C#）SVG；环与不可达如实列出 |
| ⑤ 关键文件逐个讲 | file_card + symbol_table + code + text | 每个关键文件：干什么、有哪些符号、关键行摘录 |
| ⑥ 我没看清的地方 | table + text | 排除计数、oversize、degraded、unresolved 逐条原因 |
| ⑦ 甜头（可选） | bonus | 仅当存在旧 trace.json：模型算子图与论文对账摘要，链回旧 index.html |

组件全集（14）：`text, custom, overview, metrics, dir_tree, package_map, project_map, entry_list, import_graph, file_card, symbol_table, code, table, bonus`。
每个组件声明 `{name, params(必填/选填), facts(可用 fact id 模式), render(doc, params) -> str}`；空串块整层不出现。

## 15. 受限 markdown / custom 守卫 / 未溯源

- markdown 子集：##/### 标题、空行分段、- 与 1. 列表、**粗体**、单反引号行内代码。**链接、图片、裸 HTML、表格、脚注不支持 → 原样当纯文本 + notes 提示**（不静默丢）。
- custom 块：允许任意 HTML + 内联 style；**禁 <script>、事件属性（on*）、外链（http/https//）、<iframe>/<object>/<embed>、javascript: 与 data: URL**；用 html.parser 逐标签重建（禁正则剥标签）；剥离后在块顶明示「本块已移除 N 处不允许的构造」。
- 未溯源：数字正则 `\d[\d,]*(?:\.\d+)?%?`，与 cites 指向事实的 numbers 集合比对；未命中只包 `<mark class="untraced">`，**数字原样保留**；跳过 <code> 子树；页顶汇总「本页有 N 处数字未溯源」。程序版必须 N=0。

## 16. 无 key 降级 / 有 key 模型

- 无 key：narrate.program(doc) 生成确定性 blocks（模板化人话，但每个数字都来自 facts），页面明示「本页由程序生成，未使用模型」。
- 有 key：复用 `papertrace.llm.client.get_llm`（PAPERTRACE_LLM_BACKEND ∈ {offline,openai,ollama}，新增 GLOSSA_LLM_BACKEND 同义）；模型只返回 blocks（组件名 + 参数 + 文字 + cites），**不写 HTML 结构、不碰事实**；validate_blocks 不过即拒绝渲染。

## 17. CLI 与退出码

```
python -m glossa analyze --repo <path> --out <dir> [--force] [--max-files N] [--no-default-excludes]
python -m glossa explain --repo <path> --out <dir> [--force] [--llm] [--bonus-trace <path>]
python -m glossa facts   --repo <path> [--kind file|pkg|…] [--offset N] [--limit N]
python -m glossa serve   # 等价 python -m glossa.mcp，stdio JSON-RPC
```
退出码沿用 papertrace.exit_codes：0 成功 / 1 trace 不合法 / 2 渲染失败或未实现 / 3 输出冲突（无 --force）/ 4 缺运行时 / 5 路径不存在或不可分析。

## 18. MCP 协议与六工具

- 传输：换行分隔 JSON-RPC 2.0 over stdio；protocolVersion **2024-11-05**；实现 initialize / notifications/initialized / tools/list / tools/call / ping；错误码 -32601（方法不存在）/-32602（参数错）/-32603（内部错）；**工具级失败用 result.isError=true，不是协议错误**；notification 不回包；畸形 JSON 行不杀进程。
- 六工具：`analyze_repo`（返回 totals + out 路径）、`get_facts`（分页，默认 limit 40，带 total）、`read_source`（**只读仓库内**、拒 .env、单次 ≤200 行）、`list_components`（14 个组件的参数与可用 fact 模式）、`explain_outline`（七块骨架 + 每块可用 fact id）、`render_explain`（收 blocks，校验后写 explain.html，返回 untraced/removed/notes/bytes）。

## 19. 页面草图（人话优先，事实折叠）

```
笺疏 · safetrace                     [程序生成 / 模型：xxx] [本页有 0 处数字未溯源]
① 这项目是什么
   SafeTrace 是一个 TypeScript monorepo，六个包……（来源：README.md 首段）
   486 个文件 · 326 个 TS · 24 个 Vue · 6 个包 · 43 条 npm 脚本
② 从哪进来  gateway:serve → src/gateway/src/server.ts …（check 是复合命令，未指向单文件）
③ 分几块    [包地图 SVG]  ▸ 目录树（折叠）
④ 谁依赖谁  [文件级 import 图 SVG]  环 2 处：a→b→a …  不可达 17 个文件
⑤ 关键文件  ▸ src/gateway/src/index.ts（29,743 字节，approx）… 符号表 + 关键行
⑥ 我没看清  排除 node_modules 等 9 类共 12,9xx 个文件；>1MB 跳过 8 个；
            TS/Vue 是近似解析；unresolved import 3 条（逐条原因）
⑦ 甜头      （无旧 trace.json 时整层不出现）
```

## 20. 文件清单（37 个新文件，每个 ≤200 行）

```
glossa/__init__.py 6            glossa/__main__.py 12        glossa/cli.py 170
glossa/exclude.py 90            glossa/scan.py 150           glossa/manifests.py 150
glossa/manifests_cs.py 130      glossa/entries.py 130        glossa/resolve.py 170
glossa/resolve_cs.py 90         glossa/facts.py 180          glossa/fact_ids.py 90
glossa/graph.py 150             glossa/schema/repo.json 200
glossa/schema_repo.py 70        glossa/repo_paths.py 60
glossa/lang/__init__.py 40      glossa/lang/python.py 150    glossa/lang/tsjs.py 190
glossa/lang/masks.py 80         glossa/lang/vue.py 60        glossa/lang/csharp.py 190
glossa/lang/generic.py 30
glossa/explain/__init__.py 4    glossa/explain/markdown.py 130  glossa/explain/guard.py 190
glossa/explain/outline.py 120   glossa/explain/narrate.py 170   glossa/explain/components.py 90
glossa/explain/comp_repo.py 180 glossa/explain/comp_file.py 180 glossa/explain/comp_text.py 120
glossa/explain/render.py 160    glossa/templates/glossa.html.j2 190
glossa/mcp/__init__.py 4        glossa/mcp/__main__.py 10    glossa/mcp/server.py 150
glossa/mcp/tools.py 120         glossa/mcp/handlers.py 190
```
复用（只 import，不改）：papertrace/paths.py 的 **portable_path**、papertrace/llm/*、papertrace/exceptions.py、papertrace/exit_codes.py、papertrace/schema_validate.py 的 **dump_trace**、papertrace/constants.py 的 HTML_MAX_BYTES、Jinja2 Environment 口径。
**不可复用（控制器读源码实测）**：schema_validate.validate_trace（内部 structural_errors 查 nodes/symbols）、paths.relativize_doc 与 paths.leaked_absolute（都只覆盖 trace 的四处字段）——这三个是 trace 专用，glossa 用自己的 schema_repo.py 与 repo_paths.py。

## 21. 新增全局约束 GC29–GC36

- GC29 绝不执行被分析仓库的代码（不 import/exec/subprocess/install）。
- GC30 绝不读 .env* 与密钥类文件内容，只登记名与字节数。
- GC31 排除、跳过、截断必须计数并上页面；不许静默丢文件。
- GC32 每文件 parse 精确度如实标注（exact/approx/file_only/skipped），页面与 json 一致。
- GC33 unresolved import/using 计数 + 逐条原因，**绝不猜 target**。
- GC34 C# 只画项目级图；using 的 namespace 态 target 必须为 null。
- GC35 旧 papertrace/ 下任何文件不许改；每任务全量 pytest 零失败；旧三份 demo 逐字节不变。
- GC36 真项目产物只落 output/（gitignore），私有代码绝不入库；测试只用合成夹具。

## 22. 风险与已知局限（如实写进 README）

| 风险 | 处置 |
|---|---|
| TS/C# 正则解析漏形态 | parse=approx + degraded 如实；夹具覆盖真项目实测形态；漏了就在页面说「没看清」 |
| 大仓扫描慢 | 目录剪枝 + 大小守卫 + 20,000 上限 + 截断明示；SafeTrace 486 文件实测秒级 |
| C# 命名空间 → 文件多对多 | D11/D12：不画文件级边，只给归属表与命中文件数 |
| 隐式全局 using / global using | D13 记 degraded，不假装完整 |
| 模型编数字 | 未溯源 mark + 页顶汇总；假 fact id 响亮拒绝 |
| 私有代码泄漏 | GC36 + 页面零绝对路径（复用 papertrace.paths） |
| 旧管线回归 | GC35 + 每任务全量 + 旧 demo 字节比对 |

## 23. 任务概览（T1–T11，详见实施计划）

| 任务 | 交付 | 依赖 |
|---|---|---|
| T1 | scan + exclude + 夹具三套 | — |
| T2 | manifests + manifests_cs + entries | T1 |
| T3 | lang/python（exact） | T1 |
| T4 | lang/masks + tsjs + vue + resolve | T2 |
| T5 | lang/csharp + resolve_cs | T2 |
| T6 | facts + fact_ids + schema/repo.json | T3,T4,T5 |
| T7 | graph（文件级 + 项目级） | T6 |
| T8 | explain/markdown + guard + outline | T6（可与 T7 并行） |
| T9 | components + comp_* + render + 模板 | T7,T8 |
| T10 | cli + narrate + __main__ + README | T9 |
| T11 | mcp 五文件 + docs + 真项目 smoke + 演示 | T10 |

## 24. 验收（六条，全部要真跑证据）

1. SafeTrace：analyze exit 0，repo.json 过 schema，totals 可解释（486 文件 / 6 包 / 43 入口 / 8 oversize / 2 secrets_seen）。
2. SafeTrace：explain exit 0，单文件离线零外链零 script，①–⑥ 非空、⑦ 不出现，无 key 未溯源数 **0**，控制器逐块读一遍确认「能读懂」。
3. PokemonData：analyze exit 0，108 个 .cs 全 parse=approx，5 个项目 + sln 解决方案文件夹被丢弃并计数，ImplicitUsings 记 degraded，项目级图有 ProjectReference 边。
4. PaperTrace 自举：analyze exit 0，Python 全 parse=exact，main_guard 入口在。
5. MCP：六工具真跑通，越界/.env 拒绝，假 fact id isError，畸形 JSON 不杀进程。
6. 全量 pytest 零失败（854 + 新增），旧三份 demo 逐字节不变，新文件全 ≤200 行，零新依赖，私有代码未入库。
