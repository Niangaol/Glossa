"""MCP 协议层（T11 / R327）：换行分隔 JSON-RPC 2.0 over stdio，标准库手写，零新依赖。

协议口径：protocolVersion 2024-11-05；实现 initialize / notifications/initialized / ping /
tools/list / tools/call。错误码 -32700 解析错 / -32600 非法请求 / -32601 方法不存在 /
-32602 参数错 / -32603 内部错。通知（无 id）一律不回包——客户端会发心跳与
notifications/initialized，回包或崩掉都会断连；畸形 JSON 行回 -32700 后继续读下一行。
stdout 只写 JSON-RPC 行，任何日志走 stderr（否则污染协议流）。
"""

from __future__ import annotations

import json

from glossa.mcp import handlers, tools

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "glossa", "version": "0.1.0"}
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class _Bad(Exception):
    """协议层拒绝：带错误码，handle_message 只负责把它翻成 error 对象。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def new_state():
    """每个连接一份状态：{'repos': {abs_path: entry}, 'initialized': False}。"""
    return {"repos": {}, "initialized": False}


def _reply(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": str(message)}}


def _initialize(state):
    state["initialized"] = True
    return {"protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": dict(SERVER_INFO)}


def _call(params, state):
    """tools/call：先在协议层挡缺参（-32602），再把工具结果原样交回（工具级失败走 isError）。"""
    if not isinstance(params, dict):
        raise _Bad(INVALID_PARAMS, "tools/call 的 params 必须是对象，收到 %r" % (params,))
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise _Bad(INVALID_PARAMS, "tools/call 缺参数 name（工具名，字符串）")
    known = {tool["name"]: tool for tool in tools.TOOLS}
    if name not in known:
        raise _Bad(INVALID_PARAMS, "没有名为 %r 的工具；可用：%s" % (name, "、".join(sorted(known))))
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise _Bad(INVALID_PARAMS, "tools/call 的 arguments 必须是对象，收到 %r" % (arguments,))
    missing = [key for key in known[name]["inputSchema"].get("required") or [] if key not in arguments]
    if missing:
        raise _Bad(INVALID_PARAMS, "工具 %s 缺少必填参数：%s" % (name, "、".join(missing)))
    return handlers.call_tool(name, arguments, state)


def handle_message(msg, state):
    """一条消息 → 一条响应；通知返回 None；任何情况下都不抛异常（协议错变 error 对象）。"""
    if not isinstance(msg, dict):
        return _error(None, INVALID_REQUEST, "消息必须是 JSON 对象，收到 %r" % (msg,))
    method, has_id, rid = msg.get("method"), "id" in msg, msg.get("id")
    if not isinstance(method, str) or not method:
        return _error(rid if has_id else None, INVALID_REQUEST, "缺少 method 字符串")
    if not has_id or method.startswith("notifications/"):
        return None                       # R327：通知一律不回包
    try:
        if method == "initialize":
            result = _initialize(state)
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": tools.TOOLS}
        elif method == "tools/call":
            result = _call(msg.get("params"), state)
        else:
            return _error(rid, METHOD_NOT_FOUND, "不认识的方法：%s" % method)
    except _Bad as exc:
        return _error(rid, exc.code, exc.message)
    except Exception as exc:              # 内部错也是协议层的事，绝不打断连接
        return _error(rid, INTERNAL_ERROR, "内部错误（%s）：%s" % (type(exc).__name__, exc))
    return _reply(rid, result)


def serve(stdin, stdout, state=None):
    """逐行读、逐行写；一行坏只回 -32700，继续读下一行（R327）。"""
    state = new_state() if state is None else state
    for line in iter(stdin.readline, ""):
        raw = line.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            reply = _error(None, PARSE_ERROR, "第 %d 列解析失败：%s" % (exc.colno, exc.msg))
        else:
            reply = handle_message(msg, state)
        if reply is None:
            continue
        stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        stdout.flush()
