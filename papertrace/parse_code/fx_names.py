"""placeholder 的名字 ↔ input_specs 的 target：两个独立字段的对应关系。

为什么形状核对不够（第十四轮 I-1）：`check_value_shape` 只比形状，两个**同形状**
参数互换 target 时它看不见。但 trace 的 `parent_id` 是用 `spec.target` 的点分路径
定位的（fx_nodes.py:142），所以**跨模块**互换会把权重挂到错误的父模块上：实测
`root.p_a` 的 parent 变成 `root/sub`、`root.p_sub_w` 变成 `root`，而
`shape_broken`/`shape_unchecked` 全是 0、`validate_trace` 仍通过、CLI exit 0。
那是**可见的错误数据**，不是「不可观测」。

地面真相：placeholder 的**名字**在图上（torch 按 `前缀 + target.replace(".", "_")`
生成，重名再加 `_N`），target 在 input_specs 里。改后者不会改前者——与形状核对
同一个道理：找另一份产物，而不是把同一份映射再算一遍。

诚实的边界：只在反推**唯一**时比较。`a.b` 与 `a_b` 压平后同名，名字这时区分不了
两个 target，跳过不猜——那是**唯一**剩下的洞，tests/test_fourteenth_review.py 的
test_ambiguous_swap_really_does_change_parent_id 构建整份 trace 证明 parent_id 确实
会写反，不假装封死。注意名字反推与模块无关，所以**同模块**的同形状互换也被拒
（第十三轮把它写成「不可观测」是错的，已按事实改写那条用例）。

本模块不 import torch。
"""

from papertrace.exceptions import BuildError

#: torch.export 给权重/缓冲/常量 placeholder 的前缀（数据输入用 forward 形参名，无前缀）。
PREFIXES = ("p_", "b_", "c_")


def _flat_index(named: dict, constants: dict) -> dict:
    """压平名 → 能压成它的**不同** target 集合（用 set：非持久缓冲会同时出现在
    named_buffers 与 exported.constants 里，那是同一个 target，不算歧义）。"""
    index: dict = {}
    for target in list(named) + list(constants):
        index.setdefault(str(target).replace(".", "_"), set()).add(str(target))
    return index


def _base(name: str) -> str | None:
    for prefix in PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return None


def check_name_target(placeholders, plan: list[dict], named: dict, constants: dict) -> None:
    """每个权重/常量 placeholder：名字反推出的 target 必须与 spec 说的一致。

    反推不唯一（压平撞名）或反推不出来时**跳过**，不猜；数据输入不参与（它的名字
    是 forward 形参名，target 本来就是 None）。
    """
    index = _flat_index(named, constants)
    by_name = {item["name"]: item for item in plan}
    problems: list[str] = []
    for node in placeholders:
        item = by_name.get(node.name)
        if item is None or item.get("kind") == "input":
            continue
        target, base = item.get("target"), _base(node.name)
        if base is None or target is None:
            continue
        candidates = index.get(base)
        if candidates is None and "_" in base:
            head, _, tail = base.rpartition("_")
            if tail.isdigit():
                # torch 的重名后缀（p_a_b_1）：先按全名查，查不到才剥后缀，
                # 否则 ws.0 这种**本来就带数字**的 target 会被剥错。
                candidates = index.get(head)
        if not candidates or len(candidates) != 1:
            continue
        expected = next(iter(candidates))
        if expected != str(target):
            problems.append(f"{node.name} 的名字对应 {expected}，但 spec 说它是 {target}")
    if problems:
        raise BuildError(
            "placeholder 的名字与 input_specs 的 target 对不上（"
            + "；".join(problems)
            + "）；名字在图上、target 在 spec 里，是两个独立字段，对不上说明 target 被改过"
            "（同形状跨模块互换会把权重挂到错误的父模块），按约定拒绝出图"
        )
