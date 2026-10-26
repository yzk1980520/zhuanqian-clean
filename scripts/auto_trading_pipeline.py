#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_trading_pipeline.py — 自动化选股实盘流水线
版本: v0.1
作者: 老三
日期: 2026-10-04

功能:
  1. 环境门检查
  2. 选股打分
  3. 持仓管理（总管独占写盘）
  4. S3失效监控
  5. 每日自动运行

使用:
  python auto_trading_pipeline.py [--dry-run] [--force]
"""
import json
import os
import sys
from datetime import datetime, date

ROOT = r"D:/open code/zhuanqian"
sys.path.insert(0, ROOT)

# 导入核心模块
from core.scoring.tdx_strategies import STRATEGIES, load_strategy
from risk_rules import TREND_TP_LADDER, CHASE_BAN_PCT, STRATEGY_STOP_LOSS_PCT
from pick_best_stock import check_market_gate, load_stock_data, calculate_scores, apply_s3_filters

# 数据文件
HOLDINGS_FILE = os.path.join(ROOT, "data", "holdings.json")
TRADE_LOG_FILE = os.path.join(ROOT, "data", "trade_log.json")
REVIEW_STATUS_FILE = os.path.join(ROOT, "data", "review_status.json")


def log(msg, force=False):
    """日志输出"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    # 写入日志文件
    log_file = os.path.join(ROOT, ".scratch", "pipeline.log")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        print(f"🔴 [scripts\\auto_trading_pipeline.py] CR-01: except Exception:", file=sys.stderr)
def load_holdings():
    """加载持仓（只读）"""
    if not os.path.exists(HOLDINGS_FILE):
        return None
    with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_trade_log():
    """加载交易日志（只读）"""
    if not os.path.exists(TRADE_LOG_FILE):
        return {"trades": []}
    with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_review_status():
    """加载门禁状态（只读）"""
    if not os.path.exists(REVIEW_STATUS_FILE):
        return {"laowu_approved": False}
    with open(REVIEW_STATUS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def run_pipeline(dry_run=True, force=False):
    """运行完整流水线"""
    log("=" * 70)
    log("自动化选股实盘流水线 v0.1")
    log("=" * 70)
    
    # 1. 门禁检查
    log("\n【第1步】门禁检查")
    import review_gate  # R0b(K47 §二 统一读法): 走唯一仲裁读法, 不直接读 laowu_approved
    gate = review_gate.evaluate(str(REVIEW_STATUS_FILE))
    laowu_approved = not gate["frozen"]
    log(f"  老五闸门(review_gate, source={gate['source']}): "
        f"{'✅ 放行' if laowu_approved else '❌ 冻结'} — {gate['reason']}")
    
    if not laowu_approved and not force:
        log("  ⚠️ 门禁未通过，跳过实盘操作")
        log("  建议: 等待总管/老五裁定后设置laowu_approved=true")
        return {
            "status": "blocked",
            "reason": "laowu_approved=False",
            "dry_run": dry_run
        }
    
    # 2. 环境门检查
    log("\n【第2步】环境门检查")
    gate_status, gate_detail = check_market_gate()
    log(f"  {gate_detail}")
    log(f"  门内: {'✅' if gate_status else '❌'}")
    
    if not gate_status and not force:
        log("  ⚠️ 环境门关闭，仅选股不出仓")
    
    # 3. 选股打分
    log("\n【第3步】选股打分")
    strategy_weights, strategy_name = load_strategy()
    log(f"  策略: {strategy_name} ({len(strategy_weights)}因子)")
    
    stocks = load_stock_data()
    log(f"  股票数: {len(stocks)}")
    
    scores = calculate_scores(stocks, strategy_weights)
    log(f"  有效股票: {len(scores)}")
    
    # 4. S3筛选
    log("\n【第4步】S3筛选")
    filtered = apply_s3_filters(stocks, scores, top_n=5)
    log(f"  推荐股票: {len(filtered)}")
    
    for i, s in enumerate(filtered, 1):
        log(f"  {i}. {s['code']} @ {s['close']:.2f} 止损{s['stop_loss']:.2f} 评分{s['score']:.0f}")
    
    # 5. 持仓检查
    log("\n【第5步】持仓检查")
    holdings = load_holdings()
    positions = []
    if holdings:
        cash = holdings.get("cash", 0)
        positions = holdings.get("holdings", [])
        log(f"  现金: {cash:.2f}")
        log(f"  持仓数: {len(positions)}")
        for p in positions:
            log(f"    {p['code']}: {p['shares']}股@{p['cost']:.2f}")
    
    # 6. 决策建议
    log("\n【第6步】决策建议")
    recommendations = []
    
    if gate_status and laowu_approved and holdings and holdings.get("cash", 0) > 10000:
        if len(positions) == 0 and filtered:
            recommendations.append({
                "action": "开仓",
                "stock": filtered[0],
                "reason": "环境门内+门禁通过+空仓+有推荐",
                "sizing": "phased 10%起步"
            })
        elif len(positions) >= 1:
            recommendations.append({
                "action": "持有观望",
                "reason": "已有持仓，等待止盈/止损信号"
            })
    else:
        recommendations.append({
            "action": "等待",
            "reason": "门禁未通过或环境门关闭或资金不足",
            "required": "laowu_approved=true + 环境门内 + cash>10000"
        })
    
    for rec in recommendations:
        log(f"  {rec['action']}: {rec['reason']}")
    
    # 7. 保存结果
    log("\n【第7步】保存结果")
    result = {
        "generated": datetime.now().isoformat(),
        "pipeline_version": "v0.1",
        "dry_run": dry_run,
        "gate": {"status": gate_status, "detail": gate_detail},
        "review": {"laowu_approved": laowu_approved},
        "holdings": holdings,
        "recommendations": recommendations,
        "filtered_stocks": filtered
    }
    
    output_file = os.path.join(ROOT, ".scratch", f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"  结果已保存: {output_file}")
    
    log("\n" + "=" * 70)
    log("流水线执行完成")
    log("=" * 70)
    
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="自动化选股实盘流水线")
    parser.add_argument("--dry-run", action="store_true", help="仅选股不出仓（默认）")
    parser.add_argument("--force", action="store_true", help="强制执行（忽略门禁）")
    parser.add_argument("--live", action="store_true", help="实盘模式（需确认）")
    args = parser.parse_args()
    
    if args.live:
        log("⚠️ 实盘模式已启用！")
        dry_run = False
    elif args.force:
        log("⚠️ 强制模式已启用！")
        dry_run = True
    else:
        dry_run = True
    
    result = run_pipeline(dry_run=dry_run, force=args.force)
    
    # 输出摘要
    print("\n" + "=" * 70)
    print("流水线摘要")
    print("=" * 70)
    print(f"状态: {result.get('status', 'unknown')}")
    print(f"环境门: {'✅ 通过' if result.get('gate', {}).get('status') else '❌ 关闭'}")
    print(f"门禁: {'✅ 通过' if result.get('review', {}).get('laowu_approved') else '❌ 未通过'}")
    print(f"推荐股票: {len(result.get('filtered_stocks', []))}只")
    print(f"建议动作: {result.get('recommendations', [{}])[0].get('action', 'N/A') if result.get('recommendations') else 'N/A'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
