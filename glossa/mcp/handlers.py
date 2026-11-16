"""六工具实现（T11）：协议层在 server.py，这里只管「做那件事 / 如实说为什么不行」。

R328：工具级失败一律 {'content': [...], 'isError': True} 并把原因写成人能照着修的话；
只有协议层（方法不存在、缺必填参数）才用 JSON-RPC error。R330：read_source 四道闸——
相对路径且 resolve 后仍在仓库内、在 scan 保留集里、不是密钥名单、单次 ≤200 行。
R331：组件表与七块骨架分别从 COMPONENTS / build_outline 现读，绝不在这里抄第二份。
信封、仓库缓存与参数解析在 state.py（R452 同尺拆分：本文件只留六个工具与分派表）。
"""

from __future__ import annotations

import os
import pathlib

from glossa import exclude, facts as facts_mod, schema_repo
from glossa.cli_facts import KINDS
from glossa.explain import components, outline, render
from glossa.mcp.state import (cache_meta, default_dir, ensure, fail, int_arg, ok,
                              repo_root, store)
from papertrace.exceptions import BuildError
from papertrace.schema_validate import dump_trace

MAX_SOURCE_LINES = 200


def analyze_repo(args, state):
    """扫一遍并写 repo.json；返回 totals / 路径 / degraded 条数 / 是否截断。"""
    root = repo_root(args)
    max_files = int_arg(args.get("max_files"), "max_files", default=20_000, minimum=1)
    doc = facts_mod.build_repo_doc(root, max_files=max_files)
    schema_repo.validate_repo(doc)           # 与 CLI 同口径：台账不合法就不写盘
    given = args.get("out")
    if given is None:
        target, overwrite = default_dir(root) / "repo.json", True    # 自己的缓存目录，覆盖是本分
    else:
        target, overwrite = pathlib.Path(str(given)) / "repo.json", args.get("force") is True
        if target.exists() and not overwrite:
            raise BuildError("输出已存在：%s（加 force=true 才覆盖，与 CLI --force 同义）" % target)
    dump_trace(doc, target, overwrite=overwrite)
    entry = store(state, root, doc, out=str(target), auto=False)
    return {"repo": str(root), "out": str(target), "totals": doc["totals"],
            "degraded": len(doc.get("degraded") or []),
            "truncated": bool((doc.get("excluded") or {}).get("truncated")),
            "analyzed_at": entry["analyzed_at"],
            "note": "已扫描并写入 %s；同一仓库的后续工具调用直接复用这份台账。" % target}


def get_facts(args, state):
    """按 kind 前缀分页翻台账；返回 items / total / offset / limit。"""
    root, entry = ensure(args, state)
    kind = args.get("kind")
    if kind is not None and kind not in KINDS:
        raise BuildError("kind 只能是这些之一：%s（收到 %r）" % ("、".join(KINDS), kind))
    offset = int_arg(args.get("offset"), "offset", default=0, minimum=0)
    limit = int_arg(args.get("limit"), "limit", default=40, minimum=0)
    rows = entry["doc"].get("facts") or {}
    prefix = "fact:" + kind if kind else None
    picked = sorted(fid for fid in rows
                    if prefix is None or fid == prefix or fid.startswith(prefix + ":"))
    return {"repo": str(root), "kind": kind, "total": len(picked),
            "offset": offset, "limit": limit, "items": [
                {"id": fid, "numbers": list(rows[fid].get("numbers") or []),
                 "text": str(rows[fid].get("text") or "")} for fid in picked[offset:offset + limit]],
            **cache_meta(entry)}


def _relative(raw):
    """R330 ①：必须相对路径；NUL、盘符、UNC、.. 一律当场拒绝。"""
    if not isinstance(raw, str) or not raw.strip():
        raise BuildError("缺少必填参数 path（仓库内相对路径，字符串）")
    if chr(0) in raw:
        raise BuildError("path 里含 NUL 字节，拒绝：%r" % raw)
    pure = pathlib.PurePath(raw)
    if pure.is_absolute() or pure.drive or pure.root:
        raise BuildError("path 必须是仓库内的相对路径，拒绝绝对路径 / UNC / 跨盘符：%s" % raw)
    rel = raw.replace(os.sep, "/")
    if ".." in pathlib.PurePosixPath(rel).parts:
        raise BuildError("path 里不许出现 ..（R330：越界一票否决）：%s" % raw)
    return rel


def read_source(args, state):
    """读保留集里的原文（带行号）；四道闸任一不过就 isError 并写清是哪一道。"""
    root, entry = ensure(args, state)
    rel = _relative(args.get("path"))
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise BuildError("path resolve 之后不在仓库内（符号链接指向外面也算越界）：%s -> %s" % (rel, target))
    inside = target.relative_to(root).as_posix()
    if exclude.is_secret_name(pathlib.PurePosixPath(inside).name):
        raise BuildError("拒绝读取密钥名单里的文件（GC30：只登记名与字节数，内容一个字节都不给）：%s" % inside)
    if inside not in entry["paths"]:
        raise BuildError("%s 不在扫描保留集里（node_modules / 被排除目录 / 白名单外扩展名 / 超限文件都不给读）" % inside)
    start = int_arg(args.get("start"), "start", default=1, minimum=1)
    text = target.read_text(encoding="utf-8")        # 非 UTF-8 由 call_tool 如实报
    lines = text.splitlines()
    end = args.get("end")
    if end is None:
        end = min(len(lines), start + MAX_SOURCE_LINES - 1) if lines else start
    end = int_arg(end, "end", default=start, minimum=1)
    if end < start:
        raise BuildError("end 必须 >= start（收到 start=%d, end=%d）" % (start, end))
    if end - start + 1 > MAX_SOURCE_LINES:
        raise BuildError("单次最多读 %d 行，本次请求 %d–%d 共 %d 行；请分页（end <= start+%d）"
                         % (MAX_SOURCE_LINES, start, end, end - start + 1, MAX_SOURCE_LINES - 1))
    if start > len(lines):
        raise BuildError("start=%d 超出文件行数 %d：%s" % (start, len(lines), inside))
    if end > len(lines):
        raise BuildError("end=%d 超出文件行数 %d（R316：不静默截断）：%s" % (end, len(lines), inside))
    body = "\n".join("%d\t%s" % (n, lines[n - 1]) for n in range(start, end + 1))
    return {"repo": str(root), "path": inside, "start": start, "end": end, "total": len(lines),
            "text": body, **cache_meta(entry)}


def list_components(args, state):
    """14 个组件现读注册表（R331：没有第二份真源）。"""
    rows = [{"name": spec["name"], "title": spec.get("title"),
             "required": list(spec["required"]), "optional": list(spec["optional"]),
             "facts": list(spec["facts"]), "section": spec.get("section")}
            for spec in components.COMPONENTS.values()]
    return {"components": rows, "total": len(rows),
            "usage": "render_explain 的 blocks[].component 只能取这些名字；params 的必填键见 required。"}


def explain_outline(args, state):
    """七块骨架现读 outline.build_outline（R331）。"""
    root, entry = ensure(args, state)
    return {"repo": str(root), "blocks": outline.build_outline(entry["doc"]), **cache_meta(entry)}


def render_explain(args, state):
    """校验 blocks 后写 explain.html；假 fact id / 未知组件 / 越界区间都响亮拒绝。"""
    root, entry = ensure(args, state)
    blocks = args.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise BuildError("blocks 必须是「非空的 JSON 数组」，收到 %r" % (blocks,))
    mode, model_name = args.get("mode") or "program", args.get("model_name") or None
    out = pathlib.Path(str(args["out"])) if args.get("out") else default_dir(root)
    path = render.write_explain(entry["doc"], blocks, out, mode=mode, model_name=model_name)
    _html, report = render.render_explain(entry["doc"], blocks, mode=mode, model_name=model_name)
    return {"repo": str(root), "out": str(path), "mode": mode, "untraced": report["untraced"],
            "removed": report["removed"], "notes": report["notes"], "bytes": report["bytes"],
            "blocks": report["blocks"], **cache_meta(entry)}


_TOOLS = {"analyze_repo": analyze_repo, "get_facts": get_facts, "read_source": read_source,
          "list_components": list_components, "explain_outline": explain_outline,
          "render_explain": render_explain}


def call_tool(name, args, state):
    """R328：成功 isError=False；失败 isError=True 且原因写清「哪里不对、怎么改」。"""
    func = _TOOLS.get(name)
    if func is None:
        return fail("没有名为 %r 的工具；可用：%s" % (name, "、".join(sorted(_TOOLS))))
    try:
        return ok(func(args if isinstance(args, dict) else {}, state))
    except BuildError as exc:
        return fail("%s：%s" % (name, exc))
    except FileExistsError as exc:
        return fail("%s：输出已存在（%s）；加 force=true 才覆盖" % (name, exc))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return fail("%s 失败（%s）：%s" % (name, type(exc).__name__, exc))
    except Exception as exc:            # 兜底但绝不静默：类型与原文都交出去，不假装成功
        return fail("%s 内部错误（%s）：%s" % (name, type(exc).__name__, exc))
