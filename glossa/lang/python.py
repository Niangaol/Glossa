"""Python 精确解析：ast 只看不跑（T3）。

R274：只用 ast.parse，绝不 import / exec / eval 被分析模块（GC29）；SyntaxError →
      parse='skipped' + degraded 含 'SyntaxError'，symbols=[]、imports=[]，不抛。
R275：docstring 只取首行（ast.get_docstring(node, clean=True).splitlines()[0]）。
      取全文会让 file_card 爆炸。
R276：嵌套符号必须带 parent（类里的方法 parent=类名，类里的类 parent=外层类名），
      顶层 parent=None。ast.walk 不给父子关系，所以自己递归。
R277：import 只抽取不解析，level/module/names 原样交给 T4 的 resolve.py。
R351：ast.Import 的每个 alias 各出一条（import os, sys → 两条），只取 names[0]
      会静默丢掉 sys 这条依赖 = 假事实。
R352：ImportFrom 的 module 可能是 None（from . import helper）→
      specifier='.'*level+(module or '')，module 键保持 None，不补空串不猜包名。
R353：main_guard 只认模块顶层的 If（tree.body 直接子节点），函数体/类体里的守卫
      不算入口；比较两侧顺序都认（__name__ == '__main__' 与 '__main__' == __name__）。
      不用 ast.walk 找 If —— 全深度会把「某函数里恰好写了这句」当成仓库入口。
R369：_collect 自己的递归会在合法长表达式上溢出（1000 项 + 连接即复现，末帧
      iter_child_nodes）。不许穿透 —— 已 append 的符号保留、degraded 记一条
      「表达式嵌套过深，符号提取不完整」，parse 仍是 'exact'（语法确实解析成功）。

已知局限（如实声明，不假装已支持）：
- import 的 asname 不记（import numpy as np 只记 specifier='numpy'），见 R351；
  记别名要改 schema 与 resolve 的口径，留给后续切片。
- 装饰器不影响 lineno：ast 给的是 def 行，不是 @decorator 行。
- kind 只看直接父节点是否为 ClassDef：写在类体内 if 分支里的 def 记 function。
- PEP 695 的 `type Alias = …`（ast.TypeAlias）第一版不收录：symbols 里没有它，
  也不会新增 kind='type'（R371）；页面统计只能说「类/函数/方法」。
"""

from __future__ import annotations

import ast

_SYMBOLS = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _kind(node: ast.AST, in_class: bool) -> str:
    """R276：class 之外，父节点是 ClassDef → method，再按 async 分一档。"""
    if isinstance(node, ast.ClassDef):
        return "class"
    if in_class:
        return "async_method" if isinstance(node, ast.AsyncFunctionDef) else "method"
    return "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"


def _doc_first_line(node: ast.AST) -> str | None:
    """R275：只要首行；空 docstring 记 None。"""
    doc = ast.get_docstring(node, clean=True)
    lines = doc.splitlines() if doc else []
    return lines[0] if lines else None


def _collect(node: ast.AST, parent: str | None, in_class: bool, out: list[dict]) -> None:
    """R276：递归遍历；只有符号节点才改变 parent（in_class 描述直接父节点）。"""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SYMBOLS):
            out.append({"name": child.name, "kind": _kind(child, in_class),
                        "line": child.lineno, "end_line": child.end_lineno,
                        "parent": parent, "doc_first_line": _doc_first_line(child)})
            _collect(child, child.name, isinstance(child, ast.ClassDef), out)
        else:
            _collect(child, parent, False, out)


def _imports(tree: ast.AST) -> list[dict]:
    """R277/R351/R352：只抽取不解析；Import 每 alias 一条，ImportFrom 的 module 原样。"""
    out: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:                     # R351 每个 alias 各一条
                out.append({"specifier": alias.name, "level": 0, "module": alias.name,
                            "names": [], "line": node.lineno, "type_only": False})
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            out.append({"specifier": "." * level + (node.module or ""), "level": level,
                        "module": node.module,               # R352 原样，可能是 None
                        "names": [a.name for a in node.names],
                        "line": node.lineno, "type_only": False})
    out.sort(key=lambda imp: imp["line"])            # 稳定排序，同 line 保持 walk 顺序
    return out


def _is_main_guard(stmt: ast.stmt) -> bool:
    """R353：顶层 If 且 test 为 __name__ == '__main__'，两侧顺序都认。"""
    if not isinstance(stmt, ast.If) or not isinstance(stmt.test, ast.Compare):
        return False
    test = stmt.test
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False

    def _is_name(node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id == "__name__"

    def _is_main(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and node.value == "__main__"

    left, right = test.left, test.comparators[0]
    return (_is_name(left) and _is_main(right)) or (_is_main(left) and _is_name(right))


def _skipped(reason: str) -> dict:
    """R274：解析失败如实 skipped，返回形状与成功时完全一致。"""
    return {"symbols": [], "imports": [], "doc_first_line": None, "main_guard": False,
            "parse": "skipped", "degraded": [reason]}


def parse_source(text: str, relpath: str) -> dict:
    """ast 精确解析一份 Python 源码；只读 text，绝不执行它（GC29）。"""
    try:
        tree = ast.parse(text, filename=relpath)
    except SyntaxError as exc:
        return _skipped(f"SyntaxError: {exc.msg} (line {exc.lineno})")
    except ValueError as exc:                # 防御性：畸形 str 输入（ast 可能抛 ValueError）
        return _skipped(f"ValueError: {exc}")
    symbols: list[dict] = []
    degraded: list[str] = []
    try:
        _collect(tree, None, False, symbols)
    except RecursionError:                   # R369：合法长表达式会让遍历自身炸掉
        # 已 append 的符号不回滚；语法确实解析成功了，所以解析状态仍是 exact——
        # 改记 skipped 会把「解析成功但符号不全」谎报成「没解析」。
        degraded.append("表达式嵌套过深，符号提取不完整")
    return {"symbols": symbols, "imports": _imports(tree),
            "doc_first_line": _doc_first_line(tree),
            "main_guard": any(_is_main_guard(s) for s in tree.body),   # R353 只认顶层
            "parse": "exact", "degraded": degraded}
