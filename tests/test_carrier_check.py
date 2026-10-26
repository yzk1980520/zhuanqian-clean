# P-B1 对照组测试 (P-C2 纪律): carrier_check 断言有效性证明
import contextlib
import importlib.util
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
spec = importlib.util.spec_from_file_location("cc", os.path.join(ROOT, "scripts", "carrier_check.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
orig = m.query_tasks


def run_with(fake):
    m.query_tasks = lambda: (fake, None)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = m.main()
    m.query_tasks = orig
    return rc


# 1. 损坏 action (空格路径拆分): 必须 P0
rc = run_with([{"TaskName": "Zhuanqian_BrokenTest", "State": "Ready",
                "Execute": "D:\\open", "Arguments": "code\\zhuanqian\\scripts\\x.bat"}])
print("对照1 损坏action:", "PASS(rc=1)" if rc == 1 else "FAIL(未命中)")

# 2. 任务 Disabled: 必须 P0
rc = run_with([{"TaskName": "Zhuanqian_X", "State": "Disabled",
                "Execute": "wscript.exe", "Arguments": '"D:\\open code\\zhuanqian\\scripts\\x.vbs"'}])
print("对照2 Disabled  :", "PASS(rc=1)" if rc == 1 else "FAIL(未命中)")

# 3. 引用脚本不存在: 必须 P1
rc = run_with([{"TaskName": "Zhuanqian_Y", "State": "Ready",
                "Execute": "wscript.exe", "Arguments": '"D:\\open code\\zhuanqian\\scripts\\ghost_2026.vbs"'}])
print("对照3 脚本缺失   :", "PASS(rc=1)" if rc == 1 else "FAIL(未命中)")

# 4. 全健康: 必须 rc=0
rc = run_with([{"TaskName": "Zhuanqian_OK", "State": "Ready",
                "Execute": "wscript.exe", "Arguments": '"D:\\open code\\zhuanqian\\scripts\\run_path_hidden.vbs"'}])
print("对照4 全健康     :", "PASS(rc=0)" if rc == 0 else f"FAIL(rc={rc})")

# 5. 写侧新鲜度 (stats 缺 run_at / 不存在文件): 临时改规则验证
m.FRESHNESS_RULES["Zhuanqian_OK"] = ("data/nonexistent_stats_2026.json", 1, "run_at")
rc = run_with([{"TaskName": "Zhuanqian_OK", "State": "Ready",
                "Execute": "wscript.exe", "Arguments": '"D:\\open code\\zhuanqian\\scripts\\run_path_hidden.vbs"'}])
print("对照5 新鲜度停更 :", "PASS(rc=1)" if rc == 1 else "FAIL(未命中)")
