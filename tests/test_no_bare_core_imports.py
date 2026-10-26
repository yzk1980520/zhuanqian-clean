# -*- coding: utf-8 -*-
"""
[守卫] 禁止"裸 import core.<a.b.c>(无 as 别名) + 下方裸用叶子名 c"病灶。

为什么需要机器卡死:
    裸 `import core.pipeline.atomic_json` 只在命名空间绑定顶层包 `core`,
    下方 `atomic_json.xxx` 是运行时 NameError。2026-10-24 老五 R0 裁定
    (deleg_c527956f) 实测 18 文件 24 处(与 87b8163b 修 message_queue.py
    同款病灶: 裸 import 被 except 吞掉 → 入队/落盘恒失败, 静默断链)。
    P1 R-5 已修复全部残留; 本守卫扫描仓内主工作树 *.py, 防复发。

判定规则(逐文件 AST, 非正则):
    对每个无别名的 `import core.<dotted>`(叶子名 c = dotted 末段):
      - c 已在模块级绑定(顶层 as 别名 import / 顶层赋值 / def / class /
        for/with 目标) → 非病灶;
      - 否则, 文件中每处 `c` 的裸 Name-Load: 若其作用域函数链(内层→外层)
        的局部绑定(形参 / 局部赋值 / 函数内 as 别名 import)均不含 c
        → 病灶(FAIL), 因为运行时该处必 NameError。
    注意: 限定用法 `core.<a.b.c>.xxx` 合法(裸 import 绑定了 core), 不判病灶;
    文件他处已有 `import core.<a.b.c> as c` 时, 残留的裸 import 行是冗余
    但无害(叶子名已被模块级别名绑定), 不判病灶。

已知边界(文档化的保守口径):
    - import 误写在 docstring 内的"死 import"不是 AST 节点, 不在本守卫
      范围(data_engineer 两份已于 R-5 一并移出 docstring 修复);
    - 条件式模块级绑定(顶层 if/try 体内的赋值)与嵌套作用域闭包, 按
      "保守放行"处理(可能漏报, 不误报)。

扫描范围: 仓库主工作树; 排除 .worktrees / archive / research_archive /
data / output / logs 等非主树目录(见 EXCLUDE_DIRS)。
"""
import ast
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 非主工作树目录 —— 这些目录是旧快照/数据/工件, 不属于现役代码, 不纳入门禁。
EXCLUDE_DIRS = {
    ".git", ".worktrees", "__pycache__", ".venv", "venv", "node_modules",
    "node-cache", "archive", "research_archive", "_archive", "data",
    "output", "logs", "cache", "backups", "baselines", "reports", "state",
    "memories", "research", ".specify", "specs", "models", "dashboards",
    "templates", "factors", "layers", "mainline",
}


def _target_names(t):
    """收集目标表达式绑定的 Name id(含元组/列表/星解包)。"""
    out = []
    if isinstance(t, ast.Name):
        out.append(t.id)
    elif isinstance(t, (ast.Tuple, ast.List)):
        for e in t.elts:
            out.extend(_target_names(e))
    elif isinstance(t, ast.Starred):
        out.extend(_target_names(t.value))
    return out


def _module_bindings(tree):
    """模块顶层(全局命名空间)无条件绑定的名字集合。"""
    binds = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            binds.add(node.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                binds.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != "*":
                    binds.add(a.asname or a.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                binds.update(_target_names(t))
        elif isinstance(node, ast.AnnAssign):
            binds.update(_target_names(node.target))
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            binds.add(node.target.id)
        elif isinstance(node, ast.For):
            binds.update(_target_names(node.target))
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars:
                    binds.update(_target_names(item.optional_vars))
    return binds


def _fn_locals(fn):
    """函数(含其子树, 保守口径)局部绑定的名字集合: 形参 + 局部赋值 + 函数内 import 别名。"""
    s = set()
    args = fn.args
    for a in args.posonlyargs + args.args + args.kwonlyargs:
        s.add(a.arg)
    if args.vararg:
        s.add(args.vararg.arg)
    if args.kwarg:
        s.add(args.kwarg.arg)
    for n in ast.walk(fn):
        if n is fn:
            continue
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            s.add(n.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                s.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name != "*":
                    s.add(a.asname or a.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                s.update(_target_names(t))
        elif isinstance(n, ast.AnnAssign):
            s.update(_target_names(n.target))
        elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
            s.add(n.target.id)
        elif isinstance(n, ast.NamedExpr):
            s.add(n.target.id)
        elif isinstance(n, ast.For):
            s.update(_target_names(n.target))
        elif isinstance(n, ast.With):
            for item in n.items:
                if item.optional_vars:
                    s.update(_target_names(item.optional_vars))
        elif isinstance(n, ast.ExceptHandler) and n.name:
            s.add(n.name)
    return s


def find_bare_core_imports(src):
    """扫描源码, 返回病灶清单 [{import_line, dotted, leaf, usage_line, scope}, ...]。

    病灶 = 无别名 `import core.<dotted>`(叶子 c)存在, 且 c 既无模块级绑定、
    在用用处作用域函数链中也无局部绑定, 但 c 被裸用(Name-Load)。
    源码不可解析时抛出 SyntaxError/ValueError(由调用方处理)。
    """
    tree = ast.parse(src)
    module_binds = _module_bindings(tree)

    fn_locals_cache = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_locals_cache[id(n)] = _fn_locals(n)

    # 每个节点的最外层→内层 函数链(递归标记, BFS 不弹栈不可靠故用递归)
    enclosing = {}

    def mark(n, chain):
        enclosing[id(n)] = [f for f in chain
                            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for c in ast.iter_child_nodes(n):
            mark(c, chain + ([c] if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) else []))
    mark(tree, [])

    # 收集无别名的 import core.<a.b.c>
    bare = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                parts = a.name.split(".")
                if a.asname is None and len(parts) > 1 and parts[0] == "core":
                    bare.append((n.lineno, a.name, parts[-1]))

    defects = []
    for lineno, dotted, leaf in bare:
        if leaf in module_binds:
            continue  # 文件已有模块级绑定(如他处 as 别名), 下方裸用合法
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and n.id == leaf and isinstance(n.ctx, ast.Load):
                chain = enclosing.get(id(n), [])
                bound = any(leaf in fn_locals_cache.get(id(f), set())
                            for f in reversed(chain))
                if not bound:
                    scope = chain[-1].name if chain else "<module>"
                    defects.append({
                        "import_line": lineno,
                        "dotted": dotted,
                        "leaf": leaf,
                        "usage_line": n.lineno,
                        "scope": scope,
                    })
    return defects


def _repo_py_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in sorted(filenames):
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    return out


def _collect():
    """扫全仓, 返回 [(relpath, defect), ...]。"""
    found = []
    for path in _repo_py_files(ROOT):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                defects = find_bare_core_imports(fh.read())
        except (SyntaxError, ValueError) as e:
            # CR-01 静默吞噬响铃化: 不可解析文件跳过但必须可见
            print("🔴 [test_no_bare_core_imports.py] 跳过不可解析文件 %s: %s"
                  % (os.path.relpath(path, ROOT), e), file=sys.stderr)
            continue
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        for d in defects:
            found.append((rel, d))
    return found


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): 全仓 AST 扫描(实测 7.72s) → 门禁快档排除
def test_no_bare_core_imports_in_repo():
    """仓内主工作树不得存在'裸 import core.<a.b.c> 且下方 c 未绑定却裸用'病灶。

    修复口径: 统一改为 `import core.<a.b.c> as c`(文件已有同模块 as 别名时
    勿重复添加, 冗余裸 import 行不判病灶)。
    """
    bad = _collect()
    assert not bad, (
        "发现裸 import core.<a.b.c> 无 as 别名、下方叶子名未绑定却被裸用的病灶"
        "(运行时 NameError, 与 87b8163b message_queue 断链同款):\n"
        + "\n".join(
            "  %s L%d: import %s (无别名) 但 L%d 在 %s 中裸用 %s.*"
            % (rel, d["import_line"], d["dotted"], d["usage_line"], d["scope"], d["leaf"])
            for rel, d in bad
        )
        + "\n修复: 将 import 改为 `import <dotted> as <leaf>`(勿与已有 as 别名重复);"
        "误写于 docstring 的 import 需移出并加 as 别名。"
    )


def test_scanner_self_check():
    """自检(先红后绿): 扫描器必须检出人为构造的裸 import 病灶, 且不误报修复形态 ——
    仿 test_no_duplicate_defs.test_scanner_self_check, 防守卫自身失效。"""
    # 红1: 模块级裸 import + 函数内裸用
    red1 = (
        "import core.pipeline.atomic_json\n"
        "def main():\n"
        "    atomic_json.update_json('x.json', {})\n"
    )
    assert len(find_bare_core_imports(red1)) >= 1, "红1: 模块级裸 import + 函数内裸用未检出"

    # 红2: 函数内裸 import + 紧邻裸用 (main() 尾段保存型, 病灶首发点)
    red2 = (
        "def main():\n"
        "    import core.pipeline.atomic_json\n"
        "    atomic_json.update_json('x.json', {})\n"
    )
    assert len(find_bare_core_imports(red2)) >= 1, "红2: 函数内裸 import + 裸用未检出"

    # 红3: 模块级裸 import + 模块级裸用
    red3 = (
        "import core.pipeline.atomic_json\n"
        "atomic_json.update_json('x.json', {})\n"
    )
    assert len(find_bare_core_imports(red3)) >= 1, "红3: 模块级裸 import + 模块级裸用未检出"

    # 绿1: 统一修复形态(带 as 别名)
    green1 = (
        "import core.pipeline.atomic_json as atomic_json\n"
        "atomic_json.update_json('x.json', {})\n"
    )
    assert find_bare_core_imports(green1) == [], "绿1: as 别名形态被误报"

    # 绿2: 限定用法(裸 import 只绑定 core, core.* 限定访问合法)
    green2 = (
        "import core.pipeline.atomic_json\n"
        "core.pipeline.atomic_json.update_json('x.json', {})\n"
    )
    assert find_bare_core_imports(green2) == [], "绿2: 限定用法被误报"

    # 绿3: 文件已有模块级 as 别名时, 冗余裸 import 行不判病灶(勿重复添加口径)
    green3 = (
        "import core.pipeline.atomic_json as atomic_json\n"
        "def b():\n"
        "    import core.pipeline.atomic_json\n"
        "    atomic_json.update_json('x.json', {})\n"
    )
    assert find_bare_core_imports(green3) == [], "绿3: 已有模块级 as 别名时的冗余裸 import 被误报"
