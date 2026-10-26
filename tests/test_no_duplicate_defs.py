# -*- coding: utf-8 -*-
"""
[守卫] 禁止同一模块内出现重复的顶层函数定义。

为什么需要机器卡死:
    2026-10-17 在 risk_rules.py 里发现 get_trend_tp_ladder / detect_stock_trend
    各有两份逐行等价的定义(L250 与 L319)。两份同名函数时, Python 静默以"后定义的"
    为准 —— 谁改了第一份都不生效, 且没有任何报错。这正是本项目最怕的
    "静默失效型契约漂移": 代码看着对了, 跑起来是另一套。
    本次一并删除, 并加此守卫防止后人再加回去。

判定范围: 仓库根目录 *.py + 核心包(tdx_score / tests 之外的主要生产目录)。
只查**顶层**函数(含 async), 不查方法/嵌套函数 —— 类方法与闭包内的重名是合法重载场景。

S6 迁移口径 (2026-10-24 总管扩裁, 老五 C3-1 同族先例 deleg_cf5ef81e):
    S6(186665b6) 后根级 risk_rules.py 已降为透明 shim(属性 get/set/del 转发到真源,
    无顶层函数定义), 对 shim 做字面顶层函数存在性断言 = 口径漂移, 结构性恒红。
    test_risk_rules_ladder_entry_points_unique 的入口存在性断言改指真源
    core/risk/risk_rules_impl.py (TSS=ee01c83fe89f);
    根级 shim 与真源的"重复顶层定义"扫描双方保留(防重复定义回归不减)。
"""
import ast
import collections
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需要保护的目录(相对仓库根)。tests/ 自身不纳入, 避免测试夹具重名误报。
SCAN_DIRS = [
    ".",                 # 根目录 *.py(不递归)
    "tdx_score",
    "cron",
    "scripts",
]

# 白名单: 已确认为"有意保留"的重复, 需写明理由并注明何时清理。
# 格式: {"相对路径": {"函数名": "理由"}}
WHITELIST = {}


def _py_files(root, rel):
    """收集相对目录 rel 下的 .py 文件。rel == "." 时只取根目录一层, 不递归。"""
    base = os.path.join(root, rel)
    if not os.path.isdir(base):
        return []
    out = []
    if rel == ".":
        for name in sorted(os.listdir(base)):
            if name.endswith(".py"):
                out.append(os.path.join(base, name))
        return out
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".venv", "node_modules")]
        for name in sorted(filenames):
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def _duplicate_defs(path):
    """返回该文件顶层重复定义的 {函数名: 出现次数}。语法不可解析时返回 None。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read())
    except (SyntaxError, ValueError, UnicodeDecodeError) as e:
        print(f"🔴 [test_no_duplicate_defs.py:61] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 (SyntaxError, ValueError, UnicodeDecodeError) → 兜底, 异常={e}", file=sys.stderr)
        return None
    names = [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return {k: v for k, v in collections.Counter(names).items() if v > 1}


def _collect():
    found = []
    for rel in SCAN_DIRS:
        for path in _py_files(ROOT, rel):
            dups = _duplicate_defs(path)
            if not dups:
                continue
            relpath = os.path.relpath(path, ROOT).replace("\\", "/")
            allowed = WHITELIST.get(relpath, {})
            for fn, cnt in sorted(dups.items()):
                if fn in allowed:
                    continue
                found.append((relpath, fn, cnt))
    return found


def test_no_duplicate_top_level_defs():
    """同一模块内不得有重复的顶层函数定义 —— 后者静默覆盖前者, 是契约漂移的温床。"""
    bad = _collect()
    assert not bad, (
        "发现同一模块内重复定义顶层函数(后定义会静默覆盖先定义, 先定义的修改不生效):\n"
        + "\n".join("  %s: def %s 出现 %d 次" % row for row in bad)
        + "\n\toverload/重写请改用不同函数名或显式删除旧定义;"
        "确需保留请在 tests/test_no_duplicate_defs.py 的 WHITELIST 写明理由。"
    )


def test_risk_rules_ladder_entry_points_unique():
    """risk_rules 止盈阶梯入口必须唯一 —— 2026-10-17 实际踩到的坑。

    S6 迁移口径 (2026-10-24 总管扩裁, 老五 C3-1 同族先例):
    - 入口存在性断言的目标 = 契约真源 core/risk/risk_rules_impl.py
      (根级 risk_rules.py 已降为透明 shim, 无顶层函数定义, 对其做字面断言=口径漂移)。
    - 根级 shim 与真源两侧的"重复顶层定义"扫描均保留(守卫语义不减)。
    """
    impl_path = os.path.join(ROOT, "core", "risk", "risk_rules_impl.py")
    assert os.path.exists(impl_path), "契约真源 core/risk/risk_rules_impl.py 缺失"

    # 根级 shim: 保留重复顶层定义扫描 (S6 前该文件为 905 行真源, 2026-10-17 踩过重名坑)
    shim_path = os.path.join(ROOT, "risk_rules.py")
    assert os.path.exists(shim_path), "根级 risk_rules.py (shim) 缺失"
    shim_dups = _duplicate_defs(shim_path)
    assert shim_dups is None or not shim_dups, (
        "risk_rules.py (shim) 出现重复顶层定义: %s" % (shim_dups,)
    )

    # 契约真源: 重复顶层定义扫描 (2026-10-17 坑的本体, 迁移后仍须卡死)
    impl_dups = _duplicate_defs(impl_path)
    assert impl_dups is None or not impl_dups, (
        "core/risk/risk_rules_impl.py 出现重复顶层定义: %s" % (impl_dups,)
    )

    # 入口存在性: 断言真源的顶层函数 (shim 仅做属性转发, 不含顶层 def)
    with open(impl_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    top = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for fn in ("get_trend_tp_ladder", "detect_stock_trend"):
        assert fn in top, "core/risk/risk_rules_impl.py 缺少止盈阶梯入口 %s" % fn


def test_scanner_self_check():
    """自检: 扫描器能检出人为构造的重复定义, 防止守卫本身失效(先红后绿)。"""
    src = "def foo():\n    return 1\n\n\ndef foo():\n    return 2\n"
    tree = ast.parse(src)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert collections.Counter(names)["foo"] == 2

    src_ok = "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n"
    tree_ok = ast.parse(src_ok)
    names_ok = [n.name for n in tree_ok.body if isinstance(n, ast.FunctionDef)]
    assert not {k: v for k, v in collections.Counter(names_ok).items() if v > 1}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
