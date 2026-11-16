# PaperTrace 无论文模式（代码侧分析）设计

> 状态：待年糕批准（2026-11-16）。批准后才写实施计划。

## §0 为什么

年糕在 m11488 说：「其实不用论文 单独的项目也可以解析的」。

实测确认他说得对，而且比原话更严重：

| 现状（不带 `--paper`） | 证据 |
|---|---|
| `symbols.code` **0 条** | `output/demo/code-only/trace.json`；`build_code_symbols` 只在 `papertrace/spine.py:72` 被调用，即只在接论文时执行 |
| HTML ③ 论文公式项清单 / ④ 未对齐清单 / ⑤ 符号表 **全是空态** | `index.html` sections = meta/ops/terms/unresolved/symbols，h2 = ①契约与来源 ②代码算子图 ③论文公式项清单 ④未对齐清单 ⑤符号表 |
| 唯一有内容的是「算子清单 + 分层算子图」 | 128 节点 / 101 边，其余全靠人自己读 |

也就是说：今天「单独一个项目」只能看到**原始算子流水**，看不到这个仓库**是什么模型、每块在干什么、有多大**。这不是「解析」，这是 dump。

本切片把「无论文也能解析」做成产品能力，落在**已有的 `build --repo`** 上（不新增子命令，年糕已拍板）。

## §1 实测事实（设计依据，全部本机跑过）

1. **模块节点带类名**：`level != "op"` 的节点 `op` 字段就是类名——GPT / Block / CausalSelfAttention / MLP / LayerNorm / Embedding / Linear / Dropout / GELU / ModuleList / ModuleDict。不需要 `import torch` 二次反射。
2. **模块节点没有形状**（`shape_in`/`shape_out` 恒空）；**算子节点有**：`matmul` 形如 `shape_in=[2,4,8,8] inputs[[2,4,8,8],[2,4,8,8]] shape_out=[2,4,8,8]`，`linear` 形如 `shape_in=[2,8,32] shape_out=[2,8,96]`。
3. **residual 可以验证**：`root/transformer.h.0` 的两个 `add` 节点 `inputs=[[2,8,32],[2,8,32]]`（两个等形状输入）；而 `root` 的 `add`（位置 id）`inputs=[[2,8,32]]` **只有一个输入**——这正是不能用「有 add 就是 residual」的理由。
4. **朴素子树聚合会把 Block 认成 mlp**（控制器原型实测：root、root/transformer、h.0、h.1 全被判 mlp）。因为 h.0 子树里既有激活又有多个 linear。所以角色识别**只能看直接子节点**，容器用 stage，不许冒充。
5. **参数可精确统计**：18 个 param 节点 `shape_out` 乘积求和 = **29856** 个标量（root 子树）。
6. **FLOPs 只能粗估**：`matmul` 的转置由前面的 `transpose` 算子完成，trace 里没有记录「这个 matmul 的哪个维度被收缩」，只有形状。所以估算公式只能是「2·∏shape_out·shape_in[-1]」，必须自称估算。
7. **成本可忽略**：`build_trace` 2.51s，第二次 `load_entry` **0.00s**（模块已缓存），`build_code_symbols` 0.00s。所以无论文路径补符号表几乎不花钱。
8. **schema 顶层是封闭的**：`additionalProperties: false` + `required` 十个键；`$defs.anchor` 没声明 additionalProperties（可加字段）。`tests/test_schema.py:15-26` 的 `ROOT_KEYS` 硬编码十个键。
9. **既有先例**：脊柱切片加 `tier`/`signals` 时选了「可选字段 + schema_version 保持 1.0.0」（`docs/superpowers/specs/2026-11-14-papertrace-spine-design.md:93`）。

## §2 设计

### A. 代码侧符号与超参台账（无论文也出）

- `papertrace/cli.py` 在 **没有 `--paper`** 时也 `load_entry(args.repo, args.entry)`，用 trace dict 调 `build_code_symbols(mod, doc)` 填 `doc["symbols"]["code"]`。
- `symbols.paper` 与 `symbols.mapping` 仍是**空数组**（没有论文就没有论文侧符号，也没有映射——空是事实，不是失败）。
- 复用现成实现，**不改 `code_table.py`**；`defined_at` 由既有的 `relativize_doc` 相对化，零新代码。
- 结果：无论文 build 后 `symbols.code` = B/T/D/H/Dh 五条，`defined_at` 指向真实行（实测 `tests/fixtures/nanogpt/model.py:20/23/24/65` 与 `papertrace/build_trace.py:20`）。

### B. 模块级「这段代码在做什么」

新模块 `papertrace/analyze_roles.py`：`module_roles(nodes) -> list[dict]`，每个模块一条：

```python
{"module_id": "root/transformer.h.0.attn", "class": "CausalSelfAttention",
 "role": "attention", "evidence": "自身 22 个算子里有 matmul→…→softmax→…→matmul 子序列", "op_count": 22}
```

**角色枚举冻结**（10 个）：`attention / mlp / layernorm / embedding / linear / activation / dropout / residual / stage / unknown`。

判据按顺序、只看直接子节点（`R182`）：

| role | 判据（可验证，不用模块名） |
|---|---|
| embedding | 直接算子含 `embedding` |
| layernorm | 直接算子含 `layer_norm` |
| attention | 直接算子序列里存在 `matmul … softmax … matmul`（softmax 前后都至少一个 matmul） |
| residual | 直接算子含 `add`，且该 add **≥2 个输入**、输入形状相同、且等于 `shape_out` |
| dropout | 直接算子非空且全是 `dropout` |
| activation | 直接算子非空且全是激活算子（gelu/relu/silu/sigmoid/tanh/mish） |
| linear | 直接算子非空且全是 `linear`/`matmul` |
| mlp | 容器：直接子模块里 **≥2 个含 linear/matmul**、**≥1 个含激活算子**，且自身没有 attention/embedding/layer_norm 直接算子 |
| stage | 有子模块、以上都不成立（Block、ModuleList、ModuleDict、root 都归这里） |
| unknown | 以上都不成立且无法归类的叶模块——**允许出现，绝不硬凑** |

`evidence` 是中文短句，必须点名判据与命中数（如「直接子节点里 2 个含 linear、1 个含 gelu」），**不许空串、不许只写规则 id**（沿用 R38/R185 的规矩）。

### C. 张量与算力体检

新模块 `papertrace/analyze_metrics.py`：`module_metrics(nodes) -> list[dict]` + `totals(rows)`：

| 字段 | 定义（诚实边界写死） |
|---|---|
| `params` | 子树内 `kind=="param"` 节点的 `shape_out` 乘积求和。**精确**，不估。 |
| `max_activation` | 子树内 `kind=="op"` 节点的 `shape_out` 乘积最大值（**元素数不是字节**）。 |
| `est_flops` | 子树内 `op in ("matmul","linear")` 的 `2·∏shape_out·shape_in[-1]` 求和；其他算子计 0。字段名带 `est_`，且 trace 与 HTML 都必须显示方法说明。 |
| `degraded` | 子树内 `degraded==true` 的节点数与原因列表（多输出算子形状不全等）。 |

方法说明文本（随 `analysis.method` 一起落盘，必须原样出现在 HTML）：

> 参数量按权重张量元素数精确统计；FLOPs 只对 matmul/linear 估算（2×输出元素数×输入最后一维），未考虑转置语义与逐元素算子，属于**粗估**，且随 batch/序列长度线性变化。

### 落盘形状（trace.json 新增可选顶层键 `analysis`）

```json
"analysis": {
  "modules": [{"module_id": "...", "class": "Block", "role": "stage", "evidence": "...",
               "op_count": 2, "params": 12608, "max_activation": 2048, "est_flops": 409600}],
  "totals": {"modules": 34, "params": 29856, "max_activation": 2048, "est_flops": 884736,
             "degraded": 2},
  "roles": {"attention": 2, "mlp": 2, "stage": 8, "unknown": 2},
  "method": "参数量按权重张量元素数精确统计；FLOPs 只对 matmul/linear 估算……"
}
```

- **可选**（不进 `required`），`schema_version` 保持 `1.0.0`（沿用脊柱先例，旧 trace 仍合法）。
- **生产者总是写**（skeleton 也写一份空的 `modules: []`），这样 HTML 不用到处兜底。
- `$defs` 新增 `analysis` / `analysisModule` 两个定义，模块条目 `additionalProperties: false`（防止下游随手塞字段）。

### HTML（③④⑤ 不再是唯一空态）

新增 `papertrace/render_analysis.py`（行构造，≤80 行），模板新增第 ⑥ 块「代码体检」：

1. 一句话总量：`34 个模块 · 参数量 29,856 · 峰值激活 2,048 元素 · 估算 FLOPs 884,736（粗估）`
2. 角色分布：`attention 2 · mlp 2 · stage 8 · unknown 2`——**unknown 必须列出来，不许隐藏**（隐藏就等于宣称全都认出来了）。
3. 模块角色表：模块 id / 类名 / 角色 / 参数量 / 峰值激活 / 估算 FLOPs / 判据。按 `module_id` 排序。
4. 形状与降级提示：`degraded 2 个`（点名 `split` 多输出），`shape_broken / shape_unchecked` 计数。
5. 方法说明原文照印。
6. ⑤ 符号表在无论文时显示 code 行 + 一行说明：「没有论文，所以没有论文侧符号与映射；这里列的是代码侧的符号」。

## §3 裁决（R181–R190）

| # | 裁了什么 | 为什么 | 错了的代价 |
|---|---|---|---|
| R181 | `analysis` 是**可选**顶层键，`schema_version` 不升（保持 1.0.0），生产者总写 | 沿用脊柱切片加 `tier`/`signals` 的先例；升版本会让磁盘上所有旧 trace 失效，收益只是好看 | 下游若把「可选」理解成「可以没有」而不守 `default`，读旧 trace 会 `UndefinedError`（响亮崩溃，不是假事实） |
| R182 | 角色只按**直接子节点**判定，容器用 `stage`；10 个枚举冻结 | 原型实测：子树聚合会把 `root`、`transformer`、`Block` 全判成 mlp | 少报能力（说不出 Block 里「一半 attention 一半 mlp」），但不会说假话；细分留 M6 |
| R183 | `residual` 判据=add 且 ≥2 个等形状输入且等于输出形状 | `root` 的位置 id `add` 只有一个输入；只有这个判据能把两者分开 | 某些广播残差（形状不等）会落到 `stage`/`unknown`，属少报 |
| R184 | `mlp` 判据=直接子模块里 ≥2 含 linear/matmul 且 ≥1 含激活，且自身无 attention/norm 直接算子 | 让 `root/transformer.h.0.mlp` 认对，同时不让 `Block` 冒充 | 非「线性+激活」结构的 MLP（如 gated）会落到 stage |
| R185 | FLOPs 字段名 `est_flops`，只算 matmul/linear，方法原文必须同时出现在 trace 与 HTML | trace 没记录收缩维度，任何精确说法都是假的 | 低估（漏逐元素与 norm 的 FLOPs），所以措辞必须写「粗估」，不能写「计算量」 |
| R186 | `params` 精确计数，不估；共享权重（同一 param 节点被多模块引用）按节点计一次 | trace 的 param 节点是唯一事实 | 如果是 weight tying，真实模型参数量更小，我们的数字会偏大——所以文档要写明这是「按 trace 里的节点数」 |
| R187 | `max_activation` 用元素数不用字节，param 节点不计入 | 字节数还要乘 dtype，且 dtype 有 null 的情况 | 用户可能以为是内存占用，所以字段名与 HTML 都写「元素」 |
| R188 | 无论文时 CLI 也 `load_entry`；`paper`/`mapping` 留空数组 | 空是事实，不是失败；把「没论文」说成「没对上」才是假话 | `load_entry` 失败会走既有 `BuildError`→exit 2 路径（import 一个坏仓库本来就该失败） |
| R189 | HTML 必须单列 `unknown` 与 `degraded` | 隐藏 unknown 等于宣称全认出来了 | 页面多几行，但每次都能看到「我们没认出来的部分」 |
| R190 | 本切片**不动** `code_table.py` / `patterns` 产出的 anchors 逻辑 / 论文侧任何代码 | 控制爆炸半径；A/B/C 都不需要改既有语义 | 若 B 的判据与 `struct_signal` 的判据漂移，会出现「HTML 说 attention、对齐时说不像」——本切片靠复用同一批算子名与同一套 kind 映射规避，漂移风险写进已知局限 |

## §4 Global Constraints（新增，实施时逐条适用）

- **GC19**：不新增任何第三方依赖（只用标准库 + 既有 sympy/jinja2/jsonschema/torch）。
- **GC20**：单文件 ≤200 行，口径 `len(pathlib.Path(f).read_text(encoding="utf-8").splitlines())`。
- **GC21**：无论文路径的既有数字不变——nodes=128（算子 75 / 权重 18 / 输入 1 / 模块 34）、edges=101、anchors=[]、unresolved=[]；新增只允许出现在 `symbols.code` 与 `analysis`。
- **GC22**：所有估算必须自称估算（字段名带 `est_` + 方法文本），禁止把估算写成实测；不允许出现「精确计算量」这类说法。
- **GC23**：`unknown` / `degraded` / `unresolved` 一律可见，不许在渲染层过滤掉。

## §5 已知局限（本切片不解决，写进 README）

1. 角色是**结构识别**，不是语义理解：自定义算子名（例如把 attention 写成 `my_attn` 并在内部调 `scaled_dot_product_attention`）会落到 `unknown`，而不是被猜成 attention。
2. `est_flops` 粗估，不含逐元素算子、norm、attention mask；不随理论上限校核。
3. 共享权重按 param 节点计数（可能偏大）。
4. 只对齐 PyTorch + torch.export 能追的仓库；追不动仍然 exit 5，不产出半份分析。
5. 本切片不做「跨模块数据流图」（算子图仍是按 parent_id 分层）；「这个张量从哪流到哪」留 M6。

## §6 验收

1. `build --repo tests/fixtures/nanogpt --out ...`（不带 `--paper`）→ `symbols.code` 5 条（B/T/D/H/Dh，`defined_at` 真实且相对化）、`paper`/`mapping` 空数组。
2. 同一产物 `analysis`：34 个模块条目、`totals.params == 29856`、`roles` 里 attention=2 / mlp=2、`unknown` 与 `degraded` 可见、`method` 非空。
3. 角色关键反例：`root` 与 `root/transformer.h.0` **不得**被判为 mlp；`root/transformer.h.0.attn` = attention；`root/transformer.h.0.mlp` = mlp；`root/transformer.h.0` = residual（两个 add）或 stage。
4. HTML 有第 ⑥ 块且含 unknown 与 method 原文；⑤ 符号表在无论文时非空并有「没有论文」的说明。
5. 带 `--paper` 的路径与既有 807 条测试**全部不变**（除本切片显式授权改写的断言）。
6. 骨架 build 也写 `analysis`（空 modules），HTML 不崩。
