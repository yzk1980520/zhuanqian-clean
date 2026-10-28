"""CI 环境依赖排除 (2026-10-28)

以下 scripts/ 测试因缺失本地数据文件/hermes二进制，在 CI runner 上无法运行。
恢复条件: 模块迁入仓库或路径相对化后移除对应条目。
"""
import os
import pytest

_ci_ignore = {
    "test_dispatch_audit_check.py",
    "test_ic_monitor_coverage.py",
    "test_p1c_runbook_path.py",
    "test_self_heal_p04_threshold.py",
    "test_self_heal_recheck.py",
}

def pytest_collection_modifyitems(items):
    """Skip environment-dependent test files in CI."""
    for item in list(items):
        # item.nodeid looks like "scripts/test_p1c_runbook_path.py::TestX::test_y"
        path_part = item.nodeid.split("::")[0]
        filename = os.path.basename(path_part)
        if filename in _ci_ignore:
            item.add_marker(pytest.mark.skip(
                reason="CI 环境依赖: 缺失本地数据文件/hermes二进制"))
            items.remove(item)
