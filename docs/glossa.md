# 笺疏 Glossa：把任意代码仓库解析成事实台账，再讲成人话

`glossa` 只做两件事：把仓库扫成一份**可以复算的 JSON 事实台账**（`repo.json`），再把台账里的事实**逐块**讲成一张**单文件、离线、无脚本**的 HTML 讲解页（`explain.html`）。没有 API key 也能用——程序版讲解的每个数字都能在台账里指出来源，页头会写「本页有 0 处数字未溯源」。

## 三条命令（可直接复制）

```powershell
cd D:\AgentPrograms\PaperTrace
$env:PYTHONPATH='D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps'

# 1) 只扫事实：写 <out>/repo.json
python -m glossa analyze --repo D:\path\to\repo --out output\glossa

# 2) 写讲解页：<out>/explain.html（默认程序版；加 --llm 才是模型版）
python -m glossa explain --repo D:\path\to\repo --out output\glossa --force

# 3) 按 kind 翻台账（可分页），13 类 kind 见 --help
python -m glossa facts --repo D:\path\to\repo --kind file --limit 20
```

常用开关：`--force` 覆盖已有输出（不带则 exit 3）、`--max-files N` 限制扫描文件数、`--no-default-excludes` 关掉默认排除、`--bonus-trace <旧 trace.json>` 与旧产物对账。

## 两样产物

- **repo.json**：11 个顶层键 `meta / totals / files / packages / projects / entries / imports / graph / excluded / degraded / facts`，过 `glossa/schema/repo.json` 校验。`files` 每行都有 `path / bytes / lines / lang / parse / symbols / imports`；`graph` 有 `nodes / edges / cycles / layers / unreachable / truncated_nodes`。
- **explain.html**：一张单文件离线页，不带 JS、不引外链，折叠全靠 `<details>`。页头写明「本页由程序生成，未使用模型」或模型徽章，以及未溯源数字的处数。

## 退出码

| 码 | 含义 |
| -- | ---- |
| 0 | 成功 |
| 1 | 生成或读到的 repo.json 过不了 schema |
| 2 | 构建或渲染失败（BuildError；含解释页超过 HTML_MAX_BYTES） |
| 3 | 输出已存在且没给 --force |
| 4 | 缺运行时，或 --llm 指定的模型后端不可用（**绝不静默降级**） |
| 5 | --repo 不存在或不是目录 |

## 语言精确度（parse 字段的真实含义）

| 语言 | parse | 到什么程度 |
| ---- | ----- | ---------- |
| python | exact | 真的 `ast.parse`：符号、import、docstring 首行、`if __name__` 守卫 |
| typescript / javascript | approx | 掩码 + 正则近似解析；不建嵌套符号父子关系；JSDoc 不解析 |
| vue | approx | 只抓 `<script>` / `<script setup>` 里的导出；模板表达式不追 |
| csharp | approx | 只到**项目级**（`.csproj` / `.sln`）引用图，文件内符号是近似的 |
| json / markdown / yaml / toml / shell / css / html / xaml / sln / csproj / text | file_only | 只登记路径、字节、行数，不产生符号与 import |
| 其它未注册语言 | skipped | 记「尚无 <lang> 解析器」，不崩 |
| 非法 UTF-8 / 语法错 | skipped | strict 解码失败或 parser 失败时如实记 skipped + degraded，不中断整仓 |

## 排除规则与计数

- 内置 **36 个默认目录名**（大小写不敏感）：`node_modules`、`.git`、`dist`、`build`、`vendor`、`__pycache__`、`.venv` 等
- 规则名协议（命中即计数，不静默）：`dir:<小写目录名>`、`dir:pythoncore`、`dir:dataset`、`ignore:<.glossaignore 行原文>`
- `.glossaignore`：仓库根一份，每行一个 glob，`#` 开头是注释，`dir/` 形式只配目录
- 密钥名单（`.env`、`*.pem`、`id_rsa` 等）**只登记文件名与字节数，内容一个字节都不读**
- 每次排除都进 `excluded.files / excluded.bytes / excluded.by_rule`；超限进 `oversize`，截断选点进 `degraded`

## 14 种 fact id（讲解页每个数字的出处）

`fact:files`（总文件/字节/行/符号）、`fact:file:<path>`、`fact:symbol:<path>#<name>`、`fact:import:<n>`、`fact:pkg:<name>`、`fact:project:<name>`、`fact:entry:<name>`、`fact:namespace:<name>`、`fact:graph`、`fact:excluded`、`fact:degraded`、`fact:source:<path>:<start>-<end>`、`fact:totals`、`fact:bonus`

每条 fact 都带 `numbers`（严格是 `text` 里真出现的数字）与 `cites` 追溯链；页面上的数字如果找不到出处，会被黄标标出并在页头计数。

## 讲解页的七块骨架

1. **这项目是什么** — `overview` + `text` + `metrics`
2. **从哪进来** — `text` + `entry_list`
3. **分几块** — `text` + `package_map`（有包才出现）+ `project_map`（有项目才出现）+ `dir_tree`
4. **谁依赖谁** — `text` + `import_graph`
5. **关键文件逐个讲** — `text` + 每个文件一对 `file_card` + `symbol_table`（最多 12 个）
6. **我没看清的地方** — `text` + `table`（按 scope/reason/count 列出全部降级说明）
7. **甜头** — `bonus`，只在 `--bonus-trace` 给了旧 trace.json 时出现

## 没有 API key 时会怎样

- 不加 `--llm`：直接出程序版，`untraced` 必须是 0——每句话的数字都来自 cites 的 numbers，取不到出处就整句不写。
- 加 `--llm` 但两个后端环境变量（`GLOSSA_LLM_BACKEND` / `PAPERTRACE_LLM_BACKEND`）都没配或都是 `offline`：仍出程序版，stdout 明写「未配置模型后端，本页由程序生成」，exit 0。
- 配了但缺 key 或调用失败（`LLMUnavailable`）：**exit 4 并如实报错**，不会偷偷退回程序版。
- 模型返回的不是合法 JSON 数组，或引用了台账里不存在的事实：`BuildError` → exit 2，整页拒绝，不塞进页面。

## 已知局限（挑活儿之前先看）

1. **TS/JS 是近似解析**：掩码 + 正则，不做完整语法分析；嵌套函数不建父子关系，JSDoc 不解析，类型别名与泛型参数不算符号。
2. **Vue 只认 `<script>` / `<script setup>` 里的导出**：`<script setup>` 里没 `export` 的局部函数抓不到；模板里的组件引用不产 import 边。
3. **re-export 不追**：`export * from './x'` / `export { y } from './x'` 只登记一条转发 import，不把目标文件的符号搬过来，链式依赖可能少边。
4. **C# 只到项目级图**：`.csproj` / `.sln` 的引用关系是准的，文件级 `using` 只能尽力对齐命名空间，跨项目符号重名不消歧。
5. **不执行被分析的代码**：动态 `import()`、`importlib`、`eval`、运行时拼出来的路径一律看不见，这类边永远不会出现在图里。
6. **不读密钥内容**：`.env`、`*.pem`、`id_rsa` 等只登记文件名与字节数，内容一个字节都不进 repo.json。
7. **大仓会截断**：超过 `--max-files`（默认 20000）时按连接数选点，图与统计都不完整，`graph.truncated_nodes` 与 degraded 里会写明；单文件超过 1 MB 记 `oversize`。
8. **非 UTF-8 文件直接跳过**：strict 解码失败即 `parse='skipped'` 并记字节位置，不做编码猜测。
9. **清单/文档文件不进关系图**：`package.json`、`.md`、`.toml` 等 `file_only` 文件没有 import 边，所以「N 个文件没有进入关系图（其中 M 个是清单、文档等不产生 import 的文件）」里的 M 不是 bug。
10. **只认仓库根一份 `.glossaignore`**：不支持子目录各自的忽略文件，也不支持 gitignore 语法。
11. **讲解页不带 JS**：折叠靠 `<details>`；整页超过 `HTML_MAX_BYTES` 时直接失败（exit 2）而不是截断——宁可不出页，也不出半张页。
