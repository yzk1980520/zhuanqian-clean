"""CI 环境依赖排除 (2026-10-28)

以下 scripts/ 测试因缺失本地数据文件/hermes二进制，在 CI runner 上无法运行。
恢复条件: 模块迁入仓库或路径相对化后移除对应条目。
"""
import os

_ci_ignore = [
    "test_dispatch_audit_check.py",
    "test_ic_monitor_coverage.py",
    "test_p1c_runbook_path.py",
    "test_self_heal_p04_threshold.py",
    "test_self_heal_recheck.py",
]

def pytest_collection_modifyitems(items):
    """Skip environment-dependent test files in CI."""
    skip_names = set(_ci_ignore)
    for item in list(items):
        path = item.fspath.relto(os.path.dirname(__file__)) if item.fspath.contains(os.path.dirname(__file__)) else None
        if path and path.name in skip_names:
            item.add_marker(__import__('pytest').mark.skip(
                reason="CI 环境依赖: 缺失本地数据文件/hermes二进制"))
            items.remove(item)
