"""Task C2 守卫：模块角色识别（只看直接子节点，GC20）。

这一组测试钉住的是「无论文模式」回答「这个模块在干什么」的方式：
角色只能来自模块自己的直接子节点，绝不跨子树聚合（否则 root / Block 都会被
误判成 mlp），也绝不看类名或模块 id 里的字符串（R202）——所以测试 8 把所
有类名涂成 "Foo" 后角色必须逐条不变。
"""
from tests.common import ROOT

import copy
from pathlib import Path

import pytest

pytest.importorskip("torch", reason="真夹具追踪需要 torch（CPU 版即可）")

from papertrace.analyze.roles import (  # noqa: E402
    _child_modules,
    _children_by_parent,
    _direct_ops,
    _mlp_child_hits,
    module_roles,
)
from papertrace.build.trace import build_trace  # noqa: E402

FIXTURE = str(ROOT / "tests" / "fixtures" / "nanogpt")
ENTRY = "model:build_model"

# R196：冻结的角色分布是实测值，改它等于改需求
FROZEN_SUMMARY = {
    "attention": 2,
    "mlp": 2,
    "layernorm": 5,
    "embedding": 2,
    "linear": 9,
    "dropout": 7,
    "activation": 2,
    "residual": 2,
    "stage": 3,
    "unknown": 0,
}

ROLE_KEYS = {"module_id", "class", "role", "evidence", "op_count"}


@pytest.fixture(scope="module")
def nodes():
    return build_trace(FIXTURE, entry=ENTRY)["nodes"]


@pytest.fixture(scope="module")
def roles(nodes):
    return {r["module_id"]: r for r in module_roles(nodes)}


def _synth_nodes():
    """合成一份最小 trace：一个模块，直接算子只有 foo / bar，没有子模块。"""
    return [
        {
            "id": "root",
            "parent_id": None,
            "level": "module",
            "op": "Mystery",
            "label": "root",
            "loc": "model.Mystery",
            "kind": None,
            "shape_in": [],
            "inputs": [],
            "shape_out": [],
            "outputs": [],
            "dtype": "float32",
            "inplace": False,
            "source": "runtime",
            "degraded": False,
            "degraded_reason": None,
            "repeat": 1,
            "stale": False,
        },
        {
            "id": "root/@001",
            "parent_id": "root",
            "level": "op",
            "op": "foo",
            "label": "foo",
            "loc": "model.Mystery",
            "kind": "op",
            "shape_in": [2, 8, 32],
            "inputs": [[2, 8, 32]],
            "shape_out": [2, 8, 32],
            "outputs": [[2, 8, 32]],
            "dtype": "float32",
            "inplace": False,
            "source": "runtime",
            "degraded": False,
            "degraded_reason": None,
            "repeat": 1,
            "stale": False,
        },
        {
            "id": "root/@002",
            "parent_id": "root",
            "level": "op",
            "op": "bar",
            "label": "bar",
            "loc": "model.Mystery",
            "kind": "op",
            "shape_in": [2, 8, 32],
            "inputs": [[2, 8, 32]],
            "shape_out": [2, 8, 32],
            "outputs": [[2, 8, 32]],
            "dtype": "float32",
            "inplace": False,
            "source": "runtime",
            "degraded": False,
            "degraded_reason": None,
            "repeat": 1,
            "stale": False,
        },
    ]


def test_attention_role_comes_from_the_matmul_softmax_matmul_pattern(roles):
    for mid in ("root/transformer.h.0.attn", "root/transformer.h.1.attn"):
        got = roles[mid]
        assert got["role"] == "attention", f"{mid} 的角色是 {got['role']}"
        assert got["op_count"] == 22, f"{mid} 的真算子数是 {got['op_count']}"
        assert "matmul" in got["evidence"] and "softmax" in got["evidence"]


def test_block_is_not_an_mlp(roles):
    """子树聚合会把 Block 误判成 mlp（GC20）；root 同理。"""
    for mid in ("root/transformer.h.0", "root/transformer.h.1"):
        assert roles[mid]["role"] != "mlp", f"{mid} 被误判成 mlp"
    for mid in ("root", "root/transformer"):
        assert roles[mid]["role"] != "mlp", f"{mid} 被误判成 mlp"


def test_residual_requires_two_equal_inputs(roles):
    for mid in ("root/transformer.h.0", "root/transformer.h.1"):
        assert roles[mid]["role"] == "residual", f"{mid} 的角色是 {roles[mid]['role']}"
    # root 的 add 只有 1 个输入（位置 id 相加），不构成 residual，只能落到 stage
    assert roles["root"]["role"] == "stage", f"root 的角色是 {roles['root']['role']}"


def test_mlp_container_is_recognized(roles):
    for mid in ("root/transformer.h.0.mlp", "root/transformer.h.1.mlp"):
        got = roles[mid]
        assert got["role"] == "mlp", f"{mid} 的角色是 {got['role']}"
        assert "linear" in got["evidence"] and "gelu" in got["evidence"]


def test_unknown_is_reported_not_guessed():
    """认不出来就必须写 unknown（R201 / GC21），还要说清为什么不猜。"""
    out = module_roles(_synth_nodes())
    assert len(out) == 1
    got = out[0]
    assert got["role"] == "unknown", f"合成了认不出的模块，却给了 {got['role']}"
    assert got["evidence"] and "不猜" in got["evidence"]


def test_roles_cover_every_module_exactly_once(nodes):
    out = module_roles(nodes)
    ids = [r["module_id"] for r in out]
    assert len(out) == 34
    assert len(set(ids)) == len(ids), "有模块被重复统计"
    assert set(ids) == {n["id"] for n in nodes if n["level"] != "op"}
    assert ids == sorted(ids), "结果没有按 module_id 升序"
    for r in out:
        assert set(r) == ROLE_KEYS, f"{r['module_id']} 的键是 {sorted(r)}"
        assert r["role"] in FROZEN_SUMMARY, f"{r['module_id']} 的角色 {r['role']} 不在冻结枚举里"
        assert r["evidence"], f"{r['module_id']} 的 evidence 是空串"


def test_role_summary_for_the_fixture(roles):
    # 先按冻结枚举零填充：unknown 0 也必须在统计里露面（R201）
    got = {role: 0 for role in FROZEN_SUMMARY}
    for r in roles.values():
        got[r["role"]] = got.get(r["role"], 0) + 1
    assert got == FROZEN_SUMMARY, f"角色分布 {got} 与冻结值不符"


def test_roles_do_not_depend_on_class_names(nodes):
    """R202：判据不许看类名 / 模块 id 里的字符串。"""
    forged = copy.deepcopy(nodes)
    for n in forged:
        if n["level"] != "op":
            n["op"] = "Foo"
    before = {r["module_id"]: r["role"] for r in module_roles(nodes)}
    after = {r["module_id"]: r["role"] for r in module_roles(forged)}
    assert after == before, "涂掉类名后角色变了，说明判据偷看了类名"
    # 探针有效性：class 字段确实被改写，证明上面这个相等不是空转
    assert all(r["class"] == "Foo" for r in module_roles(forged))

def _synth_node(node_id, parent_id, level, op, kind, inputs=None, shape_out=None):
    """合成 trace 节点；算子节点必须 kind == "op" 才算「这个模块在算什么」。"""
    return {
        "id": node_id,
        "parent_id": parent_id,
        "level": level,
        "op": op,
        "label": op,
        "loc": "model." + op,
        "kind": kind,
        "shape_in": list(shape_out or []),
        "inputs": [list(i) for i in inputs] if inputs else [],
        "shape_out": list(shape_out or []),
        "outputs": [],
        "dtype": "float32",
        "inplace": False,
        "source": "runtime",
        "degraded": False,
        "degraded_reason": None,
        "repeat": 1,
        "stale": False,
    }


def _role_of(module_id, nodes):
    """只取这一个模块的角色行，省得每个用例都写字典推导。"""
    return {r["module_id"]: r for r in module_roles(nodes)}[module_id]


def test_attention_needs_matmul_on_both_sides_of_softmax():
    """matmul → softmax，只有一侧有 matmul：不是 attention。

    钉住 analyze/roles.py:75-84 的 `if before and after`——改成 or 就红。
    """
    nodes = [
        _synth_node("m", None, "module", "Mystery", None),
        _synth_node("m/@001", "m", "op", "matmul", "op"),
        _synth_node("m/@002", "m", "op", "softmax", "op"),
    ]
    got = _role_of("m", nodes)
    assert got["role"] == "unknown", f"softmax 只有一侧有 matmul，却给了 {got['role']}"
    assert "attention" not in got["evidence"], f"evidence 里出现了 attention：{got['evidence']}"


def test_residual_requires_every_add_to_be_equal_shaped():
    """两个 add：第一个等形状、第二个两项形状不齐——不是 residual。

    钉住 analyze/roles.py:97-102 的「每个 add 都符合」——换成 any 就红。
    """
    nodes = [
        _synth_node("m", None, "module", "Mystery", None),
        _synth_node("m/@001", "m", "op", "add", "op",
                    inputs=[[2, 8, 32], [2, 8, 32]], shape_out=[2, 8, 32]),
        _synth_node("m/@002", "m", "op", "add", "op",
                    inputs=[[2, 8, 32], [2, 8, 64]], shape_out=[2, 8, 32]),
    ]
    got = _role_of("m", nodes)
    assert got["role"] == "unknown", f"有一个 add 形状不齐，却给了 {got['role']}"
    assert "residual" not in got["evidence"], f"evidence 里出现了 residual：{got['evidence']}"


def test_mlp_excludes_modules_that_do_softmax_themselves():
    """子模块像 mlp（2 个线性 + 1 个激活），但自身直接算子有 softmax：只能落到 stage。

    钉住 analyze/roles.py:112-113 的排除闸——删掉就红。
    """
    nodes = [
        _synth_node("m", None, "module", "Mystery", None),
        _synth_node("m/@001", "m", "op", "softmax", "op"),
        _synth_node("m/fc", "m", "module", "Foo", None),
        _synth_node("m/fc/@linear", "m/fc", "op", "linear", "op"),
        _synth_node("m/fc/@gelu", "m/fc", "op", "gelu", "op"),
        _synth_node("m/proj", "m", "module", "Bar", None),
        _synth_node("m/proj/@matmul", "m/proj", "op", "matmul", "op"),
    ]
    got = _role_of("m", nodes)
    assert got["role"] == "stage", f"自身有 softmax 却被判成 {got['role']}"
    assert "2 个直接子模块" in got["evidence"]


def test_residual_needs_the_add_output_to_match_its_inputs():
    """add 的输入彼此等形状，但 shape_out 与它们不等：不是 residual。

    钉住 analyze/roles.py:94 的 `return shapes[0] == node.get("shape_out")`——
    「≥2 项」「各项相同」两条子条件已有守卫，这是最后一个没被钉的；去掉它，
    下面这条必红（输入 [2,8,32] 会漏判成 residual）。
    """
    nodes = [
        _synth_node("m", None, "module", "Mystery", None),
        _synth_node("m/@001", "m", "op", "add", "op",
                    inputs=[[2, 8, 32], [2, 8, 32]], shape_out=[2, 16, 32]),
    ]
    got = _role_of("m", nodes)
    assert got["role"] == "unknown", f"add 的输出形状与输入不等，却给了 {got['role']}"
    assert "residual" not in got["evidence"], f"evidence 里出现了 residual：{got['evidence']}"


def test_mlp_gate_also_refuses_layer_norm_and_embedding_modules():
    """自身直接算子是 layer_norm / embedding：mlp 闸必须拒放行（两个名字都要有牙）。

    为什么问到闸这一层：`_classify` 在 :137/:139 先把这两个名字判成 layernorm /
    embedding，行为入口根本走不到 mlp 分派——所以只写「角色不是 mlp」的行为测试，
    把闸里的名字删掉仍然全绿（收尾评审 V4）。这里用产品自己的切分函数取出该模块
    的 ops / submods / children，直接钉 analyze/roles.py:112 的排除闸。
    """
    for own in ("layer_norm", "embedding"):
        nodes = [
            _synth_node("m", None, "module", "Mystery", None),
            _synth_node("m/@001", "m", "op", own, "op"),
            _synth_node("m/fc", "m", "module", "Foo", None),
            _synth_node("m/fc/@linear", "m/fc", "op", "linear", "op"),
            _synth_node("m/fc/@gelu", "m/fc", "op", "gelu", "op"),
            _synth_node("m/proj", "m", "module", "Bar", None),
            _synth_node("m/proj/@matmul", "m/proj", "op", "matmul", "op"),
        ]
        # 行为层：不是 mlp（layer_norm / embedding 各归自己的角色）
        got = _role_of("m", nodes)
        assert got["role"] != "mlp", f"自身有 {own} 却被判成 mlp"
        # 守卫层：闸本身不认这个 mlp 形状的容器——删掉闸里任一名字，这里必红
        children = _children_by_parent(nodes)
        kids = children["m"]
        assert _mlp_child_hits(_direct_ops(kids), _child_modules(kids), children) is None, (
            f"闸放行了自己含 {own}、子模块像 mlp 的容器（analyze/roles.py:112）")
