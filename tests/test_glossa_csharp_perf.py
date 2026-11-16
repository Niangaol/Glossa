"""R467–R469：C# 声明解析不许指数回溯（性能回归钉 + 语义钉子）。

修复前实测（同一台机、同一进程路径）：
  ConfiguredAssistantProvider 构造器行 DECL.match 单行 17.98s；
  DataDirectoryNotFoundException 构造器行 > 8s（探针超时截断）；
  PokemonData 全仓 analyze（1016 个可扫文件）因此数十分钟跑不完。
"""

from __future__ import annotations

import time

from glossa.lang import csharp

# 两条 PokemonData 实测卡住的行 + 一条泛型方法（守住 R383 不许回归）。
PATHOLOGICAL = (
    "    public ConfiguredAssistantProvider(IAppSettings settings, HttpClient? http = null)",
    "    public DataDirectoryNotFoundException(string message) : base(message) { }",
    "    public T Get<T>(string id)",
    "    {",
)


def _parse(body: tuple[str, ...]) -> dict:
    text = "namespace Demo;\npublic class Demo\n{\n" + "\n".join(body) + "\n}\n"
    return csharp.parse_source(text, "Demo.cs")


def test_pathological_declarations_do_not_backtrack_exponentially():
    started = time.monotonic()
    result = _parse(PATHOLOGICAL)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, ("C# 声明解析发生指数回溯：%d 行耗时 %.2fs"
                          % (len(PATHOLOGICAL), elapsed))
    got = {(s["name"], s["kind"]) for s in result["symbols"] if s["kind"] != "class"}
    # 构造器不记符号（既有口径）；泛型方法必须仍然是方法（R383 不许回归）。
    assert got == {("Get", "method")}, got
    assert result["parse"] == "approx"


def test_generic_and_tuple_shapes_still_resolve():
    result = _parse((
        "    private readonly (string? Key, string? Model)? _sig;",
        "    public static void Main(string[] args)",
        "    {",
        "    }",
        "    public async Task<Dictionary<string, int>> LoadAsync(int id)",
        "    {",
        "    }",
    ))
    got = {(s["name"], s["kind"]) for s in result["symbols"] if s["kind"] != "class"}
    assert got == {("_sig", "field"), ("Main", "method"), ("LoadAsync", "method")}, got
