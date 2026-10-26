#!/usr/bin/env python3
"""
daily_review.py — 收盘复盘脚本
职责: 15:30汇总当日交易、更新数据、生成明日计划
"""

import json
import sys
from pathlib import Path
from datetime import datetime

PROJECT = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(PROJECT))

def load_trade_log():
    """加载交易日志"""
    log_file = PROJECT / "data" / "trade_log.json"
    if log_file.exists():
        with open(log_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def load_holdings():
    """加载持仓"""
    holdings_file = PROJECT / "data" / "holdings.json"
    with open(holdings_file, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_daily_review():
    """生成每日复盘"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始收盘复盘...")
    
    # 1. 加载数据
    trades = load_trade_log()
    holdings = load_holdings()
    
    # 2. 统计今日交易
    today = datetime.now().strftime('%Y-%m-%d')
    if isinstance(trades, list):
        today_trades = [t for t in trades if isinstance(t, dict) and t.get('timestamp', '').startswith(today)]
    else:
        today_trades = []
    
    buys = [t for t in today_trades if t.get('action') == 'buy']
    sells = [t for t in today_trades if t.get('action') == 'sell']
    
    print(f"\\n  【今日交易统计】")
    print(f"    买入: {len(buys)}笔")
    print(f"    卖出: {len(sells)}笔")
    
    # 3. 计算盈亏
    total_buy_amount = sum(t.get('amount', 0) for t in buys)
    total_sell_amount = sum(t.get('amount', 0) for t in sells)
    
    print(f"    买入金额: {total_buy_amount:.2f}元")
    print(f"    卖出金额: {total_sell_amount:.2f}元")
    
    # 4. 持仓状态
    # P0修复(20261023): 实锤盲区8天 — holdings.json 顶层键实为 'holdings'(list, 含status字段),
    # 'positions' 是幽灵键恒0 → 复盘恒报"持仓0只"且L105恒输出"买入"。优先'holdings', 缺则回退'positions'兼容旧schema。
    positions = holdings.get('holdings', holdings.get('positions', []))
    positions = [p for p in positions if p.get('status', 'active') == 'active']  # 只计在持, 防已平仓记录污染
    cash = holdings.get('available_cash', 0)
    total_assets = holdings.get('total_assets', 0)
    
    print(f"\\n  【当前持仓状态】")
    print(f"    持仓: {len(positions)}只")
    print(f"    现金: {cash:.2f}元")
    print(f"    总资产: {total_assets:.2f}元")
    
    # 5. 生成明日建议
    market_decision_file = PROJECT / "data" / "market_adaptation_decision.json"
    with open(market_decision_file, 'r', encoding='utf-8') as f:
        decision = json.load(f)
    
    gate_open = decision.get('gate', {}).get('open', False)
    market_state = decision.get('market', {}).get('label', '震荡')
    position_ratio = decision.get('position', {}).get('ratio', 0.3)
    
    print(f"\\n  【明日计划建议】")
    print(f"    环境门: {'开' if gate_open else '关'}")
    print(f"    市场状态: {market_state}")
    print(f"    建议仓位: {position_ratio*100:.0f}%")
    
    if not gate_open:
        print(f"    ⚠️ 环境门关，建议控制仓位或空仓")
    
    # 6. 保存复盘报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'date': today,
        'trades': {
            'buys': len(buys),
            'sells': len(sells),
            'buy_amount': total_buy_amount,
            'sell_amount': total_sell_amount
        },
        'positions': {
            'count': len(positions),
            'cash': cash,
            'total_assets': total_assets
        },
        'market': {
            'gate_open': gate_open,
            'state': market_state,
            'position_ratio': position_ratio
        },
        # P0修复(20261023): 本表达式随L59键修复自动转正 — 持1只博迈科时len=1→"观望"; 旧bug下positions恒0→恒"买入"
        'recommendation': '买入' if gate_open and len(positions) < 1 else '观望'
    }
    
    report_file = PROJECT / "output" / "diagnostic" / f"daily_review_{today}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\\n  ✅ 复盘报告已保存: {report_file}")

    # 7. 写 feedback_log（append-only，不复盘日志本身）
    _write_after_close_feedback(today, gate_open, market_state, positions, total_assets, cash)

    return report


def _write_after_close_feedback(
    date_str: str,
    gate_open: bool,
    market_state: str,
    positions: list,
    total_assets: float,
    cash: float,
) -> None:
    """盘后复盘结论追加到 data/feedback_log.jsonl（append-only）"""
    feedback_log = PROJECT / "data" / "feedback_log.jsonl"
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # 构建观察结论
    pos_info = positions[0] if positions else None
    if pos_info:
        # P0修复(20261023): holdings.json 条目键为 symbol/sh603727, 旧读法 code 恒"?"
        code = pos_info.get("symbol", pos_info.get("code", "?"))
        pnl_pct = pos_info.get("pnl_pct", 0.0)
        observation = (
            f"环境门={'开' if gate_open else '关'}，持仓{code}浮{(pnl_pct):+.1f}%，"
            f"总资产{total_assets:.0f}元"
        )
        suggested_action = (
            "保持持仓观察" if gate_open
            else "空仓观望，等待环境门开启"
        )
        related_factors = ["volatility20", "max_ret5_low"] if not gate_open else []
    else:
        observation = f"环境门={'开' if gate_open else '关'}，市场状态={market_state}，无持仓"
        suggested_action = "保持空仓，等待环境门开启信号" if not gate_open else "继续选股轮动"
        related_factors = []

    record = {
        "ts": ts,
        "review_type": "after_close",
        "date": date_str,
        "observer": "daily_review.py",
        "observation": observation,
        "suggested_action": suggested_action,
        "related_factors": related_factors,
        "weight_suggestion": None,
        "confidence": "medium",
        "source_script": "scripts/daily_review.py",
    }

    with open(feedback_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"  ✅ 反馈已追加到 feedback_log.jsonl: {ts} {observation[:40]}...")

if __name__ == "__main__":
    report = generate_daily_review()
    print(f"\\n✅ 收盘复盘完成")
