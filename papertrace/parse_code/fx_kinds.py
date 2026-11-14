"""InputKind → trace.json 的 kind：认识哪些、明确拒绝哪些。

从 fx_signature 拆出来（第十四轮 M-3）：那个文件已经贴着「单源文件 ≤200 行」的约束，
而 kind 映射是一张**独立的表**，与「怎么解析张量」无关。拆开之后两边都能各自生长。

本模块不 import torch：只读 spec.kind 的名字，方便在没装 torch 的机器上被 import。
"""

from papertrace.exceptions import BuildError

# InputKind 的名字 → 我们 trace.json 里的 kind。
# 只有**验证过**的种类才进这张表：PARAMETER/BUFFER/CONSTANT_TENSOR/USER_INPUT 都有
# 真实导出用例（tests/test_model_zoo.py 的 18 个模型 + 各轮回归）。
KIND_MAP = {
    "PARAMETER": "param",
    "BUFFER": "param",
    "CONSTANT_TENSOR": "const",
    "USER_INPUT": "input",
}

#: 认识但**明确不支持**的 InputKind：宁可 exit 2 让人来看，也不按张量猜着喂。
REFUSED_KINDS = {
    "TOKEN": (
        "TOKEN 是 TokenArgument（副作用/控制流的令牌），不是张量数据输入，"
        "也不该按张量塞进 example_inputs"
    ),
    # 第十六轮 I-2：CUSTOM_OBJ 是 exported.constants 里的 ScriptObject
    # （torch/_export/converter.py:627-642 只把 ScriptObject 建成这一类）。第十一轮
    # 曾把它映射成 const，但**从来没有真实导出背书**：torch 2.15 会把
    # self.obj.add(x) 常量折叠成 x+3，造不出 CUSTOM_OBJ 的 spec。没有验证过的分支
    # 不该写成「已支持」，所以 M1a 先拒绝，M1b 补真实 ScriptObject 导出用例再放开。
    "CUSTOM_OBJ": (
        "CUSTOM_OBJ 是 exported.constants 里的 ScriptObject（自定义对象常量），"
        "不是张量；M1a 没有真实导出用例验证它的取值与命名，M1b 再支持"
    ),
}


def spec_kind(spec) -> str:
    """不认识的 InputKind 一律拒绝，**不默认成 input**。

    默认成 input 会把一个权重/缓冲悄悄标成数据输入：名字覆盖齐全、schema 也过，
    整份 trace 的 kind 却是反的（第九轮 I-2）。torch 2.15 的 InputKind 有
    PARAMETER/BUFFER/CONSTANT_TENSOR/USER_INPUT（映射见 KIND_MAP）与
    TOKEN/CUSTOM_OBJ（明确拒绝，见 REFUSED_KINDS）；将来 torch 加了新种类，宁可
    exit 2 让人来补映射，也不要静默猜。
    """
    kind = getattr(spec, "kind", None)
    text = str(getattr(kind, "name", None) or kind).upper()
    if text in REFUSED_KINDS:
        raise BuildError(
            f"input_specs 里有 {text}：{REFUSED_KINDS[text]}；"
            "本切片不支持，按约定拒绝出图（不把它当数据输入猜）"
        )
    if text not in KIND_MAP:
        raise BuildError(
            f"input_specs 里有不认识的 InputKind：{text!r}；"
            "已知的是 " + "/".join(sorted(KIND_MAP))
            + "。不猜它是权重还是输入（猜错会把整类标反），请升级 papertrace 的 KIND_MAP"
        )
    return KIND_MAP[text]
