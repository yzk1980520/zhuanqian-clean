# -*- coding: utf-8 -*-
"""
持仓与交易记录一致性测试
"""

import json
import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent / 'data'


def load_json(filename):
    filepath = BASE_DIR / filename
    with open(filepath, encoding='utf-8') as f:
        return json.load(f)


def test_holdings_structure():
    """测试holdings.json结构完整性"""
    data = load_json('holdings.json')
    
    required_fields = ['holdings', 'available_cash', 'total_assets', 'position_ratio', 'updated_at']
    for field in required_fields:
        assert field in data, f"缺失字段: {field}"
    
    # 验证数据类型
    assert isinstance(data['holdings'], list), "holdings应为列表"
    assert isinstance(data['available_cash'], (int, float)), "available_cash应为数字"
    assert isinstance(data['total_assets'], (int, float)), "total_assets应为数字"
    
    print("✅ test_holdings_structure 通过")


def test_assets_balance():
    """验证总资产平衡"""
    data = load_json('holdings.json')

    # 总资产 = 可用现金 + 持仓市值（有持仓时不相等是正常的）
    total_value = data['available_cash']
    for h in data.get('holdings', []):
        total_value += h.get('position_value', 0)

    assert abs(data['total_assets'] - total_value) < 1.0, \
        f"总资产({data['total_assets']}) != 可用现金+持仓市值({total_value:.2f})"

    print("✅ test_assets_balance 通过")


def test_trade_log_structure():
    """测试trade_log.json结构"""
    data = load_json('trade_log.json')
    
    assert 'trades' in data, "缺失字段: trades"
    assert isinstance(data['trades'], list), "trades应为列表"
    
    # 验证最新交易
    if data['trades']:
        latest = data['trades'][-1]
        assert 'trade_id' in latest, "交易记录缺失trade_id"
        assert 'date' in latest, "交易记录缺失date"
        assert 'code' in latest, "交易记录缺失code"
        assert 'action' in latest, "交易记录缺失action"
    
    print("✅ test_trade_log_structure 通过")


def test_cooldown_tracking():
    """测试冷却期追踪"""
    cooldown_file = BASE_DIR / 'cooldown.json'

    if cooldown_file.exists():
        data = json.load(open(cooldown_file, encoding='utf-8'))
        # 冷却期记录可能为空（新持仓或刚重置）
        if data and data.get('stock_code'):
            assert 'stock_code' in data, "冷却期记录缺失stock_code"
            assert 'cooldown_end_date' in data, "冷却期记录缺失cooldown_end_date"
            print("✅ test_cooldown_tracking 通过")
        else:
            print("⚠️ test_cooldown_tracking: 冷却期记录为空（当前无冷却需求）")
    else:
        print("⚠️ 冷却期文件不存在（首次交易前正常）")


def test_date_format():
    """测试日期格式统一性"""
    holdings = load_json('holdings.json')
    trade_log = load_json('trade_log.json')

    # holdings.updated_at 可以是 ISO 8601 或 YYYY-MM-DD HH:MM:SS
    updated_at = holdings.get('updated_at', '')
    assert updated_at and len(updated_at) >= 10, \
        f"holdings.updated_at 不能为空，实际为: {updated_at}"

    # trade_log中的date应为YYYY-MM-DD
    for trade in trade_log.get('trades', []):
        date_str = trade.get('date', '')
        if len(date_str) == 10:
            assert date_str[4] == '-', \
                f"trade.date 格式不规范: {date_str}"

    print("✅ test_date_format 通过")


def test_no_duplicate_holdings():
    """验证无重复持仓"""
    holdings = load_json('holdings.json')
    
    codes = [h['code'] for h in holdings['holdings']]
    assert len(codes) == len(set(codes)), "存在重复持仓代码"
    
    print("✅ test_no_duplicate_holdings 通过")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("持仓与交易记录一致性测试")
    print("=" * 60)
    
    tests = [
        test_holdings_structure,
        test_assets_balance,
        test_trade_log_structure,
        test_cooldown_tracking,
        test_date_format,
        test_no_duplicate_holdings,
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
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    exit(0 if success else 1)
