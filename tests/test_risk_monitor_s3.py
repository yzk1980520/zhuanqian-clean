#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_risk_monitor_s3.py — S3 移动止盈阶梯 + 时间止损 TDD 测试
===============================================================
验收断言见 R0 任务单：独立手判 worked-example，非重算实现
"""
import sys
import os
from datetime import date, timedelta
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from core.ops.risk_monitor import check_trailing_take_profit, check_time_stop
import core.ops.risk_monitor as rm


def test_trailing_tp_12pct_up_trend():
    """浮盈 12%、趋势 up：命中第2档(10%,0.05) → 锁止盈价=峰值×0.95；已触发档数≥2。断言非 0.15"""
    holding = {
        "code": "sh600000",
        "name": "测试股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 11.2,  # 浮盈 12%
        "peak_price": 11.2,     # 峰值价 = 当前价（创新高）
        "entry_date": "2026-01-01",
        "trend": "up",
    }
    result = check_trailing_take_profit(holding)
    print(f"Test 12% up: {result}")
    
    # 独立手判期望：
    # S3阶梯 up: [(6,0.15),(10,0.05),(15,0.07),(25,0.09),(999,0.12)]
    # 浮盈 12% ≥ 10% (第2档激活) 且 < 15% (第3档)
    # → 命中第2档，容忍 5% → 锁止盈价 = 11.2 * 0.95 = 10.64
    # 已触发档数 = 2 (6%和10%档)
    assert result["lock_price"] is not None, "应有锁止盈价"
    assert abs(result["lock_price"] - 10.64) < 0.01, f"锁价应为 10.64，实际 {result['lock_price']}"
    assert result["triggered_tiers"] >= 2, f"已触发档数应≥2，实际 {result['triggered_tiers']}"
    # 关键断言：首档容忍 15% 不应被用作锁价（防错用）
    assert abs(result["lock_price"] - 11.2 * 0.85) > 0.01, "不应用首档 15% 容忍算锁价（那是激活容，非锁价）"
    print("✅ PASS: 浮盈12%趋势up → 第2档锁价=峰值×0.95")


def test_trailing_tp_4pct_below_first_tier():
    """浮盈 4%：未达首档激活(6%) → 锁止盈价=None、未触发"""
    holding = {
        "code": "sh600000",
        "name": "测试股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 10.4,  # 浮盈 4%
        "peak_price": 10.4,
        "entry_date": "2026-01-01",
        "trend": "up",
    }
    result = check_trailing_take_profit(holding)
    print(f"Test 4%: {result}")
    
    assert result["lock_price"] is None, "未达首档激活应无锁价"
    assert result["triggered_tiers"] == 0, "未触发任何档"
    assert not result["alert_triggered"], "不应触发分批止盈告警"
    print("✅ PASS: 浮盈4% → 无锁价、未触发")


def test_trailing_tp_peak_fallback_warning():
    """缺 peak_price 字段：用当前价近似并告警"""
    holding = {
        "code": "sh600000",
        "name": "测试股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 11.2,  # 浮盈 12%
        # 无 peak_price
        "entry_date": "2026-01-01",
        "trend": "up",
    }
    result = check_trailing_take_profit(holding)
    print(f"Test no peak: {result}")
    
    # 应用当前价近似 peak，仍能计算
    assert result["lock_price"] is not None, "缺peak时用当前价近似仍应算出锁价"
    assert "peak_fallback" in result.get("warnings", []), "应有 peak_fallback 告警"
    print("✅ PASS: 缺peak字段 → 近似计算+告警")


def test_trailing_tp_exactly_6pct():
    """浮盈恰=6%：命中第1档(6%,0.15) → 锁止盈价=峰值×0.85
    两组价格量级：cost=100,peak=106 和 cost=10,peak=10.6（验证浮点容差生效）"""
    # 组1：百元股
    holding1 = {
        "code": "sh600000",
        "name": "百元股",
        "cost": 100.0,
        "shares": 100,
        "current_price": 106.0,
        "peak_price": 106.0,
        "entry_date": "2026-01-01",
        "trend": "up",
    }
    result1 = check_trailing_take_profit(holding1)
    print(f"Test exactly 6% (100→106): {result1}")
    
    assert result1["current_tier"] == 1, f"百元股恰6%应命中第1档，实际 {result1['current_tier']}"
    assert result1["lock_price"] is not None, "应有锁价"
    assert abs(result1["lock_price"] - 106.0 * 0.85) < 0.01, f"锁价应为 106*0.85=90.1，实际 {result1['lock_price']}"
    assert result1["lock_tolerance"] == 0.15, f"容忍度应为0.15，实际 {result1['lock_tolerance']}"
    
    # 组2：十元股（浮点易漏档）
    holding2 = {
        "code": "sz000001",
        "name": "十元股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 10.6,
        "peak_price": 10.6,
        "entry_date": "2026-01-01",
        "trend": "up",
    }
    result2 = check_trailing_take_profit(holding2)
    print(f"Test exactly 6% (10→10.6): {result2}")
    
    assert result2["current_tier"] == 1, f"十元股恰6%应命中第1档，实际 {result2['current_tier']}"
    assert result2["lock_price"] is not None, "应有锁价"
    assert abs(result2["lock_price"] - 10.6 * 0.85) < 0.01, f"锁价应为 10.6*0.85=9.01，实际 {result2['lock_price']}"
    assert result2["lock_tolerance"] == 0.15, f"容忍度应为0.15，实际 {result2['lock_tolerance']}"
    print("✅ PASS: 恰=6% 两组价量级均命中第1档（浮点容差生效）")


def test_trailing_tp_exactly_10pct():
    """浮盈恰=10%：命中第2档(10%,0.05) → 锁止盈价=峰值×0.95"""
    holding = {
        "code": "sh600000",
        "name": "测试股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 11.0,  # 恰 10%
        "peak_price": 11.0,
        "entry_date": "2026-01-01",
        "trend": "up",
    }
    result = check_trailing_take_profit(holding)
    print(f"Test exactly 10%: {result}")
    
    assert result["current_tier"] == 2, f"恰10%应命中第2档，实际 {result['current_tier']}"
    assert abs(result["lock_price"] - 11.0 * 0.95) < 0.01, f"锁价应为 11.0*0.95=10.45，实际 {result['lock_price']}"
    assert result["lock_tolerance"] == 0.05, f"容忍度应为0.05，实际 {result['lock_tolerance']}"
    print("✅ PASS: 恰=10% → 第2档锁价=峰值×0.95")


def test_trailing_tp_exactly_25pct():
    """浮盈恰=25%：命中第4档(25%,0.09) → 锁止盈价=峰值×0.91"""
    holding = {
        "code": "sh600000",
        "name": "测试股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 12.5,  # 恰 25%
        "peak_price": 12.5,
        "entry_date": "2026-01-01",
        "trend": "up",
    }
    result = check_trailing_take_profit(holding)
    print(f"Test exactly 25%: {result}")
    
    assert result["current_tier"] == 4, f"恰25%应命中第4档，实际 {result['current_tier']}"
    assert abs(result["lock_price"] - 12.5 * 0.91) < 0.01, f"锁价应为 12.5*0.91=11.375≈11.38，实际 {result['lock_price']}"
    assert result["lock_tolerance"] == 0.09, f"容忍度应为0.09，实际 {result['lock_tolerance']}"
    print("✅ PASS: 恰=25% → 第4档锁价=峰值×0.91")


def test_time_stop_115_days_warning():
    """entry 距今 115 交易日：剩5日≤5 → time_stop_warning=True, reached=False"""
    holding = {
        "code": "sh600000",
        "name": "测试股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 11.0,
        "entry_date": "2025-04-01",
    }
    entry = date(2025, 4, 1)
    today = date.today()
    
    # 使用 patch.object 确保 mock 自动还原
    with patch.object(rm, 'count_trading_days', side_effect=lambda s, e: 115 if s == entry and e == today else rm.count_trading_days(s, e)):
        holding["entry_date"] = entry.isoformat()
        result = check_time_stop(holding)
        print(f"Test 115 days: {result}")
        
        assert result["time_stop_warning"] is True, "剩5日应触发 warning"
        assert result["time_stop_reached"] is False, "未达120日不应 reached"
    print("✅ PASS: 115交易日 → warning 非 reached (mock已自动还原)")


def test_time_stop_120_days_reached():
    """entry 距今 120 交易日：time_stop_reached=True（含等号）"""
    holding = {
        "code": "sh600000",
        "name": "测试股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 11.0,
        "entry_date": "2025-03-01",
    }
    entry = date(2025, 3, 1)
    today = date.today()
    
    with patch.object(rm, 'count_trading_days', side_effect=lambda s, e: 120 if s == entry and e == today else rm.count_trading_days(s, e)):
        holding["entry_date"] = entry.isoformat()
        result = check_time_stop(holding)
        print(f"Test 120 days: {result}")
        
        assert result["time_stop_reached"] is True, "120日含等号应 reached"
        assert result["time_stop_warning"] is True, "120日也应 warning"
    print("✅ PASS: 120交易日 → reached+warning (mock已自动还原)")


def test_time_stop_118_days_warning():
    """entry 距今 118 交易日：剩2日≤5 → time_stop_warning（非 reached）"""
    holding = {
        "code": "sh600000",
        "name": "测试股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 11.0,
        "entry_date": "2025-04-01",
    }
    entry = date(2025, 4, 1)
    today = date.today()
    
    with patch.object(rm, 'count_trading_days', side_effect=lambda s, e: 118 if s == entry and e == today else rm.count_trading_days(s, e)):
        holding["entry_date"] = entry.isoformat()
        result = check_time_stop(holding)
        print(f"Test 118 days: {result}")
        
        assert result["time_stop_warning"] is True, "剩2日应触发 warning"
        assert result["time_stop_reached"] is False, "未达120日不应 reached"
    print("✅ PASS: 118交易日 → warning 非 reached (mock已自动还原)")


def test_time_stop_121_days_reached():
    """entry 距今 121 交易日：time_stop_reached；TIME_STOP=120 硬断言"""
    holding = {
        "code": "sh600000",
        "name": "测试股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 11.0,
        "entry_date": "2025-03-01",
    }
    entry = date(2025, 3, 1)
    today = date.today()
    
    with patch.object(rm, 'count_trading_days', side_effect=lambda s, e: 121 if s == entry and e == today else rm.count_trading_days(s, e)):
        holding["entry_date"] = entry.isoformat()
        result = check_time_stop(holding)
        print(f"Test 121 days: {result}")
        
        assert result["time_stop_reached"] is True, "超120日应 reached"
        assert result["time_stop_warning"] is True, "超120日也应 warning"
    print("✅ PASS: 121交易日 → reached (mock已自动还原)")


def test_zero_write_to_trade_data():
    """交易数据零写：跑前后 trade_log.json / holdings.json 的 mtime 不变"""
    import time
    
    trade_log_path = os.path.join(PROJECT_DIR, "data", "trade_log.json")
    holdings_path = os.path.join(PROJECT_DIR, "data", "holdings.json")
    
    mtime_trade_before = os.path.getmtime(trade_log_path)
    mtime_hold_before = os.path.getmtime(holdings_path)
    
    # 等待 1 秒确保 mtime 会变（如果被写入）
    time.sleep(1.1)
    
    # 运行检查函数
    holding = {
        "code": "sh600000",
        "name": "测试股",
        "cost": 10.0,
        "shares": 1000,
        "current_price": 11.2,
        "peak_price": 11.2,
        "entry_date": "2026-01-01",
        "trend": "up",
    }
    check_trailing_take_profit(holding)
    check_time_stop(holding)
    
    # 生成报告（会写 risk_report_latest.json，但不应碰 trade_log/holdings）
    from core.ops.risk_monitor import generate_daily_report
    generate_daily_report()
    
    mtime_trade_after = os.path.getmtime(trade_log_path)
    mtime_hold_after = os.path.getmtime(holdings_path)
    
    print(f"trade_log mtime: {mtime_trade_before} → {mtime_trade_after}")
    print(f"holdings mtime: {mtime_hold_before} → {mtime_hold_after}")
    
    assert mtime_trade_before == mtime_trade_after, "trade_log.json 被修改了！"
    assert mtime_hold_before == mtime_hold_after, "holdings.json 被修改了！"
    print("✅ PASS: 交易数据零写验证通过")


if __name__ == "__main__":
    print("=" * 60)
    print("S3 风控 TDD 测试开始")
    print("=" * 60)
    
    try:
        test_trailing_tp_12pct_up_trend()
        test_trailing_tp_4pct_below_first_tier()
        test_trailing_tp_peak_fallback_warning()
        test_trailing_tp_exactly_6pct()
        test_trailing_tp_exactly_10pct()
        test_trailing_tp_exactly_25pct()
        test_time_stop_115_days_warning()
        test_time_stop_120_days_reached()
        test_time_stop_118_days_warning()
        test_time_stop_121_days_reached()
        test_zero_write_to_trade_data()
        
        print("\n" + "=" * 60)
        print("🎉 所有测试通过！")
        print("=" * 60)
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ FAIL: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)