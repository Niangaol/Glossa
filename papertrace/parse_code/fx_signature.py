"""torch.export 的 input_specs：谁是真输入、谁是权重/缓冲/常量。

为什么不再靠名字猜：`p_ + 参数全名.replace(".", "_")` 会把 `sub.x` 和根上的
`sub_x` 压成同一个 `p_sub_x`，谁后写谁赢——结果权重被标成 input、真输入被标成
param，`shape_in` 跟着错，而 summary 的计数还可能「看起来正常」。
`graph_signature.input_specs` 是导出器自己给的权威信息：`spec.kind` 区分
PARAMETER / BUFFER / USER_INPUT / CONSTANT_TENSOR，`spec.target` 是参数的点分路径。

本模块不 import torch：只读 spec 的属性，方便在没装 torch 的机器上被 import。
"""

from papertrace.exceptions import BuildError, TraceUnsupported
from papertrace.parse_code.fx_contract import check_contract

# InputKind 的名字 → 我们 trace.json 里的 kind
KIND_MAP = {
    "PARAMETER": "param",
    "BUFFER": "param",
    "CONSTANT_TENSOR": "const",
    "USER_INPUT": "input",
    "TOKEN": "input",
    "CUSTOM_OBJ": "input",
}


def _spec_name(spec) -> str | None:
    arg = getattr(spec, "arg", None)
    name = getattr(arg, "name", None)
    return name if isinstance(name, str) else None


def _spec_kind(spec) -> str:
    """不认识的 InputKind 一律拒绝，**不默认成 input**。

    默认成 input 会把一个权重/缓冲悄悄标成数据输入：名字覆盖齐全、schema 也过，
    整份 trace 的 kind 却是反的（第九轮 I-2）。torch 2.15 的 InputKind 只有
    PARAMETER/BUFFER/CONSTANT_TENSOR/USER_INPUT/TOKEN/CUSTOM_OBJ，全在 KIND_MAP 里；
    将来 torch 加了新种类，宁可 exit 2 让人来补映射，也不要静默猜。
    """
    kind = getattr(spec, "kind", None)
    text = str(getattr(kind, "name", None) or kind).upper()
    if text not in KIND_MAP:
        raise BuildError(
            f"input_specs 里有不认识的 InputKind：{text!r}；"
            "已知的是 " + "/".join(sorted(KIND_MAP))
            + "。不猜它是权重还是输入（猜错会把整类标反），请升级 papertrace 的 KIND_MAP"
        )
    return KIND_MAP[text]


def input_plan(exported) -> list[dict]:
    """把 input_specs 摊平成 [{name, kind, target}]。

    torch.export 保证顺序与图的 placeholder 顺序一致；但这是一份**约定**，
    placeholder_args 会逐个核对名字，不靠顺序静默对齐。
    """
    signature = getattr(exported, "graph_signature", None)
    specs = getattr(signature, "input_specs", None) or []
    plan: list[dict] = []
    for spec in specs:
        name = _spec_name(spec)
        if name is None:
            continue
        target = getattr(spec, "target", None)
        plan.append(
            {
                "name": name,
                "kind": _spec_kind(spec),
                "target": str(target) if target is not None else None,
            }
        )
    return plan


def module_of_target(target: str | None) -> str:
    """参数点分路径 → 它所属的模块路径（根模块是空串）。"""
    if not target:
        return ""
    return target.rsplit(".", 1)[0] if "." in target else ""


def classify(plan: list[dict]) -> dict:
    """从 plan 抽出四张表：权重名、常量名、真输入名（按顺序）、参数名→模块路径。"""
    params: set[str] = set()
    consts: set[str] = set()
    inputs: list[str] = []
    owner: dict[str, str] = {}
    for item in plan:
        kind, name = item["kind"], item["name"]
        if kind not in ("param", "const", "input"):
            # 手工拼的 plan 也要 fail-closed：else 分支会把未知 kind 当数据输入。
            raise BuildError(
                f"input_specs 里 {name} 的 kind={kind!r} 不认识（只接受 param/const/input）；"
                "不猜它是权重还是输入，按约定拒绝出图"
            )
        if kind == "param":
            params.add(name)
            owner[name] = module_of_target(item.get("target"))
        elif kind == "const":
            consts.add(name)
            owner[name] = module_of_target(item.get("target"))
        else:
            inputs.append(name)
    return {"params": params, "consts": consts, "inputs": inputs, "owner": owner}

def placeholder_args(module, exported, plan: list[dict], example_inputs) -> list:
    """按图里 placeholder 的顺序，把真实张量（权重/缓冲/常量/数据）排好。

    observe 不能再拿 `exported.module()` 跑：那个 GraphModule 的 placeholder 被换成了
    target 名（`sub_x`、`sub_x_1`），和 `exported.graph` 的名字对不上，参数节点连
    观察值都拿不到。这里用原图 + input_specs 指到的真实张量，键就是图里的名字。
    """
    params = dict(module.named_parameters(remove_duplicate=False))
    buffers = dict(module.named_buffers(remove_duplicate=False))
    named: dict = {**params, **buffers}
    constants = dict(getattr(exported, "constants", None) or {})
    spec_by_name = {item["name"]: item for item in plan}
    placeholders = [n.name for n in exported.graph.nodes if n.op == "placeholder"]
    check_contract(placeholders, plan, params, buffers)
    user_names = [item["name"] for item in plan if item.get("kind") == "input"]
    if len(user_names) != len(example_inputs):
        raise TraceUnsupported(
            f"example_inputs 有 {len(example_inputs)} 项，图里有 {len(user_names)} 个数据输入"
            f"（{'、'.join(user_names) or '无'}）；请按 forward 形参顺序给，多/少都不猜"
        )
    queue = list(example_inputs)
    args: list = []
    for node in exported.graph.nodes:
        if node.op != "placeholder":
            continue
        spec = spec_by_name[node.name]
        kind, target = spec.get("kind"), spec.get("target")
        if kind == "param":
            if target in named:
                args.append(named[target])
                continue
            raise BuildError(
                f"input_specs 说 {node.name} 是权重（target={target}），但模块里找不到它"
            )
        if kind == "const":
            if target in constants:
                args.append(constants[target])
                continue
            if target in buffers:
                args.append(buffers[target])
                continue
            if target in params:
                raise BuildError(
                    f"input_specs 说 {node.name} 是常量（target={target}），"
                    "但模块里它是可训练参数；常量与权重不能混，按约定拒绝出图"
                )
            raise BuildError(
                f"input_specs 说 {node.name} 是常量（target={target}），但拿不到它的值"
            )
        if not queue:
            raise TraceUnsupported(
                f"example_inputs 不够：placeholder {node.name} 没有对应的真实张量"
            )
        args.append(queue.pop(0))
    if queue:
        raise TraceUnsupported(f"example_inputs 多出 {len(queue)} 项，torch.export 没用到")
    return args
