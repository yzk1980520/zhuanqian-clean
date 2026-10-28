# CI 环境依赖排除 (2026-10-28)
# 以下 scripts/ 测试因缺失本地数据文件/hermes二进制，在 CI runner 上无法运行
collect_ignore = [
    "test_dispatch_audit_check.py",
    "test_ic_monitor_coverage.py",
    "test_p1c_runbook_path.py",
    "test_self_heal_p04_threshold.py",
    "test_self_heal_recheck.py",
]
