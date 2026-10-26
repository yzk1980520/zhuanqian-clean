#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cron_daily_select.py — 每日定时选股任务
版本: v0.1
作者: 老三
日期: 2026-10-04

功能:
  1. 环境门检查
  2. A股筛选
  3. 多因子打分
  4. S3筛选
  5. 结果保存
  6. 门禁状态检查

使用:
  python cron_daily_select.py
"""
import json
import os
import sys
from datetime import datetime, date

ROOT = r"D:/open code/zhuanqian"
sys.path.insert(0, ROOT)

# 导入核心模块
from core.scoring.tdx_strategies import load_strategy
from risk_rules import TREND_TP_LADDER, CHASE_BAN_PCT, STRATEGY_STOP_LOSS_PCT
from daily_auto_select import check_market_gate, load_stock_data, calculate_scores, apply_s3_filters


def log(msg):
    """日志输出"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    # 写入日志文件
    log_file = os.path.join(ROOT, ".scratch", "cron_daily_select.log")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        print(f"🔴 [scripts\\cron_daily_select.py] CR-01: except Exception:", file=sys.stderr)
def load_review_status():
    """加载门禁状态"""
    review_file = os.path.join(ROOT, "data", "review_status.json")
    if not os.path.exists(review_file):
        return {"laowu_approved": False}
    with open(review_file, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    log("=" * 60)
    log("每日定时选股任务开始")
    log("=" * 60)

    # 1. 门禁检查
    log("\n【第1步】门禁检查")
    import review_gate  # R0b(K47 §二 统一读法): 走唯一仲裁读法, 消除各写各的
    gate = review_gate.evaluate(os.path.join(ROOT, "data", "review_status.json"))
    laowu_approved = not gate["frozen"]
    log(f"  老五闸门(review_gate, source={gate['source']}): "
        f"{'✅ 放行' if laowu_approved else '❌ 冻结'} — {gate['reason']}")

    if not laowu_approved:
        log("  ⚠️ 门禁未通过，仅生成选股报告，不推送通知")
    else:
        log("  ✅ 门禁已通过，生成选股报告并推送通知")

    # 2. 环境门检查
    log("\n【第2步】环境门检查")
    gate_status, gate_detail = check_market_gate()
    log(f"  {gate_detail}")
    log(f"  门内: {'✅' if gate_status else '❌'}")

    # 3. 加载策略权重
    log("\n【第3步】加载策略权重")
    strategy_weights, strategy_name = load_strategy()
    log(f"  策略: {strategy_name} ({len(strategy_weights)}因子)")

    # 4. 加载股票数据
    log("\n【第4步】加载股票数据")
    stocks = load_stock_data()
    log(f"  股票数: {len(stocks)}")

    # 5. 计算打分
    log("\n【第5步】多因子打分")
    scores = calculate_scores(stocks, strategy_weights)
    log(f"  有效股票: {len(scores)}")

    # 6. S3筛选
    log("\n【第6步】S3筛选")
    top_n = 5
    filtered = apply_s3_filters(stocks, scores, top_n)
    log(f"  推荐股票: {len(filtered)}")

    for i, s in enumerate(filtered, 1):
        log(f"  {i}. {s['code']} @ {s['close']:.2f} 止损{s['stop_loss']:.2f} 评分{s['score']:.0f}")

    # 7. 保存结果
    log("\n【第7步】保存结果")
    today = date.today().isoformat()
    output_file = os.path.join(ROOT, "data", f"selection_{today}.json")

    result = {
        "generated": datetime.now().isoformat(),
        "date": today,
        "gate": {"status": gate_status, "detail": gate_detail},
        "review": {"laowu_approved": laowu_approved},
        "strategy": strategy_name,
        "stocks_count": len(stocks),
        "filtered_stocks": filtered
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"  结果已保存: {output_file}")

    # 8. 输出摘要
    log("\n" + "=" * 60)
    log("任务完成")
    log("=" * 60)
    log(f"环境门: {'✅ 通过' if gate_status else '❌ 关闭'}")
    log(f"门禁: {'✅ 通过' if laowu_approved else '❌ 未通过'}")
    log(f"推荐股票: {len(filtered)}只")
    log(f"输出文件: {output_file}")
    log("=" * 60)

    # 返回状态码
    if gate_status and laowu_approved and filtered:
        return 0  # 完全就绪
    elif gate_status or laowu_approved:
        return 1  # 部分就绪
    else:
        return 2  # 阻塞


if __name__ == "__main__":
    sys.exit(main())
