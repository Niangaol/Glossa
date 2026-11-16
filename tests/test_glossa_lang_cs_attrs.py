"""R401–R402：C# attribute 目标前缀的守卫测试（T5 修复轮 2）。

与 tests/test_glossa_lang_cs.py 分文件：那份已 199 行，本轮 3 条守卫塞进去必超 200
（派发书 task-T5-fix2-brief.md 授权拆 tests/test_glossa_lang_cs_attrs.py）。
既有文件零改动，旧断言一条不放宽。
"""
from glossa.lang import csharp


def _parse(src):
    return csharp.parse_source(src, "X.cs")


# --- R402 m1：直贴（中间不夹 namespace）的目标前缀 attribute 必须整条丢弃 ---


def test_directly_adjacent_targeted_attributes_are_dropped_whole():
    """R401 复现两条：命中目标前缀的 attribute 体必须整条丢，不许漏第二项。

    夹具刻意让 attribute **紧邻**声明（不夹 `namespace N;`，也不夹空行）：
    旧测试正是因为中间有 namespace 行把 held 吞掉了，才没抓住这个 bug。
    """
    r = _parse('[assembly: AssemblyVersion("1.0.0.0"), System.CLSCompliant(true)]\n'
               "public class A\n"
               "{\n"
               "    [return: MarshalAs(1), CLSCompliant(true)]\n"
               "    public int M() { }\n"
               "}\n")
    by = {s["name"]: s for s in r["symbols"]}
    assert by["A"]["kind"] == "class"
    assert by["M"]["kind"] == "method"
    assert by["A"]["attributes"] == []       # 旧行为：['CLSCompliant']
    assert by["M"]["attributes"] == []       # 旧行为：['CLSCompliant']
    assert r["degraded"] == []               # R382 口径不变：这四个前缀静默丢弃


# --- R402 m2：held 只能被紧邻的一个符号消费，后面的符号不许拿 ---


def test_held_attributes_are_consumed_by_exactly_one_symbol():
    """正例放在文件末尾时没有后续符号承接，抓不住「held 不复位」（删 held = [] 必红）。"""
    r = _parse("[Serializable]\n"
               "public class B { }\n"
               "public class D { }\n")
    got = {s["name"]: s["attributes"] for s in r["symbols"]}
    assert got == {"B": ["Serializable"], "D": []}


# --- R402 m3：六个「第一版未实现」的前缀不许静默丢弃 ---

_UNSUPPORTED = ("field", "event", "method", "property", "type", "typevar")


def test_unsupported_attribute_target_prefixes_are_disclosed():
    r = _parse("namespace N;\n"
               "public class C\n"
               "{\n"
               "    [field: Aa]\n    public int Fld;\n"
               "    [event: Aa]\n    public event System.EventHandler Evt;\n"
               "    [method: Aa]\n    public void Mtd() { }\n"
               "    [property: Aa]\n    public int Prp { get; }\n"
               "}\n"
               "[type: Aa]\npublic class Dd { }\n"
               "[typevar: Aa]\npublic class Tt<T> { }\n")
    for prefix in _UNSUPPORTED:
        msg = ("attribute 目标前缀 %s 第一版未贴到符号（X.cs）" % prefix)
        assert r["degraded"].count(msg) == 1, (prefix, r["degraded"])
    assert sum(d.startswith("attribute 目标前缀 ")
               for d in r["degraded"]) == 6
    got = {s["name"]: s["attributes"] for s in r["symbols"]}
    assert got["Fld"] == [] and got["Evt"] == [] and got["Mtd"] == []
    assert got["Prp"] == [] and got["Dd"] == [] and got["Tt"] == []
