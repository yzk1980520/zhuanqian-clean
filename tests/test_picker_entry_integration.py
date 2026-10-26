#!/usr/bin/env python3
"""
test_picker_entry_integration.py: 选股入口集成测试
测试边界（Seams）:
  - run_integrated_picker() → 返回候选池
  - check_position_for_pick(project_path) → 持仓检查
  - check_cooldown_for_pick(project_path) → 冷却期检查
"""
import sys
import os
import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPositionCheck:
    """持仓检查测试（public seam: check_position_for_pick）"""

    # 2026-10-24 T051 C4 对齐: check_position_for_pick()/check_cooldown_for_pick() 为 0 参签名
    # (P0#1 修复后, PROJECT 读模块级/动态模块属性), 旧 (project_path) 传参口径已失效 →
    # 改 monkeypatch 模块 PROJECT 指向 tmp_path (测试侧对齐真源签名)。

    def test_empty_position_allows_pick(self, tmp_path, monkeypatch):
        """测试: 空仓时应允许选股"""
        import core.pipeline.integrated_picker as ip

        holdings_file = tmp_path / "data" / "holdings.json"
        holdings_file.parent.mkdir(parents=True, exist_ok=True)
        holdings_file.write_text(json.dumps({"holdings": []}), encoding="utf-8")

        monkeypatch.setattr(ip, "PROJECT", str(tmp_path))
        allow, count, msg = ip.check_position_for_pick()
        assert allow == True, f"空仓应允许选股, 实际: {msg}"
        assert count == 0
        assert "空仓" in msg or "无持仓" in msg

    def test_having_position_blocks_pick(self, tmp_path, monkeypatch):
        """测试: 有持仓时应阻止选股"""
        import core.pipeline.integrated_picker as ip

        holdings_file = tmp_path / "data" / "holdings.json"
        holdings_file.parent.mkdir(parents=True, exist_ok=True)
        holdings_file.write_text(
            json.dumps({"holdings": [{"code": "600000", "name": "测试", "shares": 100}]},
                       ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(ip, "PROJECT", str(tmp_path))
        allow, count, msg = ip.check_position_for_pick()
        assert allow == False, f"有持仓应阻止选股, 实际: {msg}"
        assert count == 1
        assert "有持仓" in msg

    def test_no_holdings_file_allows_pick(self, tmp_path, monkeypatch):
        """测试: 无持仓文件时应允许选股"""
        import core.pipeline.integrated_picker as ip
        # 不创建 holdings.json
        monkeypatch.setattr(ip, "PROJECT", str(tmp_path))
        allow, count, msg = ip.check_position_for_pick()
        assert allow == True, f"无持仓文件应允许选股, 实际: {msg}"
        assert count == 0


class TestCooldownCheck:
    """冷却期检查测试（public seam: check_cooldown_for_pick）"""

    def test_cooldown_config_value(self):
        """测试: 冷却期配置应为5天"""
        from core.pipeline.integrated_picker import COOLDOWN_DAYS
        assert COOLDOWN_DAYS == 5, f"冷却期应为5天, 实际{COOLDOWN_DAYS}天"

    def test_recent_entry_in_cooldown(self, tmp_path, monkeypatch):
        """测试: 刚买入的股票应处于冷却期"""
        import core.pipeline.integrated_picker as ip
        # 2026-10-24 T051 C4 对齐: 0 参签名 + monkeypatch 模块 PROJECT

        # 模拟今日买入 (0 天 < 5 天冷却期)
        entry_date = date.today().isoformat()

        holdings_file = tmp_path / "data" / "holdings.json"
        holdings_file.parent.mkdir(parents=True, exist_ok=True)
        holdings_file.write_text(json.dumps({
            "holdings": [{"code": "600000", "entry_date": entry_date, "shares": 100}]
        }, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(ip, "PROJECT", str(tmp_path))
        allow, days, msg = ip.check_cooldown_for_pick()
        assert allow == False, "3天内应处于冷却期"
        assert days < 5

    def test_old_entry_exits_cooldown(self, tmp_path, monkeypatch):
        """测试: 超过冷却期的股票不应阻止选股"""
        import core.pipeline.integrated_picker as ip
        # 2026-10-24 T051 C4 对齐: 0 参签名 + monkeypatch 模块 PROJECT

        # 模拟10天前买入（超过5天冷却期）
        entry_date = (date.today() - timedelta(days=10)).isoformat()

        holdings_file = tmp_path / "data" / "holdings.json"
        holdings_file.parent.mkdir(parents=True, exist_ok=True)
        holdings_file.write_text(json.dumps({
            "holdings": [{"code": "600000", "entry_date": entry_date, "shares": 100}]
        }, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(ip, "PROJECT", str(tmp_path))
        allow, days, msg = ip.check_cooldown_for_pick()
        assert allow == True, f"10天前买入应已结束冷却期, 实际: {msg}"
        assert days >= 5


class TestPickerConfigConstants:
    """选股配置常量验证"""

    def test_enable_gap_strategy_default(self):
        """测试: 断层策略默认关闭"""
        from core.pipeline.integrated_picker import ENABLE_GAP_STRATEGY
        assert ENABLE_GAP_STRATEGY == False

    def test_enable_ic_monitor_default(self):
        """测试: IC监控默认开启"""
        from core.pipeline.integrated_picker import ENABLE_IC_MONITOR
        assert ENABLE_IC_MONITOR == True

    def test_financial_top_n_range(self):
        """测试: 财务过滤范围在合理区间"""
        from core.pipeline.integrated_picker import FINANCIAL_TOP_N
        assert 50 <= FINANCIAL_TOP_N <= 500, f"FINANCIAL_TOP_N应在50-500之间, 实际{FINANCIAL_TOP_N}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
