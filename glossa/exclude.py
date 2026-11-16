"""排除规则、语言白名单与密钥名单（T1）。

规则名协议（GC31：命中即计数，不静默）：
  默认目录          dir:<小写目录名>
  嵌入式运行时前缀  dir:pythoncore
  数据集目录        dir:dataset
  .glossaignore 行  ignore:<行原文>
"""

from __future__ import annotations

import fnmatch
import pathlib

# spec §12：默认排除目录，大小写不敏感（此处全小写）
DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset({
    "node_modules", ".git", "bin", "obj", "dist", "build", "out", "target",
    "vendor", "third_party", "__pycache__", ".venv", "venv", ".nuget-packages",
    "publish", ".tmp", "tmp", "var", "snapshots", "qdrant-config",
    "qdrant-storage", ".next", ".nuxt", "coverage", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".idea", ".vscode", ".agent-teams",
    ".chorography", ".video_agent", ".zcode", ".test-tmp", "cache", ".cache",  # R348
})

LANG_BY_EXT: dict[str, str] = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".cjs": "javascript", ".vue": "vue", ".cs": "csharp",
    ".json": "json", ".md": "markdown", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".sh": "shell", ".bat": "shell", ".ps1": "shell",
    ".css": "css", ".html": "html", ".xaml": "xaml", ".sln": "sln",
    ".csproj": "csproj", ".txt": "text",
}

SYMBOL_LANGS: frozenset[str] = frozenset(
    {"python", "typescript", "javascript", "vue", "csharp"}
)

# spec §12：密钥名单。只登记名与字节数，内容一个字节都不读（R266 / GC30）
SECRET_PATTERNS: tuple[str, ...] = (
    ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12",
    "id_rsa", "id_ed25519", "*.keystore", "secrets.*", "credentials.*",
)


def is_secret_name(name: str) -> bool:
    """密钥文件名？命中只登记名与字节数，绝不读内容（R266 / GC30）。

    R364：大小写一律显式 lower + fnmatchcase，不依赖 os.path.normcase
    （Windows 折叠大小写、POSIX 不折叠；依赖 OS 会在 Linux 上漏检
    `SECRET.PEM` / `.ENV.PROD`，把密钥内容读进 repo.json = GC30 泄漏）。
    """
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, pat.lower()) for pat in SECRET_PATTERNS)


def _ignore_hit(name: str, rel: str, ignore: list[str], is_dir: bool) -> str | None:
    """.glossaignore 单条命中；`dir/` 形式只配目录，规则名 ignore:<行原文>。

    R364：大小写显式 lower + fnmatchcase，不依赖 os.path.normcase。
    """
    low_name, low_rel = name.lower(), rel.lower()
    for line in ignore:
        if line.endswith("/") and not is_dir:
            continue
        pat = line[:-1] if line.endswith("/") else line
        low_pat = pat.lower()
        if fnmatch.fnmatchcase(low_name, low_pat) or fnmatch.fnmatchcase(low_rel, low_pat):
            return "ignore:" + line
    return None


def match_dir(dirname: str, rel_parent: str, ignore: list[str], use_default: bool) -> str | None:
    """目录命中的规则名；rel_parent 为父目录相对路径（'.' 表示仓库根）。"""
    rel = dirname if rel_parent in ("", ".") else rel_parent + "/" + dirname
    hit = _ignore_hit(dirname, rel, ignore, True)
    if hit is not None:
        return hit
    if not use_default:
        return None
    low = dirname.lower()
    if low in DEFAULT_EXCLUDED_DIRS:
        return "dir:" + low
    if low.startswith(("pythoncore-", "python-3")):
        return "dir:pythoncore"
    if "-dataset-" in low or low.endswith("-main"):
        return "dir:dataset"
    return None


def match_file_rule(name: str, rel_path: str, ignore: list[str]) -> str | None:
    """文件命中的 .glossaignore 规则名；目录专属行（dir/）不在这里生效。"""
    return _ignore_hit(name, rel_path, ignore, False)


def load_glossaignore(root: pathlib.Path) -> list[str]:
    """读仓库根 .glossaignore：每行一个 glob，空行与 # 注释跳过。"""
    path = pathlib.Path(root) / ".glossaignore"
    if not path.is_file():
        return []
    rules: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            rules.append(line)
    return rules
