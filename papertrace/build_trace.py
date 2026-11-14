"""build 的编排入口。

本切片只会产出**空骨架**：合法的 trace.json，节点/边/锚点全为空。
这不是 M1a 完成——没有算子图就是没有算子图，不允许塞示例节点冒充。
真正的编排（ingest → parse_code → parse_paper → align → detail）在后续切片接。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from papertrace.schema_validate import minimal_trace


def repo_commit(repo: str | Path) -> str:
    """尽量拿到真实 commit；拿不到就写 dirty-<hash>，绝不假装是个真 commit。"""
    path = Path(repo)
    if path.is_dir():
        try:
            out = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return "dirty-skeleton"


def skeleton_trace(*, repo_url: str, commit: str | None = None) -> dict:
    """合法的空 trace。nodes 必须是 []，锚点必须是 []。"""
    return minimal_trace(
        repo_url=repo_url,
        commit=commit or "dirty-skeleton",
    )
