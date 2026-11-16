"""MCP 工具的公共底座（T11）：结果信封、仓库缓存与参数解析。

R328 的两种返回形状（成功 / 失败）只在这里拼：工具函数只管返回 payload 或抛 BuildError。
缓存键一律 str(root.resolve())，所以同一个仓库的相对/绝对/带尾斜杠写法命中的是同一份 doc；
命中缓存时由 cache_meta 明说「这是旧事实」，三个查询类工具共用同一句披露（评审④）。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib

from glossa import facts as facts_mod
from papertrace.exceptions import BuildError

CACHE_ROOT = pathlib.Path("output") / "mcp-cache"


def ok(payload):
    """成功信封：JSON-RPC 的内容块是字符串，所以 payload 在这里序列化一次。"""
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": False}


def fail(message):
    """失败信封（R328）：原因直接写给人看，客户端靠 isError 分辨「工具说不行」。"""
    return {"content": [{"type": "text", "text": str(message)}], "isError": True}


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def repo_root(args):
    """repo → 绝对路径；不存在/不是目录说清是哪一种。"""
    raw = args.get("repo")
    if not isinstance(raw, str) or not raw.strip():
        raise BuildError("缺少必填参数 repo（仓库根目录，字符串）")
    root = pathlib.Path(raw).expanduser().resolve()    # R470：与 CLI 同一个入口形状（绝对路径）
    if not root.is_dir():
        raise BuildError("仓库根目录不存在或不是目录：%s" % root)
    return root


def int_arg(value, name, *, default=None, minimum=None):
    """JSON 里的布尔不是整数（True==1 会让 limit 悄悄变 1），所以显式挡掉。"""
    if value is None:
        if default is None:
            raise BuildError("缺少必填参数 %s" % name)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise BuildError("%s 必须是整数，收到 %r" % (name, value))
    if minimum is not None and value < minimum:
        raise BuildError("%s 必须 >= %d，收到 %d" % (name, minimum, value))
    return value


def default_dir(root):
    """没给 out 时的落地目录：output/mcp-cache/<repo>-<路径 hash 前 8 位>。"""
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]
    return pathlib.Path.cwd() / CACHE_ROOT / ("%s-%s" % (root.name or "repo", digest))


def cache_meta(entry):
    """缓存状态 + 「旧事实」披露：auto 表示这次刚自动分析过、没有旧事实。

    R473：不再返回 cached 布尔——它只是下面这句 note 的副本（analyze_repo 那边还恒 false），
    「是否来自本次会话缓存」由 note 的整句说清，字段删掉不丢信息。
    """
    if entry["auto"]:
        note = "仓库不在缓存里，这次已自动 analyze 一次（%s）；要换扫描参数请直接调用 analyze_repo。" % entry["analyzed_at"]
    else:
        note = ("本结果来自本次会话缓存（analyze 于 %s）；仓库若在之后改过，这里仍是旧事实，"
                "请用 analyze_repo（force=true）重扫。" % entry["analyzed_at"])
    return {"note": note}


def store(state, root, doc, *, out, auto):
    """把 doc 连同查表用的 path/行数索引放进 state['repos']。"""
    files = doc.get("files") or []
    entry = {"doc": doc, "analyzed_at": now(), "out": out, "auto": auto,
             "paths": {row["path"] for row in files},
             "lines": {row["path"]: int(row.get("lines") or 0) for row in files}}
    state.setdefault("repos", {})[str(root)] = entry
    return entry


def ensure(args, state):
    """取缓存；没有就自动 analyze 一次（只进内存，不写盘）。"""
    root = repo_root(args)
    entry = state.setdefault("repos", {}).get(str(root))
    if entry is None:
        entry = store(state, root, facts_mod.build_repo_doc(root), out=None, auto=True)
    return root, entry
