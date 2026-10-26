#!/usr/bin/env python3
"""
持仓止损止盈策略执行器（2026-09-18 修复版）
遵循 P17/P18 统一规则：
- 硬止损 8%
- 分级移动止盈 TRAIL_STOP_LADDER {0.1:0.06, 0.2:0.08, 0.4:0.1, 1.0:0.12}
- 时间止损 120日
"""
import json, os, sys
from datetime import datetime, timedelta

TRAIL_STOP_LADDER = {0.1: 0.06, 0.2: 0.08, 0.4: 0.1, 1.0: 0.12}
HARD_STOP = -0.08
TIME_STOP = 120

def calc_hard_stop(cost, ratio=HARD_STOP):
    """计算硬止损价"""
    if cost <= 0:
        return 0
    return round(cost * (1 + ratio), 2)

def calc_trailing_stop(cost, current):
    """计算移动止损价"""
    if cost <= 0 or current <= 0:
        return 0
    pnl = (current - cost) / cost
    if pnl <= 0:
        return calc_hard_stop(cost)
    # 找到对应梯回撤
    trail = TRAIL_STOP_LADDER[min(TRAIL_STOP_LADDER)]
    for up_to in sorted(TRAIL_STOP_LADDER):
        if pnl >= up_to:
            trail = TRAIL_STOP_LADDER[up_to]
    return round(current * (1 - trail), 2)

def calc_take_profits(cost, ratios=(0.10, 0.20, 0.25)):
    """计算止盈目标"""
    if cost <= 0:
        return [0, 0, 0]
    return [round(cost * (1 + r), 2) for r in ratios]

def calc_time_stop(entry_date, asof_date=None, max_days=TIME_STOP):
    """计算是否触发时间止损。
    entry_date 解析失败时 loud fail（抛 ValueError），禁止静默返回 False 掩盖缺陷。
    """
    if isinstance(entry_date, str):
        try:
            entry_date = datetime.strptime(entry_date, "%Y-%m-%d").date()
        except Exception as e:
            # loud fail(2026-10-17 修): 原为 print + return False。
            # 静默返回 False 意味着"未触发时间止损", 而真实情况是"根本算不出来" ——
            # 这是一个**方向性谎言**: 该被时间止损卖出的仓位会继续持有, 且无任何告警。
            # 实测这是 data/message_queue.json 里那条"时间止损日期解析失败"告警卡住不发的源头。
            # 调用方仅测试(无生产调用方), 故改为抛错不影响主链路。
            raise ValueError(f"entry_date 解析失败: {entry_date!r} (期望格式 %Y-%m-%d)") from e
    asof = asof_date or datetime.now().date()
    if isinstance(asof, str):
        asof = datetime.strptime(asof, "%Y-%m-%d").date()
    return (asof - entry_date).days >= max_days

def analyze_position(cost, shares, current, entry_date=None, asof_date=None):
    """分析持仓状态"""
    if not cost or cost <= 0 or not shares or shares <= 0:
        return {'error': 'invalid input'}
    total_cost = cost * shares
    market_value = current * shares
    pnl = (current - cost) / cost
    pnl_value = (current - cost) * shares
    hard = calc_hard_stop(cost)
    trailing = calc_trailing_stop(cost, current)
    tps = calc_take_profits(cost)
    time_stop = calc_time_stop(entry_date, asof_date) if entry_date else False
    advice = get_advice(pnl * 100)
    return {
        'cost': cost, 'shares': shares, 'current': current,
        'total_cost': total_cost, 'market_value': market_value,
        'pnl_pct': round(pnl * 100, 2), 'pnl_value': round(pnl_value, 2),
        'hard_stop': hard, 'trailing_stop': trailing,
        'take_profits': tps, 'time_stop_triggered': time_stop, 'advice': advice,
    }

def get_advice(pnl_pct):
    """获取操作建议"""
    if pnl_pct <= -8:
        return "⚠️ 触发硬止损，立即卖出"
    if pnl_pct <= -5:
        return "⚠️ 接近止损，准备卖出"
    if pnl_pct >= 15:
        return "✅ 移动止盈激活"
    if pnl_pct >= 5:
        return "📊 持有观察"
    if pnl_pct >= 0:
        return "📊 微盈，持有"
    return "📉 微亏，观察"

if __name__ == "__main__":
    result = analyze_position(45.70, 500, 46.47, "2026-09-18")
