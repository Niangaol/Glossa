# PaperTrace

把 PyTorch 仓库的算子级数据流图，与论文里的公式项逐项对上账。别人看结构，我们做对账。

## 现在是什么状态

**M1a：真实算子追踪。** 已经能跑通的链路：

```text
仓库 + 入口模型 → torch.export 真实执行 → 抓每个 aten 算子 → trace.json（节点带真实形状、模块层级、shape 一致性）
```

论文 ingest 与「公式项 ↔ 算子」对账的**脊柱**已经接进 `build --paper`（S9）：
`meta.paper`、`symbols`、`anchors`、`unresolved` 四个槽都会如实填，拿不到依据就只写
`unresolved`——默认 `offline` 后端下一项 anchor 都不出（没有 judge 判定、没有 embedding
检索），公式项按同构层逐层展开，共 8 条全部落 `unresolved` 并逐条写清为什么（4 个公式项
× 2 个同构层，R161）。配了判断题后端时，即使结构同构没命中，judge 也会判「算子类型 +
词法」候选并给出**黄线**锚点——**绿线仍然只发给结构对上账的项**（S15/R112：回退候选没有
形状与序列依据）。结构同构命中时**逐层展开**（M4a B 方案，R161）：每个同构组各出一条
anchor（如 `transformer.h.0.attn` 与 `transformer.h.1.attn` 两组各出 4 条），anchor 带
`code_group`（形如 `root/transformer.h.0.attn`）标明落在哪一层。
还没做的：mismatch 判定、交互式前端。
这些仍然是桩，**空就是空**，不会塞示例数据。

本地模型（Ollama / 7B / nomic-embed-text）**故意没装**，不是缺步骤。默认后端是 `offline`，任何要模型的地方会直接报 `LLMUnavailable`，不允许编造结果。

## 快速跑通

依赖装在仓库内的 `pydeps/`（见 `docs/ENVIRONMENT.md`），不污染系统 Python：

```bat
cd /d D:\AgentPrograms\PaperTrace
set PYTHONPATH=D:\AgentPrograms\PaperTrace\pydeps
python -m pytest -q
python -m papertrace --help
```

真实追踪一个 nanoGPT（本仓库自带夹具）：

```bat
python -m papertrace build --repo tests/fixtures/nanogpt --entry model:build_model --out output/m1a
python -m papertrace build --repo tests/fixtures/nanogpt --paper tests/fixtures/papers/vaswani2017/attention.tex --out output/spine
python -m papertrace dump --trace output/m1a/trace.json
python -m papertrace dump --trace output/m1a/trace.json --ops
python -m papertrace dump --trace output/m1a/trace.json --edges
```

脊柱切片（论文 → 公式项 → 符号 → 信号 → 分档 → `trace.json` + `index.html`）的跑法，
Windows pwsh 里可直接复制（三个环境变量是测试纪律，见 `docs/ENVIRONMENT.md`）：

```pwsh
$env:PYTHONPATH='D:\AgentPrograms\PaperTrace;D:\AgentPrograms\PaperTrace\pydeps'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
python -m papertrace build --repo tests/fixtures/nanogpt --entry model:build_model --out output/spine-nowhere
python -m papertrace build --repo tests/fixtures/nanogpt --paper tests/fixtures/papers/vaswani2017/attention.tex --out output/spine
python -m papertrace build --repo tests/fixtures/nanogpt --paper tests/fixtures/papers/vaswani2017/attention.tex --skeleton --out output/spine-skeleton
python -m papertrace build --repo tests/fixtures/nanogpt --skeleton --out output/spine-skeleton-only
```

四种输入各产出一份 trace：① 不带 `--paper` → 没有论文侧，anchors/unresolved 全空，
行为与 M1a 逐项一致（nodes/edges 计数见「字段约定」）；② 带 `--paper`（本地 `.tex`；
只有 `ingest_mode=tex` 实现了，`arxiv:…` 不联网，如实空态 + unresolved）；③ `--skeleton --paper`
→ 空骨架 + 论文脊柱：没有模型实例，5 个 `symbol` 与 4 个 `paper_unit` 全进 `unresolved`
（不追踪就没有算子图，结构同构无从命中，走每项一条的回退口径）；④ 纯 `--skeleton` → 只写合法的空 trace，不追踪。
产物固定是 `<out>/trace.json` 与 `<out>/index.html` 两个文件（`index.html` 是单文件离线 HTML，
零外链，8MB 上限，超限抛 `BuildError` 而不是静默截断）。

`--ops` 一行一个算子，下面是本仓库夹具的**真实输出**（形状是第二遍执行跑出来的，不是推的）：

```text
root/@020        transformer.wte                    (2, 8) -> (2, 8, 32) embedding
root/@037        transformer.h.0.attn               (2, 4, 8, 8) -> (2, 4, 8, 8) matmul
root/@043        transformer.h.0.attn               (2, 4, 8, 8) -> (2, 4, 8, 8) softmax
```

权重/输入节点不是算子，`--ops` 里它们的输入形状打 `-`；算子**确实没有数据入参**（只用权重/缓冲，
比如 `slice`）也打 `-`。只有老格式 trace 缺 `inputs` 字段时才打 `(?)`——`(?)`、`-`、0 维标量的
`()` 三者互不混淆。

`--edges` 一行一条边，左列是**消费者真实拿到的输入形状**，右列是**生产者真实吐出的输出形状**。
行首空格 = 两边核实相等，`!` = 对不上，`?` = 有一边没观察到（未核实，不等于一致）：

前两行是夹具的真实输出（embedding 的数据入边是 token id `(2, 8)`，权重边 `(64, 32)` 也在，但不冒充主输入）：

```text
  (64, 32)         生产者 (64, 32)         root/@015 (placeholder) -> root/@020 (embedding) e:root/@015->root/@020:args[0]
  (2, 8)           生产者 (2, 8)           root/@020 (embedding) -> root/@022 (add) e:root/@020->root/@022:args[0]
```

第三行是**反例**（不是夹具输出）：消费者只取了 split 的第 2 项 `(2, 8)`，却拿到 `(2, 6)`——

```text
! (2, 6)           生产者 (2, 8)           root/@031 (split) -> root/@034 (add) e:root/@031->root/@034:args[1][0]
```

末行给 `edges=N shape_broken=M shape_unchecked=K`。两边的形状不是同一条推断抄两遍：导出图会用真实张量
**再跑一遍**（`fx_observe`），边两端取的是这次执行里各自的实际形状。

### 接云端中转（可选）

不配任何变量时，默认后端仍是 `offline`：该报 `LLMUnavailable` 就报，不编造结果。
要真接模型（OpenAI 兼容中转；本地 ollama 仍未实现），设这四个变量：

```bat
set PAPERTRACE_LLM_BACKEND=openai
set PAPERTRACE_OPENAI_BASE_URL=https://api.deepseek.com
set PAPERTRACE_OPENAI_API_KEY=sk-...
set PAPERTRACE_LLM=deepseek-chat
```

- `PAPERTRACE_LLM_BACKEND=openai:deepseek` 这种写法也认得，但冒号后缀只是**被容忍的写法，
  不是模型名**：模型名只从 `PAPERTRACE_LLM` 读，写进后缀会被直接丢掉。
- 上面三个变量缺任何一个，第一次调用模型时会**点名缺哪个**（抛 `LLMUnavailable`），
  不会默默套一个默认模型名顶上去。
- **DeepSeek 没有 embeddings 端点。** 只配 openai 时检索分 `s_retr` 仍然是 0，出的是
  **黄线**（有 judge、没检索证据），不是绿线——配了 key 也不等于绿。
- **两个变量别设混**：`PAPERTRACE_LLM_BACKEND` 是**后端选择器**（`offline` / `openai` / `ollama`），
  `PAPERTRACE_LLM` 是**模型名**。名字写错不会报错，只会静默走回 offline（所以「没点亮」先查这两个）。
- **S17 修订（m03858 已批）**：`embed_texts()` 返回 `list[list[float]]` 而不是 `np.ndarray`——
  本机 `pydeps/` 里没有 numpy（工程计划书 Task 11 原来的措辞不成立）。配的后端没有
  `/embeddings` 时 `embed` 必须抛 `LLMUnavailable`，不许拿假向量顶。

### offline 为什么全 unresolved

默认 `offline` 后端下 `chat` / `embed` 直接抛 `LLMUnavailable`（R83：不返回固定 yes、
不返回假向量），于是判断题拿不到 yes/no、检索拿不到分数：`anchors == []`，全部公式项进
`unresolved`，每条带 reason。条数随场景而不同，都是如实数：真实追踪（带模型）下是
**0 个 symbol + 8 个 paper_unit**（4 个公式项 × 2 个同构层，逐层各报一条）；`--skeleton
--paper` 下是 5 个 symbol + 4 个 paper_unit（骨架没有模型实例，符号抽不到；没有算子图，
结构同构不命中，走每项一条的回退口径）——**空清单就是诚实的答案**，不是 bug，也不该为了
「好看」把线连上。

分档公式写死在代码里（`papertrace/spine.py`）：`a = 0.30·s_retr + 0.50·s_judge + 0.20·s_struct`，
`c = sigmoid(4·(a−0.5))`；`c≥0.75` 绿实线、`0.45≤c<0.75` 黄虚线、`c<0.45` 不连线；
**U1 门：绿线还要求 `s_struct ≥ 0.5`**。

下表是**本切片的可达值**。本切片结构分 `s_struct` 上限是 **0.8**（只可能加
`BASE_SCORE 0.5` + `BONUS_CONFIG 0.1` + `BONUS_ISOMORPHIC 0.2`；设计文档 §2 里
+0.2 论文 N 层 / −0.4 shape 冲突 / −0.3 双向检索三条规则本切片不可判定，留给 M4）。
设计文档 §2 那张表用的是 `s_struct=1` 的**理论值**，与这里口径不同——照抄会写出用户
永远看不到的数字（第 4 行「弱检索 0.25 → 绿线」在本切片实际是黄线）：

| 场景 | 设计文档 §2（理论 s_struct=1） | 本切片可达（s_struct=0.8） |
| --- | --- | --- |
| 全 offline，c=0 | 0.231475 → 不连线（none） | 0.204240 → 不连线（none） |
| 词法满分但 judge=no | 0.500000 → 黄线 | 0.460085 → 黄线 |
| judge=yes、无 embedding | 0.689974 → 黄线 | 0.654753 → 黄线 |
| judge=yes + 弱检索 0.25 | 0.750260 → 绿线 | 0.719100 → **黄线**（档位翻了） |
| 三项全满 | 0.880797 → 绿线 | 0.862949 → 绿线 |
| U1 反例 (s_retr,s_judge,s_struct)=(1,1,0) | 0.768525 → 黄线 | 0.768525 → 黄线（s_struct=0 不受上限影响） |

精确门槛（用 `sigmoid(4·(0.30·s_retr+0.50·s_judge+0.20·s_struct−0.5))` 实测算过）：

- `s_judge=1` 时要绿线需要 `s_retr ≥ 0.382177`（0.3822 → 0.750005 绿；0.3812 → 0.749780 黄）。
- `s_retr=0`（DeepSeek 没有 embeddings 端点）时天花板是 `c=0.654753` **黄线**：
  配 DeepSeek 中转永远出不了绿线。
- `s_judge=0` 时即使检索满分也只到 `c=0.460085` **黄线**（judge 权重 0.50 是决定性的）。
- 绿线门独立生效：`s_struct=0.49` → `c=0.830897` 仍黄线；`0.5` → `0.832018` 绿线。

所以要点亮绿线，得让检索信号真的拿得到：**DeepSeek 没有 `/embeddings`**，配它时 `s_retr`
恒 0，天花板就是黄线；换一个真提供 `/embeddings` 的 OpenAI 兼容后端，并且 judge 能答 `yes`，
才够得到绿线——只配 `PAPERTRACE_LLM_BACKEND=openai` 而 embeddings 端点取不到，仍然是黄线。

### trace.json 的字段约定

- **节点 id**：模块节点是路径（`root`、`root/transformer.h.0.attn`），算子/输入/权重节点一律
  `root/@037`——`@` 不会出现在模块路径里，所以两种 id 不可能撞车。真有子模块名里带 `@`，
  `build` 直接报 `BuildError` 要求改名，而不是生成一份 id 打架的 trace。
- **`kind`**：`op` | `input` | `param` | `const`。**谁是谁由 `graph_signature.input_specs` 说了算**：
  `PARAMETER`/`BUFFER` → `param`，`CONSTANT_TENSOR` → `const`，`USER_INPUT` → `input`；
  `TOKEN` 与 `CUSTOM_OBJ` **明确拒绝**，不认识的 `InputKind` 也拒绝，不默认成 `input`。
  `TOKEN` 是 `TokenArgument`（副作用/控制流的令牌），不是张量，不该按张量喂。
  `CUSTOM_OBJ` 是 `exported.constants` 里的 `ScriptObject` 常量（torch 只把 ScriptObject
  建成这一类）：第十一轮曾把它映射成 `const`，但**从来没有真实导出用例背书**——torch 2.15
  会把 `self.obj.add(x)` 常量折叠成 `x+3`，造不出 `CUSTOM_OBJ` 的 spec。第十六轮起
  **先拒绝**（exit 2），M1b 补真实 ScriptObject 导出用例再放开；没验证过的分支不写成「已支持」。
  标成 `input` 会让合法模型凭空多一个数据输入、随后 `example_inputs` 数量对不上而 exit 5，
  所以「不默认成 input」这条对两者都成立。
  `parent_id` 用 `spec.target` 的点分路径（`transformer.h.0.attn`）定位所属模块，不靠名字猜。
  **常量与字面量算子要分清**：`self.const = torch.ones(...)` 这种**属性**被导出器抬成
  `CONSTANT_TENSOR`，单独标 `kind=const`，摘要写「常量 N」而不是塞进「权重 N」；
  而 forward 里现写的 `torch.ones(2,4)` 在导出图里就是一个 `ones` **算子**（`kind=op`），
  它的 `inputs` 为空。两者都不是数据入参，也都不是可训练权重。
  **拿不到 `input_specs` 就 fail-closed**：判据是「**每个 placeholder 都被 spec 覆盖**」，
  不是「plan 是不是空字典」——`classify([])` 是个非空 dict，只看真假会被它绕过去。
  有未覆盖的 placeholder、spec 多出图里没有的名字、同一个名字既被标成权重又被标成输入、
  spec 顺序与 placeholder 顺序不一致、或出现**不认识的 `InputKind`**（不默认成 input），
  一律 `BuildError`（**exit 2**，CLI 与直接调 `build_op_nodes` 同一个码），不再退回 mangled 名猜：
  `p_+参数全名` 会把 `sub.x` 与根上的 `sub_x` 压成同一个 `p_sub_x`，也会把形参 `p_x` 和
  参数 `x` 的压平名混为一谈，猜错的代价是整份 trace 的 kind 反过来（权重标 input、
  输入标 param、常量消失），而且计数可能「看起来正常」。
  真的没有 placeholder（纯常量模型）时，空 plan 是合法的。
  **边界要说清**：`build_op_nodes` 自己只保证「覆盖齐全、不重叠、无幽灵名、kind 都认识」；
  「这个 kind 标得**对不对**」由 `fx_contract` + `placeholder_args` 把八道关，地面真相各不相同：
  ① spec 说它是权重 → **模块**里必须真有这个参数/缓冲；
  ② **模块**里每个参数/缓冲 → 必须被某个 `param`/`const` spec 认领；
  ③ 传入的 plan 必须与 **`torch.export` 自己的 `input_specs`** 逐项一致（name/kind/target/顺序）。
  只有 ① 是单向的：把真实权重标成 `input`、再给 `example_inputs` 多补一项，数量校验就骗过去了
  （实测放行过），② 才堵得住。但 ①② 都堵不住**两边互换**：模块有名为 `x` 的参数、forward 也有
  形参 `x` 时，把 `p_x` 标 input、`x` 标 param(target=x)，名字全覆盖、顺序对、认领齐、数量还对，
  四道旧关卡全过而 kind 正好相反（实测 CLI exit 0）——③ 才堵得住，因为 kind 的权威是导出器。
  `const` 的值**只能来自 `exported.constants`**：不许顶替可训练参数，也不许顶替缓冲
  （缓冲是可变状态，`BUFFER` 映射成 `param`；给 const 开第二套语义等于允许手改 plan 蒙混出图）。
  `build_op_nodes` 是**内部 API**：外部调用请传 `exported=`，入口会把四张表与导出器重生的表核对；
  不传就等于声明「这份 plan 已经核过契约」——只有已经跑过 `placeholder_args` 的调用方
  才该这么用（`fx_trace` 自己是传 `exported=` 的）。
  trace.json 里不存 input_specs，所以 `validate_trace` 只查 schema 与结构，**查不出 kind 标反**
  ——那一道关在 build 时**把守**，地面真相是模块与导出器，不是 plan 自己（存一份同源摘要也查不出）。
  **这两道「与导出器核对」的关，牙齿到底在哪**（实测写死，别当成万能）：正常 CLI 路径里
  `plan` 与关里的 `expected` 是**同一个纯函数算两遍**（`input_plan(exported)`），平时根本不触发。
  真正抓得住的是两类：① **管线自己漂移**——`fx_trace.classify`/`fx_trace.input_plan` 与
  `fx_nodes`/`fx_signature` 各自的 import 绑定是独立的，某一级改坏了另一级就拒绝
  （`tests/test_eleventh_review.py` 里 monkeypatch `fx_trace.classify` 的两条用例）；
  ② **直接 API 传伪造 plan**——外部调 `build_op_nodes(..., exported=)` 时四张表对不上就拒绝。
  抓不到的也有两类，说清楚免得给假安全感：把 `fx_signature`/`fx_trace`/`fx_nodes` **三处
  `input_plan` 引用全换掉**就能绕过（monkeypatch 权威本身不在威胁模型内，实测放行）；
  `KIND_MAP` **自己映射错了**这两道关也抓不到（plan 与 expected 一起错）——那一类靠钉死每个
  `InputKind` 映射值的测试与 model zoo 的精确计数把。
  **第十二轮补的三道防线**（评审指出 ③ 的 `expected` 也是从**调用方传进来的** `exported` 重生的：
  传一个 `SimpleNamespace` 就能让 plan 与 expected 一起错、两道关全过，实测放行）：
  ④ **类型守卫**：`placeholder_args` 与 `build_op_nodes(exported=)` 入口要求 `exported` 是
  `torch.export.export()` 的真产物（`ExportedProgram`），鸭子类型的替身一律 exit 2；
  ⑤ **顺序不变量**：torch 自己在 `ExportGraphSignature` 的 docstring 里写死
  `Inputs = [*parameters_buffers_constant_tensors, *flattened_user_inputs]`，权重/缓冲/常量
  必须全部排在数据输入之前——「两边互换」恰好破这条（名字、顺序、认领、数量全都对）。
  这不是我们发明的启发式：24 个真实模型实测无一违反，18 个 zoo 模型有正向对照用例；
  ⑥ **恰好认领一次**：同一个参数/常量被两个 placeholder 认领就拒绝（用 `Counter` 而不是 `set`，
  `set` 会把重复压成一个、让图里凭空多出一模一样的权重节点）。
  ⑤⑥ 在**真** `ExportedProgram` 上就地改 `graph_signature.input_specs` 也复现过，所以类型守卫单独不够。
  **第十三轮补的第七道**（评审实测：④⑤⑥ 之后，在真产物上互换两个参数的 `target` 仍能全过——
  名字、顺序、认领、四张表**完全不变**，trace 把 `p_a` 记成 `b` 的形状、`shape_broken` 还是 0）：
  ⑦ **形状核对**：`placeholder_args` 取到真实张量后，与 `node.meta["val"]` 的形状逐项比。
  那是导出器在图上做 fake 传播的结果，与 `input_specs` 的 `target` 映射是**两个独立字段**，
  所以这是真核对而不是同源比对。不同形状的 target 互换（参数↔参数、参数↔缓冲、常量↔常量）
  一律 exit 2 并点名「取到的张量是 (1,4)，但导出图里这个节点是 (2,4)」。
  **这一关在动态形状下会静默跳过**：`node.meta["val"]` 的维是 `SymInt` 时无法与整数逐项比，
  实现直接 return。M1a 不传 `dynamic_shapes`，所以当前没有路径走到这里；M1b 支持动态批长时
  **必须记一个独立的 `shape_gate_skipped` 计数**（不复用边级 `shape_unchecked`），
  或者干脆对动态形状 `TraceUnsupported`——不能让一道关悄悄失效而计数看起来全 0。
  **第十四轮补的第八道**（评审实测：⑦ 之后，**同形状、跨模块**的 target 互换仍然全过——
  `Sub.w` 与根 `M.a` 都是 `(2,4)` 时，trace 把 `root.p_a` 的 `parent_id` 写成 `root/sub`、
  `root.p_sub_w` 写成 `root`，而 `shape_broken`/`orphan` 全 0、`validate_trace` 通过、CLI exit 0。
  那是**可见的错误数据**；第十三轮写的「同形状互换没有任何可见差异」是错的，已纠正）：
  ⑧ **名字 ↔ target 核对**（`fx_names.check_name_target`）：placeholder 的**名字**在图上
  （torch 的 `placeholder_naming_pass` 生成，`torch/_export/utils.py:1080-1215`），`target` 在
  `input_specs` 里。改后者不会改前者——与 ⑦ 同一个道理：找另一份产物，而不是把同一份映射再算一遍。
  **第十五轮把实现从「反推索引」改成「正向核对」**，因为反推是**有损**的：torch 生成名字时
  先剥**开头**的 `L__self___`/`self_`、把非字母数字换成 `_`、再 `lower()`
  （`utils.py:1113-1119`、`:1168`；嵌套的 `sub.self_attn` **不剥**，实测确认）。
  第十四轮只按 `target.replace(".", "_")` 反推，后果是双向的：
  - **误杀合法模型**（评审 C1）：`self_attn.weight` 的名字是 `p_attn_weight`，反推索引里
    `attn_weight` 唯一指向 `attn.weight`，与 spec 说的 `self_attn.weight` 不符 → exit 2。
    `a-b`+`a_b`、`W`+`w`、`x`+`self_x` 同理，四个合法模型全被拒、不写 trace。
  - **漏检 + 静默写错 parent**（评审 C2）：`self_a`/`self_b` 的 base `a_weight` 在索引里
    **查不到**（索引键是 `self_a_weight`）→ 跳过不猜 → 互换 target 后 `parent_id` 写反、
    CLI exit 0、counts 全 0。这**不是**已文档化的压平歧义，是映射缺失。
  正向核对按 torch 的规则把 spec 的 `target` 映射成期望的 base，再与图上观察到的 base 比
  （允许 `_N` 重名后缀，**先比全名**：`ws.0` 的 base 本来就是 `ws_0`，先剥后缀会漏检，
  `test_parameter_list_target_swap_is_refused` 钉死这个顺序）。
  **按构造不会误杀**：参数真名叫 `self_` 时 base 是空串，反推会误杀，正向不会。
  对不上就 exit 2，报错同时给出**观察到的 base** 与**按 target 应当得到的 base**
  （「`p_a_weight` 去掉前缀 'p_' 后的 base 是 'a_weight'，而 target='self_b.weight'
  按 torch 的命名规则应当是 'self_b_weight'」）——只印后两者的话，`strip_name(target)`
  恰好等于 `target` 时会印成同一个值，用户看不出为什么被拒（第十六轮 M-2）。
  **认不出前缀就拒绝，不静默跳过**（第十六轮 I-1）：原来 `prefix is None` 直接 continue，
  等于 torch 一旦改命名规则、或直接 API 传个怪名字，这道关就悄悄失效。当前 torch 2.15
  的前缀表是 `p_`/`b_`/`c_`/`obj_`/`token`，我们只留 `p_`/`b_`/`c_`：`obj_` 与 `token`
  对应的种类已在更早一步被拒，万一直接 API 传进来会撞上「认不出前缀」而不是走没验证过的分支。
  `tests/test_sixteenth_review.py` 真的把图上的 placeholder 改名（`node.name` 是可写成员）
  来模拟「torch 换了命名规则」，并钉到 CLI 级 exit 2。
  **这条用例证明的是「认不出前缀会 exit 2」，不是「torch 真换了前缀之后映射仍然正确」**——
  它防的是版本漂移导致的静默失效；映射本身的正确性靠 `KIND_MAP` 钉死值、model zoo
  与真实导出用例，别把这两件事混为一谈（第十七轮评审 Minor 4）。
  期望值不是我自己拍的：`tests/test_fifteenth_review.py` 用六个真实模型
  （`self_attn`+`attn`、`self_a`/`self_b`、`a-b`+`a_b`、`W`+`w`、嵌套 `self_attn`、`x`+`self_x`）
  把我们的 `strip_name` 与 torch **真实生成的名字**逐个交叉核对，并断言 `parent_id` 精确正确；
  另有 11 个温和命名模型与 18 个 zoo 模型的正向对照。
  名字核对与模块无关，所以**同模块**的同形状互换也被拒——第十三轮那条「不可观测」用例
  已按事实改写成 `test_same_shape_target_swap_is_refused_by_the_name_gate`。
  残余边界（说全，不留「已封死」的错觉）：
  - **压平撞名**：`a.b` 与 `a_b`、`self_attn.weight` 与 `attn.weight` 正向映射到同一个 base，
    名字区分不了它们，互换仍然抓不到，`parent_id` 确实会写反。两条 trace 级用例把这个代价
    钉成可见事实：`test_fourteenth_review.py::test_ambiguous_swap_really_does_change_parent_id`、
    `test_fifteenth_review.py::test_flattening_clash_swap_is_still_not_observable_by_name`。
  - **这一关单独调不是完整权威**：`_matches` 允许任意 `_数字` 后缀，所以
    `check_name_target([p_a_1], target='a')` 会被接受；端到端由 ⑥ 的「恰好认领一次/未认领」
    拒绝（`test_sixteenth_review.py` 把两层都钉死：单关接受 + 两个模型端到端拒绝）。
    要让它独立可复用，得精确复刻 torch 的冲突计数，那会引入新的误杀风险，M1a 不做。
  - **CUSTOM_OBJ 属 M1b 验证项**：现在直接拒绝，不是「支持了但没测」。
  就地篡改真产物的 spec 属于「篡改权威本身」，与 monkeypatch 掉全部 `input_plan` 同一类，
  不在本切片的威胁模型内；⑤⑥⑦⑧ 只抓其中**可观测**的改法。
- **形状**：`shape_out` 是第 1 项输出；`outputs` 是全部输出（`[]` = 无张量输出，
  `[[]]` = 0 维标量）。`inputs` 是**数据**入参形状（按参数顺序，权重位置整个跳过），
  `shape_in` 就是 `inputs[0]`；权重边不会冒充输入（藏在 `cat([w, x])` 这类**容器**里的权重也照样
  整个跳过），只用权重的算子 `inputs` 为空、`shape_in` 也为空（`--ops` 打 `-`，绝不回退成
  权重形状）。权重本身的形状看 param 节点和它的入边。
- **`dump --ops` 每行带 `kind`**（`kind=param`/`kind=input`/`kind=const`）：param 与 input 互换时
  终端上直接看得出来，不用去翻 JSON。
- **权重派生量不算数据输入**：`self.w[0]`、`self.w[:, :2]`、权重的转置/切片这类**只由权重算出来**
  的中间张量，和权重本身同等对待——它们不进 `inputs`，`shape_in` 仍是模型数据入参的形状。
  反过来 `x[0]` 这种从数据张量上取的切片仍是输入，不会被误伤。
- **常量派生量也不算数据输入**：`ones_like(x)`/`zeros_like(x)`/`full_like`/`new_*` 只借输入
  的形状和 dtype，产出的是常量——它们自己的 `inputs` 记空，下游 `cat([ones_like(x), y])`
  的 `shape_in` 是 `y` 的形状。`rand_like` 不在这个名单里（随机数不是常量）。
  `example_inputs()` 必须按 `forward` 形参顺序给。数量对不上时 `build` 一律 `exit 5`：
  多数情况 `torch.export` 当场报「missing a required argument」，漏到我们这层的则由
  `placeholder_args` 明说「按 forward 形参顺序给，多/少都不猜」——两种情况都不写 trace。
  **pytree 输入（dict/list）本切片不自动摊平**：`forward(d)` 的 `d` 是 dict 时，导出器把它摊成
  `d_a`、`d_b` 两个数据输入，而 `example_inputs()` 给的是一个容器 → 数量对不上 → exit 5，
  消息点名「图里有 2 个数据输入（d_a、d_b）」。**这是范围控制，不是技术上必须猜**：M1b 用
  导出器同一个 `pytree.tree_flatten((example_inputs, {}))` 再与 `exported.call_spec.in_spec`
  对照即可支持，结构不一致就拒绝，全程不猜顺序。本切片先不做；直接调 `placeholder_args`
  时自己给摊平后的元组即可（`tests/test_twelfth_review.py` 的 pytree 三条就是这么测的）。
- **边**：按参数位置一条条连（`args[1][0]` 这种 label），`torch.cat([a, b])` 不会丢边。
  每条边同时记 `shape`（消费者这一项的真实输入）、`producer_shape`（生产者真实输出）和
  `checked`。`shape_consistent` 只在 `checked` 时才有意义；两边对不上就是 False，
  `dump --edges` 打 `!`；没观察到就打 `?`，**未核实不算通过**。
- **`meta.runtime`**：这次追踪怎么来的——设备、torch 版本、dtype、**实际**的 batch/seq_len、
  示例输入、entry，`requested`（命令行请求的 batch/seq_len，和实际值分开记，免得自相矛盾），
  `real_execution`（第二遍真实执行是否成功；**失败时根本不写 trace**，见退出码 5），以及 `counts`
  （operators/degraded/fused/orphan/shape_broken/shape_unchecked）。没有它就没法判断这份 trace 能不能复现。
  **orphan = 既没有入边、也没有出边、也不被图输出引用的算子**（三个条件都要断）。只看入边会把
  「被下游用着的数据源」误报成孤点——`torch.rand(2,4)` 没有入边但有出边，它是源不是孤点；
  常量源同理，被用着就有出边，所以**不需要给常量开豁免名单**。只看边又会把「直接 `return`
  的常量/零实参算子」误报成孤点：`return torch.ones(2,4)` 一条边都没有，但它是图的输出，
  不是孤点（tuple/dict 输出里的每一项都算被引用）。一个谁都不用、也不是输出的 `torch.ones`
  会被数出来。
  **已知取舍：本切片不做死代码检测**——「有入边但没人用」的死算子按这个定义不算 orphan，
  也不计入任何其它计数。`orphan == 0` 不等于「没有死代码」，要查死代码得另做输出可达性分析。
- **`symbols`（M1b 起）**：代码侧符号表与论文侧符号表的对照，符号名冻结 `B`/`T`/`D`/`H`/`Dh`。
  `T` 记的是**声明的**超参数 `config.block_size`（夹具 16），不是运行时序列长度——后者是
  `min(block_size, DEFAULT_SEQ_LEN)`（夹具 8），另记在 `meta.runtime.seq_len`。两者不是一回事，
  拿 `T` 去对论文里的序列长度会对错账。`Dh = D // H` 是**派生量**（夹具 `GPTConfig` 没有
  `head_dim` 字段），与论文侧 `d_k` 的精确对账由 M4 负责；整除不成立时也只发向下取整的值，
  `codeSymbol` 没有「约等」字段，不会假装两侧相等。
  **符号表记「声明值」，运行时形状在 `nodes` 里**（R31）：夹具 `GPTConfig` 的类默认值是
  `block_size=1024 / n_head=12 / n_embd=768`（`tests/fixtures/nanogpt/model.py:20-24`），
  `build_model()` 实际传的是 `16 / 4 / 32`。`symbols` 是 trace 的**顶层键**（不在 `meta` 里），
  `defined_at` 指向**类默认值所在行**（1024/12/768 那几行），`value` 是**实例值**（16/4/32）——
  两者本来就不是一回事，别拿 `symbols[].value` 当运行时形状：运行时形状只认 `nodes[].shapes`
  与 `meta.runtime`。
- **`anchors` / `code_expr_range`（S9 起）**：一条 anchor = 一个论文公式项对同构组里的算子节点
  （逐层展开，R161：结构路径下每个同构组各出一条，回退路径每项一条）。
  `code_expr_range` 记的是 **trace 节点 id 区间**（单个 `root/@037`，多个 `root/@037..root/@045`，
  按结构信号 `pairs` 的 node_id 首尾），**仍是纯节点 id 区间、不换成 `file:line`**：换格式会让
  `index.html` 的彩线全部静默消失（`render_html.py:98` 拿它当节点 id 用），真实行号在
  `nodes[].loc` 上——**算子节点的 `loc` 现在是真实 `file:line`**（M1b 已落地）；M1a 时它全是
  `model.GPT` 这类模块路径（编行号就是造假）。HTML 的算子行显示 `basename:line`，完整路径在
  `title` 里。**路径已相对化**：算子 `loc` 写出时转成相对构建时工作目录的路径（分隔符统一 `/`，
  口径与例外见「路径是相对构建目录的」）——它记录的是「相对构建目录」的位置，不是自包含的，
  换目录打开会指错；**op 节点 `loc` 是 `file:line` 而 module 节点 `loc` 仍是模块路径**
  （同一字段两种语义，既有设计；module 的 `loc` 是模块路径不是文件路径，不参与相对化）。
  **R133 修订**：另两条溯源字段 `meta.repo.url` 与 `meta.paper.source` **同样相对化**（同一口径）——它们是「这份
  trace 从哪来」的机器可读记录（`paper.source` 是本机 `.tex` 路径，`repo.url` 是命令行传入的仓库路径）；
  不在构建目录之下的绝对路径保持原样，分享 `trace.json` 只在这一种情形下还会带上本机目录。
  给人读的正文侧则只显 `basename`：算子行与符号表的
  完整路径进 `title`，HTML 里的仓库名取 `Path(...).name`。
  `tier` 只有 `green`/`yellow`/`none` 三档，`none` **绝不写成 anchor**，只进 `unresolved`；
  `source` 只可能是 `model`（判断题给了 yes）或 `static`（只有结构/检索依据）——anchor 不是
  实测出来的，所以永远不是 `runtime`。`signals` 里的 `s_retr`/`s_judge`/`s_struct` 与
  `confidence` 是**同一份数**（schema 会强制三者自洽），不是各算一遍。
  **R91：`anchor.signals.s_retr` 只认逐项值**——本项 `forward[term_id]` 全部条目 `score` 的最大值。
  单元级 `retrieval['s_retr']` 只是 S6 的调用级汇总，**不得直接写进 anchor**：M1b 若有人拿单元级
  汇总填 anchor，公式项会凭「同批次里别的项检索得好」蹭到高置信度，假绿线就是这么复发的。
  **R82 偏离说明（HTML 侧）**：`index.html` 的公式项清单列不出公式项的 `kind`——schema 的
  `anchor` 不携带 `kind` 也不携带 `latex`，铁律是 `trace.json` 才是唯一契约，渲染器不许为拿一个
  `kind` 重新解析论文。要让 HTML 显示 kind，得扩 schema 让 S9 把 `term.kind` 写进 anchor，属新切片。
  **逐层口径（M4a，R161/R163/R164）**：结构同构命中时每个同构组各出一条 anchor，anchor 另带
  可选 `code_group`（组 id，形如 `root/transformer.h.0.attn`，即「顶层模块前缀 + 点式单段
  路径」；回退路径不写这个键，schema 里声明但不进 required）。代价如实说：judge 每
  「公式项 × 同构层」调一次——夹具 `n_layer=2` 时 4 项 × 2 层 = 8 次，层数更多则线性增长，
  anchor 数与 `index.html` 公式项表行数同比例增长（本片夹具 8 条 / 8 行）。`s_retr` 与
  `s_struct` 是**公式单元级**的（同一单元各层取到同一个值），只有 `s_judge` 逐层各问一次，
  所以同一 term 的两条 anchor 只可能因 `s_judge` 不同而 `confidence` 不同（R164）。HTML
  公式项表**一条 anchor 一行**（R166/L4），「层」列显示 `code_group` 去掉顶层 `root/` 前缀后的
  组路径（`transformer.h.0.attn` / `transformer.h.1.attn`），回退路径没有层，显示 `—`；
  `unresolved` 的两层共用同一个 term ref，在表里合并成一行（逐层的条数以 `trace.json` 的
  `unresolved` 为准）。
- **结构同构不命中时 judge 仍然工作（S15）**：`pairs` 为空时，回退候选由算子类型过滤 +
  词法排序产出（每个公式项最多 3 个、全局最多 12 个，`papertrace/align/candidates.py`），
  判断题只判这些候选。**这条路的 `tier` 上限锁死在 `yellow`（R112）**：回退候选没有形状与
  序列依据，`confidence` 照实计算（可能 ≥0.75），但绿线是「结构对上了」的承诺，不发。
  回退产出的 anchor 的 `evidence` 以「最高黄线」开头，`code_expr_range` 只写 judge 确认的
  **那一个**节点（不按首尾区间猜，否则会画出没人审过的彩线，R117）。offline 下拿不到 yes，
  仍然一条 anchor 都不产，只进 `unresolved` 并自报「回退候选没拿到判断题 yes」。
- **结构校验**：`validate_trace` 除了 JSON Schema 还查 `id`/`parent_id`/边的 `id`/`src`/`dst`
  必须是字符串（是 list/dict 时报「必须是字符串」，**不会漏成 `TypeError` 和 traceback**）、重复 id、悬空边、`parent_id` 不存在、
  module 节点必须 `source=static`、**边两端必须是算子节点**（不接受 module→op / op→module）、
  **不接受自环**（`src == dst`）。这些错误一律 `TraceSchemaError`，不静默放过。
  **tier 与 signals 的复核（S16 / L3b，R171）**：anchor 带 `tier` 时，校验按 `signals` 重算档位，
  判据是 **tier 不得高于重算结果**（rank `none`(0) < `yellow`(1) < `green`(2)）——把 tier 往高涂
  （升格）过不了校验，RF3 抓的就是这个；而 R112 回退路径把 green 保守封顶成 yellow 的**下调**
  放行，那是产品自己的合法行为。不带 `tier` 键的旧 trace 不做这项复核，必须通过。

### 一个算子只归一个公式项

anchor 是「归属」断言——这个公式项的工作由哪个算子节点实现——不是「相关」断言。所以认领规则是：

- **同一公式单元内，一个算子节点最多被一个公式项的 anchor 认领（独占）**：让用户看见一个算子
  同时是两个公式项的实现，那是错的，不是「保留可能性」。
- **跨公式单元允许共享**：不同单元的公式本来就是不同的事，同一个算子被两个单元各自认领没有矛盾。
- 候选生成器（`papertrace/align/candidates.py`）**仍然不去重**——它是纯函数、不知道谁被认领；
  唯一性由 `papertrace/spine_claims.py` 在编排层执行。
- 候选被前面项占尽的项会落进 `unresolved`，原因写「被同一公式单元里更早的公式项认领」——
  与「根本没有候选」是**两种不同**的文案，用户分得清是哪种。

R158 之后 anchor 的 `code_expr_range` 一律是**单节点**（回退路径不再按首尾区间猜），所以「认领口径」
与「区间口径」是同一件事；若将来结构路径的一个公式项又产出多节点区间，得重新裁决区间内部的节点算不算
被认领，并补上测试（global-constraints.md GC16 的唤醒条件）。

**已知局限**：认领是**按项编号顺序的贪心**，不是全局最大匹配。理论上存在「先来的项抢走了后面的项
更该用的节点」的情形；这时后面的项落 `unresolved` 并写明原因，而不是硬抢。

### 路径是相对构建目录的

写进 `trace.json` 的路径不再是机器相关的绝对路径：

- **`meta.repo.url` / `meta.paper.source` / 算子节点 `loc` / 代码符号 `defined_at`** 四类字段，
  写出时都转成相对**构建时工作目录**的路径，分隔符统一 `/`。
- **不在构建目录之下的绝对路径保持原样**（比如 `--repo D:\other\proj` 而 cwd 在别处），
  不硬造 `..` 跳出形态。
- **后果**：把 `trace.json` / `index.html` 换到别的目录打开时，相对路径会指错——它记录的是
  「相对构建目录」的位置，**不是自包含的**。
- **module 节点的 `loc` 不参与相对化**：它是模块路径（如 `model.GPT`）不是文件路径，本就不可点击。

### 入口契约：模块:工厂函数

`--entry` 指向一个**零参可调用对象**，它返回模型实例。推荐写成工厂函数，而不是直接给类：

```python
# 你仓库里的 model.py
def build_model():
    return GPT(GPTConfig(n_layer=2, n_head=4, n_embd=32, block_size=16, vocab_size=64))
```

```bat
python -m papertrace build --repo path\to\repo --entry model:build_model --paper none --out output
```

- 零参类也能用（`--entry model:TinyNet`），但 `GPT(config)` 这种必须给工厂，我们不猜你的配置。
- 示例输入优先用模型自带的 `example_inputs()`；没有就按 `config.vocab_size` + `config.block_size` 造 token id；都没有就报 `BuildError`，不会拿随机形状糊弄。
- 缺 torch → 退出码 **4**；追不动 → 退出码 **5**；仓库/入口对不上、`input_specs` 与图**或模块**或**导出器自己**对不上（含名字与 `target` 对不上）→ 退出码 **2**。三种情况都**不写** `trace.json`。
  分界线一句话：**spec 与图/模块对不上是契约错误（2）**，**torch 追不动或 `example_inputs` 数量不对是能力边界（5）**。
  「追不动」有四种：① `torch.export` 就失败（数据依赖分支）；② 导出图能画出来，但拿真实张量
  **再跑一遍会炸**（自定义算子只有 meta 实现、真 CPU 实现抛错）；③ 图里有**非张量节点**
  （`get_attr`/`call_module`）——`forward` 里写 `torch.no_grad()` 时，导出器会把那段包成子模块
  `submod_N`。这种图契约校验是过的，但那个 `get_attr` 不是张量：空根模块构造 `GraphModule`
  当场 `AttributeError`，就算把子模块挂回去跑通，它也会被标成 `param`，让「权重 1」变成「权重 2」
  （实测）。`torch.cond` / `torch.while_loop` 这类高阶控制流也走这条 exit 5（导出器把分支图
  存成 `true_graph_0`/`while_loop_body_0` 等非张量 `get_attr`）——它们的 `input_specs` 顺序是
  正常的，**不是顺序不变量误杀**，实测 `check_contract` 通过后才被这道能力边界拒绝。
  所以一律 exit 5 并点名是哪几个节点，把 `no_grad` 移到 `forward` 外可绕过。
  ② 以前会照常产出 `source=runtime` 的 trace，把推断形状冒充成真实形状；现在一律 exit 5——
  没有第二遍执行，就不许说自己是 runtime。④ **pytree 输入没摊平**（dict/list 被导出器摊成多个
  数据输入，`example_inputs()` 给的却是容器本身）——同样 exit 5、不写 trace；M1b 用导出器
  同一个 `tree_flatten` + `call_spec.in_spec` 对照来支持，不猜顺序。
- 退出码 5 时 stderr 前面可能有 torch 自己打的一二十行诊断图/警告（那是它的内部输出，
  我们拦不住）；**papertrace 的结论永远在最后一行**，脚本里请只看退出码。

## 已知局限（如实说明，不装作已经支持）

- **逐层对齐已落地（M4a，R161）**：结构同构命中时每个同构组各出一条 anchor（本片夹具
  `transformer.h.0.attn` 与 `transformer.h.1.attn` 两组），anchor 带 `code_group` 标明落在哪一层；代价是 judge 调用数、
  anchor 数与 HTML 公式项表行数都随层数线性增长（judge 每「公式项 × 同构层」一次）。
  **仍有限**：同构判定按组内子序列做，跨组混合结构（如残差在不同层插入位置不同）仍可能只
  命中一部分层；层数 >2 的规模化只有单测覆盖，夹具本身只有 2 层。
- **默认 offline 后端下逐层口径看不见**：`offline` 是默认后端，一条 anchor 都不产，演示产物
  `index.html` 公式项表的「层」列全是 `—`；逐层那一列只有配了判断题后端才看得到，该路径由
  `tests/test_spine_html.py` 覆盖，不在三个演示场景里。
- **`s_struct` 的 +0.2 是二值的「有没有同构」**，不含「对齐了几项」（R80）——同构图对得多不等于分高。
- **`conflicts` / `backward` 没落进 trace**：四类对账输入里这两类本切片是缺口，属 M4。
- **S18 修订（m03858 已批）**：本切片不引 KaTeX，公式用等宽原始 LaTeX 文本 + 静态 SVG 展示，
  KaTeX `\htmlId` 推迟到 M2 前端。这是对冻结规则（工程计划书 :75 / :611）的显式批准偏离，不是漏改。
- **S16 修订（m03858 已批）**：`anchor` 增加可选 `tier` + `signals`，结构校验钉住 **tier 不得高于
  signals 重算结果**（R171）——所以手改 trace 把 tier 涂绿（升格）是过不了 schema 校验的
  （RF3）；反向把 green 涂成 yellow / none 的保守下调不再被抓，那是为了让 R112 回退路径的
  合法封顶过校验而主动让出的一小步（代价写进 design §6 已知局限）。
- **equation 环境里未转义的 `%` 一律当注释**：这与 LaTeX 语义一致（`%` 到行尾就是注释），
  行内逐字（`\verb`/`\url`）里的 `%` 已按定界符配对保护，但 `equation` 内裸写的 `%`
  仍会吃掉其后直到行尾的内容。
- **花括号下标暂不匹配**：`d_{kk}` 这类带花括号的下标抽不出来，论文侧只认 `d_k` 这种
  单下标形式。
- **`_read_title` 是启发式**：从 .tex 里猜论文标题，猜不到就留空，不联网查、不编一个。

## 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 内部错误：生成的 trace 不合 schema（属 bug，不是用法问题） |
| 2 | 用法/入口/契约错误（仓库不存在、entry 对不上、trace.json 非法、`input_specs` 与图**或模块**或**导出器自己**对不上：缺项/多项/顺序/未知或拒绝的 kind（`TOKEN`/`CUSTOM_OBJ`）/权重与输入标反/常量顶替参数或缓冲/plan 与 `input_specs` 逐项不一致/`exported` 不是真 `ExportedProgram`/违反「权重排在数据输入之前」的顺序不变量/同一个参数被认领多次/`target` 取到的张量形状与导出图里这个节点不符/placeholder 的名字与 `target` 对不上/认不出 placeholder 前缀/非输入 spec 没给 `target`） |
| 3 | 目标文件已存在，未加 `--force` |
| 4 | 缺运行时（没装 torch） |
| 5 | 模型可加载但追不动（export 失败、导出图无法真实再执行、图里有非张量的 `get_attr`/`call_module`（如 `forward` 内的 `no_grad`、`torch.cond`/`torch.while_loop` 的分支图），或 `example_inputs` 数量与数据输入个数对不上（含 pytree 输入未摊平）） |

`TOKEN`/`CUSTOM_OBJ` 归 **2** 是**契约策略**而不是「你输入写错了」：spec 里出现本切片不支持的
`InputKind` 就是契约错误（与未知 kind 同一类）；`no_grad`/`cond` 归 **5** 是**能力边界**（spec 完全合法，
只是图里有非张量节点）。两者的分界线是「spec 合不合法」，不是「用户有没有写错」。

契约错误退出（码 2）**不会**删除上一次构建留下的 `trace.json`——失败发生在写出之前，旧产物原样留在磁盘上。

`index.html` 是**派生产物**：每次 `build` 都重新生成并覆盖，**不受 `--force` 约束**（R74）；
`--force` 只约束 `trace.json`（对应码 3）。HTML 渲染失败时报码 2，且 `trace.json` 早已写出、绝不回删。

## 文档

- 框架实现计划：`docs/superpowers/plans/2026-11-14-papertrace-framework.md`
- M1a 算子追踪计划：`docs/superpowers/plans/2026-11-14-papertrace-m1a.md`
- 完整工程计划（含 S1–S13 修订、Task 0–15、验收映射）：`docs/superpowers/plans/2026-11-14-papertrace-engineering-plan.md`
- 人读版计划书：`PaperTrace_工程落地计划书.docx`
- 环境说明：`docs/ENVIRONMENT.md`（torch 与 Ollama 都属可选，见该文）

## 铁律

- 结论必须带 `source ∈ {runtime, static, model}`。拿不到就空态 + 原因，禁止 mock 填界面。
- 对齐只能是「检索 Top-5 → yes/no 判断题 → 结构加权」，禁止让模型一次吐出「公式→行号」映射。
- `detail` 只追加不覆盖；子结论与父结论矛盾时写 `conflicts` 并把父节点标记 `stale`。
- 多输出算子（如 `split`）必须标 `degraded=true` 并说明原因，不能假装形状完整；多输出节点的边形状按 `getitem` 的索引逐项解析。
- 融合算子（`scaled_dot_product_attention` 等）必须标 degraded 并在 stderr 警告：它把论文里好几个公式项吞成了一个 aten 算子，安静通过等于漏检。
