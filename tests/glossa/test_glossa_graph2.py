"""T6 修复轮 2（R406）：graph.nodes 的 lang/package 必须填实，不许恒 None。

T9 的图与关键文件卡片要按语言着色、按包分组，None 会被渲染成「未知语言」。
"""
from tests.common import FIXTURES
import pathlib
import shutil

from glossa import facts
from tests._tmp import scratch_dir

FIX = FIXTURES / "repos"


def _copy(name):
    dst = scratch_dir("glossa-graph2-" + name)
    shutil.copytree(FIX / name, dst, dirs_exist_ok=True)
    return dst


def test_graph_nodes_carry_lang_and_package():
    doc = facts.build_repo_doc(_copy("ts-monorepo"))
    nodes = {node["id"]: node for node in doc["graph"]["nodes"]}
    server = nodes["packages/a/src/server.ts"]
    assert server["lang"] == "typescript"
    assert server["package"] == "@x/a", "子包归属要按包目录最长前缀判定"
    assert nodes["apps/web/App.vue"]["lang"] == "vue"
    assert nodes["apps/web/App.vue"]["package"] is None, "apps/web 不是 workspace 包"
    assert nodes["packages/b/src/index.ts"]["package"] == "@x/b"


def test_project_level_nodes_keep_null_lang_and_package():
    doc = facts.build_repo_doc(_copy("cs-solution"))
    assert doc["graph"]["level"] == "project"
    assert [(n["lang"], n["package"]) for n in doc["graph"]["nodes"]] == [(None, None)] * 2


def test_project_nodes_label_with_the_project_name():
    """M-7：label 是页面显示项目名的唯一字段，退化成 csproj 路径用户就看不到项目名。"""
    doc = facts.build_repo_doc(_copy("cs-solution"))
    assert {node["label"] for node in doc["graph"]["nodes"]} == {"Demo.App", "Demo.Core"}


def test_file_nodes_fall_back_to_their_id_as_label():
    doc = facts.build_repo_doc(_copy("ts-monorepo"))
    nodes = doc["graph"]["nodes"]
    assert nodes and all(node["kind"] == "file" for node in nodes)
    assert all(node["label"] == node["id"] for node in nodes)
