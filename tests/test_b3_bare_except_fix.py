# -*- coding: utf-8 -*-
"""B3 附带修复 TDD: system_audit_checker 预存 P0 语法错 + 裸 except: 静默吞没扫描。

坐实 (做 B3 时顺带发现, 非 B3 引入):
  - 原 L37 孤儿 `except (AttributeError) as e:` 无配对 try + `cmd` 未定义 → 整个审计脚本
    不可 py_compile (.bak_B3_20261009 改前同样错, git 无历史 untracked 新文件)
  - 该段本意 = "扫全库裸 except: 静默吞没" (原 detail 自述), 原实现是 grep shell 命令
  - 修复: 逻辑抽成纯函数 _find_bare_except_lines (可测, 绕开 shell 转义陷阱)

seam: _find_bare_except_lines(text) 纯函数 (不扫全库, 喂受控文本)
       + system_audit_checker.py 可 py_compile (语法错根除)
"""
import os
import py_compile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAC = Path(ROOT) / "scripts" / "system_audit_checker.py"


def _bare_fn():
    """取 _find_bare_except_lines 纯函数 (不 import 全脚本触发扫描副作用)。"""
    import ast
    src = SAC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_find_bare_except_lines":
            ns = {}
            exec(compile(ast.get_source_segment(src, node), "<fn>", "exec"), ns)
            return ns["_find_bare_except_lines"]
    raise AssertionError("_find_bare_except_lines 未在 system_audit_checker.py 找到")


def test_bare_except_fn_detects_bare_only():
    """裸 `except:` 命中; `except X:` / `except (A,B):` 不误报 (静默吞没只查裸 except)。"""
    fn = _bare_fn()
    text = "\n".join([
        "def a():",           # 0
        "    try:",           # 1
        "        pass",       # 2
        "    except:",        # 3 ← 裸 except: 命中
        "        pass",       # 4
        "def b():",          # 5
        "    try:",          # 6
        "        pass",       # 7
        "    except ValueError:",   # 8 ← 特定异常, 不命中
        "        pass",
        "    except (A, B):",       # 10 ← 多异常, 不命中
        "        pass",
    ])
    hits = fn(text)
    assert hits == [3], f"应只命中裸 except: (index 3), 实际 {hits}"


def test_bare_except_fn_ignores_except_with_name():
    """except 后跟异常类名 / 注释 → 不命中。"""
    fn = _bare_fn()
    # "try:\n    pass\nexcept KeyError as e:\n    pass" → lines[2]=except KeyError (不命中) → []
    assert fn("try:\n    pass\nexcept KeyError as e:\n    pass") == []
    # "try:\n    pass\nexcept:\n    pass" → lines[2]=裸 except: 命中 → [2]
    assert fn("try:\n    pass\nexcept:\n    pass") == [2]
    # 注释不影响: `except:  # silent` 仍是裸 → [2]
    assert fn("try:\n    pass\nexcept:  # silent\n    pass") == [2]


def test_system_audit_checker_compilable():
    """根除预存 P0: system_audit_checker.py 可 py_compile (原孤儿 except 语法错)。"""
    try:
        py_compile.compile(str(SAC), doraise=True)
    except py_compile.PyCompileError as e:
        raise AssertionError(f"system_audit_checker.py 仍不可编译 (预存孤儿 except 未根除): {e}")
    # 死读串必须无残留 (B3 主修项: 嵌套 laowu.approved 死读)
    src = SAC.read_text(encoding="utf-8")
    assert ".get('laowu', {}).get('approved'" not in src, "嵌套死读 laowu.approved 残留"
