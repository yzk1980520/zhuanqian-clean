#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IC监控 + 复杂度检查 自动化运行脚本
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_ic_check():
    """运行IC质量检查"""

    result = subprocess.run(
        [sys.executable, 'scripts/factor_ic_recompute.py'],
        capture_output=True,
        text=True,
        timeout=60
    )
    return result.returncode == 0


def run_complexity_check():
    """运行复杂度检查（简化版，仅检查关键文件）"""

    # 简化检查：验证关键脚本语法正确
    try:
        import py_compile
        py_compile.compile('integrated_picker.py', doraise=True)
        py_compile.compile('backtest/backtest_rotation.py', doraise=True)
        return True
    except py_compile.PyCompileError as e:
        print(f"  ❌ 语法错误: {e}")
        return False


def run_tests():
    """运行测试套件（门禁快档, 2026-10-26 t_81fad29b P3: pytest 门禁快档）。

    快档 = `pytest tests/ -q -m "not slow and not backtest"`（97项重件已挂
    @pytest.mark.slow / @pytest.mark.backtest, 见
    docs/pytest_timeout_investigation_20261025.md §5.2 落地）, 稳进 180s 预算。
    重件走全量/夜间档（scripts/pytest_full_nightly.py, 夜间 cron 无预算约束）。
    只改调用面 marker 过滤, 断言语义零改动。
    """

    # 门禁快档：排除重件（slow/backtest 族）, 180s 预算内必达
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/', '-q', '--tb=line',
         '-m', 'not slow and not backtest'],
        capture_output=True,
        text=True,
        timeout=180
    )
    # 显示最后测试结果摘要
    lines = result.stdout.split('\n')
    for line in lines[-10:]:
        if 'passed' in line or 'failed' in line or 'error' in line:
            print(line)
    return result.returncode == 0


def generate_summary(ic_ok, complexity_ok, tests_ok):
    """生成执行摘要"""
    summary = {
        'timestamp': datetime.now().isoformat(),
        'ic_quality': 'PASS' if ic_ok else 'FAIL',
        'complexity': 'PASS' if complexity_ok else 'FAIL',
        'tests': 'PASS' if tests_ok else 'FAIL',
        'overall': 'PASS' if (ic_ok and complexity_ok and tests_ok) else 'FAIL'
    }
    
    for key, value in summary.items():
        print(f"  {key}: {value}")
    
    # 保存报告
    report_path = Path('data/daily_monitor_report.json')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"\n报告已保存: {report_path}")
    return summary


def main():
    """主函数"""
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 运行各项检查
    ic_ok = run_ic_check()
    complexity_ok = run_complexity_check()
    tests_ok = run_tests()
    
    # 生成摘要
    summary = generate_summary(ic_ok, complexity_ok, tests_ok)
    
    # 返回退出码
    sys.exit(0 if summary['overall'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
