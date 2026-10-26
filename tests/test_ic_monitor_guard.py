# -*- coding: utf-8 -*-
"""IC 监控假绿守卫回归 (老三 2026-09-27, 台账C件2, 交@laowu验收)。

老五验收口径: "改回假绿 exit=0 会被回归打回"——锁死 decide_exit_code() 三态:
  ① 全因子无有效IC(n_valid==0)  → exit=4 (假绿守卫: 监控未真正工作, 绝不视为无告警)
  ② 有因子告警(alerts非空)       → exit=3 (需人工复核)
  ③ 至少一因子产出非None IC 且无告警 → exit=0

被测函数 = scripts/factor_ic_monitor_20d.decide_exit_code (纯函数, 老五③升级后从main抽出)。
注意: 该模块顶层有 import backtest + os.chdir, 故 import 前后保存/恢复 cwd 防污染其它测试。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".scratch"))  # [t_laosan_c1_test_alignment] 2026-10-23 归档后 .scratch 已无 factor_ic_scan 源, 此 path 项为无害残留


def _decide():
    """惰性 import(仅一次), 隔离模块顶层 chdir + 防 factor_ic_monitor_20d 顶层 argv[1] 窗口日解析在 pytest 下崩。"""
    cwd = os.getcwd()
    m = sys.modules.get("factor_ic_monitor_20d")
    if m is None:
        saved_argv = sys.argv
        sys.argv = [sys.argv[0]]  # 使 factor_ic_monitor_20d 顶层 "if len(argv)>1" 走默认窗口分支
        try:
            import factor_ic_monitor_20d as m
        finally:
            sys.argv = saved_argv
            os.chdir(cwd)
    return m.decide_exit_code


class TestFakeGreenGuard:
    def test_fake_green_returns_4(self):
        """① 假绿: 全因子样本不足(无 rolling20_ic_mean)且无告警 → 必须 exit=4, 不得=0。"""
        d = _decide()
        out = {'f1': {'status': '样本不足', 'n_sections': 0}}
        assert d(out, []) == 4, "全因子无有效IC是假绿, 必须=4 (老五P0判据)"

    def test_no_alert_with_valid_ic_returns_0(self):
        """③ 正常: 至少一因子有有效IC且无告警 → exit=0。"""
        d = _decide()
        out = {'f1': {'rolling20_ic_mean': 0.05, 'alert': False}}
        assert d(out, []) == 0, "有有效IC无告警应=0"

    def test_alert_returns_3(self):
        """② 告警: 有因子告警 → exit=3 (需人工复核)。"""
        d = _decide()
        out = {'f1': {'rolling20_ic_mean': 0.02, 'alert': True}}
        assert d(out, ['f1']) == 3, "有告警应=3, 优先级高于假绿判定"

    def test_alert_takes_precedence_over_fake_green(self):
        """优先级: 有告警时即便全因子无有效IC也=3(告警优先), 不是4。"""
        d = _decide()
        out = {'f1': {'status': '样本不足', 'n_sections': 0}}
        assert d(out, ['f1']) == 3, "alerts 非空优先于假绿=4"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
