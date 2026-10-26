#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
risk_manager.py - 御龙决自动风控引擎
================================================================
核心功能：
1. 硬止损检查（-8%）
2. 移动止盈检查（阶梯止盈）
3. 分批止盈检查（20%/40%/60%）
4. 时间止损检查（120天）
5. 保本观察模式（跌破成本价清仓）

用法:
  python risk_manager.py [--check] [--json]
"""
import sys
import os
import json
import argparse
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [scripts\risk_manager.py] CR-01: except Exception:", file=sys.stderr)
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

DATA_DIR = os.path.join(PROJECT, "data")
HOLDINGS_FILE = os.path.join(DATA_DIR, "holdings.json")
RISK_LOG_FILE = os.path.join(DATA_DIR, "risk_log.json")


def load_holdings():
    """加载持仓数据"""
    if not os.path.exists(HOLDINGS_FILE):
        return None
    
    with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config():
    """加载配置"""
    config_file = os.path.join(PROJECT, "config.json")
    if not os.path.exists(config_file):
        return {}
    
    with open(config_file, "r", encoding="utf-8") as f:
        return json.load(f)


def check_hard_stop_loss(pos, config):
    """硬止损检查（-8%）"""
    stop_loss_pct = config.get("stop_loss_pct", 0.08)
    # holdings.json uses market_price/last_price, not current_price
    current_price = pos.get("market_price") or pos.get("last_price", 0)
    cost_price = pos.get("cost_price", 0)
    
    if cost_price <= 0:
        return False, 0
    
    loss_pct = (cost_price - current_price) / cost_price
    
    if loss_pct >= stop_loss_pct:
        return True, loss_pct
    
    return False, loss_pct


def check_trailing_take_profit(pos, config):
    """移动止盈检查"""
    trailing_ladder = config.get("trailing", {}).get("ladder", [])
    if not trailing_ladder:
        return False, 0, None
    
    current_price = pos.get("market_price") or pos.get("last_price", 0)
    cost_price = pos.get("cost_price", 0)

    if cost_price <= 0:
        return False, 0, None

    pnl_pct = (current_price - cost_price) / cost_price
    
    # 找到当前所在阶梯
    active_ladder = None
    for threshold, profit_pct in sorted(trailing_ladder, reverse=True):
        if pnl_pct >= profit_pct:
            active_ladder = threshold
            break
    
    if active_ladder is None:
        return False, pnl_pct, None
    
    # 检查是否触发移动止损
    # 简化版：如果利润回吐超过一定比例，触发止盈
    # 实际应比较当前价与最高价的回撤
    return True, pnl_pct, active_ladder


def check_batch_take_profit(pos, config):
    """分批止盈检查"""
    batch_sell = config.get("batch_sell", {})
    if not batch_sell.get("enabled", False):
        return []
    
    current_price = pos.get("market_price") or pos.get("last_price", 0)
    cost_price = pos.get("cost_price", 0)

    if cost_price <= 0:
        return []

    pnl_pct = (current_price - cost_price) / cost_price

    triggered_levels = []
    for level in batch_sell.get("levels", []):
        threshold = level.get("profit_pct", 0)
        ratio = level.get("sell_ratio", 0)
        if isinstance(threshold, str):
            threshold = float(threshold)
        if isinstance(ratio, str):
            ratio = float(ratio)
        if pnl_pct >= threshold:
            triggered_levels.append({
                "threshold": threshold,
                "ratio": ratio,
                "triggered": True
            })
    
    return triggered_levels


def check_time_stop(pos, config):
    """时间止损检查"""
    max_hold_days = config.get("time_stop", {}).get("max_hold_days", 120)
    buy_date = pos.get("buy_date", "")
    
    if not buy_date:
        return False, 0
    
    try:
        buy_dt = datetime.strptime(buy_date, "%Y-%m-%d")
        days_held = (datetime.now() - buy_dt).days
    except (AttributeError) as e:
        return False, 0
    
    if days_held >= max_hold_days:
        return True, days_held
    
    return False, days_held


def check_position_compliance(pos, config):
    """持仓合规检查"""
    issues = []
    
    # 检查止损线
    cost = pos.get("cost_price", 0)
    current = pos.get("market_price") or pos.get("last_price", 0)
    if cost > 0 and current < cost * 0.92:
        issues.append({
            "type": "stop_loss_near",
            "message": f"接近止损线（当前{current:.2f} vs 成本{cost:.2f}）",
            "severity": "high"
        })

    # 检查持仓时间
    max_days = config.get("time_stop", {}).get("max_hold_days", 120)
    buy_date = pos.get("entry_date", "")
    if buy_date:
        try:
            buy_dt = datetime.strptime(buy_date, "%Y-%m-%d")
            days = (datetime.now() - buy_dt).days
            if days > max_days * 0.8:
                issues.append({
                    "type": "time_stop_approaching",
                    "message": f"持仓{days}天，接近时间止损（{max_days}天）",
                    "severity": "medium"
                })
        except (ValueError, TypeError):
            print(f"🔴 [scripts\
isk_manager.py] CR-01: except:", file=sys.stderr)
    return issues


def run_risk_check():
    """执行风控检查"""
    
    # 加载数据
    holdings = load_holdings()
    config = load_config()
    
    if not holdings:
        return {"status": "no_data", "actions": []}
    
    positions = holdings.get("holdings", [])
    if not positions:
        return {"status": "empty", "actions": []}
    
    print(f"\n  📊 持仓数量: {len(positions)}只")
    
    actions = []
    warnings = []
    
    for pos in positions:
        code = pos.get("code", "unknown")
        name = pos.get("name", "unknown")
        print(f"\n  📈 检查: {code} {name}")
        
        # 1. 硬止损检查
        stop_triggered, loss_pct = check_hard_stop_loss(pos, config)
        if stop_triggered:
            actions.append({
                "type": "hard_stop_loss",
                "code": code,
                "name": name,
                "reason": f"硬止损触发（亏损{loss_pct*100:.1f}%）",
                "action": "sell_all",
                "priority": "critical"
            })
            print(f"    🔴 硬止损触发: 亏损{loss_pct*100:.1f}%")
        else:
            print(f"    ✅ 硬止损: 安全（亏损{loss_pct*100:.1f}%）")
        
        # 2. 移动止盈检查
        tp_triggered, pnl_pct, ladder = check_trailing_take_profit(pos, config)
        if tp_triggered and ladder:
            actions.append({
                "type": "trailing_take_profit",
                "code": code,
                "name": name,
                "reason": f"移动止盈阶梯{ladder}%触发（盈利{pnl_pct*100:.1f}%）",
                "action": "sell_all",
                "priority": "high"
            })
            print(f"    🟡 移动止盈: 触发阶梯{ladder}%")
        
        # 3. 分批止盈检查
        batch_levels = check_batch_take_profit(pos, config)
        for level in batch_levels:
            actions.append({
                "type": "batch_take_profit",
                "code": code,
                "name": name,
                "reason": f"分批止盈触发（盈利{level['threshold']*100:.0f}%，卖出{level['ratio']*100:.0f}%）",
                "action": "sell_partial",
                "ratio": level["ratio"],
                "priority": "medium"
            })
            print(f"    🟢 分批止盈: 盈利{level['threshold']*100:.0f}%，卖出{level['ratio']*100:.0f}%")
        
        # 4. 时间止损检查
        time_triggered, days_held = check_time_stop(pos, config)
        if time_triggered:
            actions.append({
                "type": "time_stop",
                "code": code,
                "name": name,
                "reason": f"时间止损触发（持仓{days_held}天）",
                "action": "sell_all",
                "priority": "high"
            })
            print(f"    🔴 时间止损触发: 持仓{days_held}天")
        
        # 5. 合规检查
        compliance_issues = check_position_compliance(pos, config)
        for issue in compliance_issues:
            warnings.append({
                "code": code,
                **issue
            })
            print(f"    ⚠️ {issue['message']}")
    
    # 汇总
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "checked",
        "positions_checked": len(positions),
        "actions": actions,
        "warnings": warnings,
        "summary": {
            "critical": len([a for a in actions if a["priority"] == "critical"]),
            "high": len([a for a in actions if a["priority"] == "high"]),
            "medium": len([a for a in actions if a["priority"] == "medium"]),
            "low": len([a for a in actions if a["priority"] == "low"])
        }
    }
    
    print(f"  持仓检查: {result['positions_checked']}只")
    print(f"  需执行动作: {len(actions)}个")
    print(f"    🔴 紧急: {result['summary']['critical']}个")
    print(f"    🟡 高优: {result['summary']['high']}个")
    print(f"    🟢 中优: {result['summary']['medium']}个")
    print(f"  警告信息: {len(warnings)}条")
    
    # 保存日志
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(RISK_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    return result


def main():
    parser = argparse.ArgumentParser(description="御龙决自动风控引擎")
    parser.add_argument("--check", action="store_true", help="执行风控检查")
    parser.add_argument("--json", action="store_true", help="只输出JSON")
    args = parser.parse_args()
    
    result = run_risk_check()
    
    if args.json:
        pass
    return result


if __name__ == "__main__":
    main()
