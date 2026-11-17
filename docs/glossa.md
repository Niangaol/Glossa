# 笺疏 Glossa：把任意代码仓库解析成事实台账，再讲成人话

`glossa` 只做两件事：把仓库扫成一份**可以复算的 JSON 事实台账**（`repo.json`），再把台账里的事实**逐块**讲成一张**单文件、离线、无脚本**的 HTML 讲解页（`explain.html`）。没有 API key 也能用——程序版讲解的每个数字都能在台账里指出来源，页头会写「本页有 0 处数字未溯源」。

## 三条命令（可直接复制）

```powershell
cd D:\AgentPrograms\PaperTrace
$env:PYTHONPATH='D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps'

# 1) 只扫事实：写 <out>/repo.json
python -m glossa analyze --repo D:\path\to\repo --out output\glossa

# 2) 写讲解页：<out>/explain.html（默认程序版；加 --ai 才是 AI 讲解版）
python -m glossa explain --repo D:\path\to\repo --out output\glossa

# 3) 按 kind 翻台账（可分页），13 类 kind 见 --help
python -m glossa facts --repo D:\path\to\repo --kind file --limit 20
```

常用开关：`--force` 对 analyze 是覆盖 repo.json、对 explain 是**重扫并覆盖 repo.json**（不加则优先复用已有台账，只有台账缺失才重扫、并在页脚写明「本页数据来自本次重扫」）；`--max-files N` 限制扫描文件数、`--no-default-excludes` 关掉默认排除、`--bonus-trace <旧 trace.json>` 与旧产物对账。

退出码 3 只属 analyze（输出已存在且没 --force）；explain 每次覆盖已存在的 explain.html（R74，这一点与 `--force` 无关）。explain 读到坏台账时**不静默重扫**：stderr 报原文并以 1 退出。
参数错误由 argparse 以 2 退出，与构建失败同码、靠 stderr 区分。

## 两样产物

- **repo.json**：11 个顶层键 `meta / totals / files / packages / projects / entries / imports / graph / excluded / degraded / facts`，过 `glossa/schema/repo.json` 校验。`files` 每行都有 `path / bytes / lines / lang / parse / symbols / imports`；`graph` 有 `nodes / edges / cycles / layers / unreachable / truncated / truncated_nodes / omitted_isolated / omitted_manifests / project_edges`。
- **explain.html**：一张单文件离线页，不带 JS、不引外链，折叠全靠 `<details>`。页头写明「本页由程序生成，未使用模型」或模型徽章，以及未溯源数字的处数。

## 退出码

| 码 | 含义 |
| -- | ---- |
| 0 | 成功 |
| 1 | 生成或读到的 repo.json 过不了 schema（explain 读到坏台账同样 exit 1，不静默重扫） |
| 2 | 构建或渲染失败（BuildError；含解释页超过 HTML_MAX_BYTES） |
| 3 | analyze 的 repo.json 已存在且没给 --force（explain 不受此码约束） |
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
- 文件级排除逐条归因进 `excluded.rules`（`dir:*` / `ext:*` / `ignore:*`），汇总进 `excluded.files / excluded.bytes`；超限进 `oversize`，截断选点进 `degraded`
- 密钥只登记 `secrets_seen`（路径 + 字节数），**不读内容、不计入 `excluded.files` / `excluded.bytes`**

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

## AI 讲解模式（`--ai`）

程序版（不带 `--ai`）仍是上面那套七块骨架 + 组件库，两种模式**并存**、互不改写：`--ai` 只把「写正文」这一步交给模型，台账、五道内容闸、组装、CSS 全部走同一份实现，产物同样是单文件、离线、无脚本的 `explain.html`。

### 命令

```powershell
$env:PYTHONPATH='D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps'

# 1) 离线桩：不联网、不需要任何 key，只用来验证流水线（页头会写明没调真模型）
python -m glossa explain --repo D:\path\to\repo --ai --llm fake --style magazine --out out --force

# 2) 离线桩换风格：report / cards
python -m glossa explain --repo D:\path\to\repo --ai --llm fake --style report --out out-report --force

# 3) 真模型：先把下面四项配齐，再 --llm openai
python -m glossa explain --repo D:\path\to\repo --ai --llm openai --style cards --out out-cards --force
```

取值口径：`--llm fake` / `--llm openai` 隐含 `--ai`；**裸 `--llm`** 仍是原来那条模型块路径（输出逐字不变）；`--llm ollama` 尚未实现，报 exit 4。

### 三套风格（`--style`，默认 magazine）

| 值 | 名字 | 版式（`glossa/explain/styles.py` 的 layout） |
| -- | ---- | ---- |
| `magazine`（默认） | 技术刊物 | `max_width=680`、单列、右侧旁注栏；纸色底、宋体标题 |
| `report` | 工程报告 | `max_width=960`、两列、左侧粘性目录；白底蓝规线 |
| `cards` | 文件图鉴 | `max_width=1000`、双列卡片；每个关键文件一张卡 |

换风格只换 CSS 与图配色，`<main>` 里的 section / id / 序号 / class **逐字节不变**：实测同一仓的 magazine / report / cards 三页，把颜色值统一替换后 `<main>` 逐字节相同（PaperTrace 11,388 字符、SafeTrace 11,744 字符），`<style>` 三份互不相同。`--style` 写错值由 argparse 以 **2** 退出（实测 `--style bogus` → 2），不猜、也不悄悄回退默认。

### 五道内容闸 + 体积上限：模型写的东西怎么才准上页

一节的 html 与图依次过 `gate_html → gate_numbers → gate_edges → gate_labels → gate_values`（五道**内容**闸）；任何一关判死就丢掉那一样东西，并在本节留一句披露——**页面上不假装成功**。体积闸不判内容，只在写盘之前卡整页字节数（下面第 6 行）。

| 闸 | 实现 | 拦什么 |
| -- | ---- | ---- |
| 安全闸 | `gates.gate_html` | `<script>/<style>/<iframe>/<object>/<embed>/<form>/<link>/<meta>/<base>` 删除、`on*` 事件属性删除、`<a href>` 的危险 scheme 只去 href；**AI 模式连内联 `style` 属性一起剥掉**（R506），程序版保留；`<img>` 只认干净的 `data:image/...`（R505），外链图片整张丢弃 |
| 溯源闸 | `gates.gate_numbers` | 这一节素材包 `facts[].numbers` 之外的数字全部 `<mark class="untraced">` 黄标并计入页头；**空集不放行**（R507）：一个数字都不可溯源时全标，不是全放。正文之外的通道（图注、卡片文字、连线标签、节标题、模型说明）**加不了黄标**（SVG 里塞 `<mark>` 非法、标题会被转义），改由 `gates.count_plain_numbers` 只计数，同样计入页头那一个总数并逐节披露（R518） |
| 连线闸 | `gates.gate_edges` | 图里每条边必须是本节素材 `facts[].edges` 里真有的 `(from, to)`，复用 `patterns.validate_figure`；编的边丢弃并逐个披露 |
| 标签闸 | `gates.gate_labels` | 图上的 label 必须是**人话**且能在本节素材原文里查到（R508）：`fact:` 开头或整串/每个词都查不到的，整张图丢弃并披露（披露里不回声模型编的 label）。**节点、柱状、卡片三种数据一起查**（R515）——bars/cards 图的 `nodes` 是空的，只看 nodes 等于对它们完全失效 |
| 数值闸 | `gates.gate_values` | 柱状图的值必须能在本节素材的 `numbers` 里核上（R516）：数值以文本印进 SVG，数字溯源闸只扫 html 扫不到图数据；编的那一条丢掉、其余照画，一条都核不上就整张图丢弃 |
| 体积闸 | `gates.gate_size` | 全页只有一个上限：`gates.MAX_PAGE_BYTES = HTML_MAX_BYTES = 8,000,000` 字节（R499 唯一真源）；超了由 `assemble.build_page` 在**写盘之前**抛 `BuildError`（exit 2），不截断、不删旧页、不出半张页 |

桩自己的图也守同一条规矩：该节素材凑够 **3 组以上「人话标签 + 真数字」**（语言文件数、各包/各节计数）时，第 1 张图画 `pattern="bars"`（最多 6 条，按值降序，值只取 `facts[].numbers`、标签写「json 文件」这种人话，绝不印 `fact:`）；凑不够就退回 layered / cards，页面照出、不崩（R513）。

### 离线桩与真模型

- **离线桩只用于验证流水线**：`--llm fake` 不联网、不调任何模型，只按真实协议的调用形状返回 JSON。用它出的每一页页头都写着「**本页由离线桩生成，未调用真实模型**」，页头统计行还恒写「未溯源 N 处 · 失败 M 节」（R509，0 也写）——看见「离线桩」三个字就说明这页不是模型写的。
- **真模型**：四项环境变量配齐即可（`GLOSSA_*` 优先，`PAPERTRACE_*` 兜底，见 `glossa/explain/llm_config.py` 的 `ENV_PAIRS`）：

| 变量 | 必填 | 含义 |
| ---- | ---- | ---- |
| `GLOSSA_LLM_BACKEND` | 是 | 只认 `openai`；其它值报配置不合法（exit 4） |
| `GLOSSA_OPENAI_BASE_URL` | 是 | OpenAI 兼容端点，如 `https://api.deepseek.com/v1` |
| `GLOSSA_OPENAI_API_KEY` | 是 | key |
| `GLOSSA_LLM` | 是 | **模型名**（变量就叫 `GLOSSA_LLM`，没有 `GLOSSA_MODEL` 这种东西） |

四项缺任何一项 `ready()` 就是 false，命令以 **4** 退出并逐个点名缺哪个变量（实测报「缺 GLOSSA_OPENAI_BASE_URL / PAPERTRACE_OPENAI_BASE_URL、GLOSSA_OPENAI_API_KEY / …、GLOSSA_LLM / …」）。

### AI 路径的退出码

| 码 | 什么时候 |
| -- | ---- |
| 0 | 页面写好，stdout 一行「讲解页：<path> · N 节 · 未溯源 M 处（· 本页由离线桩生成…）」 |
| 2 | AI 页组装失败（含整页超过 8,000,000 字节）；**argparse 参数错误也在这个码**：`--style` 写错值、`--llm` 写错值、`--ai` 配裸 `--llm`、`--ai` 配 `--llm offline`（实测 2） |
| 4 | 后端不可用：四项没配齐、backend 不是 `openai`、配了但连不上（`LLMUnavailable`）、`--llm ollama` 尚未实现。**绝不静默退回程序版** |

### 实测（2026-11-17，离线桩，六个页面）

环境：Windows 11 + Python 3.13.15，`--llm fake`，逐页命令见 `.superpowers/sdd/2026-11-17-glossa/task-A10-report.md` §7。产物只写 `output/demo-ai/<name>/`（`.gitignore` 里，私有代码不入库）。

| 页面 | 仓库 | 风格 | 节 | 图 | 其中 bars | 字节 | 未溯源 | `<script>` | 外链 | 「超过 8000 字节」 |
| ---- | ---- | ---- | --: | --: | --: | --: | --: | --: | --: | --: |
| `output/demo-ai/papertrace` | PaperTrace | magazine | 5 | 5 | 1 | 21,494 | 0 | 0 | 0 | 0 |
| `output/demo-ai/pokemondata` | PokemonData | magazine | 5 | 5 | 1 | 21,773 | 0 | 0 | 0 | 0 |
| `output/demo-ai/safetrace` | SafeTrace | magazine | 5 | 5 | 1 | 21,812 | 0 | 0 | 0 | 0 |
| `output/demo-ai/safetrace-report` | SafeTrace | report | 5 | 5 | 1 | 21,868 | 0 | 0 | 0 | 0 |
| `output/demo-ai/safetrace-cards` | SafeTrace | cards | 5 | 5 | 1 | 21,786 | 0 | 0 | 0 | 0 |
| `output/demo-ai/papertrace-report` | PaperTrace | report | 5 | 5 | 1 | 21,550 | 0 | 0 | 0 | 0 |

六页的图序列都是 `bars → layered → cards → cards → cards`；第 1 张 bars 的六行（值全部来自该节 `facts[].numbers`）：

| 页面 | 条形（label=value，按值降序） |
| ---- | ---- |
| PaperTrace | markdown 文件=312 / python 文件=270 / typescript 文件=11 / json 文件=6 / css 文件=3 / text 文件=3 |
| PokemonData | javascript 文件=224 / json 文件=222 / python 文件=193 / csharp 文件=108 / css 文件=97 / text 文件=92 |
| SafeTrace | typescript 文件=326 / json 文件=78 / vue 文件=24 / markdown 文件=20 / javascript 文件=15 / shell 文件=8 |

## 没有 API key 时会怎样（程序版与老模型块路径）

- 不加 `--ai`、也不加 `--llm`：直接出程序版，`untraced` 必须是 0——每句话的数字都来自 cites 的 numbers，取不到出处就整句不写。
- **加 `--ai` 但四项变量没配齐**：**exit 4 并逐个点名缺哪个变量**，绝不偷偷退回程序版（与下面老路径不同，见上面「AI 路径的退出码」）；只想验证流水线就写 `--llm fake`。
- 加**裸 `--llm`**（老模型块路径）但两个后端环境变量（`GLOSSA_LLM_BACKEND` / `PAPERTRACE_LLM_BACKEND`）都没配或都是 `offline`：仍出程序版，stdout 明写「未配置模型后端，本页由程序生成」，exit 0。
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
12. **`meta.repo.url` 只记仓库目录名**：不带父目录路径，换机器、换工作目录都一样；别指望用它定位仓库。
13. **边数是三元组口径**：`graph.edges` 按 `(from,to,kind)` 合并计数，同一对文件既有静态 `import` 又有动态
    `import()` 时算两条边；页面与 MCP 提示一律用 `len(graph["edges"])`，别再用 `set((from,to))` 去重，
    否则同一个仓会给出两个数（SafeTrace 就吃过 445 vs 443 的亏）。

## 实测（2026-11-16，三个真实仓库）

环境：Windows 11 + Python 3.13.15；每个仓库都跑 `glossa analyze --force` 再 `glossa explain --force`，
产物只写 `output/demo-glossa/<name>/`（已在 `.gitignore` 里，私有代码不入库）。命令模板：

```powershell
$env:PYTHONPATH='D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps'
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python -m glossa analyze --repo <仓库路径> --out output\demo-glossa\<name> --force
python -m glossa explain --repo <仓库路径> --out output\demo-glossa\<name> --force
```

| 仓库 | files | symbols | imports | packages | projects | entries | degraded | 图截断节点 | explain 块 | 未溯源数字 | exit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| SafeTrace（TS/Vue 安全情报） | 485 | 1,019 | 1,955 | 8 | 0 | 53 | 123 | 233 | 37 | 0 | 0 / 0 |
| PokemonData（.NET + Vue） | 1,016 | 3,348 | 913 | 2 | 5 | 16 | 256 | 2 | 38 | 0 | 0 / 0 |
| PaperTrace 自举（本仓） | 556 | 2,032 | 1,163 | 3 | 2 | 10 | 10 | 69 | 38 | 0 | 0 / 0 |

`exit` 列是 analyze / explain 两个退出码。三组都真跑完、产物都落盘，没有一组被跳过。

三行数字都在 **2026-11-17 最终修复轮（R482–R497）之后**用绝对路径重跑取得（`--repo D:\AgentPrograms\PaperTrace`）。
自举行比 T11 修复轮多 16 个文件，都是本轮新增的东西在同一棵树里：`glossa/explain/comp_graph.py`、
`narrate_graph.py`、六个测试文件与 `.superpowers/` 下的过程文档——不是排除规则变了（`excluded.truncated=false` 未变）。
`degraded` 8 → 10 的两条也是本轮的新规矩带来的：`sln:<夹具>` 的解决方案文件夹未纳入（R486）与
`repo:paths` 的仓外绝对路径披露（R493，26 处，全部来自夹具与历史产物原文）；`图截断节点` 66 → 69 随文件数上涨
（`truncated` 仍为 `false` 的是 `excluded`，图截断是 `graph.truncated=true`，两者不是一回事）。
SafeTrace 与 PokemonData 两行与上一轮逐项一致（485 / 1,019 / 1,955 / 8 / 0 / 53 / 233 / 37 块、1,016 / 3,348 / 913 / 2 / 5 / 16 / 2 / 38 块），
未溯源数字都是 0，退出码都是 0 / 0。

几件值得记下来的事：

1. **自举先要 `.glossaignore`**：仓根没有忽略文件时，`output/` 里的历史探针文件会把 `--max-files`（20000）
   占满，`excluded.truncated` 变成 `true`，`papertrace/cli.py` 这类核心文件被挤出保留集。加了
   `output/`、`.tmp/`、`pydeps/` 三行之后自举 `truncated = false`，入口也回到真实源码（10 个入口）。
2. **PokemonData 的 108 个 `.cs` 全是 `approx`**：C# 解析器只到「声明行 + 花括号扫尾」的近似精度，
   这一栏没有因为修了回溯问题而变化（修的是复杂度，不是精度）。
3. **analyze 耗时**：PokemonData 修完 4.02 秒跑完；修复前卡在同一批构造器行上（单行 17.98 秒，
   全仓 >10 分钟没结局），根因是 C# 返回类型正则的指数回溯，见计划 R467–R469。
4. **`read_source` 只给保留集里的文件**：三组 smoke 里 review 用的都是 analyze 产出的同一份台账，
   密钥名单里的文件（SafeTrace 的 `.env.example` / `.env.local`）只出现在 `secrets_seen`，内容一个字节都没读。
5. **讲解页可读性是真读过的**：SafeTrace 的 37 块逐块读完，仍列出 16 条术语未解释、数字自相矛盾
   （同一页「445 条边」与「443 条边」并存）、降级原因被掩码这类问题——「测试全绿」不等于「人读得懂」，
   这份清单已交给后续修复轮。**T11 修复轮已把边数统一**：页面两处都数 `len(graph["edges"])`（按
   `(from,to,kind)` 合并），SafeTrace 复跑后两句都是 445，矛盾消失。
6. **MCP 六工具端到端**：stdio 起 `python -m glossa.mcp`，13 行请求换 12 行响应（通知按协议不回包），
   坏 JSON 回 `-32700`、未知方法回 `-32601`、假 fact id 的 `render_explain` 回 `isError`，stderr 全程为空。
7. **`--repo .` 必须和绝对路径是同一本台账**：修复前 `--repo .` 会让 `_wash` 把「.」当路径前缀，
   535/535 条 `file.path` 变成 `README./md` 这种坏形态而 exit 0、零告警；修复后同一个仓两种写法的 totals
   逐项相同（540 / 1,990 / 1,141 / 3 / 2 / 10），`file.path` 里 `./` 出现 0 次。`repo.json` 全文仍有 24 处
   `./`，全部在 `facts.text` 的便携路径里（如 `./glossa/facts.py`），那是合法形态，不是脏路径。
