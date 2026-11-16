"""打包元数据契约（R482）：glossa 要进分发包、jinja2 要声明、运行时资源要随包。

不真的 pip install（本机 pip 被沙箱挡死）：只读 pyproject.toml 与 setuptools 的纯函数 API。
"""
import fnmatch
import pathlib
import tomllib

import pytest
from setuptools import find_packages

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQUIRED = {"glossa", "glossa.explain", "glossa.lang", "glossa.mcp", "papertrace"}


def _cfg():
    with open(PYPROJECT, "rb") as fh:
        return tomllib.load(fh)


def _find_cfg():
    return _cfg()["tool"]["setuptools"]["packages"]["find"]


def _dep_name(spec):
    """'Jinja2>=3.1' -> 'jinja2'：大小写与版本号写法不参与比对。"""
    cut = len(spec)
    for ch in "<>=!~;[":
        idx = spec.find(ch)
        if idx != -1:
            cut = min(cut, idx)
    return spec[:cut].strip().lower()


def _patterns(package):
    return _cfg()["tool"]["setuptools"]["package-data"][package]


def _assets(package):
    """包目录下除 .py 之外的运行时资源，返回相对包目录的 posix 路径。"""
    base = ROOT / package
    return sorted(
        path.relative_to(base).as_posix()
        for path in base.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".py"
    )


def test_dependencies_declare_jinja2_and_jsonschema():
    names = [_dep_name(dep) for dep in _cfg()["project"]["dependencies"]]
    assert "jsonschema" in names, names
    assert "jinja2" in names, names


def test_packages_find_includes_glossa():
    # 命名空间发现（setuptools 在 pyproject.toml 里的默认）是普通发现的超集，
    # 所以 find_packages 命中的包构建时一定也在（where/exclude 都跟配置对齐）。
    cfg = _find_cfg()
    found = set(find_packages(where=str(ROOT), include=cfg["include"], exclude=cfg.get("exclude", [])))
    missing = REQUIRED - found
    assert not missing, "未收进分发包：%s（include=%s）" % (sorted(missing), cfg["include"])


def test_package_data_covers_template_and_schema():
    patterns = _patterns("glossa")
    for asset in ("templates/glossa.html.j2", "schema/repo.json"):
        assert (ROOT / "glossa" / asset).is_file(), "资源缺失：%s" % asset
        assert any(fnmatch.fnmatch(asset, pat) for pat in patterns), (asset, patterns)


@pytest.mark.parametrize("package", ["glossa", "papertrace"])
def test_every_runtime_asset_is_shipped(package):
    """R495：rglob 覆盖检查扩到 papertrace/templates（spine.html.j2 之前不在 package-data 里）。"""
    patterns = _patterns(package)
    assets = _assets(package)
    uncovered = [a for a in assets if not any(fnmatch.fnmatch(a, pat) for pat in patterns)]
    assert not uncovered, "%s 的资源不会进 wheel：%s（patterns=%s）" % (package, uncovered, patterns)
    assert assets, "包目录下没有可检查的资源：%s" % package


def test_glossa_and_papertrace_templates_are_both_declared():
    """R495：两个模板包各有且只认自己的 *.j2（glossa 的 schema 也必须在）。"""
    assert any(fnmatch.fnmatch("templates/spine.html.j2", pat) for pat in _patterns("papertrace"))
    assert any(fnmatch.fnmatch("templates/glossa.html.j2", pat) for pat in _patterns("glossa"))
    assert (ROOT / "papertrace" / "templates" / "spine.html.j2").is_file()
