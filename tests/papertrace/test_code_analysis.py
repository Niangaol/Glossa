"""Task C4 守卫：组装层 + schema 可选 `analysis`（GC22 / R206–R210）。

这一组测试钉住「角色 + 指标 + 代码符号表 → trace.analysis」的组装口径：
- R206：角色表与指标表按 module_id 合并，两边集合不一致就抛 BuildError，
  绝不静默丢模块；
- R207：roles 只列真出现过的角色，从合并后的 modules 现数，不写零项；
- R208：totals 只能用 analysis_totals 的返回值，不另算一遍；
- R209：骨架模式（analysis 全空）也要能过 schema；
- R210：analyze_code 只写 symbols.code 与 analysis，nodes/edges/anchors/
  unresolved/meta 一个字节都不许动；
- GC22：analysis 在 schema 里不进 required，schema_version 仍是 1.0.0。
"""
from tests.common import ROOT

import copy
import json
from pathlib import Path

import pytest

pytest.importorskip("torch", reason="真夹具追踪需要 torch（CPU 版即可）")

import papertrace.build.analysis as ca  # noqa: E402
from papertrace.analyze.roles import ROLES  # noqa: E402
from papertrace.build.trace import build_trace, load_entry  # noqa: E402
from papertrace.build.analysis import METHOD_TEXT, analyze_code, empty_analysis  # noqa: E402
from papertrace.exceptions import BuildError, TraceSchemaError  # noqa: E402
from papertrace.schema.validate import load_schema, minimal_trace, validate_trace  # noqa: E402

REPO = str(ROOT / "tests" / "fixtures" / "nanogpt")
ENTRY = "model:build_model"

# brief：合并后每条恰好 8 个键（角色 5 个 + 指标 3 个）
MODULE_KEYS = {
    "module_id",
    "class",
    "role",
    "evidence",
    "op_count",
    "params",
    "max_activation",
    "est_flops",
}

# R210：analyze_code 不许碰的五个字段
GUARDED = ("nodes", "edges", "anchors", "unresolved", "meta")


@pytest.fixture(scope="module")
def model_and_doc():
    """真夹具：模块实例与一次真追踪同源（brief 的 load_entry + build_trace）。"""
    return load_entry(REPO, entry=ENTRY), build_trace(REPO, entry=ENTRY)


@pytest.fixture(scope="module")
def doc(model_and_doc):
    mod, raw = model_and_doc
    return analyze_code(raw, mod)


def _snapshot(trace: dict) -> dict:
    return {key: json.dumps(trace[key], sort_keys=True) for key in GUARDED}


def test_analysis_has_every_module_once(model_and_doc):
    mod, raw = model_and_doc
    before = _snapshot(raw)
    out = analyze_code(raw, mod)
    # 原地填，返回同一个 doc
    assert out is raw
    # R210：五个字段逐字不变（sort_keys 保证键序不影响比较）
    assert _snapshot(raw) == before
    modules = raw["analysis"]["modules"]
    assert len(modules) == 34, f"analysis.modules 有 {len(modules)} 条"
    ids = [m["module_id"] for m in modules]
    assert len(set(ids)) == 34, "有模块被重复统计"
    assert ids == sorted(ids), "modules 没有按 module_id 升序"
    assert set(ids) == {n["id"] for n in raw["nodes"] if n["level"] != "op"}
    for m in modules:
        assert set(m) == MODULE_KEYS, f"{m['module_id']} 的键是 {sorted(m)}"
        assert m["role"] in ROLES, f"{m['module_id']} 的角色 {m['role']} 不在冻结枚举里"
        assert m["evidence"], f"{m['module_id']} 的 evidence 是空串"
    # 收尾评审 M-2：roles 分布只列真出现过的角色、值都 ≥1。把它改成
    # counts.get(role, 0) 补满十键，下面两条必须红（R207：不写零项）。
    roles = raw["analysis"]["roles"]
    assert set(roles) <= set(ROLES), f"roles 出现了冻结枚举之外的角色：{sorted(roles)}"
    assert 0 not in roles.values(), f"roles 里补了 0 项：{roles}"


def test_symbols_code_is_filled_without_a_paper(doc):
    rows = doc["symbols"]["code"]
    assert {row["symbol"] for row in rows} == {"B", "T", "D", "H", "Dh"}
    assert len(rows) == 5, f"symbols.code 有 {len(rows)} 条"


def test_symbols_paper_and_mapping_stay_empty_without_a_paper(doc):
    assert doc["symbols"]["paper"] == []
    assert doc["symbols"]["mapping"] == []


def test_analysis_is_optional_in_the_schema():
    skeleton = minimal_trace()
    assert "analysis" not in skeleton
    validate_trace(skeleton)
    schema = load_schema()
    assert "analysis" not in schema["required"], "GC22：analysis 不许进 required"
    assert "analysis" in schema["properties"]
    # GC22：schema_version 的 const 保持 1.0.0 不动
    assert schema["properties"]["meta"]["properties"]["schema_version"]["const"] == "1.0.0"
    # R209：骨架模式的空 analysis 也要能过 schema
    skeleton["analysis"] = empty_analysis()
    validate_trace(skeleton)


def test_analysis_shape_passes_validation(doc):
    validate_trace(doc)
    forged = copy.deepcopy(doc)
    forged["analysis"]["roles"] = {"attention": -1}
    with pytest.raises(TraceSchemaError):
        validate_trace(forged)


def test_method_text_says_it_is_an_estimate(doc):
    method = doc["analysis"]["method"]
    assert "粗估" in method, f"方法说明没有自称粗估：{method!r}"
    assert method == METHOD_TEXT, "analysis.method 与 code_analysis.METHOD_TEXT 不一致"
    # GC19：不许出现冒充实测的说法
    for banned in ("精确计算量", "实测 FLOPs"):
        assert banned not in METHOD_TEXT, f"GC19：METHOD_TEXT 里不许出现 {banned!r}"


def test_merge_raises_when_the_two_tables_disagree(monkeypatch, model_and_doc):
    """C4 I-1（Ruling R215）：R206 的 BuildError 分支要有守门。

    两个方向都试：module_metrics 少返回一个模块、module_roles 少返回一个模块，
    analyze_code 都必须抛 BuildError，且消息里点名那个缺失的 module_id——
    绝不静默丢模块。砍表只砍一行（34→33），被测路径真被走到（计数器见断言）。
    """
    mod, raw = model_and_doc
    missing = "root/transformer.wte"
    metric_calls = []
    real_metrics = ca.module_metrics

    def fewer_metrics(nodes):
        got = real_metrics(nodes)
        metric_calls.append(len(got))
        return [r for r in got if r["module_id"] != missing]

    monkeypatch.setattr(ca, "module_metrics", fewer_metrics)
    with pytest.raises(BuildError) as excinfo:
        ca.analyze_code(copy.deepcopy(raw), mod)
    assert missing in str(excinfo.value), f"错误信息没有点名缺失的模块：{excinfo.value}"
    assert metric_calls == [34], f"module_metrics 的调用记录是 {metric_calls}"

    # 先还原指标表，否则两个表同时少一个模块、又「对得上」了，就测不到反向分支
    monkeypatch.setattr(ca, "module_metrics", real_metrics)

    role_calls = []
    real_roles = ca.module_roles

    def fewer_roles(nodes):
        got = real_roles(nodes)
        role_calls.append(len(got))
        return [r for r in got if r["module_id"] != missing]

    monkeypatch.setattr(ca, "module_roles", fewer_roles)
    with pytest.raises(BuildError) as excinfo:
        ca.analyze_code(copy.deepcopy(raw), mod)
    assert missing in str(excinfo.value), f"错误信息没有点名缺失的模块：{excinfo.value}"
    assert role_calls == [34], f"module_roles 的调用记录是 {role_calls}"


def test_method_text_names_weight_tying_and_buffers(doc):
    """F1（C3 I-1）：params 的口径必须如实，不许再自称「精确统计」。

    钉住两个词同时出现，防止有人把文案改回自夸；同时钉住旧的自夸句不许回来。
    """
    method = doc["analysis"]["method"]
    assert "共享权重" in method, f"METHOD_TEXT 没交代共享权重会重复计数：{method!r}"
    assert "buffer" in method, f"METHOD_TEXT 没交代注册 buffer 也按 param 计入：{method!r}"
    assert "参数量按权重张量元素数精确统计" not in method, "自夸句又回来了"
