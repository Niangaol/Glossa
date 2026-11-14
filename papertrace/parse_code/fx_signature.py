"""torch.export 的 input_specs：谁是真输入、谁是权重/缓冲/常量。

为什么不再靠名字猜：`p_ + 参数全名.replace(".", "_")` 会把 `sub.x` 和根上的
`sub_x` 压成同一个 `p_sub_x`，谁后写谁赢——结果权重被标成 input、真输入被标成
param，`shape_in` 跟着错，而 summary 的计数还可能「看起来正常」。
`graph_signature.input_specs` 是导出器自己给的权威信息：`spec.kind` 区分
PARAMETER / BUFFER / USER_INPUT / CONSTANT_TENSOR，`spec.target` 是参数的点分路径。

本模块不 import torch：只读 spec 的属性，方便在没装 torch 的机器上被 import。
"""

from papertrace.exceptions import TraceUnsupported
from papertrace.parse_code.fx_graph import all_val_shapes, val_dtype, val_shape

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
    kind = getattr(spec, "kind", None)
    text = getattr(kind, "name", None) or str(kind)
    return KIND_MAP.get(str(text).upper(), "input")


def input_plan(exported) -> list[dict]:
    """把 input_specs 摊平成 [{name, kind, target}]，顺序即 placeholder 顺序。"""
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
    named: dict = {}
    named.update(dict(module.named_parameters(remove_duplicate=False)))
    named.update(dict(module.named_buffers(remove_duplicate=False)))
    constants = dict(getattr(exported, "constants", None) or {})
    spec_by_name = {item["name"]: item for item in plan}
    queue = list(example_inputs)
    args: list = []
    for node in exported.graph.nodes:
        if node.op != "placeholder":
            continue
        spec = spec_by_name.get(node.name) or {}
        kind, target = spec.get("kind"), spec.get("target")
        if kind == "param":
            if target in named:
                args.append(named[target])
                continue
            raise TraceUnsupported(
                f"input_specs 说 {node.name} 是权重（target={target}），但模块里找不到它"
            )
        if kind == "const":
            if target in constants:
                args.append(constants[target])
                continue
            if target in named:
                args.append(named[target])
                continue
            raise TraceUnsupported(
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


def runtime_meta(module, torch_mod, example_inputs) -> dict:
    """把「这次追踪到底怎么跑的」记进 trace，不然结果无法复现也无法解释。"""
    shapes = []
    for item in example_inputs:
        if isinstance(item, (list, tuple)):
            shapes.extend(all_val_shapes(item))
        else:
            shape = val_shape(item)
            if shape is not None:
                shapes.append(shape)
    dtype = val_dtype(example_inputs[0]) if example_inputs else None
    return {
        "ok": True,
        "reason": None,
        "device": "cpu",
        "torch_version": str(getattr(torch_mod, "__version__", "")),
        "dtype": dtype,
        "batch": shapes[0][0] if shapes and shapes[0] else None,
        "seq_len": shapes[0][1] if shapes and len(shapes[0]) > 1 else None,
        "entry": f"{type(module).__module__}.{type(module).__name__}",
        "example_inputs": shapes,
    }
