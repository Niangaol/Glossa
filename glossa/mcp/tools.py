"""六工具的 name / description / inputSchema（T11 / R331：只声明契约，不做实现）。

description 一律写「什么时候用这个工具」，因为接上来的模型只有这几行字可看；
inputSchema 的 required 与类型照计划里的六工具契约，服务器在协议层就按 required 拒缺参（-32602）。
"""

from __future__ import annotations

_DESC = {
    "analyze_repo": "扫描一个仓库并写 repo.json 事实台账（总是重扫，不读会话缓存）。任何讲解工作的第一步；"
                    "要换 max_files、要覆盖已有输出、要重扫改过的仓库时都先调它。",
    "get_facts": "按 id 前缀分页翻事实台账（kind=file/pkg/entry/... 或不填看全部）。"
                 "写讲解前用它核对要引用的 fact id 与 numbers，别凭印象编。",
    "read_source": "读仓库内某个保留文件的原文（带行号，单次最多 200 行）。"
                   "需要引用具体代码时用它；越界、被排除目录、密钥文件一律拒绝并说明原因。",
    "list_components": "列出 14 个渲染组件及必填/选填参数与可用事实模式。"
                       "写 render_explain 的 blocks 之前读它，别手抄组件名。",
    "explain_outline": "返回七块骨架（标题、可用组件、每块的真 fact id）。"
                       "决定讲解结构时用它，facts 列表里的 id 就是你能引用的全部。",
    "render_explain": "校验 blocks 并写单文件离线 explain.html，返回未溯源数字处数与字节数。"
                      "讲解的最后一步；假 fact id、未知组件、越界行区间都会被响亮拒绝。",
}
_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}


def _schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required)}


TOOLS = [
    {"name": "analyze_repo", "description": _DESC["analyze_repo"], "inputSchema": _schema({
        "repo": {**_STR, "description": "仓库根目录（绝对路径最稳，相对路径按 server 进程的 cwd 解释）"},
        "out": {**_STR, "description": "repo.json 的落地目录；省略时写 output/mcp-cache/<repo>-<hash>/"},
        "force": {**_BOOL, "description": "输出已存在时是否覆盖（默认 false，与 CLI 的 --force 同义）"},
        "max_files": {**_INT, "description": "最多扫多少个文件，默认 20000；超过会截断并记 degraded"},
    }, ("repo",))},
    {"name": "get_facts", "description": _DESC["get_facts"], "inputSchema": _schema({
        "repo": {**_STR, "description": "仓库根目录（需与 analyze_repo 时同一个目录）"},
        "kind": {**_STR, "description": "只取这一类 fact（file/pkg/project/entry/import/symbol/"
                                        "namespace/graph/excluded/degraded/source/totals/bonus）"},
        "offset": {**_INT, "description": "跳过前 N 条，默认 0"},
        "limit": {**_INT, "description": "本次最多返回 N 条，默认 40"},
    }, ("repo",))},
    {"name": "read_source", "description": _DESC["read_source"], "inputSchema": _schema({
        "repo": {**_STR, "description": "仓库根目录"},
        "path": {**_STR, "description": "仓库内的相对路径（用 / 分隔；不许绝对路径、UNC、.. 或 NUL）"},
        "start": {**_INT, "description": "起始行号，从 1 开始，默认 1"},
        "end": {**_INT, "description": "结束行号（含）；省略则按 200 行上限自动截到 start+199"},
    }, ("repo", "path"))},
    {"name": "list_components", "description": _DESC["list_components"], "inputSchema": _schema({})},
    {"name": "explain_outline", "description": _DESC["explain_outline"], "inputSchema": _schema({
        "repo": {**_STR, "description": "仓库根目录"},
    }, ("repo",))},
    {"name": "render_explain", "description": _DESC["render_explain"], "inputSchema": _schema({
        "repo": {**_STR, "description": "仓库根目录"},
        "blocks": {"type": "array", "description": "组件块数组；每块只许 component/params/cites/section/title/notes 六个键",
                   "items": {"type": "object"}},
        "out": {**_STR, "description": "explain.html 的落地目录；省略时写 output/mcp-cache/<repo>-<hash>/"},
        "mode": {**_STR, "description": "program（程序版，默认）或 model（模型版，页头带模型名）"},
        "model_name": {**_STR, "description": "mode=model 时页头显示的模型名"},
    }, ("repo", "blocks"))},
]
