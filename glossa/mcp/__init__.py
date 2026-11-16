"""MCP server（T11）：把 glossa 的六种能力按 JSON-RPC 2.0 over stdio 暴露出去。

server.py 是协议层（分派、错误码、逐行不退出），handlers.py 是六个工具的实现，
tools.py 只放 name / description / inputSchema 三个键。
"""
