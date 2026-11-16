"""Task C3 守卫：参数量 / 峰值激活 / 粗估 FLOPs（纯函数层，R200 / R203 / R204）。

这一组测试钉住「代码体检」的三个口径，全部只吃 trace 的 nodes：
- params 只数 kind == "param" 的节点元素数求和：含共享权重（weight tying 的
  同一份权重挂在多个模块下会重复计数）与注册 buffer（fx 层把 BUFFER 也标成
  param），所以与 torch 的 unique named_parameters 口径不同，不是同一个数；
- max_activation 只数 kind == "op" 的算子输出元素数（R203：权重不是激活），
  而且数的是**元素个数不是字节**（2048 个元素，按 float32 字节算是 8192）；
- est_flops 只对 matmul / linear 用 2·∑shape_out·shape_in[-1] 求和，字段名带
  est_ 就是不许冒充实测（GC19）；
- R200：shape 为空或字段缺失一律计 0，绝不抛异常、绝不猜维度；
- R204：totals 的三个数字必须等于 root 那一行（同一份子树口径），不许另算一遍。
"""

from pathlib import Path

import pytest

pytest.importorskip("torch", reason="真夹具追踪需要 torch（CPU 版即可）")

from papertrace.analyze_metrics import analysis_totals, module_metrics  # noqa: E402
from papertrace.build_trace import build_trace  # noqa: E402

FIXTURE = str(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nanogpt")
ENTRY = "model:build_model"

# R203 / brief：每条恰好 4 个键，缺数据时是 0 不是 None
ROW_KEYS = {"module_id", "params", "max_activation", "est_flops"}
TOTAL_KEYS = {
    "modules",
    "params",
    "max_activation",
    "est_flops",
    "degraded",
    "degraded_reasons",
}

ATTN_C_ATTN = "root/transformer.h.0.attn.c_attn"
LN_1 = "root/transformer.h.0.ln_1"

# F3（C3 M-1）：module_metrics 必须按 module_id 升序返回——期望值手工写死在这里，
# 不再「先 sorted 再比 sorted」那种恒真断言。喂逆序 nodes 也必须得到这张表。
EXPECTED_MODULE_IDS = [
    "root",
    "root/lm_head",
    "root/transformer",
    "root/transformer.drop",
    "root/transformer.h",
    "root/transformer.h.0",
    "root/transformer.h.0.attn",
    "root/transformer.h.0.attn.attn_dropout",
    "root/transformer.h.0.attn.c_attn",
    "root/transformer.h.0.attn.c_proj",
    "root/transformer.h.0.attn.resid_dropout",
    "root/transformer.h.0.ln_1",
    "root/transformer.h.0.ln_2",
    "root/transformer.h.0.mlp",
    "root/transformer.h.0.mlp.c_fc",
    "root/transformer.h.0.mlp.c_proj",
    "root/transformer.h.0.mlp.dropout",
    "root/transformer.h.0.mlp.gelu",
    "root/transformer.h.1",
    "root/transformer.h.1.attn",
    "root/transformer.h.1.attn.attn_dropout",
    "root/transformer.h.1.attn.c_attn",
    "root/transformer.h.1.attn.c_proj",
    "root/transformer.h.1.attn.resid_dropout",
    "root/transformer.h.1.ln_1",
    "root/transformer.h.1.ln_2",
    "root/transformer.h.1.mlp",
    "root/transformer.h.1.mlp.c_fc",
    "root/transformer.h.1.mlp.c_proj",
    "root/transformer.h.1.mlp.dropout",
    "root/transformer.h.1.mlp.gelu",
    "root/transformer.ln_f",
    "root/transformer.wpe",
    "root/transformer.wte",
]


@pytest.fixture(scope="module")
def nodes():
    return build_trace(FIXTURE, entry=ENTRY)["nodes"]


@pytest.fixture(scope="module")
def rows(nodes):
    return {r["module_id"]: r for r in module_metrics(nodes)}


def _prod(shape) -> int:
    """测试侧的形状求积（与产品口径无关，只用于把期望值算给人看）。"""
    out = 1
    for dim in shape or []:
        out *= dim
    return out


def _dropout_only_nodes() -> list[dict]:
    """合成一个只有 dropout 算子的模块：没有权重、没有 matmul / linear。"""
    return [
        {
            "id": "root",
            "parent_id": None,
            "level": "module",
            "op": "Dropout",
            "label": "root",
            "loc": "model.Dropout",
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
            "op": "dropout",
            "label": "dropout",
            "loc": "model.Dropout",
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


def _shape_broken_nodes() -> list[dict]:
    """R200：缺 shape_in / shape_out 键、空 shape 的 matmul 与 linear。"""
    return [
        {"id": "root", "parent_id": None, "level": "module", "op": "Mystery", "kind": None},
        {"id": "root/@001", "parent_id": "root", "level": "op", "op": "matmul", "kind": "op"},
        {
            "id": "root/@002",
            "parent_id": "root",
            "level": "op",
            "op": "linear",
            "kind": "op",
            "shape_in": [],
            "shape_out": [],
        },
    ]


def _module(node_id: str = "root", parent_id=None, op: str = "Mystery") -> dict:
    """合成一个模块节点（kind 是 None，与真夹具一致：模块节点不是 param/op）。"""
    return {
        "id": node_id,
        "parent_id": parent_id,
        "level": "module",
        "op": op,
        "label": node_id,
        "loc": "model." + op,
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
    }


def _op(node_id: str, op: str, shape_in: list[int], shape_out: list[int]) -> dict:
    """合成一个挂在 root 下面的算子节点。"""
    return {
        "id": node_id,
        "parent_id": "root",
        "level": "op",
        "op": op,
        "label": op,
        "loc": "model." + op,
        "kind": "op",
        "shape_in": list(shape_in),
        "inputs": [list(shape_in)],
        "shape_out": list(shape_out),
        "outputs": [list(shape_out)],
        "dtype": "float32",
        "inplace": False,
        "source": "runtime",
        "degraded": False,
        "degraded_reason": None,
        "repeat": 1,
        "stale": False,
    }


def test_params_are_exact_for_the_fixture(rows, nodes):
    assert rows["root"]["params"] == 29856, f"root 的参数量是 {rows['root']['params']}"
    assert rows[ATTN_C_ATTN]["params"] == 3072, f"c_attn 的参数量是 {rows[ATTN_C_ATTN]['params']}"
    assert rows[LN_1]["params"] == 32, f"ln_1 的参数量是 {rows[LN_1]['params']}"
    # 口径自校验：18 个 param 节点、34 个模块，一条不多一条不少
    assert sum(1 for n in nodes if n.get("kind") == "param") == 18
    assert len(rows) == 34
    # F3（C3 M-1）：升序要真断言。喂逆序的 nodes，返回的 module_id 序列必须
    # 等于上面手工写死的那张升序表，不许再 sorted 一遍比 sorted
    ids = [r["module_id"] for r in module_metrics(list(reversed(nodes)))]
    assert ids == EXPECTED_MODULE_IDS, "module_metrics 没有按 module_id 升序返回"
    # 正序（夹具原始顺序本来就不是升序的：ln_f 排在 h.0 前面）也得到同一张表
    assert [r["module_id"] for r in rows.values()] == EXPECTED_MODULE_IDS
    for r in rows.values():
        assert set(r) == ROW_KEYS, f"{r['module_id']} 的键是 {sorted(r)}"
        for key in ("params", "max_activation", "est_flops"):
            assert type(r[key]) is int, f"{r['module_id']} 的 {key} 类型是 {type(r[key])}"


def test_max_activation_counts_elements_not_bytes(rows, nodes):
    root = rows["root"]
    assert root["max_activation"] == 2048, f"root 的峰值激活是 {root['max_activation']}"
    # 按元素数算是 2048；若按 float32 字节算会 ×4 成 8192
    assert root["max_activation"] != 8192
    # 2048 = 2×8×128，来自 h.0.mlp.c_fc 那条 linear 的输出
    op_products = [_prod(n.get("shape_out")) for n in nodes if n.get("kind") == "op"]
    assert max(op_products) == 2048
    assert [2, 8, 128] in [n.get("shape_out") for n in nodes if n.get("kind") == "op"]
    # R203 探针：子树里有 4096 个元素的权重张量，把 param 算进激活就会得到 4096
    param_products = [_prod(n.get("shape_out")) for n in nodes if n.get("kind") == "param"]
    assert max(param_products) == 4096


def test_est_flops_only_counts_matmul_and_linear(rows):
    assert rows["root"]["est_flops"] == 884736, f"root 的估算 FLOPs 是 {rows['root']['est_flops']}"
    assert rows[ATTN_C_ATTN]["est_flops"] == 98304, f"c_attn 的估算 FLOPs 是 {rows[ATTN_C_ATTN]['est_flops']}"
    # 2×1536×32 = 98304（c_attn 输出 [2,8,96]，输入最后一维 32）
    assert 2 * 1536 * 32 == 98304
    # 除 matmul / linear 之外计 0：ln_1 子树里只有 layer_norm
    assert rows[LN_1]["est_flops"] == 0, f"ln_1 的估算 FLOPs 是 {rows[LN_1]['est_flops']}"


def test_module_without_metrics_is_zero_not_none():
    """只有 dropout 算子的模块：没权重、没 matmul/linear，必须是 int 的 0。"""
    out = module_metrics(_dropout_only_nodes())
    assert len(out) == 1
    got = out[0]
    assert got["params"] == 0 and type(got["params"]) is int
    assert got["est_flops"] == 0 and type(got["est_flops"]) is int
    assert type(got["max_activation"]) is int
    # 探针有效性：dropout 的输出形状确实被认了出来（512 个元素），
    # 所以上面两个 0 不是「什么都没解析」造成的
    assert got["max_activation"] == 512
    # R200：缺字段 / 空 shape 一统计 0，不许抛异常
    broken = module_metrics(_shape_broken_nodes())
    assert len(broken) == 1
    zero = broken[0]
    assert (zero["params"], zero["max_activation"], zero["est_flops"]) == (0, 0, 0)


def test_est_flops_stays_zero_outside_the_whitelist():
    """C3 I-2：FLOPs 白名单要有反向钉子。

    合成一个自身带 conv2d（外加 softmax / layer_norm / add / mul 这些逐元素算子）
    的模块：白名单外的算子一个都不该贡献 FLOPs，所以 est_flops 必须只来自那条
    linear。谁把 conv2d 加进 FLOP_OPS，这条测试就红。
    """
    nodes = [_module()]
    nodes.append(_op("root/@001", "conv2d", [1, 3, 8, 8], [1, 4, 6, 6]))
    nodes.append(_op("root/@002", "softmax", [2, 8, 32], [2, 8, 32]))
    nodes.append(_op("root/@003", "layer_norm", [2, 8, 32], [2, 8, 32]))
    nodes.append(_op("root/@004", "add", [2, 8, 32], [2, 8, 32]))
    nodes.append(_op("root/@005", "mul", [2, 8, 32], [2, 8, 32]))
    nodes.append(_op("root/@006", "linear", [2, 8, 32], [2, 8, 64]))

    out = module_metrics(nodes)
    assert len(out) == 1
    got = out[0]
    assert got["est_flops"] == 65536, f"白名单外的算子被计了 FLOPs：{got['est_flops']}"
    # 探针有效性：linear 的 2×1024×32 确实被算到，max_activation 也确实读到了形状
    assert 2 * 1024 * 32 == 65536
    assert got["max_activation"] == 1024, f"形状没读到：{got['max_activation']}"
    assert got["params"] == 0


def test_degraded_reasons_sort_even_when_they_differ():
    """C3 M-2：degraded_reasons 的升序要能测出来。

    真夹具的两个降级节点 reason 逐字相同，排序根本看不出来；这里合成用例，故意按
    z/y/m/a 逆序插入，再塞一个空串 reason（空串不是原因，必须被跳过）。
    期望 ['a 原因', 'm 原因', 'y 原因', 'z 原因']。
    注意：str 哈希随机化开着（没固定 PYTHONHASHSEED），只放两个 reason 的话，去掉
    sorted() 后有 1/2 概率「碰巧升序」（两个元素的集合迭代两种次序等概，评审用 80 个 PYTHONHASHSEED 实测 40/80），变异探针会时红时绿；放 4 个 + 空串，
    碰巧升序的概率降到 1/24，这才是「必红」。
    """
    nodes = [_module()]
    for index, reason in enumerate(("z 原因", "y 原因", "m 原因", "a 原因", "")):
        node = _op("root/@00" + str(index), "split", [2, 8, 32], [2, 8, 32])
        node["degraded"] = True
        node["degraded_reason"] = reason
        nodes.append(node)

    totals = analysis_totals(module_metrics(nodes), nodes)
    assert totals["degraded"] == 5, f"降级节点数是 {totals['degraded']}"
    assert totals["degraded_reasons"] == ["a 原因", "m 原因", "y 原因", "z 原因"]


def test_degraded_nodes_are_reported(nodes):
    totals = analysis_totals(module_metrics(nodes), nodes)
    assert totals["degraded"] == 2, f"降级节点数是 {totals['degraded']}"
    reasons = totals["degraded_reasons"]
    assert len(reasons) >= 1
    assert reasons == sorted(set(reasons)), "degraded_reasons 没有去重升序"
    assert all(r and r.strip() for r in reasons), "degraded_reasons 里出现了空串"
    # 两个降级节点都是 split（多输出算子）；reason 原文由 parse_code/fx_nodes.py
    # 生成，里面没有 "split" 字样，所以按节点 op 点名而不是按子串
    assert {n["op"] for n in nodes if n.get("degraded")} == {"split"}
    assert set(reasons) == {
        n["degraded_reason"]
        for n in nodes
        if n.get("degraded") and (n.get("degraded_reason") or "").strip()
    }


def test_totals_sum_the_root_subtree(rows, nodes):
    totals = analysis_totals(list(rows.values()), nodes)
    root = rows["root"]
    assert set(totals) == TOTAL_KEYS, f"totals 的键是 {sorted(totals)}"
    # R204：同一份子树口径，直接取 root 那一行，不另算一遍
    assert totals["params"] == root["params"] == 29856
    assert totals["max_activation"] == root["max_activation"] == 2048
    assert totals["est_flops"] == root["est_flops"] == 884736
    assert totals["modules"] == 34
    assert type(totals["modules"]) is int
