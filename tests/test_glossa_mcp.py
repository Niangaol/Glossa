"""T11：MCP 协议与六工具。in-process 调 handle_message，不起子进程。"""
import io
import json
import shutil
from pathlib import Path

from glossa.mcp import handlers, server, tools
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"


def _repo(name='ts-monorepo'):
    dst = scratch_dir("glossa-t11-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst


def _req(method, params=None, rid=1):
    m = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        m["params"] = params
    return m


def _call(name, args, state):
    return server.handle_message(_req("tools/call",
                                      {"name": name, "arguments": args}), state)


def test_initialize_returns_protocol_version_and_capabilities():
    st = server.new_state()
    r = server.handle_message(_req("initialize", {"protocolVersion": "2024-11-05",
                                                 "capabilities": {},
                                                 "clientInfo": {"name": "t", "version": "1"}}), st)
    assert r["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in r["result"]["capabilities"]
    assert r["id"] == 1


def test_tools_list_has_exactly_six_tools_with_schemas():
    st = server.new_state()
    r = server.handle_message(_req("tools/list"), st)
    names = {t["name"] for t in r["result"]["tools"]}
    assert names == {"analyze_repo", "get_facts", "read_source",
                     "list_components", "explain_outline", "render_explain"}
    assert len(tools.TOOLS) == 6
    for t in tools.TOOLS:
        assert t["inputSchema"]["type"] == "object"
        assert t["description"]


def test_notification_gets_no_reply():
    st = server.new_state()
    assert server.handle_message({"jsonrpc": "2.0",
                                    "method": "notifications/initialized"}, st) is None


def test_unknown_method_returns_32601():
    st = server.new_state()
    r = server.handle_message(_req("nope/method"), st)
    assert r["error"]["code"] == -32601


def test_malformed_json_line_does_not_kill_the_loop():
    st = server.new_state()
    stdin = io.StringIO("{not json}\n" + json.dumps(_req("ping")) + "\n")
    stdout = io.StringIO()
    server.serve(stdin, stdout, st)
    lines = [json.loads(x) for x in stdout.getvalue().splitlines() if x.strip()]
    assert len(lines) == 2
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["result"] == {}          # ping 仍被处理


def test_missing_params_returns_32602():
    st = server.new_state()
    r = server.handle_message(_req("tools/call", {"name": "analyze_repo"}), st)
    assert r["error"]["code"] == -32602


def test_analyze_repo_tool_returns_totals_and_path():
    root = _repo()
    st = server.new_state()
    r = _call("analyze_repo", {"repo": str(root)}, st)
    assert r["result"]["isError"] is False
    payload = json.loads(r["result"]["content"][0]["text"])
    assert payload["totals"]["files"] == 13
    assert payload["totals"]["imports"] == 9
    assert "repo.json" in payload["out"]


def test_get_facts_pages_with_total():
    root = _repo()
    st = server.new_state()
    _call("analyze_repo", {"repo": str(root)}, st)
    r = _call("get_facts", {"repo": str(root), "kind": "file",
                            "offset": 0, "limit": 5}, st)
    payload = json.loads(r["result"]["content"][0]["text"])
    assert len(payload["items"]) == 5
    assert payload["total"] == 13
    assert all(i["id"].startswith("fact:file:") for i in payload["items"])


def test_read_source_refuses_outside_repo_and_secrets():
    root = _repo()
    (root / ".env.local").write_text("SECRET=abc123", encoding="utf-8")
    st = server.new_state()
    _call("analyze_repo", {"repo": str(root)}, st)
    for bad in ("../outside.ts", str(root.parent / "x.ts"), ".env.local",
                "node_modules/left-pad/index.js"):
        r = _call("read_source", {"repo": str(root), "path": bad}, st)
        assert r["result"]["isError"] is True, bad
        assert "abc123" not in json.dumps(r, ensure_ascii=False)


def test_read_source_caps_at_200_lines():
    root = _repo()
    st = server.new_state()
    _call("analyze_repo", {"repo": str(root)}, st)
    r = _call("read_source", {"repo": str(root),
                              "path": "packages/a/src/server.ts",
                              "start": 1, "end": 500}, st)
    assert r["result"]["isError"] is True
    assert "200" in r["result"]["content"][0]["text"]
    ok = _call("read_source", {"repo": str(root),
                               "path": "packages/a/src/server.ts",
                               "start": 1, "end": 3}, st)
    assert ok["result"]["isError"] is False
    text = ok["result"]["content"][0]["text"]
    assert "circuit" in text and "1" in text


def test_render_explain_rejects_fake_fact_id_with_iserror():
    root = _repo()
    st = server.new_state()
    _call("analyze_repo", {"repo": str(root)}, st)
    r = _call("render_explain", {"repo": str(root), "blocks": [
        {"component": "text", "params": {"text": "共 13 个文件"},
         "cites": ["fact:ghost"]}]}, st)
    assert r["result"]["isError"] is True
    assert "fact:ghost" in r["result"]["content"][0]["text"]
    assert "error" not in r          # 工具级失败，不是协议错误（R328）


def test_outline_and_components_have_no_second_source_of_truth():
    root = _repo()
    st = server.new_state()
    _call("analyze_repo", {"repo": str(root)}, st)
    r = _call("explain_outline", {"repo": str(root)}, st)
    blocks = json.loads(r["result"]["content"][0]["text"])["blocks"]
    assert [b["title"] for b in blocks][0] == "这项目是什么"
    rc = _call("list_components", {}, st)
    comps = json.loads(rc["result"]["content"][0]["text"])["components"]
    assert len(comps) == 14
    assert {c["name"] for c in comps} == set(__import__("glossa.explain.components",
                                                      fromlist=['COMPONENTS']).COMPONENTS)
