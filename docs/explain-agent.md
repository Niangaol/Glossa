# 讲解技能包：把 glossa 的六个 MCP 工具用到「能读的讲解页」为止

这份文档是给**接上来的模型**读的：你通过 MCP（stdio、换行分隔 JSON-RPC 2.0）拿到六个工具，
目标是产出一张单文件、离线、无脚本的讲解页。事实只有一个来源——`analyze_repo` 生成的事实台账；
台账里没有的 id 和数字，你不知道，也不许编。

## 一、什么时候走这条链

用户说「给我讲讲这个仓库 / 写个架构说明 / 这项目是干嘛的」时走这里。顺序固定（六个工具都要用）：
`analyze_repo` → `list_components` → `explain_outline` → `get_facts` → `read_source` → `render_explain`。

| 步 | 工具 | 干什么 | 什么时候必须调 |
| -- | ---- | ------ | -------------- |
| 1 | `analyze_repo` | 扫仓库、写 repo.json、把台账缓存进本次会话 | 每个仓库的第一件事 |
| 2 | `list_components` | 列出 14 个渲染组件与各自的必填/选填 params、可用事实模式 | **写 blocks 之前**：先拿到组件名与参数契约，别手抄、别猜 |
| 3 | `explain_outline` | 七块骨架 + 每块的真 fact id | 决定写哪几块之前 |
| 4 | `get_facts` | 按 kind 分页翻事实（id / numbers / text） | 要引用一个 id 之前核对 |
| 4b | `read_source` | 读保留文件原文（带行号，单次 ≤200 行） | 要贴具体代码之前 |
| 5 | `render_explain` | 校验 blocks 并写 explain.html | 最后一步 |

`list_components` 为什么必须单独占一步：它是唯一知道「`params` 该写哪些键」的地方。组件表来自
`glossa/explain/components.py` 的注册表（唯一真源），运行期改注册表它立刻跟着变；不调它，「`file_card`
要不要 `path`」「`metrics` 的 `keys` 能填什么」只能靠猜，而猜错会被整页拒绝。

协议层：initialize / notifications/initialized / ping / tools/list / tools/call；**通知不回包**。
工具级失败是 `result.isError = true` + 原因文本；只有协议层问题（方法不存在、缺必填参数、JSON 坏了）
才是 JSON-RPC `error` 对象。看到 isError 就读原因改参数，别拿同一份参数重试。

## 二、14 个组件的参数契约

这张表由 `glossa/explain/components.py` 的 `COMPONENTS` 生成（唯一真源，改注册表就重新生成，别手抄）：

| 组件 | 必填 params | 选填 params | 可用事实模式 | section |
| ---- | ----------- | ----------- | ------------ | ------- |
| `text` | `text` | `title` | 任意（由 cites 决定） | — |
| `custom` | `html` | `title` | 任意（由 cites 决定） | — |
| `overview` | — | — | fact:totals、fact:files | 1 |
| `metrics` | `keys` | — | fact:totals | 1 |
| `dir_tree` | — | `max_depth` | fact:files | 3 |
| `package_map` | — | — | fact:pkg:* | 3 |
| `project_map` | — | — | fact:project:* | 3 |
| `entry_list` | — | `limit` | fact:entry:* | 2 |
| `import_graph` | — | — | fact:graph | 4 |
| `file_card` | `path` | — | fact:file:<path> | 5 |
| `symbol_table` | `path` | `kind` | fact:symbol:<path>#* | 5 |
| `code` | `path`、`start`、`end` | — | fact:source:<path>:* | 5 |
| `table` | `fact`、`columns` | `limit` | 该 fact id | 6 |
| `bonus` | — | — | fact:bonus | 7 |

每个 block 只许这六个顶层键：`component` / `params` / `cites` / `section` / `title` / `notes`——
多一个键整页拒绝（R448-D16），与「未知组件响亮报错」同口径。`cites` 里的 id 必须逐字出现在
`explain_outline` 的 facts 或 `get_facts` 的返回里；`section` 取 1–7，决定这块的标题用七块骨架的哪一条。

## 三、三条禁令（违反会被整页拒绝，不是警告）

1. **不许编 fact id。** `cites` 或 `params.fact` 里出现台账没有的 id → `BuildError`，整页拒绝，
   报错会点名组件与那个假 id。落笔前用 `get_facts` / `explain_outline` 核对。
2. **数字必须有出处。** `text` / `custom` 里的每个数字都要能在该块 cites 的 numbers 并集里找到；
   找不到的会被页面打黄标，页头「本页有 N 处数字未溯源」的 N 就会非零。程序版的目标是 0。
3. **不许写 `<script>`、`<style>`、外链、事件属性（onclick= 之类）。** `custom` 组件会剥掉这些构造，
   并在页面上明示「本块已移除 N 处不允许的构造」；`text` 走受限 markdown，只认标题/列表/粗体/行内代码。

## 四、端到端示例（真仓库：ts-monorepo 夹具，13 个文件 / 10 个符号 / 9 条 import）

① `analyze_repo {"repo": "<夹具路径>"}` → `totals.files = 13`、`totals.symbols = 10`、
`totals.imports = 9`，`out` 指向 `.../repo.json`。
② `list_components {}`（无参数）→ `total = 14`，每项给 `name / required / optional / facts / section`；
   例：`{"name": "file_card", "required": ["path"], "optional": [], "facts": ["fact:file:<path>"], "section": 5}`。
   从这里抄出下面要用的 `component` 名与 `params` 键，别凭印象写。
③ `explain_outline {"repo": ...}` → 七块：① 这项目是什么 ② 从哪进来 ③ 分几块 ④ 谁依赖谁
⑤ 关键文件逐个讲 ⑥ 我没看清的地方 ⑦ 甜头（没有 bonus 事实时 required=false）。
④ `get_facts {"repo": ..., "kind": "entry"}` → items 里是 `fact:entry:serve` / `fact:entry:check` / `fact:entry:test`。
⑤ `render_explain {"repo": ..., "blocks": [...]}`，blocks 用下面这份（组件名与 params 来自 ②，真 id 来自 ③④）：

```json
[
  {"component": "metrics", "params": {"keys": ["files", "symbols", "imports"]}, "cites": ["fact:totals"], "section": 1},
  {"component": "text", "params": {"text": "全仓 13 个文件、10 个符号、9 条 import。"}, "cites": ["fact:totals"], "section": 1},
  {"component": "entry_list", "params": {}, "cites": ["fact:entry:serve", "fact:entry:check", "fact:entry:test"], "section": 2},
  {"component": "file_card", "params": {"path": "packages/a/src/server.ts"}, "cites": ["fact:file:packages/a/src/server.ts"], "section": 5}
]
```

返回 `{untraced: 0, removed: 0, bytes: <页字节数>, blocks: 4, out: ".../explain.html"}`。
（这份 blocks 在本机用同一夹具真跑过：untraced=0、removed=0，证据见 `docs/glossa.md` 的「实测」小节。）
注意 `fact:totals` 的 numbers 是 `[0, 1, 2, 3, 4, 6, 9, 10, 13]`——正文里写 13 / 10 / 9 才不算未溯源。

## 五、没有 API key 时怎么办

- 这条链不需要 key：`render_explain` 的 `mode` 默认 `program`，页面页头直说「本页由程序生成，未使用模型」。
- 写讲解的是你（模型），不是服务器：服务器只负责校验与渲染。想让 CLI 那条路自己写，用
  `python -m glossa explain --llm`（后端由 `GLOSSA_LLM_BACKEND` / `PAPERTRACE_LLM_BACKEND` 决定）。
- 没有 key 就别假装：`mode` 不要填 `model`，`model_name` 也别填；填了就是谎报来源。

## 六、`read_source` 的四道闸（会被拒，也会告诉你为什么）

1. **必须是仓库内的相对路径**：绝对路径、UNC、跨盘符、含 NUL、含 `..`、符号链接指向仓库外，一律拒绝；
2. **必须在扫描保留集里**：node_modules、默认排除目录、白名单外扩展名、超限文件都不给读；
3. **密钥名单不读内容**：`.env` / `*.pem` / `id_rsa` / `secrets.*` 等只登记名与字节数，一个字节都不给；
4. **单次 ≤200 行**：超了明说「请分页」，不会静默截到 200 行。

## 七、缓存语义（别把旧事实当新闻）

`analyze_repo` 把台账缓存在本次会话里，key 是仓库的绝对路径。其余工具没有缓存时会自动 analyze 一次，
并在返回里写「仓库不在缓存里，这次已自动 analyze 一次」。命中缓存时返回的 `note` 写明「本结果来自本次
会话缓存（analyze 于 …）」；仓库在这之后改过，台账仍是旧的——要新事实就再调 `analyze_repo`（`force: true`）。
`analyze_repo` 自己**总是重扫**、不读缓存；返回里也没有 `cached` 字段了（R473 删掉），缓存状态只看 `note`。

## 八、渲染前自检清单

- [ ] 每块的 `component` 都在 14 个之内，`params` 的必填键齐（这两条来自 `list_components`，不是手抄的）；
- [ ] 每个 cites 的 id 都来自 `explain_outline` 或 `get_facts` 的返回；
- [ ] `text` 里的每个数字都在 cites 的 numbers 并集里；
- [ ] 没有 `<script>` / `<style>` / 外链 / 事件属性；
- [ ] `render_explain` 返回 `untraced == 0` 且 `removed == 0`；
- [ ] 页面能离线打开，页头写着「本页有 0 处数字未溯源」。
