#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S3实盘监控脚本 - 持仓状态实时追踪
执行方式: python s3_live_monitor.py [--push]
"""
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [scripts\s3_live_monitor.py] CR-01: except Exception:", file=sys.stderr)
PROJECT = Path(__file__).parent.parent.resolve()
DATA_DIR = PROJECT / "data"
HOLDINGS_FILE = DATA_DIR / "holdings.json"
ALERT_STATE_FILE = DATA_DIR / "position_alerts_state.json"
MONITOR_LOG = DATA_DIR / "s3_monitor_log.jsonl"

# S3配置
S3_LADDER = [(6, 0.15), (10, 0.05), (15, 0.07), (25, 0.09), (999, 0.12)]
STOP_LOSS_PCT = 0.10
POSITION_RATIO = 0.5

def log(msg: str):
    """记录监控日志"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {"ts": ts, "msg": msg}
    print(f"[{ts}] {msg}")
    with open(MONITOR_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def load_holdings():
    """加载当前持仓"""
    if not HOLDINGS_FILE.exists():
        return []
    with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("holdings", [])

def get_account_status():
    """获取账户状态"""
    if not HOLDINGS_FILE.exists():
        return None
    with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        "total_assets": data.get("total_assets", 0),
        "available_cash": data.get("available_cash", 0),
        "position_ratio": data.get("position_ratio", 0),
        "updated_at": data.get("updated_at", ""),
    }

def check_s3_conditions(holdings, account):
    """检查S3失效触发条件"""
    alerts = []
    
    # 1. 单股集中度检查
    for pos in holdings:
        cost = pos.get("cost_price", 0)
        current = pos.get("current_price", pos.get("last_price", 0))
        if cost <= 0 or current <= 0:
            continue
        
        pnl_pct = (current - cost) / cost
        if pnl_pct > 0.30:
            alerts.append({
                "type": "concentration",
                "level": "warning",
                "code": pos.get("code", ""),
                "name": pos.get("name", ""),
                "message": f"单股浮盈{pnl_pct*100:.1f}% > 30%，建议强制减半",
                "pnl_pct": round(pnl_pct * 100, 2)
            })
    
    # 2. 持仓状态检查
    for pos in holdings:
        code = pos.get("code", "")
        cost = pos.get("cost_price", 0)
        current = pos.get("current_price", pos.get("last_price", 0))
        high_price = pos.get("high_price", current)
        
        if cost <= 0 or current <= 0:
            continue
        
        pnl_pct = (current - cost) / cost
        drawdown = (high_price - current) / high_price if high_price > 0 else 0
        
        # 硬止损检查
        if pnl_pct <= -STOP_LOSS_PCT:
            alerts.append({
                "type": "stop_loss",
                "level": "critical",
                "code": code,
                "name": pos.get("name", ""),
                "message": f"硬止损触发! 浮亏{pnl_pct*100:.1f}% <= -{STOP_LOSS_PCT*100}%",
                "pnl_pct": round(pnl_pct * 100, 2),
                "stop_price": round(cost * (1 - STOP_LOSS_PCT), 2)
            })
        
        # 移动止盈检查（S3五档）
        if pnl_pct > 0:
            threshold = 0.15  # 默认首档
            for profit_thresh, dd_thresh in S3_LADDER:
                if pnl_pct * 100 < profit_thresh:
                    threshold = dd_thresh
                    break
            else:
                threshold = S3_LADDER[-1][1]
            
            # 修复: 计算回撤触发价（从最高价回撤threshold%触发止盈）
            trail_price = high_price * (1 - threshold)
            if drawdown >= threshold:
                alerts.append({
                    "type": "trailing_stop",
                    "level": "warning",
                    "code": code,
                    "name": pos.get("name", ""),
                    "message": f"移动止盈触发! 从高点{high_price:.2f}回撤{drawdown*100:.1f}% >= {threshold*100:.0f}%",
                    "high_price": round(high_price, 2),
                    "current": round(current, 2),
                    "trail_price": round(trail_price, 2),
                    "threshold": round(threshold * 100, 1)
                })
    
    return alerts

def check_roll_stats():
    """检查滚动统计（需要历史交易数据）"""
    trade_log = DATA_DIR / "trade_log.jsonl"
    if not trade_log.exists():
        return None
    
    trades = []
    with open(trade_log, "r", encoding="utf-8") as f:
        for line in f:
            try:
                trades.append(json.loads(line.strip()))
            except Exception:
                print(f"🔴 [scripts\s3_live_monitor.py] CR-01: except (AttributeError, FileNotFoundError, IOError, PermissionError, json.JSONDecodeError) as e:", file=sys.stderr)
    if len(trades) < 20:
        return {"status": "insufficient_data", "trades": len(trades)}
    
    # 计算最近20笔胜率
    recent = trades[-20:]
    wins = sum(1 for t in recent if t.get("pnl", 0) > 0)
    win_rate = wins / len(recent)
    
    # 计算最大回撤
    equity = [100.0]  # 归一化
    for t in recent:
        pnl_pct = t.get("pnl_pct", 0) / 100
        equity.append(equity[-1] * (1 + pnl_pct))
    peak = max(equity)
    max_dd = (peak - min(equity)) / peak
    
    return {
        "win_rate": round(win_rate * 100, 1),
        "max_drawdown": round(max_dd * 100, 1),
        "trades": len(recent),
        "trigger_retreat": win_rate < 0.45 or max_dd > 0.50
    }

def main(push=False):
    """主监控流程"""
    log("=" * 50)
    log("S3实盘监控启动")
    
    # 1. 加载持仓
    holdings = load_holdings()
    account = get_account_status()
    
    if not account:
        log("⚠️ 无法读取holdings.json")
        return
    
    log(f"总资产: {account['total_assets']:,.2f}元")
    log(f"可用现金: {account['available_cash']:,.2f}元")
    log(f"持仓数: {len(holdings)}")
    
    # 2. 检查持仓状态
    alerts = check_s3_conditions(holdings, account)
    
    if alerts:
        log(f"⚠️ 发现 {len(alerts)} 条告警:")
        for a in alerts:
            log(f"  [{a['level'].upper()}] {a['message']}")
            
            # 写入告警队列（如果启用推送）
            if push and a["level"] == "critical":
                write_alert_queue(a)
    else:
        log("✅ 持仓状态正常")
    
    # 3. 检查滚动统计
    roll_stats = check_roll_stats()
    if roll_stats:
        if roll_stats.get("trigger_retreat"):
            log(f"🔴 失效触发! 滚动{roll_stats['trades']}笔 胜率{roll_stats['win_rate']}% 回撤{roll_stats['max_drawdown']}%")
            log("   建议: 自动回退S2/CTRL")
        else:
            log(f"📊 滚动统计: 胜率{roll_stats.get('win_rate', 'N/A')}% 回撤{roll_stats.get('max_drawdown', 'N/A')}%")
    
    # 4. 输出JSON摘要（供外部调用）
    summary = {
        "timestamp": datetime.now().isoformat(),
        "account": account,
        "holdings_count": len(holdings),
        "alerts": alerts,
        "roll_stats": roll_stats,
        "s3_config": {
            "ladder": S3_LADDER,
            "stop_loss_pct": STOP_LOSS_PCT,
            "position_ratio": POSITION_RATIO
        }
    }
    
    # 写入状态文件
    status_file = DATA_DIR / "s3_monitor_status.json"
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    log(f"状态已写入: {status_file}")
    log("=" * 50)

def write_alert_queue(alert):
    """写入告警队列供推送"""
    queue_file = DATA_DIR / "message_queue.json"
    queue = []
    if queue_file.exists():
        try:
            with open(queue_file, "r", encoding="utf-8") as f:
                queue = json.load(f)
        except Exception:
            print(f"🔴 [scripts\s3_live_monitor.py] CR-01: except (AttributeError, FileNotFoundError, IOError, PermissionError, json.JSONDecodeError) as e:", file=sys.stderr)
    queue.append({
        "id": f"s3_alert_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "content": f"🔔 S3告警 [{alert['level'].upper()}] {alert['message']}",
        "platform": "feishu",
        "ts": datetime.now().timestamp()
    })
    
    with open(queue_file, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    push = "--push" in sys.argv
    main(push=push)
