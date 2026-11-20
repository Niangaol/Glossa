# PaperTrace 脊柱切片：我代年糕做的全部裁决（Rulings I made）

分支 **spine**（从 master `e71d613` 切出），Task S1–S11。
本清单**穷尽**列出控制器（lead）在施工过程中代用户做的每一条裁决，按作出顺序排列，每条附**「错了的代价」**。
来源：`.superpowers/sdd/2026-11-14-papertrace-spine/progress.md`（账本）里的 `Ruling:` 行与编号裁决段。
**你读到任何一条觉得不对，直接说，我改。** 这些决定本来该由你拍板，我为了不卡住流程先裁了，代价都写在下面。

共 **101 条**（2 条 preflight + R1–R98 + R25a）。

| 编号 | 阶段 | 我裁了什么 | 为什么这么裁 | 错了的代价 |
|---|---|---|---|---|
| **P1** | preflight | SDD 的三个 bash 脚本（sdd-workspace / task-brief / review-package）改用 Node 在 run_code 内复刻 | PATH 里的 bash 是 WSL（E_ACCESSDENIED），Git bash.exe 报 couldn't create signal pipe, Win32 error 5 | Node 复刻若与 awk 语义不一致，brief 会抽错段；已用实际 brief 行数逐个验证 |
| **P2** | preflight | 用就地分支 spine，不另开 worktree | pydeps/ 与 PYTHONPATH 是绑定到本目录的，换目录就全炸 | 没有隔离，分支搞坏会污染工作树；靠 git 可回退 |
| **R1** | S3 | t1.latex 取 \sqrt{d_k} 原串真实子串、kind=scale；倒数语义写编排层 reason，不重写 latex；拆项只处理 = 右侧 | 夹具注释里的 t1: \frac{1}{\sqrt{d_k}} 是提示不是契约，计划明写「证明没重写公式」 | t1 的 latex 与论文原式不一致＝重写了公式 |
| **R2** | S4 | build_code_symbols(mod, bundle) 的 bundle 是 build_trace 产出的 trace dict，不是 S2 的 PaperBundle；两个同名概念在各自 docstring 写清 | B 的 value 要取 bundle['meta']['runtime']['batch'] | S4 拿 PaperBundle 去取 meta.runtime 直接 KeyError |
| **R3** | S6 | code_units / paper_terms 的结构由 S6 定义并写进 docstring，S9 负责组装 | offline 下这条路径不产生分数，只有注入测试后端时才走到 | S9 传错结构 → 检索静默返回空 |
| **R4** | 全局 | 把每处钉桩测试的改写移到打破它的那个 Task（S6 改 test_imports、S9 改 test_cli），不留在 S11 | 计划原把它们全排在 S11，但 S6/S9 一实现就红 | 中间 Task 全量红，无法判断有没有回归 |
| **R5** | S6 | embed.py 返回标注改 list[list[float]]，删掉 if TYPE_CHECKING: import numpy 整块（S17 已批） | numpy 不在 pydeps，本机 import 成功是环境侥幸 | 留一个指向不存在依赖的类型注解，干净机器上炸（重犯框架切片 C2） |
| **R6** | S9 | GC8 的六个 counts 不在 trace.json 里，由 report.print_build_summary 从 nodes/edges 算出打印；测试断言 nodes/edges 与打印文本 | 顶层无 counts 键、meta.counts 为 null | 断言不存在的键 → 恒失败或恒真 |
| **R7** | 计划 | 把计划里 ## 收尾 Task S11 改成 ## Task S11：收尾（…） | task-brief 的标题模式要求 ^#+ Task <ID>，原标题抽不出 brief（实测只有 1 行） | S11 派不下去，或 brief 为空让 implementer 没有要求 |
| **R8** | 评审 | reviewer 的 Global Constraints 用「指向 global-constraints.md 并要求先读」代替逐字 paste 6558 字节 | 该文件就是计划 GC 段 + Review Focus 段的逐字副本，效果等价且省控制器上下文 | reviewer 不读该文件就会漏掉约束；已在 prompt 里写明 read this first |
| **R9** | S1 | GC1「单源文件 ≤200 行」的口径是 .py 源文件；schema/trace.schema.json 是声明式数据文件且本 Task 前已 280+ 行 → 不计入 | 评审模板明确不 flag 既有文件体积 | 若用户认为 JSON 也算源文件则需拆 schema；纯机械改动随时可做 |
| **R10** | S3 | 拆项只处理第一个顶层 = 的右侧；左侧 \mathrm{Attention}(Q,K,V) 不产生项 | 左侧是函数记号不是运算项 | 左侧被当项 → 多出假项 |
| **R11** | S3 | latex_to_sympy_safe 是表达式解析器：含顶层 = 或白名单外宏 → ok=False | 由 split_formula 先剥左侧再调它 | Vaswani 整式必然 ok=False → 返回 [] → 四项测试红 |
| **R12** | S3 | split_formula 与 latex_to_sympy_safe 都必须先按行剥掉 % 注释再处理 | marker 写在公式体内时 latex 会残留 % papertrace-id: 行 | 注释被当符号 |
| **R13** | S3 | d_k 保持为名为 d_k 的单个 Symbol，不拆成 d*k | parse_expr 天然如此，且符号表要按 d_k 配对 | 符号表配对失败 |
| **R14** | S2 | verbatim/lstlisting/Verbatim/BVerbatim/minted 整段置空、latex 取 code 视图；删掉 _marker(body) | 代码环境里的公式不该被抽成论文单元 | 代码环境里的公式被误抽 |
| **R15** | S3 | 子串规则压倒 brief 的示意项文本：t1.latex=\sqrt{d_k}(scale)、t3.latex=V(matmul)；禁止改测试去接受重写后的 latex | 同 R1，brief 的示意文本是语义提示 | 同 R1 |
| **R16** | S3 | split_formula 先丢第一个顶层 = 及左侧；latex_to_sympy_safe 遇 = 或白名单外宏 → ok=False/expr=None/raw=原串，绝不抛 | fail-closed 但不冒 traceback | 抛异常冒到 CLI |
| **R17** | S3 | Term 只有 index/latex/kind，无 term_id；项 ID 由编排层拼 f"{unit_id}-t{index}" | S3 不该知道 unit_id | S3/S9 的 ID 口径不一致 → anchor ref 对不上 |
| **R18** | S3 | 只吞解析/翻译异常，禁裸 except；ok=False 必带 raw=原串 | 裸 except 会吞掉真 bug | 吞掉 KeyboardInterrupt/SystemExit 或掩盖真缺陷 |
| **R19** | S3 | R15–R19 逐字写进 report | 裁决要能跨 Task 传递 | 裁决丢失，后续 Task 重犯 |
| **R20** | S4 | D%H≠0 时仍产 Dh=D//H 向下取整；codeSymbol 没有「不精确」字段，不发明；精确对账归 M4 | schema 只有 var/symbol/defined_at 必填 + value/used_by 可选 | 非整除时静默给错值；用 value_mismatch 暴露而不是编字段 |
| **R21** | S4 | 定位失败/字段缺失的符号一律不返回；由 S9 用「冻结五符号 − 实际返回」生成 unresolved{kind:symbol}；绝不编行号 | 三个函数都返回 list[dict]，没有 unresolved 通道 | 编造 defined_at（用户点开就要信的字段） |
| **R22** | S4 | paper 侧只抽带下标标识符 [A-Za-z]+_[A-Za-z0-9]+，不抽 Q/K/V；按 symbol 去重保留首次；first_seen=unit_id；论文没给数值 value=None 绝不猜；映射只冻结 d_k↔Dh；paper None→matched 且 value 取代码侧；两侧都有值且不等才 value_mismatch | Q/K/V 是张量不是超参；论文夹具确实没给 d_k 数值 | 猜论文数值＝造假；静默取一个值当双方的值 |
| **R23** | S5 | +0.2 论文N层 / −0.4 shape冲突 / −0.3 双向检索 三条本切片不可判定 → 不触发、记 misses 写明原因；s_struct 上限 0.8；绝不编论文侧证据、不扩签名偷运论文正文 | struct_signal(nodes, terms, config) 拿不到论文散文也拿不到论文声明的 shape | 编造论文证据 → 假绿线 |
| **R24** | S5 | +0.1 的唯一可工作读法是代码侧超参名；冻结名单 (n_layer, n_head, n_embd, block_size) 四个全在才 +0.1 一次 | 论文符号是 d_k 这类，永远不会出现在 config 里 | 每个名字 +0.1 → 分数虚高 |
| **R25** | S5 | 只取 level=='op'，按 parent_id 分组、组内各自贪心子序列匹配、取 nodes 顺序第一个命中的组；kind→op 映射冻结（matmul→matmul；scale→mul/div；norm→softmax；act→gelu/relu/sigmoid/tanh；transpose→transpose；concat→cat） | 全 trace 75 个算子，跨模块扁平匹配会误命中 | 跨模块误命中 → 假对齐 |
| **R25a** | S5 | 必须再过滤 kind=='op'（排除 18 权重 + 1 输入的 placeholder）；只对齐第一层是已知局限，写进 docstring，不许改签名或返回多组（M4a 已落地，见 specs/2026-11-15-papertrace-layers-design.md） | op-level 94 个里混着 placeholder；h.0.attn 与 h.1.attn 完全同构 | placeholder 混进序列 → 同构误判 |
| **R26** | S3 | 接受 implementer 的设计改动：门在 split_terms.py:53-54 是唯一权威，:158 的改动对任何能过门的输入都不可达 | 生产行为不变，而「扫描器静默跳过未知宏」正是 S2 刚修掉的 C1 同族 | 若门不是唯一权威，就会静默跳过未知宏 |
| **R27** | S3 | 把评审的 Minor 升级为 Important：exposed 硬编码 True → y=\frac{a}{b} 的除法操作数被贴 matmul | 评审理由「仅影响夹具外公式」不成立；控制器亲跑探针实测 | 除法操作数连到矩阵乘算子＝假对齐 |
| **R28** | S3 | 修法验收六条行为（夹具四项与精确子串完全不变、y=\frac{a}{b} 恰好 1 项 scale、y=\sqrt{\frac{a}{b}} 恰好 1 项等），机制由 implementer 定 | 只给验收不给机制，避免过度指定 | 修一处坏一处 |
| **R29** | S3 | 透明的 \frac 两侧都必须被表示；某侧没产项时由该侧自己补一个，kind 一律 scale、latex 是该侧精确子串 | fix1 自身引入新 Important：一侧产项另一侧无项时另一侧连同除法静默消失 | 除法连同操作数静默消失 |
| **R30** | S3 | R29 维持，补项 kind 一律 scale 正确不改 | LaTeX 的 \frac 永远表示逐元素除法，从不表示乘以逆矩阵；scale→{mul,div} 与算子语义一致 | 标 matmul 反而会连到矩阵乘算子，那才是假对齐 |
| **R31** | S4 | 值取实例 mod.config、定义点取类源码（inspect.getsourcefile(type(mod)) + config 类名 + 正则）；测试用每符号冻结期望子串（B→DEFAULT_BATCH / T→block_size / D→n_embd / H→n_head / Dh→n_head）避免同义反复 | 实例值与类默认值不同，两者都要真实 | defined_at 指错文件行；测试同义反复 |
| **R32** | S4 | T=16 是声明超参、运行时是 8；允许加一小段中文 README 注记，S11 复核，不许重构 README | 夹具 block_size=16 而 seq_len=8 | 用户以为 T=16 是实测值 |
| **R33** | S4 | 裁决逐字写进 report | 同 R19 | 同 R19 |
| **R34** | S3 | 「每侧恰好一项」是简写，真不变量是「任何一侧都不许消失」；\frac{QK V}{d_k}→3 项是正确行为，补项只在该侧一项都没产出时发生 | 分子侧本身是乘积，贡献 2 项 | 按字面「恰好一项」去修会把乘积分子压成一项、反而丢因子 |
| **R35** | S4 | 保留 brief 冻结的测试名不改名，体内追加手工构造的 value_mismatch 断言（code Dh=4 vs paper d_k=8）让名字变成真话 | 10 个测试名是契约；原测试体走真夹具 paper value=None 只断言 matched | 测试名不副实，误导下一个人跳过该补的场景 |
| **R36** | S4 | _locate_config_field 改 fail-closed：已知 class_name 时圈不到类体的候选文件整个跳过，绝不整文件查找；全部找不到→None→按 R21 省略 | 评审评 Minor 理由「当前夹具不触发」；控制器不接受，与 R27 同一把尺子 | defined_at 指向看起来合法其实指错文件错行的诱饵行 |
| **R37** | S5/S7 | pairs 是 judge 的唯一候选来源；同构不命中→pairs==[]→不调 judge→s_judge=0；绝不瞎凑候选、不做全配对、不引词法候选生成器（S15 未批） | 4 项×75 算子≈300 次 API 不可接受；DeepSeek 无 embeddings 时检索给不出候选 | 瞎凑候选 → 假绿线；全配对 → 成本失控 |
| **R38** | S5 | hits/misses 是可在 HTML evidence 里展示的中文短句，点名规则与触发/未触发原因，不许裸规则 id 或空串 | 用户要在页面上读懂为什么 | 裸规则 id 用户看不懂 |
| **R39** | S5 | 裁决逐字写进 report | 同 R19 | 同 R19 |
| **R40** | S6 | code_units=[{code_id,text}]、paper_terms=[{term_id,text}]，由 S9 组装，term_id=f"{unit_id}-t{index}"；S6 不碰 schema、不 import Term/PaperUnit | 避免 S6 耦合 S2/S3 的类型 | S6 依赖上游类型 → 改一处动一片 |
| **R41** | S6 | s_retr = 两表全部 score 的最大值 clip[0,1]，不是两个 max 取平均 | 平均会把一侧的弱命中注水 | 注水 → 假绿线 |
| **R42** | S6 | conflicts：forward 每 term 的 top1 code，再看 backward[该 code] 的 top1 term 是否一致；只记录不参与计算 | 冲突取平均会抬过 0.75 | 冲突被平均掉 → 假绿线 |
| **R43** | S6 | monkeypatch 替换 embed.py 自己引用的 get_llm，不改 client.py 协议/分派；测试绝不联网 | 改协议会与 S8 打架 | S6/S8 冲突 |
| **R44** | S6 | embed_texts 只转调、LLMUnavailable 原样上抛；retrieve_bidirectional 是唯一捕获点 | 多处捕获会出现兜底假分数 | 兜底假分数 |
| **R45** | S6 | 返回标注改 list[list[float]]（S17），整块删 TYPE_CHECKING/import numpy | 同 R5 | 同 R5 |
| **R46** | S6 | 裁决逐字写进 report | 同 R19 | 同 R19 |
| **R47** | S7 | judge 的 term 是公式项文本字符串，允许收紧标注 term: str，绝不允许 mapping: dict 参数 | 铁律：判断题不是生成题 | 自由生成对应关系 |
| **R48** | S7 | JUDGE_PROMPT 一字不改；judge_prompt=原文+固定格式输入区；JUDGE_PROMPT_VERSION="judge-v1"；DRILL_PROMPT 一字不动 | prompt 漂移会让判定不可复现 | 判定不可复现 |
| **R49** | S7 | JudgeResult 无 reason 字段 → offline 断言 JudgeResult(False,"") 且 judge_score==0.0；reason 是 S9 的责任 | 给 JudgeResult 加字段会破坏既有契约 | 破坏契约 |
| **R50** | S7 | evidence 取 Evidence: 行其余文本→strip→按字符数截断 40（不按字节）；空→judge_score 强制 0 | 中文 40 字节只有 13 字；空依据给分就是假绿线 | 截断过短；空依据给分 |
| **R51** | S7 | Verdict 解析逐行找 strip 后以 Verdict: 或 Verdict：（全角）开头的行，键与值都大小写不敏感，取值首 token，只有 yes→True；绝不从自由文本搜 yes；不对整个响应取首 token | 整个响应的首 token 是 Verdict:，按字面解析真实 DeepSeek 全判失败 | 真实后端全判失败；或自由文本里的 yes 被误接受 |
| **R52** | S7 | tests/test_align_no_generation.py 用 rglob 递归扫 align+llm，禁 generate_alignment/对应关系如下/请列出 | 非递归 grep 会漏文件 | 漏掉子目录里的自由生成 |
| **R53** | S7 | chat 返回 ChatResult(text,model,backend) 不是 str，必须取 .text | 实测 client.py:23-26 是 NamedTuple | AttributeError 或把 NamedTuple 当文本 |
| **R54** | S6 | 三处 zip 前校验 len(vectors)==len(units)，不等 raise ValueError；不许静默补齐/截断/兜底 0.0/部分结果 | 评审评 Minor 理由「需后端违反自身协议」；控制器升级：模块自相矛盾（cosine 对维度不齐明抛）+ 后果是静默错误的 s_retr + S8 解析 HTTP JSON 后就可达 | 静默错误的 s_retr → confidence → tier → 用户看到的绿/黄线 |
| **R55** | S8 | S8 加分派后必须同步改写 tests/test_imports.py:86-87（依赖 get_llm 恒返 offline），不许删测试 | 删测试会掩盖回归 | 掩盖回归 |
| **R56** | S9 | S9 绝不能用 except Exception 一把兜住 retrieve 新增的 ValueError 出口；只捕 LLMUnavailable/IngestError 这类预期不可用 | 一把兜住会让 R54 的 fail-closed 变回静默 | fail-closed 失效 |
| **R57** | S7 | judge_score：yes=True 且 evidence 非空非纯空白→1.0，否则 0.0；no 一律 0.0 | 空依据必须归零 | 空依据给分 |
| **R58** | S7 | tests/test_align_no_generation.py 早已存在 53 行且已满足 R52 → 不许重建/覆盖/重写；唯一允许的改动是把 "请列出对应关系" 加严成 "请列出"；brief 点名的签名测试写进新文件 test_spine_judge.py | brief 写「新」是事实错误（控制器 preflight 漏查）；已 grep 确认加严不误伤 | 覆盖已入库的守卫文件 |
| **R59** | S8 | model 只从 PAPERTRACE_LLM 读；冒号后缀不作 model 来源；缺 model → LLMUnavailable 点名它；绝不猜默认模型名 | qwen2.5-coder:7b 是 ollama 的默认，openai 路径不许套用 | 请求一个不存在的模型名 |
| **R60** | S8 | 纠正 brief：tests/test_llm_hint.py 一行不许动（它测 ollama，S8 后仍未实现）；真正被打破的只有 test_llm_offline.py:30-36，拆成 ollama 保留 + openai 另立；_offline_hint 的 offline 分支必须保留 "backend=offline" 与 "预期行为" 两个子串 | brief Step 5 说要改 test_llm_hint.py 是不准确的 | 改错文件、放宽测试 |
| **R61** | S8 | 必须先捕 HTTPError（报真实状态码）再 URLError 再 TimeoutError；JSON 坏/choices 空/缺字段各自 LLMUnavailable 带具体原因；禁裸 except Exception | 实测 HTTPError 是 URLError 子类、socket.timeout is TimeoutError | 状态码被吞、超时被误分类 |
| **R62** | S8 | isinstance 协议检查照 brief 写（已证 Python 3.13 上带数据成员的 runtime_checkable 协议可用），不退化成 hasattr | hasattr 检查更弱 | 漏掉协议不符的后端 |
| **R63** | S8 | README 新增「接云端中转（可选）」小节：四个环境变量、DeepSeek 无 embeddings → s_retr 仍 0 → 黄线不是绿线、后缀不是模型名、默认仍 offline；不许重构 README 其他部分 | 用户配了 openai 会以为能出绿线 | 用户以为配了就能出绿线 |
| **R64** | S8 | _offline_hint 必须改成如实描述（openai 已实现、ollama 仍未实现） | 原文写「这两条在框架切片里尚未实现」，S8 后成假话 | 提示语成假话 |
| **R65** | S7 | 给 test_non_yes_no_answer_is_not_yes 增加值级反例 "Verdict: not yes"/"Verdict: 我觉得 yes"/"Verdict: yesish"；两个攻击面都要有人看守，不许合并或删 test_free_text_yes_is_not_accepted | 评审实测：把 _is_yes 变异成 "yes" in value.lower() 整套全绿 | 值级子串变异存活 |
| **R66** | S7 | 用 sha256 钉死整段冻结文本，两个常量都要钉；docstring 写明改正文就更新 hash 并升 JUDGE_PROMPT_VERSION；既有断言不许删 | startswith(JUDGE_PROMPT) 按构成为真，正文任何编辑无人看守 | prompt 被改而测试全绿 |
| **R67** | S9 | anchor.source：s_judge>0 → "model"；否则（只有结构/检索依据）→ "static"；绝不用 "runtime" | anchor 不是实测出来的 | 标 runtime＝造假来源 |
| **R68** | S9 | code_expr_range 填匹配到的算子节点 id 区间（单个 root/@037，多个 root/@037..root/@045）；绝不编造 file:line；docstring+README 写明逐算子定位属 M1b | M1a 的 op 节点 loc 全是 'model.GPT'，没有逐算子行号，而 schema 必填 string | 编造行号（与 R21/R36 同族） |
| **R69** | S9 | 三个 signal 必须先算出存局部变量、同一份既喂 confidence() 又写进 anchor.signals，不许分别计算或中途取整 | schema/anchor.py 会自动执法 tier 与 signals 自洽 | S1 的守卫把 S9 自己的输出判成非法 |
| **R70** | S9 | meta.model.prompt_version 写 JUDGE_PROMPT_VERSION（"judge-v1"）不是默认 "0"；name 写后端真实 name；embed_model 写真实名或 "none" | minimal_trace 播种的是 prompt_version="0"/name="offline" | prompt 版本不可追溯 |
| **R71** | S10 | shape 格式化成 Python tuple repr (2, 4, 8, 8)（逗号后一个空格）；空 shape_in 渲染 '-' 不是 '(?)' | **注：空列表那半句是控制器写错的，已被 R96 纠正**（'-' 是 inputs 的三态，shape 的 [] 应是 '()'） | 见 R96 |
| **R72** | S10 | S18 已由用户批准（m03858），本切片确定不引 KaTeX，公式用等宽原始 LaTeX 文本 + 静态 SVG；不许再当待决项、不许自行 vendoring KaTeX/字体 | brief :15-18 仍写「S18 待批」是过期文本 | 偏离用户已批的决定 |
| **R73** | S10 | HTML 写入点在 cli.py 两条路径汇合处（skeleton 与真实 build 都写）；render 抛 BuildError → stderr 说清「trace.json 已写出，HTML 渲染失败：<原因>」→ return 2；绝不因 HTML 失败删 trace.json 或谎报没写出 | 只在 else 分支写会让 skeleton 没有页面 | 用户以为 trace 也没了 |
| **R74** | S10 | index.html 是派生产物，每次 build 都覆盖，不受 --force 约束，不许因它已存在就 exit 3 | dump_trace 的 overwrite 只管 trace.json | 二次 build 无故失败 |
| **R75** | S10 | xmlns="http://www.w3.org/2000/svg" 是命名空间标识符不是资源引用，允许；测试正则必须排除 xmlns 属性；其余任何 http(s):// 与 //cdn 一律禁止 | 浏览器不 fetch xmlns；HTML5 里 inline svg 甚至可省略 xmlns | 要么画出浏览器不认的 SVG、要么写一条永远红的测试 |
| **R76** | S9 | retrieve.py 的 _OFFLINE_REASON 改成用 configured_backend() 拼真实后端名 + 带上 exc 具体原因；保住既有四条断言；加具名测试（openai + embeddings 404 → reason 含 openai、含 embedding、不含矛盾措辞） | S8 范围禁令造成的跨任务后果：配 openai 但 404 时 reason 仍谎称 offline（分数与 tier 都对，错的是解释） | 解释失实（与 R64 同族） |
| **R77** | S8 | GC10 与 R63 的提交粒度冲突 → 不重写历史，记一次有条件豁免：R63 的 README 新节本身就是 S8 的交付物，同提交更原子；更具体的指令压倒更一般的 GC10。S11 的文档同步仍必须单独提交 | GC10 的立法意图是把跨任务文档同步与代码分开 | 提交粒度不一致 |
| **R78** | S9 | 拆项的门是 split_formula(unit.latex)==[]，不是 latex_to_sympy_safe(整式).ok；spine 路径根本不调用 latex_to_sympy_safe | 实测整式含 = 与 \mathrm{Attention} 必然 ok=False，但 split_formula 正确给 4 项且逐项 ok=True | 照 brief 字面实现 → 黄金夹具一个 anchor 都出不来，yellow 测试永远不可能绿 |
| **R79** | S9 | CLI 在 build_trace 成功后用 load_entry(args.repo, args.entry) 再取一次模块传给 attach_paper；绝不重新追踪；load_entry 抛异常不许冒 traceback | build_trace 只返回 dict 而 brief 明令不许改它；实测第二次 load_entry 只 0.003s（模块已在 sys.modules） | 重新追踪 → GC8 变化 + 耗时翻倍 |
| **R80** | S9 | s_struct 的 +0.2 是二值的「有没有同构」不含「对齐了几项」，是 R25 既定粗粒度不是 S9 缺陷；M4 要区分覆盖度应看 anchors/unresolved 条数比或给 struct_signal 加覆盖率字段，不是调权重 | 实测 [matmul] 单项与黄金 4 项都是 0.80；对同一 term 列表贪心子序列是全有或全无 | 调权重会破坏用户拍板写死的公式 |
| **R81** | S10 | HTML 测试期望值必须用 markupsafe.escape(reason) 比对；三不许：不许关 autoescape、不许把 reason 里的 '<' 删掉或改成「低于」、不许断言原始未转义串然后声称通过 | 真实 reason 含 '<'（置信度 0.20 < 0.45，332 字符），title 含双引号 | 测试永远红，或篡改解释（与 R76 同族） |
| **R82** | S10 | kind 不许编，也不许为拿 kind 重新解析论文；第②块改列 term_id/tier/confidence/aten_ops/evidence；项清单取「anchors ∪ unresolved 里 kind=='paper_unit' 且 ref 形如 *-t<N>*」的并集 | schema 的 anchor 不携带 kind 也不携带 latex；offline 默认路径 anchors=0、unresolved=4 条 term ref | 绕过 trace.json 唯一契约＝造假；只读 anchors 则默认页面一个公式项都不显示 |
| **R83** | S10 | R73 的行号按当前 HEAD 更新（cli.py :139 之后、:140 return 0 之前） | S9 把 cli.py 从 157 改到 178 行，原记的 :118/:119 全部失效 | 写错位置 → skeleton 不写 HTML |
| **R84** | S10 | green/yellow 视觉区分的测试 doc 必须走真实路径造（build_trace → load_entry → 单实例假后端 → patch embed 与 judge 两处 get_llm → attach_paper），不许手捏 anchor 当产品输出，必须断言调用计数 >=1；none 用例可手工构造带 tier='none' 的 doc 直接喂 render_html；不许改 S9 让它产 none-tier anchor | offline 真后端产 anchors=0，真实 openai 只能产 yellow，拿不到现成绿线 doc | 手捏 anchor＝mock 填产品输出 |
| **R85** | S9 | 逐项 s_retr = 本项 forward[term_id] 全部条目 score 的最大值 clip[0,1]，缺键/空表→0.0；任何 anchor/unresolved 的 signals 绝不用单元级 retrieval['s_retr']；不许用 backward 补分 | 评审 I-1：单元级标量复制给每个公式项，兄弟项命中 1.0 把零检索项抬上绿线；控制器用正交向量复现修前 4 条全绿、修后 t1/t3 正确降黄 | 假绿线 + signals 宣称有检索支撑 |
| **R86** | S9 | IngestError 早退前补 doc['meta']['model'] = _model_meta() | 早退在 _model_meta() 之前 return → 留 minimal_trace 默认 prompt_version="0"/name="offline" | 配 openai 却谎称 offline（与 R76 同族） |
| **R87** | S9 | spine.py 必须压回 ≤200 行，只许从模块 docstring 腾空间；绝不删 fail-closed 守卫/R37/R54/R69 注释/测试 | 198 行只剩 2 行余量，helper 约需 7 行 | 删守卫注释 → 下一个人重犯 |
| **R88** | S9 | S9 七条 Minor 全部 deferred，本轮禁修 | Minor 永不进修循环（fix-loop.md） | 范围蔓延 |
| **R89** | S9 | 评审举的 c=sigmoid(4·(0.62−0.5))=0.6178 隐含 s_struct=0.6 且 s_judge=1，不可达（s_struct=0.6→同构没命中→pairs=[]→不调 judge→s_judge=0）；验收测试必须用可达输入 s_struct=0.8 + s_judge=1 + 逐项 s_retr=0 → 0.654753 yellow | 机制成立但数字不在可达路径上 | 测试钉在不可达路径上＝恒真 |
| **R90** | S11 | brief 三处过期项：①第 3 条三处测试改写已全部完成，只核验不许重做/改名（S9 的 test_cli 名字成立）②第 5 条只有 S15 未批，S16/S17/S18/S19 已于 m03858 全批，计划四处散文要同步 ③旧框架账本路径是有意交叉链接，保留并追加指针段 | 照字面派会让 S11 重做已完成工作、甚至把已加强的测试改回去 | 重做已完成工作、削弱已加强的测试、让 git 历史与账本引用失效 |
| **R91** | S11 | S11 在 README 与 schema 注释写明「anchor.signals.s_retr 只认逐项值，单元级 retrieval['s_retr'] 只是 S6 调用级汇总，不得直接写进 anchor」 | 单元级 s_retr 仍在 S6 契约里，M1b 若有人直接拿它填 anchor，R85 会复发；本轮不改 S6（已结案，波及 16 条检索测试） | R85 的假绿线复发 |
| **R92** | S10 | S10 必须渲染第三种真实场景 --skeleton --paper（nodes=0/edges=0/anchors=0/unresolved=9，5 条 symbol + 4 条 paper_unit）；算子图优雅处理空节点集；未对齐清单同时显示两种 kind；符号表处理代码侧为空；四种输入都要能渲染 | 控制器实跑发现该场景真实存在且 S9 评审 M-3 指出无测试 | 默认骨架路径页面崩或空 |
| **R93** | S10 | brief Step 6 的「file:// 打开 + 截图」人工验收改由控制器在 S11 做，implementer 只需产出 HTML + 静态自检结论；不许因没法截图而 BLOCKED 或跳过 Step 6 | implementer 没有浏览器工具 | implementer 卡死。**后被 R94 修正：控制器也做不了** |
| **R94** | S11 | 浏览器目检本机做不了（Tabbit 两个实例都 BROWSER_LAUNCH_FAILED，注册表记录合法、进程也在跑）→ 不做 ACL 手术、不申请提权；验收改为控制器机器验证每条承重性质 + 视觉效果交用户本人打开看；绝不声称做了没做的目检 | recovery.md 明令不许改 OS ACL 绕过沙箱、不许自己启服务或换浏览器后端；为验证性目检提权不成比例 | 声称做了没做的验收＝欺骗用户 |
| **R95** | S11 | README 数学表一律用可达值（s_struct=0.8），禁止照抄设计文档 §2 的 s_struct=1 理论值（尤其第 4 行「弱检索 0.25→绿线」实际是黄线，档位翻了）；必须写明精确门槛 s_retr ≥ 0.382177 与 DeepSeek 天花板 0.654753 yellow | 本切片 s_struct 上限 0.8（R23），设计文档那张表是理论表 | 文档给出用户永远看不到的数字＝假承诺 |
| **R96** | S10 | 纠正 R71 的空列表条款（控制器自己写错）：render_html.fmt_shape 必须与 report.fmt_shape 逐输入一致（[]→"()"）；不许 render_html import report（会把 torch 拖进纯渲染器 import 图），用测试钉住；inputs 的三态仍可以是 '-' | render/report.py:16-22 的 fmt_shape 是 None→"(?)"、[]→"()"；R71 把 inputs 的三态错记成 shape 的三态 | 同一 trace 在 CLI 与 HTML 语义不同，'-' 把「0 维标量」与「没有数据」混为一谈（report docstring 明令禁止） |
| **R97** | S10 | 模板 :119 的 code_only 改成如实的 paper_only + 说明 code_var 是冻结语义表对应变量非观测 + 加测试断言说明文字与实际 status 一致；不许改 mapping.py | code_only 与 paper_only 含义相反，页面主动告诉用户相反的事实；与 R76 完全同族 | 解释失实（与数据失实同族） |
| **R98** | S10 | 页眉改 doc.meta.* + Environment 换 undefined=StrictUndefined + 测试证明它对不可解析路径响亮抛 UndefinedError；顺手补 prompt_version 显示 | 模板写 doc.schema_version/doc.created_at 而契约里在 doc.meta. 下，Jinja2 默认 Undefined 静默渲染空串；主交付物每页页眉可见破损且整类笔误无守卫 | 静默省略 + 系统性无守卫 |

## 需要你拍板的三件事（我没有裁，留给你）

1. **S15 仍未批**（词法候选生成器）。本切片用 R37 的「结构同构产出 pairs」当 judge 的唯一候选来源，
   代价是 judge 以结构为前提、`s_judge` 与 `s_struct` 不独立，**结构错配时 judge 救不回来**。
2. **要不要把 spine 合并回 master**。合并是 worktree 外的副作用，按流程我必须停下来问你。
3. **SDD workspace 要不要保留**。账本、briefs、reports、裁决清单都在 **gitignored 的 `.superpowers/`** 下，
   **不在 git history 里**；技能说评审干净后删掉 workspace，但删了这份裁决记录就永久没了。我倾向保留。

## 已知局限（不是缺陷，是范围）

- **只对齐第一层**（`h.0.attn`）。夹具 `n_layer=2`，两层完全同构，按 R25 确定性选第一层。逐层对齐属 M4。（M4a 已落地，见 specs/2026-11-15-papertrace-layers-design.md）
- **s_struct 上限 0.8**（R23）：三条规则拿不到论文侧证据，不触发、记 misses。
- **+0.2 是二值的**（R80）：不含「对齐了几项」的覆盖度。
- **conflicts / backward 未落进 trace**：M4「四类对账」的输入缺口。
- **code_expr_range 是算子节点 id 区间不是 file:line**（R68）：逐算子源码定位属 M1b。
- **HTML 列不出公式项 kind**（R82）：schema 的 anchor 不携带 kind/latex；要 kind 得扩 schema，属新切片。
- **配 DeepSeek 中转永远出不了绿线**（R95）：DeepSeek 无 embeddings → s_retr=0 → 天花板 c=0.654753 yellow。
- **浏览器视觉目检没做**（R94）：本机 Tabbit 起不来，我没做 ACL 手术也没提权。机器验证做了，视觉效果要你自己打开看。
