# -*- coding: utf-8 -*-
"""
系统节点统一性测试
"""

import json
import os
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'


def load_json(filename):
    filepath = DATA_DIR / filename
    with open(filepath, encoding='utf-8') as f:
        return json.load(f)


def test_holdings_data_integrity():
    """测试持仓数据完整性"""
    data = load_json('holdings.json')
    
    # 必需字段（schema来自atomic_json写入标准，不含冗余updated）
    required_fields = ['holdings', 'available_cash', 'total_assets', 'position_ratio', 'updated_at']
    for field in required_fields:
        assert field in data, f"holdings.json 缺失字段: {field}"
    
    # 类型检查
    assert isinstance(data['holdings'], list), "holdings 应为列表"
    assert isinstance(data['available_cash'], (int, float)), "available_cash 应为数字"
    assert isinstance(data['total_assets'], (int, float)), "total_assets 应为数字"
    assert isinstance(data['position_ratio'], (int, float)), "position_ratio 应为数字"
    
    # 数据一致性：总资产应等于可用现金（空仓时）
    if len(data['holdings']) == 0:
        assert abs(data['total_assets'] - data['available_cash']) < 0.01, \
            f"空仓时总资产({data['total_assets']})应等于可用现金({data['available_cash']})"
    
    print("✅ test_holdings_data_integrity 通过")


def test_trade_log_structure():
    """测试交易记录结构"""
    data = load_json('trade_log.json')
    
    # 必需字段
    assert 'trades' in data, "trade_log.json 缺失 trades 字段"
    assert isinstance(data['trades'], list), "trades 应为列表"
    
    # 检查最近一条交易记录
    if data['trades']:
        latest = data['trades'][-1]
        required_keys = ['trade_id', 'date', 'code', 'name', 'action', 'shares', 'price']
        for key in required_keys:
            assert key in latest, f"交易记录缺失字段: {key}"
        
        # 检查永鼎卖出记录
        yongding_sells = [t for t in data['trades'] if '600105' in t.get('code', '') and t.get('action') == 'sell']
        assert len(yongding_sells) > 0, "应存在永鼎股份卖出记录"
        
        # 验证成交价格（允许0.01误差）
        sell = yongding_sells[-1]
        price = float(sell.get('price', 0))
        assert abs(price - 44.86) < 0.05, f"永鼎卖出价格应为约44.86，实际为{price}"
        profit = float(sell.get('profit_pct', 0))
        assert abs(profit - (-1.84)) < 0.05, f"永鼎盈亏应为约-1.84%，实际为{profit}%"
    
    print("✅ test_trade_log_structure 通过")


def test_cooldown_tracking():
    """测试冷却期追踪"""
    cooldown_file = DATA_DIR / 'cooldown.json'

    if not cooldown_file.exists():
        print("⚠️ test_cooldown_tracking: cooldown.json 不存在（首次交易前正常）")
        return

    data = json.load(open(cooldown_file, encoding='utf-8'))

    # 冷却期记录可能为空（新持仓或刚重置）
    if data and data.get('stock_code'):
        assert 'stock_code' in data, "冷却期记录缺失stock_code"
        assert 'cooldown_end_date' in data, "冷却期记录缺失cooldown_end_date"
        print("✅ test_cooldown_tracking 通过")
    else:
        print("⚠️ test_cooldown_tracking: 冷却期记录为空（当前无冷却需求）")


def test_date_format_consistency():
    """测试日期格式一致性"""
    holdings = load_json('holdings.json')
    trade_log = load_json('trade_log.json')

    # holdings.updated_at 可以是 ISO 8601 或 YYYY-MM-DD HH:MM:SS
    updated_at = holdings.get('updated_at', '')
    assert updated_at and len(updated_at) >= 10, \
        f"holdings.updated_at 不能为空，实际为: {updated_at}"

    # trade_log 中的 date 字段应为 YYYY-MM-DD
    for trade in trade_log.get('trades', []):
        date_str = trade.get('date', '')
        if len(date_str) == 10:
            assert date_str[4] == '-', \
                f"trade.date 格式不规范: {date_str}"

    print("✅ test_date_format_consistency 通过")


def test_no_duplicate_holdings():
    """测试无重复持仓"""
    holdings = load_json('holdings.json')
    
    codes = [h['code'] for h in holdings.get('holdings', [])]
    assert len(codes) == len(set(codes)), f"存在重复持仓代码: {codes}"
    
    print("✅ test_no_duplicate_holdings 通过")


def test_risk_rules_parameters():
    """测试风控参数一致性 (C3-1 R0裁定 2026-10-24: 禁对shim文本做字面串匹配)

    根级 risk_rules.py 是S6透明代理shim(已无 'X = 值' 字面定义), 串匹配恒FAIL。
    改断运行时常量: 经根级shim(透明代理)读真源 core/risk/risk_rules_impl.py,
    monkeypatch/属性patch语义亦经代理get/set转发到实现模块, 口径唯一。
    """
    import sys
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

    import risk_rules  # 根级shim → 真源 core/risk/risk_rules_impl.py

    assert risk_rules.TIME_STOP_TRADING_DAYS == 120, \
        f"TIME_STOP_TRADING_DAYS 应为120 (2026-09-06延长至120日), 实际 {risk_rules.TIME_STOP_TRADING_DAYS}"
    assert risk_rules.CHASE_BAN_PCT == 4.0, \
        f"CHASE_BAN_PCT 应为4.0 (2026-08-16拍板/2026-09-25口径统一), 实际 {risk_rules.CHASE_BAN_PCT}"
    assert hasattr(risk_rules, "TREND_TP_LADDER"), "应定义 TREND_TP_LADDER (S3移动止盈阶梯)"
    stop_loss = risk_rules.STRATEGY_STOP_LOSS_PCT
    assert isinstance(stop_loss, dict) and stop_loss, "STRATEGY_STOP_LOSS_PCT 应为非空dict"
    assert all(v == 0.1 for v in stop_loss.values()), \
        f"全策略止损应统一0.1 (2026-09-30三方会签8%→10%), 实际 {stop_loss}"

    print("✅ test_risk_rules_parameters 通过 (真源运行时常量: 120日/4.0%/TREND_TP_LADDER/止损全0.1)")


def test_cron_jobs_status():
    """测试Cron Jobs状态"""
    cron_file = Path('D:/Hermes agent/Hermes Agent CN Desktop/data/hermes-home/cron/jobs.json')
    
    if not cron_file.exists():
        print("⚠️ test_cron_jobs_status: jobs.json 不存在")
        return
    
    with open(cron_file, encoding='utf-8') as f:
        data = json.load(f)
    
    jobs = data.get('jobs', [])
    
    # 检查关键任务是否存在
    # jobs.json实际只有"每周三方复盘会"任务（总管配置）
    required_jobs = ['每周三方复盘会']
    job_names = [j.get('name', '') for j in jobs]

    for required in required_jobs:
        assert any(required in name for name in job_names), f"缺少关键任务: {required}"
    
    # 检查无致命错误
    fatal_errors = [j for j in jobs if j.get('last_error') and 'fatal' in j.get('last_error', '').lower()]
    assert len(fatal_errors) == 0, f"存在{len(fatal_errors)}个致命错误"
    
    print(f"✅ test_cron_jobs_status 通过 ({len(jobs)} 个任务)")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("系统节点统一性测试")
    print("=" * 60)
    
    tests = [
        test_holdings_data_integrity,
        test_trade_log_structure,
        test_cooldown_tracking,
        test_date_format_consistency,
        test_no_duplicate_holdings,
        test_risk_rules_parameters,
        test_cron_jobs_status,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: 意外错误 - {e}")
            failed += 1
    
    print("=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    exit(0 if success else 1)
