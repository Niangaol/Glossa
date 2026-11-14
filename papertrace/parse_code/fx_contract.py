"""input_specs 的契约校验：spec ↔ 图 ↔ 模块，三方对不上就拒绝出图。

为什么单独一个文件：这些判据与「怎么把真实张量排好」是两件事，混在 placeholder_args 里
会让那个函数既做校验又做取值，行数也压不住（单源文件 ≤200 行）。

四条判据的地面真相各不相同，缺一不可：
- 缺项/多项/顺序：地面真相是**图的 placeholder 列表**；
- 未被认领的参数/缓冲：地面真相是**模块自己**（named_parameters/named_buffers）。
  只查「spec 说权重 → 模块里真有」是单向的：把真实权重标成 input、再给 example_inputs
  多补一项，数量校验就骗过去了，权重会顶着 kind=input 出图（第十轮探针实测放行）。
- plan 与导出器逐项一致：地面真相是 **torch.export 自己的 input_specs**。
  上面三条都抓不住「两边互换」（第十一轮 C1）。

全部抛 BuildError（exit 2）：spec 与图/模块对不上属于**契约错误**，不是「torch 追不动」。
"""

from papertrace.exceptions import BuildError


def check_contract(placeholders: list[str], plan: list[dict], params: dict, buffers: dict) -> None:
    """placeholders 按图里的顺序；plan 是 input_plan 摊平后的 [{name, kind, target}]。"""
    spec_by_name = {item["name"]: item for item in plan}
    # 缺一个就说明这份 input_specs 不是给这张图的（老 torch / 手工拼的 exported），
    # 继续往下走会把某个参数当成普通输入悄悄 pop 掉一个 example_inputs，形状全错还不报错。
    missing = [name for name in placeholders if name not in spec_by_name]
    extra = [name for name in spec_by_name if name not in placeholders]
    problems: list[str] = []
    if missing:
        problems.append("缺少 placeholder：" + "、".join(missing))
    if extra:
        problems.append("多出图里不存在的 placeholder：" + "、".join(extra))
    if problems:
        raise BuildError(
            "graph_signature.input_specs 与图对不上（" + "；".join(problems) + "）；"
            "无法判断谁是权重/输入，按约定拒绝出图"
        )
    # 顺序也要对：example_inputs 按 placeholder 顺序被消费，spec 错位的话形状相同的
    # 两个输入会被静默喂反（torch 2.15 实测一致，这里只是把约定钉死）。
    ordered = [item["name"] for item in plan]
    if ordered != placeholders:
        raise BuildError(
            "input_specs 的顺序与图的 placeholder 顺序不一致："
            + "、".join(ordered) + " ≠ " + "、".join(placeholders)
            + "；按约定拒绝出图（不猜哪个对应哪个）"
        )
    claimed = {
        item["target"] for item in plan
        if item["kind"] in ("param", "const") and item.get("target")
    }
    unclaimed = sorted((set(params) | set(buffers)) - claimed)
    if unclaimed:
        raise BuildError(
            "模块里有参数/缓冲没被任何 param|const 的 input_specs 认领："
            + "、".join(unclaimed)
            + "；通常意味着它被标成了数据输入（权重与输入标反），按约定拒绝出图"
        )


def check_plan_table(plan: dict, expected: dict) -> None:
    """build_op_nodes 的入口断言：四张表必须与导出器自己的 input_specs 重生的一致。

    build_op_nodes 拿不到 module、也拿不到 example_inputs，单靠它判断不了 kind 对不对；
    调用方给了 exported 就在这里钉死「plan 是不是导出器那份」。不给 exported 时它是
    **内部 API**：只有 fx_trace 那条已经核过契约的路径才该这么用（第十一轮 Q4）。
    """
    problems: list[str] = []
    for key in ("params", "consts"):
        have = set(plan.get(key) or ())
        want = set(expected.get(key) or ())
        if have != want:
            problems.append(
                f"{key} 多了 {sorted(have - want)}、少了 {sorted(want - have)}"
            )
    have_in = list(plan.get("inputs") or ())
    want_in = list(expected.get("inputs") or ())
    if have_in != want_in:
        problems.append(f"inputs 应为 {want_in}，传入的是 {have_in}")
    if dict(plan.get("owner") or ()) != dict(expected.get("owner") or ()):
        problems.append("owner（参数所属模块路径）与导出器给的不一致")
    if problems:
        raise BuildError(
            "传给 build_op_nodes 的 plan 与 torch.export 自己的 input_specs 不一致（"
            + "；".join(problems)
            + "）；kind 的权威是导出器而不是调用方，按约定拒绝出图"
        )


def _triples(items: list[dict]) -> list[tuple]:
    return [(i.get("name"), i.get("kind"), i.get("target")) for i in items]


def check_plan_source(plan: list[dict], expected: list[dict]) -> None:
    """调用方传进来的 plan 必须与导出器自己给的 input_specs 逐项一致。

    为什么这条不能省：kind 的权威是 torch.export，不是调用方。反向认领的地面真相是
    「模块有哪些参数」，它抓得住「权重被标成 input 且没人认领」，却抓不住**两边互换**：
    模块有名为 x 的参数、forward 也有形参 x 时，把 p_x 标 input、x 标 param(target=x)，
    于是名字全覆盖、顺序对、x 也被认领了、example_inputs 数量还对得上——四道关卡全过，
    trace 里权重与输入的 kind 正好相反（第十一轮 C1 探针实测放行，CLI exit 0）。
    """
    if _triples(plan) == _triples(expected):
        return
    want_by_name = {item["name"]: item for item in expected}
    have = {item["name"] for item in plan}
    problems: list[str] = []
    for item in plan:
        want = want_by_name.get(item["name"])
        if want is None:
            problems.append(f"{item['name']} 不在导出器的 input_specs 里")
            continue
        for field in ("kind", "target"):
            if item.get(field) != want.get(field):
                problems.append(
                    f"{item['name']} 的 {field} 应为 {want.get(field)!r}，"
                    f"传入的是 {item.get(field)!r}"
                )
    missing = [item["name"] for item in expected if item["name"] not in have]
    if missing:
        problems.append("导出器给了但 plan 里没有：" + "、".join(missing))
    if [i["name"] for i in plan] != [i["name"] for i in expected]:
        problems.append("顺序与导出器给的不一致")
    raise BuildError(
        "传入的 input_specs 与 torch.export 自己给的不一致（"
        + "；".join(problems or ["逐项字段对不上"])
        + "）；kind 的权威是导出器而不是调用方，按约定拒绝出图"
    )
