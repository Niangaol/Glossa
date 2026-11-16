"""Task C3 守卫：参数量 / 峰值激活 / 粗估 FLOPs（纯函数层，R200 / R203 / R204）。

这一组测试钉住「代码体检」的三个口径，全部只吃 trace 的 nodes：
- params 只数 kind == "param" 的权重张量元素数，是**精确**值不是估计；
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


def test_params_are_exact_for_the_fixture(rows, nodes):
    assert rows["root"]["params"] == 29856, f"root 的参数量是 {rows['root']['params']}"
    assert rows[ATTN_C_ATTN]["params"] == 3072, f"c_attn 的参数量是 {rows[ATTN_C_ATTN]['params']}"
    assert rows[LN_1]["params"] == 32, f"ln_1 的参数量是 {rows[LN_1]['params']}"
    # 口径自校验：18 个 param 节点、34 个模块，一条不多一条不少
    assert sum(1 for n in nodes if n.get("kind") == "param") == 18
    assert len(rows) == 34
    ids = [r["module_id"] for r in sorted(rows.values(), key=lambda r: r["module_id"])]
    assert ids == sorted(ids), "结果没有按 module_id 升序"
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
