"""模块角色识别：回答「这个模块在干什么」（Task C2，无论文模式）。

三条铁律，写在这里免得后来人改错：
- GC20：角色只看模块的直接子节点，禁止跨子树聚合冒充自身角色
  （子树聚合会把 root / Block 全判成 mlp，那是原型已经踩过的坑）；
- R202：判据只认算子名，不认类名、不认模块 id 里的字符串；
- R201 / GC21：认不出来就写 unknown，绝不为「看起来全都认出来了」放宽判据。
"""

# 冻结的激活算子名单（判据 6）与线性算子名单（判据 7 / 8）
ACTIVATION_OPS = {"gelu", "relu", "silu", "sigmoid", "tanh", "mish"}
LINEAR_OPS = {"linear", "matmul"}

# 冻结枚举（10 个），顺序即优先级
ROLES = (
    "attention",
    "mlp",
    "layernorm",
    "embedding",
    "linear",
    "activation",
    "dropout",
    "residual",
    "stage",
    "unknown",
)


def module_roles(nodes: list[dict]) -> list[dict]:
    """按 module_id 升序，每条恰好 5 个键。"""
    children = _children_by_parent(nodes)
    modules = [n for n in nodes if n.get("level") != "op"]
    out = []
    for mod in sorted(modules, key=lambda m: m["id"]):
        kids = children.get(mod["id"], [])
        ops = _direct_ops(kids)
        submods = _child_modules(kids)
        role, evidence = _classify(ops, submods, children)
        out.append(
            {
                "module_id": mod["id"],
                "class": mod.get("op", ""),
                "role": role,
                "evidence": evidence,
                "op_count": len(ops),
            }
        )
    return out


def _children_by_parent(nodes: list[dict]) -> dict:
    """parent_id → 直接子节点列表（一遍扫描，别对每个模块再扫全表）。"""
    table: dict = {}
    for node in nodes:
        table.setdefault(node.get("parent_id"), []).append(node)
    return table


def _direct_ops(kids: list[dict]) -> list[dict]:
    """直接子节点里真正干活的算子：level == "op" 且 kind == "op"。

    param / input / const 是权重与输入占位，不算「这个模块在算什么」。
    """
    return [k for k in kids if k.get("level") == "op" and k.get("kind") == "op"]


def _child_modules(kids: list[dict]) -> list[dict]:
    return [k for k in kids if k.get("level") != "op"]


def _op_names(ops: list[dict]) -> list[str]:
    return [n.get("op") for n in ops]


def _has_attention_pattern(op_names: list[str]) -> bool:
    """matmul … softmax … matmul：某个 softmax 前后各有至少 1 个 matmul。"""
    for i, name in enumerate(op_names):
        if name != "softmax":
            continue
        before = any(n == "matmul" for n in op_names[:i])
        after = any(n == "matmul" for n in op_names[i + 1 :])
        if before and after:
            return True
    return False


def _add_inputs_are_equal_shaped(node: dict) -> bool:
    """add 的输入 ≥2 项、各项形状相同、且等于该 add 的 shape_out。"""
    shapes = node.get("inputs") or []
    if len(shapes) < 2:
        return False
    if any(shape != shapes[0] for shape in shapes):
        return False
    return shapes[0] == node.get("shape_out")


def _has_residual_add(ops: list[dict]) -> bool:
    """有 add，且每个 add 都是等形状相加——残差连接的特征。"""
    adds = [n for n in ops if n.get("op") == "add"]
    if not adds:
        return False
    return sum(1 for n in adds if _add_inputs_are_equal_shaped(n)) == len(adds)


def _mlp_child_hits(ops: list[dict], submods: list[dict], children: dict):
    """mlp 判据：直接子模块里含 linear/matmul 的 ≥2 个、含激活算子的 ≥1 个。

    只看每个子模块自己的直接算子（GC20：不递归进子树）；
    本模块直接算子若含 softmax / layer_norm / embedding 就不是 mlp。
    """
    op_names = _op_names(ops)
    if any(name in op_names for name in ("softmax", "layer_norm", "embedding")):
        return None
    linear_children, act_children = 0, 0
    linear_names: set = set()
    act_names: set = set()
    for sub in submods:
        sub_ops = _op_names(_direct_ops(children.get(sub["id"], [])))
        linear_hits = [n for n in sub_ops if n in LINEAR_OPS]
        if linear_hits:
            linear_children += 1
            linear_names.update(linear_hits)
        act_hits = [n for n in sub_ops if n in ACTIVATION_OPS]
        if act_hits:
            act_children += 1
            act_names.update(act_hits)
    if linear_children >= 2 and act_children >= 1:
        return linear_children, sorted(linear_names), act_children, sorted(act_names)
    return None


def _classify(ops: list[dict], submods: list[dict], children: dict):
    """判据顺序即优先级；返回 (role, evidence)，evidence 必须点名判据与命中数。"""
    op_names = _op_names(ops)
    if _has_attention_pattern(op_names):
        return "attention", f"自身 {len(ops)} 个算子里有 matmul→…→softmax→…→matmul 子序列"
    if "layer_norm" in op_names:
        return "layernorm", f"直接算子含 {op_names.count('layer_norm')} 个 layer_norm"
    if "embedding" in op_names:
        return "embedding", f"直接算子含 {op_names.count('embedding')} 个 embedding"
    if _has_residual_add(ops):
        adds = sum(1 for n in ops if n.get("op") == "add")
        return "residual", f"{adds} 个 add 的输入都 ≥2 项且各项形状相同"
    if ops and all(name == "dropout" for name in op_names):
        return "dropout", f"直接算子 {len(ops)} 个全是 dropout"
    if ops and all(name in ACTIVATION_OPS for name in op_names):
        return "activation", f"直接算子 {'/'.join(op_names)} 全在冻结激活名单里"
    if ops and all(name in LINEAR_OPS for name in op_names):
        return "linear", f"直接算子 {'/'.join(op_names)} 全在 linear/matmul 名单里"
    hits = _mlp_child_hits(ops, submods, children)
    if hits:
        linear_children, linear_names, act_children, act_names = hits
        joined_linear = "/".join(linear_names)
        joined_act = "/".join(act_names)
        return "mlp", f"直接子节点里 {linear_children} 个含 {joined_linear}、{act_children} 个含 {joined_act}"
    if submods:
        own = f"自身只有 {'/'.join(op_names)}" if op_names else "自身无直接算子"
        return "stage", f"{len(submods)} 个直接子模块，{own}，未命中任何结构判据"
    if not op_names:
        return "unknown", "模块既无直接算子也无直接子模块，按约定不猜"
    return "unknown", f"直接算子 {'/'.join(op_names)} 不在冻结的激活/线性/归一化名单里，按约定不猜"
