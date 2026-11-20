# PaperTrace 讲解页 + MCP 讲解 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 新增独立的纯讲解页 explain.html（原 index.html 字节级不动）+ 零依赖手写 stdio MCP server，让模型拿事实写讲解、程序管排版与溯源标记。

**Architecture:** 三层——事实层（已有 trace.json，不改）/ MCP 工具层（6 个工具，标准库 JSON-RPC 2.0 over stdio）/ 渲染层（blocks 校验 → 13 个组件从 facts 取数生成 HTML/SVG → 未溯源标记 → 单文件离线页）。模型只交回 blocks JSON，不写文件；无 key 时程序用同一份事实骨架生成如实模板叙述并自报「未使用模型」。

**Tech Stack:** Python 3.13 + 标准库（json/sys/pathlib/re/html.parser/argparse/io）+ 已装 jinja2（模板）；模型侧复用 papertrace/llm/openai_backend.py（可注入 transport）。**零新依赖**。

**Spec:** docs/superpowers/specs/2026-11-16-papertrace-explain-design.md（逐条实现它；D-A/D-B/D-C 是控制器的默认裁决，用户可推翻）

**Preflight 实测事实**（output/controller-probes/explain_preflight.md，派发前控制器真跑）：
BASE render/html.py sha256 = 3b8104004c8e242282a3b0e719e8370606960e35e0e096ca3a3e66cd6df4dba6（GC24 比对基准）；
nodes level 计数 op 94 / module 34，kind 计数 op 75 / param 18 / input 1 / 无 kind 34；唯一 input 节点 id = root/@018；
图是 DAG（Kahn 覆盖 128/128），最长链 **56 步**，头 placeholder (2, 8) → embedding (2, 8, 32)，尾 linear (2, 8, 64)；
totals 数值升序去重 = [2, 34, 2048, 29856, 884736]；
root/transformer.h.0.attn 实测 op_count **22**、params 4352、max_activation 1536、est_flops 147456、
evidence 原文「自身 22 个算子里有 matmul→…→softmax→…→matmul 子序列」；
symbols.code 的 var = DEFAULT_BATCH/block_size/n_embd/n_head/Dh；
meta.repo = {url: tests/fixtures/nanogpt（相对路径）, commit: dirty-subdir, entry_module: model:build_model}，created_at = 2026-11-16T05:04:18+00:00；
三份演示 anchors：code-only 0 / with-paper 0（unresolved 8）/ fallback-yellow 4（全 yellow）；
_groups(doc) 返回 30 组布局字典（键 parent/width/height/nodes），4 个模块没有算子组（root/transformer、root/transformer.h、root/transformer.h.0.mlp、root/transformer.h.1.mlp）；
exit_codes 实测 UNIMPLEMENTED=2 / MISSING_RUNTIME=4 / UNTRACEABLE=5（**没有 6**），cli.py 里 trace 不合法 return 1、dump 冲突 return 3、HTML 渲染失败 return 2。

## Global Constraints

- 单文件 ≤200 行（Python 产品源码，口径 len(Path(f).read_text(encoding='utf-8').splitlines())；测试不限）。
- 零新依赖：只用标准库 + 已装 torch/sympy/jinja2/jsonschema。禁 numpy/requests/mcp/anyio/httpx/pydantic/uvicorn/markdown 库。
- 不许用 mock 填产品输出；假对象只注入测试，单实例，且必须断言被测路径真被走到（计数器 ≥1）。
- 默认 offline：不配 PAPERTRACE_LLM_BACKEND 时不得发起任何网络调用。
- GC8 不变式：nodes=128（op 75 / param 18 / input 1 / module 34）、edges=101、analysis.modules=34、totals.params=29856、totals.degraded=2、totals.est_flops=884736。
- GC19：估算字段带 est_，方法说明同时出现在 analysis.method 与页面；禁「精确计算量」「实测 FLOPs」。
- GC23：模板 StrictUndefined 下兜底用 X | default('…', true)，不用 or；{% if %} 裸属性用 and 短路。
- **GC24**：explain.html 与 index.html 同源同一份 trace；本切片禁改 render/html.py / render/analysis.py / render/symbols.py / render/terms.py / spine.html.j2 / analyze/roles.py / analyze/metrics.py / build/analysis.py / schema/trace.json / build/trace.py / spine*.py / align/* / parse_*/*。验收含「原页字节级不变」。
- **GC25**：MCP server 的 stdout 只许一行一个 JSON-RPC 响应；日志走 stderr。
- **GC26**：模型文字里的数字未命中 cites 的 fact 数值集合 → 必须打 <mark class="untraced"> 且原样保留数字；禁删改、禁静默通过。
- **GC27**：custom 块被剥离的构造必须同时在页面与工具返回里可见。
- **GC28**：无模型参与的页面顶部横幅必须明说「未使用模型」；有模型参与必须写出模型名与 trace 的 commit/created_at。
- 测试环境：PYTHONPATH 含仓库根 + pydeps；**禁 pytest tmp_path**，临时目录用 tests/_tmp.py::scratch_dir；走 CLI 的测试 cwd 钉在仓库根。
- 本机 bash 不可用 → 一律 pwsh。每 Task 一次提交；既有断言不许删。
- 改既有文件后核行尾（core.autocrlf=true）；提交用 git -c core.autocrlf=false commit。变异还原一律 git show HEAD:<file> 取 blob + write_bytes，**禁 git checkout --**。
- 行数口径一律 Python splitlines 或 git numstat（pwsh Get-Content .Count 对 LF 文件少算）。

**测试命令前缀（每条 Run 都隐含它）：**
```
$env:PYTHONPATH='D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; & 'C:\Users\niangao\AppData\Local\Programs\Python\Python313\python.exe' -m pytest <目标> -q
```
BASE = e5aaa2d，基线全量 **854 passed**。每 Task 结束跑一次全量，条数只许增不许减。

## Review Focus

spec 隐含但各任务测试容易漏掉、最可能咬到真人的五类输入（每类已在归属任务里加了钉子）：

1. **骨架/空 trace**（nodes=[]、analysis.modules=[]、symbols.code=[]）：讲解页仍要出得来，如实说「没有可讲的事实」，不许崩、不许编模块。→ Task E1/E5 各一条。
2. **退化 blocks**（blocks=[]、只有 custom、缺 title、cites=[]）：页面仍合法，横幅与溯源汇总仍在，不静默变空白页。→ Task E3/E5。
3. **数字形态**（千分位 29,856 / 小数 0.5 / 百分号 50% / 负号 / 行内代码里的数字 / HTML 属性里的数字）：标记判定既不误伤也不漏。→ Task E2。
4. **畸形 custom HTML**（未闭合标签、大写 <SCRIPT>、属性值里带 > 、嵌套 <script>）：守卫不漏剥也不把整页吃掉。→ Task E2。
5. **畸形 JSON-RPC 输入**（空行、半行 JSON、非法 JSON、数组批量、通知无 id、未知方法、params 非对象）：server 不崩、stdout 仍纯净。→ Task E7。

---

### Task E1: 事实索引、主链、人话名

**Files:**
- Create: papertrace/explain/__init__.py（包声明，1 行 docstring）
- Create: papertrace/explain/facts.py（≤190 行）
- Create: papertrace/explain/outline.py（≤150 行）
- Create: papertrace/explain/names.py（≤90 行）
- Test: tests/test_explain_facts.py、tests/test_explain_outline.py、tests/test_explain_names.py

**Interfaces:**
- Consumes: trace dict（schema/trace.json 的既有形状：nodes/edges/analysis/symbols/meta）。
- Produces:
  - facts.build_index(doc: dict) -> dict[str, dict]：fact_id → {"fact_id": str, "kind": str, "numbers": list[int], "data": dict}。fact_id 体系见 spec §8.1（fact:overview / fact:totals / fact:totals/<key> / fact:module/<module_id> / fact:node/<node_id> / fact:edge/<edge_id> / fact:symbol/<var> / fact:chain / fact:source/<path>:<a>-<b>）。numbers 升序去重。
  - facts.numbers_of(index: dict[str, dict], cites: list[str]) -> set[int]：未知 fact_id 抛 KeyError（由 E3 转成校验问题）。
  - facts.get_facts(doc: dict, kind: str, module_id: str | None = None, limit: int = 40, offset: int = 0) -> dict：{"items": list[dict], "total": int, "next_offset": int | None}；kind ∈ overview/modules/module/ops/edges/symbols/totals；每条 item 带 fact_id；未知 kind 抛 ValueError。
  - outline.main_chain(doc: dict) -> list[dict]：从唯一 kind==input 节点出发、按边数最长的一条路径（DAG 上 DP；同长并列取 node id 字典序最小），每项 {"node_id","op","label","shape_out"}。**这是启发式主链，不是唯一真相**，页面与返回里都要这么标注。
  - outline.outline(doc: dict) -> dict：{"chain": main_chain(doc), "groups": {role: [module_id…]}, "order": [module_id…], "totals": dict, "symbols": list, "counts": {"nodes": int, "edges": int}}；order 按角色优先级 attention→mlp→layernorm→embedding→linear→其余→unknown，同角色按 module_id 升序。
  - names.layer_of(module_id: str) -> int | None：取 id 里 h.<n> 的 n（多个取第一个）；无则 None。
  - names.human_name(module_id: str, cls: str, role: str) -> str：形如「第 1 层 · 注意力 · 输出投影（Linear）」；末段不在映射表里 → 原样用末段，不猜；无层号 → 省略「第 N 层 · 」。

- [ ] **Step 1: 写红测试**（三个文件，真夹具 build 一次做 module 级 fixture，用 scratch_dir）
```python
# tests/test_explain_facts.py
def test_index_covers_every_node_edge_module_symbol(real_doc):
    idx = build_index(real_doc)
    assert len([k for k in idx if k.startswith('fact:node/')]) == 128
    assert len([k for k in idx if k.startswith('fact:edge/')]) == 101
    assert len([k for k in idx if k.startswith('fact:module/')]) == 34
    assert idx['fact:totals']['numbers'] == [2, 34, 2048, 29856, 884736]
def test_numbers_of_unions_only_cited_facts(real_doc):
    idx = build_index(real_doc)
    assert numbers_of(idx, ['fact:totals/params']) == {29856}
    assert 29856 in numbers_of(idx, ['fact:totals'])
def test_get_facts_pages_without_overlap_or_gap(real_doc):
    a = get_facts(real_doc, 'ops', limit=40, offset=0)
    b = get_facts(real_doc, 'ops', limit=40, offset=40)
    assert a['total'] == 94 and b['next_offset'] == 80
    assert not ({i['fact_id'] for i in a['items']} & {i['fact_id'] for i in b['items']})
def test_empty_trace_index_is_empty_not_fake():
    idx = build_index({'nodes': [], 'edges': [], 'analysis': {'modules': [], 'totals': {}, 'roles': {}}, 'symbols': {'code': []}})
    assert idx['fact:overview']['numbers'] == [0]
    assert not [k for k in idx if k.startswith('fact:module/')]
# tests/test_explain_outline.py
def test_chain_is_a_real_path_in_the_graph(real_doc):
    chain = main_chain(real_doc)
    ids = [c['node_id'] for c in chain]
    edges = {(e['src'], e['dst']) for e in real_doc['edges']}
    assert all((a, b) in edges for a, b in zip(ids, ids[1:]))
    assert len(chain) == 56  # preflight 实测真值，不是猜的
def test_outline_groups_cover_all_34_modules(real_doc):
    o = outline(real_doc)
    assert sum(len(v) for v in o['groups'].values()) == 34
    assert o['order'][0].startswith('root/transformer.h.0.attn')
# tests/test_explain_names.py
def test_human_name_uses_layer_and_role():
    assert human_name('root/transformer.h.0.attn.c_proj', 'Linear', 'linear') == '第 1 层 · 注意力 · 输出投影（Linear）'
def test_unknown_tail_is_kept_verbatim_not_guessed():
    assert 'mystery_part' in human_name('root/transformer.h.2.mystery_part', 'Foo', 'unknown')
def test_no_layer_number_when_id_has_none():
    assert '第' not in human_name('root/lm_head', 'Linear', 'linear')
```
注：human_name 的精确中文词表由实现者定，但**必须先写进测试再实现**，且末段未知时原样保留；上面第一条的期望串若与词表冲突，以词表为准并同步改这条期望（只许改期望值，不许删断言）。

- [ ] **Step 2: 跑红** Run: pytest tests/test_explain_facts.py tests/test_explain_outline.py tests/test_explain_names.py -q → Expected: FAIL（ModuleNotFoundError: papertrace.explain）
- [ ] **Step 3: 实现三个模块**（签名见 Interfaces；main_chain 用拓扑 DP，不要 BFS 最短路；numbers 只收 int，float 值若是整数则转 int）
- [ ] **Step 4: 跑绿** Run: 同上 → Expected: PASS；再跑全量 → Expected: 854 + 新增，零回归
- [ ] **Step 5: 变异探针**（≥2 条，逐条记录改了哪行/几条红/测试名/还原后 sha256）
  - M1：main_chain 的并列取舍改成取 id 字典序最大 → **补一条 test_chain_tie_break_is_deterministic**（同一 doc 跑两次结果全等 + 与 reversed(nodes) 喂入结果全等）必红。
  - M2：get_facts 的 offset 改成 offset+1 → 分页测试必红。
  - 还原一律 git show HEAD:<file> + write_bytes，核 sha256 全等。
- [ ] **Step 6: 提交** git -c core.autocrlf=false commit -m "feat: index trace facts, compute the main chain and human module names"

---

### Task E2: 受限 markdown + custom 守卫 + 未溯源标记

**Files:**
- Create: papertrace/explain/markdown.py（≤130 行）
- Create: papertrace/explain/guard.py（≤190 行）
- Test: tests/test_explain_markdown.py、tests/test_explain_guard.py

**Interfaces:**
- Consumes: E1 的 numbers_of（标记时传 set[int]）。
- Produces:
  - markdown.render_markdown(text: str) -> tuple[str, list[str]]：(html, notes)。支持 ##/### 小标题、空行分段、- 无序列表、1. 有序列表、**粗体**、单反引号行内代码；不支持的构造（链接/图片/裸 HTML/表格/脚注）**原样当纯文本显示**并往 notes 追加一条中文说明。所有文本先 html.escape 再插标签。
  - guard.sanitize_html(html: str) -> tuple[str, list[str]]：(clean, removed)。剥离 spec §8.3 列的构造，removed 每项是一句中文描述（含被剥的标签/属性名）。允许内联 style/class、<details>/<summary>、内联 SVG（xmlns 例外）、相对链接 index.html、页内锚点 #…。
  - guard.mark_untraced(html: str, allowed: set[int]) -> tuple[str, int]：(marked_html, count)。用 re.split(r'(<[^>]*>)', html) 分离标签与文本，只处理文本段；跳过 <code> 子树内的文本；数字正则 r'\d[\d,]*(?:\.\d+)?%?'，去千分位、去 %、整数值转 int 后与 allowed 比对；未命中 → 包 <mark class="untraced" title="未在引用的事实里找到这个数字">原数字</mark>，**数字原样**。

- [ ] **Step 1: 写红测试**
```python
# tests/test_explain_markdown.py
def test_headings_lists_bold_and_inline_code():
    html, notes = render_markdown('## 标题\n\n- 一项\n- **粗** 与 ' + chr(96) + 'code' + chr(96))
    assert '<h2>' in html and '<li>' in html and '<strong>粗</strong>' in html and '<code>code</code>' in html
    assert notes == []
def test_unsupported_link_is_shown_verbatim_not_dropped():
    html, notes = render_markdown('见 [文档](https://x.test)')
    assert '[文档](https://x.test)' in html and len(notes) == 1
def test_raw_html_is_escaped_not_executed():
    html, _ = render_markdown('<script>alert(1)</script>')
    assert '<script>' not in html and '&lt;script&gt;' in html
# tests/test_explain_guard.py
def test_script_event_and_remote_src_are_stripped_and_reported():
    clean, removed = sanitize_html('<div onclick="x()" style="color:red">hi<script>bad()</script><img src="https://x.test/a.png"></div>')
    assert 'onclick' not in clean and '<script' not in clean and 'https://x.test' not in clean
    assert 'style="color:red"' in clean and 'hi' in clean and len(removed) == 3
def test_uppercase_script_and_unclosed_tags_are_still_stripped():
    clean, removed = sanitize_html('<SCRIPT>bad()</SCRIPT><div><b>bold')
    assert 'bad()' not in clean and len(removed) >= 1
def test_inline_svg_xmlns_and_relative_link_survive():
    clean, removed = sanitize_html('<svg xmlns="http://www.w3.org/2000/svg"></svg><a href="index.html">档案</a><a href="#s1">节</a>')
    assert removed == [] and 'xmlns' in clean and 'href="index.html"' in clean
def test_untraced_number_is_marked_and_kept_verbatim():
    out, n = mark_untraced('<p>参数量 29,857 与 29,856</p>', {29856})
    assert n == 1 and '<mark class="untraced"' in out and '29,857' in out
    assert '<mark class="untraced" title="未在引用的事实里找到这个数字">29,856</mark>' not in out
def test_numbers_in_code_and_attributes_are_not_marked():
    out, n = mark_untraced('<p data-x="999"><code>12345</code> 50% 与 0.5</p>', {50, 1})
    assert n == 1 and '12345' in out and '<mark' not in out.split('</code>')[0]
```
注：最后一条的 allowed/期望值实现者可按自己的归一化口径调整，但**必须同时钉住「code 内不标记」「属性内不标记」「百分号归一」「小数比对」四件事**，不许只留一条恒真断言。

- [ ] **Step 2: 跑红** Run: pytest tests/test_explain_markdown.py tests/test_explain_guard.py -q → Expected: FAIL（ModuleNotFoundError）
- [ ] **Step 3: 实现两个模块**（守卫用 html.parser.HTMLParser 逐标签重建，不要纯正则删标签；mark_untraced 用 re.split 分离标签与文本并跟踪 <code> 深度）
- [ ] **Step 4: 跑绿** Run: 同上 → PASS；全量零回归
- [ ] **Step 5: 变异探针**（≥3 条）M1：mark_untraced 把未命中数字改成 allowed 里最接近的值 → 数字原样断言必红；M2：sanitize_html 放行 onclick → 剥离测试必红；M3：render_markdown 静默丢掉不支持的构造 → verbatim 测试必红。逐条记录 + 还原核 sha256。
- [ ] **Step 6: 提交** git -c core.autocrlf=false commit -m "feat: render a restricted markdown subset and guard custom html with provenance marks"

---

### Task E3: blocks 校验 + 组件注册表 + 事实类组件

**Files:**
- Create: papertrace/explain/blocks.py（≤150 行）
- Create: papertrace/explain/components.py（≤120 行）
- Create: papertrace/explain/comp_facts.py（≤190 行）
- Test: tests/test_explain_blocks.py、tests/test_explain_components.py

**Interfaces:**
- Consumes: E1 build_index/numbers_of/get_facts/outline/names；E2 render_markdown/sanitize_html/mark_untraced。
- Produces:
  - components.Ctx = NamedTuple('Ctx', doc: dict, index: dict, outline: dict, repo_root: Path | None)
  - components.COMPONENTS: dict[str, dict]，每项 {"args": {名: {"required": bool, "type": str}}, "fn": callable, "doc": str, "example": dict}；13 个名字见 spec §7.2（E3 先注册 text/custom/overview/metrics/module_card/symbol_table/table 七个，其余六个由 E4 注册进同一张表，合计 13）。
  - components.render_block(block: dict, ctx: Ctx) -> str：返回该块 HTML；text 走 render_markdown + mark_untraced；custom 走 sanitize_html + mark_untraced，被剥构造在块顶插一行可见提示；其余组件直接调 fn，**组件自产数字不标记**。
  - components.component_menu() -> list[dict]：给 MCP list_components 用（name/args/doc/example）。
  - blocks.validate_blocks(payload: dict, index: dict[str, dict]) -> list[str]：空列表＝通过。检查 payload 是 dict、blocks 是 list、每块是 dict、component 是已知名字、args 是 dict 且必填齐全、cites 是 list[str] 且**每个 fact_id 都存在于 index**（不存在 → 问题，spec §7.1）。问题文本必须含「第 N 块」与具体原因。
  - comp_facts.overview(ctx) / metrics(ctx, keys=None) / module_card(ctx, module_id) / symbol_table(ctx) / table(ctx, kind, columns=None, module_id=None) -> str。module_card 必须含人话名、原始 module_id、类名、角色、**判据原文逐字**、op_count 与三项指标（千分位）；指标口径说明逐字取 analysis.method。

- [ ] **Step 1: 写红测试**
```python
# tests/test_explain_blocks.py
def test_unknown_component_is_rejected_with_block_number(real_doc):
    problems = validate_blocks({'blocks': [{'component': 'nope', 'args': {}}]}, build_index(real_doc))
    assert len(problems) == 1 and '第 1 块' in problems[0] and 'nope' in problems[0]
def test_missing_required_arg_is_rejected(real_doc):
    problems = validate_blocks({'blocks': [{'component': 'module_card', 'args': {}}]}, build_index(real_doc))
    assert problems and 'module_id' in problems[0]
def test_fake_citation_is_rejected(real_doc):
    problems = validate_blocks({'blocks': [{'component': 'text', 'args': {'markdown': 'x'}, 'cites': ['fact:module/root/does.not.exist']}]}, build_index(real_doc))
    assert problems and 'fact:module/root/does.not.exist' in problems[0]
def test_empty_blocks_and_missing_cites_are_legal(real_doc):
    idx = build_index(real_doc)
    assert validate_blocks({'blocks': []}, idx) == []
    assert validate_blocks({'blocks': [{'component': 'custom', 'args': {'html': '<p>hi</p>'}}]}, idx) == []
# tests/test_explain_components.py
def test_module_card_carries_verbatim_evidence_and_human_name(real_ctx):
    html = render_block({'component': 'module_card', 'args': {'module_id': 'root/transformer.h.0.attn'}}, real_ctx)
    row = next(m for m in real_ctx.doc['analysis']['modules'] if m['module_id'] == 'root/transformer.h.0.attn')
    assert row['evidence'] in html and '4,352' in html and '147,456' in html and 'root/transformer.h.0.attn' in html
    assert '22' in html  # op_count 实测 22，不是 6
def test_metrics_uses_thousands_separators_and_method_text(real_ctx):
    html = render_block({'component': 'metrics', 'args': {}}, real_ctx)
    assert '29,856' in html and '884,736' in html and real_ctx.doc['analysis']['method'] in html
def test_text_block_marks_untraced_number(real_ctx):
    html = render_block({'component': 'text', 'args': {'markdown': '参数量 29,857'}, 'cites': ['fact:totals']}, real_ctx)
    assert '<mark class="untraced"' in html and '29,857' in html
def test_custom_block_reports_stripped_constructs_visibly(real_ctx):
    html = render_block({'component': 'custom', 'args': {'html': '<p>ok</p><script>x()</script>'}}, real_ctx)
    assert '<script' not in html and '已移除' in html and 'ok' in html
def test_component_numbers_are_never_marked(real_ctx):
    html = render_block({'component': 'metrics', 'args': {}}, real_ctx)
    assert 'untraced' not in html
```

- [ ] **Step 2: 跑红** Run: pytest tests/test_explain_blocks.py tests/test_explain_components.py -q → Expected: FAIL
- [ ] **Step 3: 实现三个模块**（注册表用 dict 字面量；render_block 只分派不写业务；组件 HTML 用字符串拼接 + html.escape，不用 jinja 子模板）
- [ ] **Step 4: 跑绿** → PASS；全量零回归
- [ ] **Step 5: 变异探针**（≥3 条）M1：validate_blocks 放行未知 fact_id → 假引用测试必红；M2：module_card 把 evidence 截断到 20 字 → 逐字断言必红；M3：render_block 给组件自产数字也打标记 → test_component_numbers_are_never_marked 必红。记录 + 还原核 sha256。
- [ ] **Step 6: 提交** git -c core.autocrlf=false commit -m "feat: validate explain blocks and render the fact-backed components"

---

### Task E4: 图 / 边 / 调用链 / 源码 / 甜头组件

**Files:**
- Create: papertrace/explain/comp_graph.py（≤190 行）
- Create: papertrace/explain/comp_code.py（≤120 行）
- Modify: papertrace/explain/components.py（只加 6 个注册项：flow_chain/ops_graph/flow_edges/callchain/code/paper_bonus，不改既有 7 项）
- Test: tests/test_explain_graph.py、tests/test_explain_code.py

**Interfaces:**
- Consumes: E1 outline.main_chain / get_facts；E3 Ctx / COMPONENTS；既有 render_html._groups（**只 import 调用，不改它**）与 render_html.fmt_shape。
- Produces: comp_graph.flow_chain(ctx, max_steps=None) / ops_graph(ctx, module_id) / flow_edges(ctx, module_id=None, edge_ids=None) / callchain(ctx, root=None) -> str；comp_code.code(ctx, path, start, end) / paper_bonus(ctx) -> str。
  - flow_chain：SVG + 有序步骤列表，每步标 shape_out（用 fmt_shape 口径），顶部注明「程序算的最长链，不是唯一真相」。
  - ops_graph：复用 _groups(doc)（**返回的是布局字典**：parent/width/height/nodes，节点键 box_w/label/link/loc_full/loc_short/loc_x/shape_in/shape_out/y）后只取 parent == module_id 的那一组；SVG markup 抄 spine.html.j2:68-81 的口径并注明来源，**不改原模板**。找不到组 → 返回一句如实说明（不抛）；**真夹具里有 4 个模块没有算子组**（root/transformer、root/transformer.h、root/transformer.h.0.mlp、root/transformer.h.1.mlp），文案要说「该模块没有直接算子，算子挂在子模块下」。
  - code：只许读 ctx.repo_root 之下的路径（repo_root = Path(doc['meta']['repo']['url']).resolve()，由 E5/E7 传入），越界/不存在 → 抛 BuildError；单次 ≤200 行；输出带行号等宽块。
  - paper_bonus：doc['anchors'] 为空 → **返回空串**（E5 见空串整块不渲染）。

- [ ] **Step 1: 写红测试**
```python
# tests/test_explain_graph.py
def test_flow_chain_svg_and_steps_match_real_shapes(real_ctx):
    html = render_block({'component': 'flow_chain', 'args': {}}, real_ctx)
    assert '<svg' in html and '最长链' in html and '(2, 8)' in html
def test_ops_graph_only_contains_the_requested_module(real_ctx):
    html = render_block({'component': 'ops_graph', 'args': {'module_id': 'root/transformer.h.0.attn'}}, real_ctx)
    assert '<svg' in html and 'root/transformer.h.1.attn' not in html
def test_ops_graph_unknown_module_says_so_instead_of_crashing(real_ctx):
    html = render_block({'component': 'ops_graph', 'args': {'module_id': 'root/nope'}}, real_ctx)
    assert 'root/nope' in html and '<svg' not in html
def test_ops_graph_module_without_direct_ops_says_so(real_ctx):
    html = render_block({'component': 'ops_graph', 'args': {'module_id': 'root/transformer.h.0.mlp'}}, real_ctx)
    assert '<svg' not in html and '子模块' in html
def test_flow_edges_shows_producer_and_consumer_shapes(real_ctx):
    html = render_block({'component': 'flow_edges', 'args': {'module_id': 'root/transformer.h.0.attn'}}, real_ctx)
    assert '<table' in html and ('producer' in html.lower() or '生产' in html)
# tests/test_explain_code.py
def test_code_block_reads_real_lines_with_numbers(real_ctx):
    html = render_block({'component': 'code', 'args': {'path': 'model.py', 'start': 140, 'end': 145}}, real_ctx)
    assert '140' in html and '145' in html and '<pre' in html
def test_code_block_refuses_to_escape_the_repo(real_ctx):
    with pytest.raises(BuildError):
        render_block({'component': 'code', 'args': {'path': '../../secrets.txt', 'start': 1, 'end': 5}}, real_ctx)
def test_paper_bonus_is_empty_without_anchors(real_ctx):
    assert render_block({'component': 'paper_bonus', 'args': {}}, real_ctx) == ''
def test_paper_bonus_renders_when_anchors_exist(real_ctx_with_paper):
    html = render_block({'component': 'paper_bonus', 'args': {}}, real_ctx_with_paper)
    assert html and '论文' in html
```
real_ctx_with_paper 用 output/demo/fallback-yellow/trace.json（anchors=4 全 yellow）或真跑一次带 --paper 的 build；**不许手编 anchors**。

- [ ] **Step 2: 跑红** → FAIL
- [ ] **Step 3: 实现两个模块 + 注册 5 项**（SVG 坐标算法抄 _groups 的口径并注明来源；不要改 render/html.py）
- [ ] **Step 4: 跑绿** → PASS；全量零回归；**核 render/html.py 的 sha256 与 BASE 全等**
- [ ] **Step 5: 变异探针**（≥2 条）M1：ops_graph 不过滤 parent（全图都画）→ 只含请求模块的断言必红；M2：code 组件去掉越界检查 → 越界测试必红（并确认它真读到了 repo 外的文件才算探针有效）。记录 + 还原核 sha256。
- [ ] **Step 6: 提交** git -c core.autocrlf=false commit -m "feat: add graph, callchain, source and paper-bonus explain components"

---

### Task E5: 整页渲染 + explain.html.j2

**Files:**
- Create: papertrace/explain/render.py（≤150 行）
- Create: papertrace/templates/explain.html.j2
- Test: tests/test_explain_render.py

**Interfaces:**
- Consumes: E1–E4 全部。
- Produces:
  - render.render_explain(doc: dict, payload: dict, *, repo_root: Path | None = None, mode: str = 'program', model_name: str | None = None) -> tuple[str, dict]：(html, report)。report = {"untraced": int, "removed": list[str], "notes": list[str], "bytes": int, "blocks": int}。校验不过 → 抛 BuildError（消息含全部问题）；超 HTML_MAX_BYTES → 抛 BuildError（沿用 R83 口径，不静默截断）。
  - render.write_explain(doc, payload, out_dir, **kw) -> tuple[Path, dict]：写 out_dir/explain.html，每次覆盖（派生产物，沿用 R74）。
  - 每个非空块包一层 <section class="blk" data-component="<组件名>">（空串块整层不出现，这是「甜头整块不出现」的可断言形态）。
  - 模板：内联 CSS、零外链；顶部横幅按 mode 分支（program → 「本页未使用模型：文字由程序按事实模板生成」；model → 模型名 + trace 的 meta.repo.commit 与 meta.created_at）；未溯源汇总 + 锚点列表；目录；blocks 顺序渲染；空串块跳过；末尾相对链接 index.html（**由 render.py 判断同目录是否存在该文件后传 show_archive_link 布尔**，模板不查文件系统）。

- [ ] **Step 1: 写红测试**
```python
def test_page_is_self_contained(real_doc):
    html, report = render_explain(real_doc, program_payload(real_doc))
    assert 'http://' not in html.replace('http://www.w3.org/2000/svg', '')
    assert 'https://' not in html and '<link' not in html and '@import' not in html
def test_program_banner_says_no_model(real_doc):
    html, _ = render_explain(real_doc, {'blocks': []}, mode='program')
    assert '未使用模型' in html
def test_model_banner_names_model_and_trace_provenance(real_doc):
    html, _ = render_explain(real_doc, {'blocks': []}, mode='model', model_name='deepseek-chat')
    assert 'deepseek-chat' in html and real_doc['meta']['repo']['commit'] in html and real_doc['meta']['created_at'] in html
def test_invalid_blocks_raise_and_write_nothing(real_doc, tmp_out):
    with pytest.raises(BuildError):
        write_explain(real_doc, {'blocks': [{'component': 'nope', 'args': {}}]}, tmp_out)
    assert not (tmp_out / 'explain.html').exists()
def test_empty_trace_still_renders_and_says_no_facts():
    doc = skeleton_like_doc()
    html, report = render_explain(doc, {'blocks': [{'component': 'overview', 'args': {}}]})
    assert '没有' in html and report['bytes'] > 0
def test_original_index_html_is_byte_identical(real_doc):
    before = render_html(real_doc).encode('utf-8')
    render_explain(real_doc, {'blocks': []})
    assert render_html(real_doc).encode('utf-8') == before
def test_oversize_page_raises_build_error(real_doc, monkeypatch):
    monkeypatch.setattr('papertrace.explain.render.HTML_MAX_BYTES', 10)
    with pytest.raises(BuildError):
        render_explain(real_doc, {'blocks': []})
def test_paper_bonus_absent_without_anchors(real_doc):
    html, _ = render_explain(real_doc, {'blocks': [{'component': 'paper_bonus', 'args': {}}]})
    assert 'data-component="paper_bonus"' not in html
```
program_payload 是 E6 的 narrate.program_blocks；E5 阶段先用一个最小 payload（overview + metrics + flow_chain + 一张 module_card）做测试，E6 再换成真降级版并补断言。最后一条钉的是「无 anchors 时页面不出现甜头块」，靠 data-component 属性断言，不许用整页子串。

- [ ] **Step 2: 跑红** → FAIL
- [ ] **Step 3: 实现 render.py + 模板**（Environment 用 StrictUndefined + select_autoescape，与 render_html 同口径但**独立实例**；兜底一律 | default(x, true)）
- [ ] **Step 4: 跑绿** → PASS；全量零回归；**再核一次原页字节级不变**
- [ ] **Step 5: 变异探针**（≥3 条）M1：横幅 program 分支改成不写「未使用模型」→ 横幅测试必红；M2：空串块也渲染成空 section → 甜头不出现的断言必红；M3：超限改成静默截断 → 超限测试必红。记录 + 还原核 sha256。
- [ ] **Step 6: 提交** git -c core.autocrlf=false commit -m "feat: render the standalone explain page with provenance banner"

---

### Task E6: 无 key 降级叙述 + explain 子命令

**Files:**
- Create: papertrace/explain/narrate.py（≤150 行）
- Create: papertrace/cli_explain.py（≤120 行）
- Modify: papertrace/cli.py（只加 import + add_parser 调用 + 分派，182 → ≤190 行）
- Test: tests/test_explain_narrate.py、tests/test_explain_cli.py

**Interfaces:**
- Consumes: E1 outline；E3 validate_blocks；E5 render_explain/write_explain。
- Produces:
  - narrate.program_blocks(doc: dict) -> dict：{"title": str, "blocks": [...]}。用 outline 的同一份骨架 + 如实模板句；**每个 text 块都带正确 cites**，每个数字都来自 facts；禁形容词性无出处判断。顺序：overview → metrics → flow_chain → 「先看这几个模块」（order 前 3 个 module_card）→ 逐角色分组叙述 → table(modules) → symbol_table → paper_bonus。
  - cli_explain.add_parser(sub) -> None：注册 explain 子命令，参数 --repo / --trace / --out（默认 output）/ --entry / --batch / --seq-len / --no-llm / --title。
  - cli_explain.run(args) -> int：--repo 与 --trace 互斥且必填其一；--repo 先 build_trace + analyze_code（复用既有函数，不重写）；--no-llm 或 backend 非 openai → program_blocks；否则走 E8 的 model_blocks（E6 阶段先留一个明确的 NotImplementedError 分支并在 E8 接上，**不许静默兜底**）；退出码沿用既有口径（实测 exit_codes：UNIMPLEMENTED=2 / MISSING_RUNTIME=4 / UNTRACEABLE=5，**没有 6**）：渲染失败 exit 2（同 cli.py:166）、trace 不合法 exit 1、缺 torch exit 4、追不动 exit 5、参数二选一错交给 argparse（exit 2）。

- [ ] **Step 1: 写红测试**
```python
# tests/test_explain_narrate.py
def test_program_blocks_have_zero_untraced_numbers(real_doc):
    payload = program_blocks(real_doc)
    html, report = render_explain(real_doc, payload, mode='program')
    assert report['untraced'] == 0 and validate_blocks(payload, build_index(real_doc)) == []
def test_program_blocks_cite_only_real_facts(real_doc):
    idx = build_index(real_doc)
    for b in program_blocks(real_doc)['blocks']:
        assert all(c in idx for c in b.get('cites', []))
def test_program_text_has_no_unsourced_adjectives(real_doc):
    payload = program_blocks(real_doc)
    joined = ' '.join(b['args'].get('markdown', '') for b in payload['blocks'] if b['component'] == 'text')
    assert '核心' not in joined and '优雅' not in joined and '强大' not in joined
# tests/test_explain_cli.py
def test_explain_repo_no_llm_writes_page(tmp_out):
    code = main(['explain', '--repo', 'tests/fixtures/nanogpt', '--out', str(tmp_out), '--no-llm'])
    assert code == 0 and (tmp_out / 'explain.html').exists()
    html = (tmp_out / 'explain.html').read_bytes().decode('utf-8')
    assert '未使用模型' in html and '29,856' in html
def test_explain_requires_exactly_one_source(tmp_out):
    assert main(['explain', '--out', str(tmp_out)]) != 0
    assert main(['explain', '--repo', 'tests/fixtures/nanogpt', '--trace', 'x.json', '--out', str(tmp_out)]) != 0
def test_explain_from_existing_trace_does_not_rebuild(tmp_out, monkeypatch):
    calls = []
    monkeypatch.setattr('papertrace.cli_explain.build_trace', lambda *a, **k: calls.append(1))
    code = main(['explain', '--trace', 'output/demo/code-only/trace.json', '--out', str(tmp_out), '--no-llm'])
    assert code == 0 and calls == []
def test_build_still_writes_index_unchanged(tmp_out):
    code = main(['build', '--repo', 'tests/fixtures/nanogpt', '--out', str(tmp_out), '--force'])
    assert code == 0 and (tmp_out / 'index.html').exists() and not (tmp_out / 'explain.html').exists()
```

- [ ] **Step 2: 跑红** → FAIL
- [ ] **Step 3: 实现 narrate + cli_explain + cli 接线**（cli.py 只加三处；核行数 ≤200）
- [ ] **Step 4: 跑绿** → PASS；全量零回归；真跑一次命令并把 stdout 与页面字节数记进报告
- [ ] **Step 5: 变异探针**（≥2 条）M1：narrate 的某句改成写死一个错数字（29,857）→ 未溯源 0 断言必红；M2：--trace 分支也调 build_trace → 不重追测试必红。记录 + 还原核 sha256。
- [ ] **Step 6: 提交** git -c core.autocrlf=false commit -m "feat: add the explain command with an honest no-model fallback"

---

### Task E7: 零依赖 MCP server

**Files:**
- Create: papertrace/mcp/__init__.py、papertrace/mcp/__main__.py（≤15 行）
- Create: papertrace/mcp/server.py（≤150 行）
- Create: papertrace/mcp/tools.py（≤180 行，含 ToolError）
- Create: papertrace/mcp/handlers.py（≤190 行）
- Test: tests/test_mcp_server.py、tests/test_mcp_tools.py

**Interfaces:**
- Consumes: E1–E6 全部 + 既有 build_trace/load_entry/analyze_code/validate_trace/dump_trace。
- Produces:
  - server.handle_message(msg: dict) -> dict | None：通知（无 id）回 None；initialize/tools/list/tools/call/ping 按 spec §6.1；未知方法 -32601、params 非对象 -32602、内部异常 -32603。
  - server.serve(stdin, stdout, stderr) -> int：逐行读；空行跳过；json.loads 失败 → 回 -32700（id 用 null）；每行响应 json.dumps(..., ensure_ascii=False) + 换行；**stdout 只许这些行**；EOF 正常退出 0。
  - tools.TOOLS: list[dict]（6 项，name/description/inputSchema，schema 是 JSON Schema draft-07 子集）；tools.call_tool(name: str, args: dict) -> dict：{"content": [{"type": "text", "text": str}], "isError": bool}；ToolError → isError True + 原因文本；未知工具名 → ToolError。
  - handlers.analyze_repo / get_facts / read_source / list_components / explain_outline / render_explain（各接 args dict，回 JSON-able dict）。read_source 越界 → ToolError；render_explain 校验不过 → ToolError 且**不写文件**。
  - **repo_root 口径**：trace 的 meta.repo.url 实测是相对路径（tests/fixtures/nanogpt），按进程 cwd 解析；analyze_repo 接受绝对路径并在返回里给 resolved 绝对路径，read_source/code 解析不到仓库根时**如实报错，不猜路径**。

- [ ] **Step 1: 写红测试**
```python
# tests/test_mcp_server.py
def test_initialize_then_tools_list_then_call():
    out = io.StringIO()
    lines = [json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}),
             json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}),
             json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}),
             json.dumps({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'list_components', 'arguments': {}}})]
    assert serve(io.StringIO(chr(10).join(lines) + chr(10)), out, io.StringIO()) == 0
    msgs = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [m['id'] for m in msgs] == [1, 2, 3]
    assert msgs[0]['result']['protocolVersion'] == '2024-11-05'
    assert len(msgs[1]['result']['tools']) == 6
def test_malformed_input_never_breaks_stdout_purity():
    out = io.StringIO()
    bad = chr(10) + 'not json' + chr(10) + '{"half":' + chr(10) + '[]' + chr(10)
    serve(io.StringIO(bad + json.dumps({'jsonrpc': '2.0', 'id': 9, 'method': 'nope'}) + chr(10)), out, io.StringIO())
    for line in out.getvalue().splitlines():
        json.loads(line)
    assert any(json.loads(l).get('error', {}).get('code') == -32601 for l in out.getvalue().splitlines())
def test_subprocess_end_to_end(tmp_out):
    proc = subprocess.run([sys.executable, '-m', 'papertrace.mcp'], input=REQUESTS, capture_output=True, text=True, cwd=REPO_ROOT, env=ENV_WITH_PYTHONPATH)
    assert proc.returncode == 0 and all(json.loads(l) for l in proc.stdout.splitlines())
# tests/test_mcp_tools.py
def test_get_facts_pages_and_read_source_stays_inside_repo(real_trace):
    r = call_tool('get_facts', {'trace': str(real_trace), 'kind': 'ops', 'limit': 5})
    assert r['isError'] is False and len(json.loads(r['content'][0]['text'])['items']) == 5
    bad = call_tool('read_source', {'trace': str(real_trace), 'path': '../../x.py', 'start': 1, 'end': 5})
    assert bad['isError'] is True
def test_render_explain_refuses_invalid_blocks_without_writing(real_trace, tmp_out):
    r = call_tool('render_explain', {'trace': str(real_trace), 'blocks': {'blocks': [{'component': 'nope', 'args': {}}]}, 'out': str(tmp_out)})
    assert r['isError'] is True and not (tmp_out / 'explain.html').exists()
def test_unknown_tool_is_a_tool_error_not_a_crash():
    assert call_tool('nope', {})['isError'] is True
```
子进程测试的 env 必须显式带 PYTHONPATH（仓库根 + pydeps），否则 exit 1 且 stderr 空（本机已踩过）。

- [ ] **Step 2: 跑红** → FAIL
- [ ] **Step 3: 实现四个文件**（server 只做分派与 IO；tools 只做 schema 与包装；handlers 只做业务；三者不许互相 import 成环）
- [ ] **Step 4: 跑绿** → PASS；全量零回归
- [ ] **Step 5: 变异探针**（≥3 条）M1：通知也回响应 → id 序列断言必红；M2：read_source 去掉越界检查 → 越界测试必红；M3：serve 把日志 print 到 stdout → stdout 纯净测试必红。记录 + 还原核 sha256。
- [ ] **Step 6: 提交** git -c core.autocrlf=false commit -m "feat: serve papertrace facts and explain rendering over a dependency-free MCP stdio server"

---

### Task E8: 有 key 的模型讲解 + 技能包 + 文档 + 演示

**Files:**
- Create: papertrace/explain/llm_explain.py（≤140 行）
- Modify: papertrace/cli_explain.py（接上 model_blocks 分支）
- Create: docs/explain-agent.md
- Modify: README.md（新增「讲解页」小节 + 已知局限更新）
- Modify: docs/superpowers/plans/2026-11-16-papertrace-explain.md（末尾执行记录）
- Test: tests/test_explain_llm.py

**Interfaces:**
- Consumes: 既有 llm.client.get_llm / ChatResult / LLMUnavailable；E3 validate_blocks；E1 outline；E3 component_menu。
- Produces: llm_explain.build_prompt(doc: dict) -> str（纯函数，可单测）；llm_explain.model_blocks(doc: dict, *, backend=None) -> dict。prompt 含 outline + component_menu + 口吻规范（教学口吻）+ 禁编数字 + custom 规则 + 要求只回 blocks JSON。解析：剥可能的代码围栏 → json.loads → validate_blocks；不合法 → 抛 BuildError（消息提示可用 --no-llm），**不静默降级**；LLMUnavailable → 向上抛由 CLI 决定降级并明示。backend 参数只为测试注入。

- [ ] **Step 1: 写红测试**（假 backend 单实例 + 计数器断言被测路径真被走到）
```python
def test_model_blocks_parses_fenced_json_and_validates(real_doc, fake_backend):
    fake_backend.reply = chr(96)*3 + 'json' + chr(10) + json.dumps(program_blocks(real_doc)) + chr(10) + chr(96)*3
    payload = model_blocks(real_doc, backend=fake_backend)
    assert fake_backend.calls == 1 and validate_blocks(payload, build_index(real_doc)) == []
def test_invalid_model_json_raises_instead_of_silent_fallback(real_doc, fake_backend):
    fake_backend.reply = '我觉得这个项目很好'
    with pytest.raises(BuildError) as e:
        model_blocks(real_doc, backend=fake_backend)
    assert '--no-llm' in str(e.value)
def test_llm_unavailable_propagates(real_doc, offline_backend):
    with pytest.raises(LLMUnavailable):
        model_blocks(real_doc, backend=offline_backend)
def test_cli_degrades_and_says_so_when_backend_offline(real_trace, tmp_out, monkeypatch):
    monkeypatch.delenv('PAPERTRACE_LLM_BACKEND', raising=False)
    assert main(['explain', '--trace', str(real_trace), '--out', str(tmp_out)]) == 0
    assert '未使用模型' in (tmp_out / 'explain.html').read_bytes().decode('utf-8')
def test_prompt_forbids_inventing_numbers_and_teaches_tone(real_doc):
    p = build_prompt(real_doc)   # prompt 组装必须是可单测的纯函数
    assert '不要编造' in p and '教学' in p and 'custom' in p
```

- [ ] **Step 2: 跑红** → FAIL
- [ ] **Step 3: 实现 llm_explain + 接 CLI + 写技能包与 README**（技能包必须含：六工具用法、blocks 完整示例、口吻规范、禁编数字、custom 规则、看未溯源数回头补 cites 的循环）
- [ ] **Step 4: 跑绿** → PASS；全量零回归
- [ ] **Step 5: 变异探针**（≥2 条）M1：解析失败改成静默返回 program_blocks → 响亮报错测试必红；M2：prompt 里删掉「不要编造」一句 → prompt 钉子测试必红。记录 + 还原核 sha256。
- [ ] **Step 6: 重生成三份演示**（code-only / with-paper / fallback-yellow 各出 explain.html；**只有 fallback-yellow 那份有 anchors=4 → 只有它出现甜头块**，code-only 与 with-paper（offline，anchors=0）都不出现），把字节数与未溯源数记进报告
- [ ] **Step 7: 提交** git -c core.autocrlf=false commit -m "feat: let a model write the explain page, with a skill pack and refreshed demos"

---

## 交付验收（全片结束时逐条核）

1. python -m papertrace explain --repo tests/fixtures/nanogpt --out output/demo-explain --no-llm → exit 0；页面零外链、横幅含「未使用模型」、未溯源数 0、含主链/模块卡/指标/体检。
2. MCP 端到端：initialize → tools/list（6）→ get_facts 分页 → render_explain → 文件写出；stdout 每行合法 JSON。
3. 在 DSH 里真挂一次 server，由控制器当讲解员产出一版模型撰写的 explain.html，交年糕读（主观验收）。
4. 原 index.html 字节级不变；GC8 六项不变；全量 pytest 绿（854 + 新增）。
5. 三份演示目录都有 explain.html；只有 fallback-yellow（anchors=4）有甜头块，code-only 与 with-paper 没有。
6. README 新增「讲解页」小节 + docs/explain-agent.md；已知局限如实更新（含「主链是启发式」「受限 markdown」「本片不讲仓库文件树」）。

## 执行记录（施工时逐 Task 追加）

| Task | 提交 | 全量条数 | 评审 | 备注 |
|---|---|---|---|---|
| E1 | | | | |
| E2 | | | | |
| E3 | | | | |
| E4 | | | | |
| E5 | | | | |
| E6 | | | | |
| E7 | | | | |
| E8 | | | | |
