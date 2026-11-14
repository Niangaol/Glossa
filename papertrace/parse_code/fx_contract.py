"""input_specs 的契约校验：spec ↔ 图 ↔ 模块，三方对不上就拒绝出图。

为什么单独一个文件：这些判据与「怎么把真实张量排好」是两件事，混在 placeholder_args 里
会让那个函数既做校验又做取值，行数也压不住（单源文件 ≤200 行）。

三条判据的地面真相各不相同，缺一不可：
- 缺项/多项/顺序：地面真相是**图的 placeholder 列表**；
- 未被认领的参数/缓冲：地面真相是**模块自己**（named_parameters/named_buffers）。
  只查「spec 说权重 → 模块里真有」是单向的：把真实权重标成 input、再给 example_inputs
  多补一项，数量校验就骗过去了，权重会顶着 kind=input 出图（第十轮探针实测放行）。

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
