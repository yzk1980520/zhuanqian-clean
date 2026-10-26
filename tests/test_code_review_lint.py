"""
test_code_review_lint.py — CR-01/CR-02/CR-03/CR-04 单元测试

覆盖 CR-01 盲区修复（2026-10-16）：
- 单语句体 except: pass 漏检（原盲点）
- except: continue 漏检（原盲点）
- 单行形式 except: pass 漏检（原盲点）
"""
import ast
import pytest
from scripts.code_review_lint import check_cr01, check_cr02, check_cr03, check_cr04, _is_silent_except_body


# ── CR-01: 异常吞噬 ──────────────────────────────────────────────────────────

class TestCR01SilentBody:
    """_is_silent_except_body 单元测"""

    def test_empty_body(self):
        assert _is_silent_except_body([]) is True

    def test_single_pass(self):
        assert _is_silent_except_body([ast.Pass()]) is True

    def test_single_continue(self):
        assert _is_silent_except_body([ast.Continue()]) is True

    def test_multi_pass_only(self):
        assert _is_silent_except_body([ast.Pass(), ast.Pass()]) is True

    def test_pass_plus_continue(self):
        assert _is_silent_except_body([ast.Pass(), ast.Continue()]) is True

    def test_with_real_statement(self):
        log_call = ast.Expr(value=ast.Call(
            func=ast.Name(id="print", ctx=ast.Load()),
            args=[ast.Constant(value="err")], keywords=[]
        ))
        assert _is_silent_except_body([ast.Pass(), log_call]) is False

    def test_with_raise(self):
        raise_node = ast.Raise(exc=ast.Name(id="ValueError", ctx=ast.Load()))
        assert _is_silent_except_body([raise_node]) is False

    def test_with_return(self):
        ret = ast.Return(value=ast.Constant(value=42))
        assert _is_silent_except_body([ret]) is False


class TestCR01Detection:
    """check_cr01 端到端检测"""

    def _findings(self, code):
        tree = ast.parse(code)
        findings = []
        check_cr01(tree, "test.py", findings)
        return findings

    def test_single_line_except_pass(self):
        """Case: except: pass（单行形式）→ 应报"""
        code = """
def f():
    try: do_something()
    except: pass
"""
        findings = self._findings(code)
        assert len(findings) >= 1
        assert any("pass/continue" in f[4] for f in findings)

    def test_multiline_except_pass_single(self):
        """Case: 多行 except 仅 pass → 应报"""
        code = """
def f():
    try:
        do_something()
    except:
        pass
"""
        findings = self._findings(code)
        assert len(findings) >= 1
        assert any("pass/continue" in f[4] for f in findings)

    def test_except_continue(self):
        """Case: except: continue → 应报（新盲点）"""
        code = """
def f():
    for i in range(10):
        try:
            do_something()
        except: continue
"""
        findings = self._findings(code)
        assert len(findings) >= 1
        assert any("pass/continue" in f[4] for f in findings)

    def test_except_return_none(self):
        """Case: except: return None → 应报"""
        code = """
def f():
    try:
        do_something()
    except:
        return None
"""
        findings = self._findings(code)
        assert len(findings) >= 1
        assert any("return" in f[4] for f in findings)

    def test_except_return_empty_list(self):
        """Case: except: return [] → 应报"""
        code = """
def f():
    try:
        do_something()
    except:
        return []
"""
        findings = self._findings(code)
        assert len(findings) >= 1

    def test_except_return_false(self):
        """Case: except: return False → 应报"""
        code = """
def f():
    try:
        do_something()
    except:
        return False
"""
        findings = self._findings(code)
        assert len(findings) >= 1

    def test_except_return_zero(self):
        """Case: except: return 0 → 应报"""
        code = """
def f():
    try:
        do_something()
    except:
        return 0
"""
        findings = self._findings(code)
        assert len(findings) >= 1

    def test_valid_except_with_raise(self):
        """Case: except 有实质处理 → 不应报"""
        code = """
def f():
    try:
        do_something()
    except ValueError:
        raise
"""
        findings = self._findings(code)
        cr01 = [f for f in findings if f[2] == "CR-01"]
        assert len(cr01) == 0

    def test_valid_except_with_log(self):
        """Case: except 记录日志 → 不应报"""
        code = """
def f():
    try:
        do_something()
    except Exception as e:
        log_error(e)
"""
        findings = self._findings(code)
        cr01 = [f for f in findings if f[2] == "CR-01"]
        assert len(cr01) == 0

    def test_valid_except_pass_with_log(self):
        """Case: except 含 pass + 实质语句 → 不应报（pass 是辅助）"""
        code = """
def f():
    try:
        do_something()
    except:
        pass
        log_error()
"""
        findings = self._findings(code)
        cr01 = [f for f in findings if f[2] == "CR-01"]
        assert len(cr01) == 0

    def test_bare_except_no_handler(self):
        """Case: bare except（无 as 变量）仅 pass → 应报"""
        code = """
def f():
    try:
        do_something()
    except:
        pass
"""
        findings = self._findings(code)
        assert len(findings) >= 1


# ── CR-02: 数据直写 ─────────────────────────────────────────────────────────

class TestCR02:
    def _findings(self, code):
        tree = ast.parse(code)
        findings = []
        check_cr02(tree, "test.py", findings)
        return findings

    def test_data_path_write(self):
        code = 'open("data/some_file.json", "w")'
        findings = self._findings(code)
        assert len(findings) >= 1
        assert findings[0][2] == "CR-02"

    def test_valid_read(self):
        code = 'open("data/some_file.json", "r")'
        findings = self._findings(code)
        cr02 = [f for f in findings if f[2] == "CR-02"]
        assert len(cr02) == 0


# ── CR-03: 超长函数 ─────────────────────────────────────────────────────────

class TestCR03:
    def _findings(self, code, n_lines):
        tree = ast.parse(code)
        findings = []
        check_cr03(tree, "test.py", findings, n_lines)
        return findings

    def test_long_function(self):
        code = "def f():\n" + "    x = 1\n" * 81
        findings = self._findings(code, 82)
        cr03 = [f for f in findings if f[2] == "CR-03"]
        assert len(cr03) >= 1

    def test_short_function(self):
        code = "def f():\n    return 1\n"
        findings = self._findings(code, 3)
        cr03 = [f for f in findings if f[2] == "CR-03"]
        assert len(cr03) == 0


# ── CR-04: TODO/FIXME 未登记 ─────────────────────────────────────────────────

class TestCR04:
    def _findings(self, src):
        findings = []
        check_cr04(src, "test.py", findings)
        return findings

    def test_todo_without_debt_id(self):
        src = "# TODO fix this\n"
        findings = self._findings(src)
        assert len(findings) >= 1
        assert findings[0][2] == "CR-04"

    def test_todo_with_debt_id(self):
        src = "# TODO DEBT-ID-001 fix this\n"
        findings = self._findings(src)
        cr04 = [f for f in findings if f[2] == "CR-04"]
        assert len(cr04) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
