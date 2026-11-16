"""R473：`cached` 不许留成恒 false 的装饰字段——本轮选 (b) 删掉它，缓存语义只由 `note` 的整句披露。

理由：cached 只是 note 的布尔副本（note 已经说清「本结果来自本次会话缓存」还是「这次刚自动 analyze 一次」），
删掉不丢信息；而要让 analyze_repo 真有复用语义，得把仓库指纹写进 schema 冻结的 repo.json 或另加侧车文件，
等于改契约。这里钉三件事：analyze_repo 响应里没有这个键、四个查询工具也没有、description 不再承诺复用缓存。
"""
import json
import shutil
from pathlib import Path

from glossa.mcp import handlers, server, tools
from tests._tmp import scratch_dir

FIX = Path(__file__).parent / "fixtures" / "repos"


def _repo(name="ts-monorepo"):
    dst = scratch_dir("glossa-claims-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst


def _call(name, args, state):
    result = handlers.call_tool(name, args, state)
    assert result["isError"] is False, result["content"][0]["text"]
    return json.loads(result["content"][0]["text"])


def _desc(name):
    return next(row["description"] for row in tools.TOOLS if row["name"] == name)


def test_analyze_repo_has_no_cached_field_and_admits_it_rescans():
    """选 (b)：响应里没有 cached；description 明说总是重扫，不再写「或复用缓存」。"""
    payload = _call("analyze_repo", {"repo": str(_repo())}, server.new_state())
    assert "cached" not in payload
    assert "总是重扫" in _desc("analyze_repo")
    assert "复用缓存" not in _desc("analyze_repo")


def test_query_tools_disclose_cache_state_in_note_only():
    """四个查询工具的缓存状态仍如实披露（note 两种形态），只是不再有 cached 布尔。"""
    root = _repo()
    state = server.new_state()
    _call("analyze_repo", {"repo": str(root)}, state)
    hit = _call("get_facts", {"repo": str(root), "kind": "file", "limit": 1}, state)
    assert "cached" not in hit and "本结果来自本次会话缓存" in hit["note"]
    auto = _call("get_facts", {"repo": str(root), "kind": "file", "limit": 1}, server.new_state())
    assert "cached" not in auto and "这次已自动 analyze 一次" in auto["note"]
