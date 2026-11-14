"""placeholder 的名字 ↔ input_specs 的 target：两个独立字段的对应关系。

为什么形状核对不够（第十四轮 I-1）：`check_value_shape` 只比形状，两个**同形状**
参数互换 target 时它看不见。但 trace 的 `parent_id` 是用 `spec.target` 的点分路径
定位的（fx_nodes.py:142），所以**跨模块**互换会把权重挂到错误的父模块上：实测
`root.p_a` 的 parent 变成 `root/sub`、`root.p_sub_w` 变成 `root`，而
`shape_broken`/`shape_unchecked` 全是 0、`validate_trace` 仍通过、CLI exit 0。
那是**可见的错误数据**，不是「不可观测」。

地面真相：placeholder 的**名字**在图上（torch 的 placeholder_naming_pass 生成，
pydeps/torch/_export/utils.py:1080-1215），target 在 input_specs 里。改后者不会改
前者——与形状核对同一个道理：找另一份产物，而不是把同一份映射再算一遍。

第十五轮把实现从「反推索引」改成「**正向核对**」，因为反推是**有损**的：
torch 生成名字时先剥开头的 `L__self___`/`self_`、把非字母数字换成 `_`、再 `lower()`
（utils.py:1113-1119、:1168）。只按 `target.replace(".", "_")` 反推会
①误杀合法模型（`self_attn` 与 `attn` 撞基名、`a-b` 与 `a_b`、`W` 与 `w`、
`x` 与 `self_x` 实测全部 exit 2）；②漏检（`self_a`/`self_b` 的 base 在索引里
查不到 → 静默跳过 → 互换 target 后 parent_id 写反而 CLI exit 0）。
正向按 torch 的规则把 spec 的 target 映射成期望的 base，再与图上观察到的 base 比，
**按构造不会误杀**（参数真名叫 `self_` 时 base 是空串，反推会误杀，正向不会）。

诚实的边界：压平撞名（`a.b` 与 `a_b`、`self_attn.weight` 与 `attn.weight`）时两个
target 正向映射到同一个 base，名字区分不了它们，核对自然通过——那是**唯一**剩下的
洞。tests/test_fourteenth_review.py 的 test_ambiguous_swap_really_does_change_parent_id
构建整份 trace 证明 parent_id 确实会写反，不假装封死。名字核对与模块无关，所以
**同模块**的同形状互换也被拒（第十三轮把它写成「不可观测」是错的，已按事实改写）。

本模块不 import torch。
"""

import re

from papertrace.exceptions import BuildError

#: torch.export 给权重/缓冲/常量 placeholder 的前缀（utils.py:58-65；
#: 数据输入用 forward 形参名，无前缀）。TOKEN 的 `token` 前缀用不到：
#: REFUSED_KINDS 在更早一步就拒绝了它。
PREFIXES = ("p_", "b_", "c_", "obj_")

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")
_LSELF = "L__self___"
_SELF = "self_"


def strip_name(target) -> str:
    """复刻 torch 的 `_strip_name` + `.lower()`（utils.py:1113-1119、:1168）。

    那个函数是 placeholder_naming_pass 里的闭包，import 不到，只能照抄规则：
    只剥**开头**的 `L__self___`/`self_`（嵌套的 `sub.self_attn` 不剥，实测确认），
    再把所有非字母数字换成 `_`，最后小写。
    """
    text = str(target)
    if text.startswith(_LSELF):
        text = text[len(_LSELF):]
    elif text.startswith(_SELF):
        text = text[len(_SELF):]
    return _NON_ALNUM.sub("_", text).lower()


def _matches(base: str, expected: str) -> bool:
    """观察到的 base 是否就是期望的 base（允许 torch 的重名后缀 `_N`）。

    先比全名：`ws.0` 的 base 本来就是 `ws_0`，先剥后缀会把它剥成 `ws` 而漏检。
    """
    if base == expected:
        return True
    head, sep, tail = base.rpartition("_")
    return bool(sep) and tail.isdigit() and head == expected


def check_name_target(placeholders, plan: list[dict]) -> None:
    """每个权重/缓冲/常量 placeholder：名字必须与 spec 的 target 正向对应。

    数据输入不参与（名字是 forward 形参名，target 本来就是 None）。
    CUSTOM_OBJ 的 target 在命名 pass 之后被改写成 `name[4:]`（utils.py:1211-1215），
    所以它既可能等于 base 本身、也可能仍是原始属性路径，两种都接受。
    """
    by_name = {item["name"]: item for item in plan}
    problems: list[str] = []
    for node in placeholders:
        item = by_name.get(node.name)
        if item is None or item.get("kind") == "input":
            continue
        target = item.get("target")
        if target is None:
            continue
        prefix = next((p for p in PREFIXES if node.name.startswith(p)), None)
        if prefix is None:
            continue
        base = node.name[len(prefix):]
        expected = [strip_name(target)]
        if prefix == "obj_":
            expected.insert(0, str(target))
        if not any(_matches(base, want) for want in expected):
            problems.append(
                f"{node.name} 的名字按 torch 的命名规则对应 {expected[0]!r}，"
                f"但 spec 说它是 {target!r}"
            )
    if problems:
        raise BuildError(
            "placeholder 的名字与 input_specs 的 target 对不上（"
            + "；".join(problems)
            + "）；名字在图上、target 在 spec 里，是两个独立字段，对不上说明 target 被改过"
            "（同形状跨模块互换会把权重挂到错误的父模块），按约定拒绝出图"
        )
