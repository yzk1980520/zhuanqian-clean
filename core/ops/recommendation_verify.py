#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
推荐结果跟踪验证脚本 v1.0
每次运行自动检查历史推荐的后续表现
"""
import sys, os, json, csv
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
from datetime import datetime
from core.pipeline.atomic_json import atomic_dump
from core.pipeline.tdx_core import get_tdx_data

TRADE_LOG = os.path.join(PROJECT_ROOT, "data", "trade_log.json")  # P2(t_febdf372): 归一 data/ 真源(根侧trade_log.json为9/23遗留,已移.trash)
OUTPUT_LOG = os.path.join(PROJECT_ROOT, "recommendation_verify.json")  # P1修复(20261023): S5迁移core/ops/后误指core/ops/, 产物写仓库根
CSV_OUTPUT = os.path.join(PROJECT_ROOT, "推荐跟踪验证.csv")  # P1修复(20261023): 同上

def verify_all_recommendations():
    """检查所有历史推荐，更新其后续表现"""
    if not os.path.exists(TRADE_LOG):
        print("❌ 无交易日志文件")
        return

    with open(TRADE_LOG, 'r', encoding='utf-8') as f:
        log = json.load(f)

    recs = log.get("recommendations", [])
    if not recs:
        print("📭 无推荐记录")
        return

    print(f"\n🔍 跟踪验证 {len(recs)} 条推荐记录...")
    updated = 0
    verify_log = []

    for rec in recs:
        code = rec.get("code", "")
        rec_date_str = rec.get("date", "")
        if not code or not rec_date_str:
            continue

        rec_price = float(rec.get("entry_price") or rec.get("buy_price") or 0)
        sell_price = rec.get("sell_price")
        sell_price = float(sell_price) if sell_price is not None else 0
        if sell_price > 0:
            # 已卖出 → 直接计算
            ret_pct = (sell_price - rec_price) / rec_price * 100 if rec_price else 0
            result = "✅盈利" if ret_pct > 0 else "❌亏损"
        else:
            # 未卖出 → 查最新价
            recs_history = get_tdx_data(code, 30)
            latest_price = recs_history[-1]["close"] if recs_history else rec_price
            ret_pct = (latest_price - rec_price) / rec_price * 100 if rec_price else 0
            ret_pct = round(ret_pct, 2)
            result = "持有中"
            # 记录最新价
            rec["current_price"] = latest_price

        rec["verified_return_pct"] = ret_pct
        rec["verified_date"] = datetime.now().strftime("%Y-%m-%d")
        verify_log.append({
            "code": code,
            "name": rec.get("name", ""),
            "date": rec_date_str,
            "score": rec.get("score", 0),
            "entry_price": rec_price,
            "verified_pct": ret_pct,
            "result": result,
        })
        updated += 1

    # 保存验证结果
    atomic_dump(verify_log, OUTPUT_LOG, ensure_ascii=False, indent=2)

    # 输出CSV
    with open(CSV_OUTPUT, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(["日期", "代码", "名称", "评分", "入场价", "当前收益%", "状态"])
        for v in verify_log:
            w.writerow([v["date"], v["code"], v["name"], v["score"],
                       v["entry_price"], v["verified_pct"], v["result"]])

    # 统计
    wins = sum(1 for v in verify_log if v["verified_pct"] > 0)
    total = len(verify_log)
    avg_ret = sum(v["verified_pct"] for v in verify_log) / total if total else 0
    print(f"✅ 验证完成: {total}条, 盈利{wins}条, 胜率{wins/total*100:.1f}%, 平均收益{avg_ret:+.2f}%")
    print(f"📁 详情: {OUTPUT_LOG}")
    print(f"📁 CSV: {CSV_OUTPUT}")

if __name__ == "__main__":
    verify_all_recommendations()
