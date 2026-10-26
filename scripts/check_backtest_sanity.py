#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_backtest_sanity.py — 回测结果合理性门禁（sanity gate）
=============================================================
来源: 2026-09-25 WorkBuddy 排查"7个变体全部只成交1笔"事故后的制度化产物。
背景: 09-21 fast-path 优化引入双 bug（合并乱序+typed dict评分崩溃），
     回测评分恒0、每变体仅1笔，而人工验收报告仍全部打勾放行。
     本脚本把验收从"人打勾"变成"机器断言"。

用法:
    python check_backtest_sanity.py [结果json路径]
    默认: data/rotation_backtest_result.json

退出码: 0=PASS, 1=FAIL（可直接接入 cron / 验收流程）
任何一条 FAIL 都必须排查根因后重跑，禁止带病交付。
"""
import sys
import json
import os
from collections import Counter

PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 门禁阈值（依据 AGENTS.md 全量132日口径；调整需老大拍板）──
MIN_TRADES = 30            # 全量窗口最少成交笔数（v36口径35笔量级，<30 视为状态机冻结/过度过滤）
MIN_VARIANTS = 2           # 至少 2 个变体
VARIANT_DISTINCT_TRADES = 3  # 各变体交易明细去重后至少 3 种不同组合（防"变体无差异"）
MAX_SAME_STOCK_RATIO = 0.30  # 单一股票占全部交易的最大占比（防"永远买同一只"=评分退化）
MIN_DISTINCT_STOCKS = 10   # 全部变体合计至少买过 10 只不同股票
MIN_HOLD_DAYS = 5          # 平均持有天数下限（时间止损120d口径下过低=退出逻辑异常）


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def trades_of(res):
    t = res.get("trades")
    if isinstance(t, list) and t and isinstance(t[0], dict):
        return t
    # summary-only: 尝试从明细字段恢复
    for k in ("trade_list", "trade_details"):
        if isinstance(res.get(k), list) and res.get(k):
            return res[k]
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJECT, "data", "rotation_backtest_result.json")
    if not os.path.exists(path):
        print(f"FAIL: 结果文件不存在: {path}")
        return 1
    data = load(path)
    results = data.get("results") if isinstance(data, dict) else data
    if not results or not isinstance(results, list):
        print("FAIL: results 结构缺失或为空")
        return 1

    checks = []  # (name, ok, detail)

    # 1) 变体数量
    checks.append(("变体数量>=2", len(results) >= MIN_VARIANTS, f"实际 {len(results)}"))

    # 2) 每个变体成交笔数
    all_trades = []
    for res in results:
        cfg = res.get("config")
        name = cfg if isinstance(cfg, str) else (cfg.get("name", "?") if isinstance(cfg, dict) else "?")
        ts = trades_of(res) or []
        n = res.get("trades") if isinstance(res.get("trades"), int) else len(ts)
        all_trades.extend(ts)
        checks.append((f"[{name}] 成交笔数>={MIN_TRADES}", n >= MIN_TRADES, f"实际 {n}"))

    # 3) 变体间差异（结果完全一致=状态机/评分退化）
    sigs = set()
    for res in results:
        ts = trades_of(res) or []
        sig = tuple(sorted((t.get("code"), str(t.get("buy_date")), str(t.get("exit"))) for t in ts))
        sigs.add(sig)
    checks.append((f"变体交易组合去重>={VARIANT_DISTINCT_TRADES}", len(sigs) >= VARIANT_DISTINCT_TRADES,
                   f"实际 {len(sigs)} 种（若=1 且止损参数不同，说明退出/评分逻辑未生效）"))

    # 4) 买入集中度（评分退化=永远买同一只）——需要交易明细；汇总格式退化为退出原因多样性检查
    codes = [t.get("code") for t in all_trades if t.get("code")]
    if codes:
        top_code, top_n = Counter(codes).most_common(1)[0]
        ratio = top_n / len(codes)
        checks.append((f"单一股票占比<={MAX_SAME_STOCK_RATIO:.0%}", ratio <= MAX_SAME_STOCK_RATIO,
                       f"{top_code} 占 {top_n}/{len(codes)} = {ratio:.1%}"))
        checks.append((f"买入不同股票数>={MIN_DISTINCT_STOCKS}", len(set(codes)) >= MIN_DISTINCT_STOCKS,
                       f"实际 {len(set(codes))} 只"))
    else:
        reasons = set()
        for res in results:
            r = res.get("reasons")
            if isinstance(r, dict):
                reasons.update(r.keys())
            elif isinstance(r, list):
                reasons.update(str(x) for x in r)
        checks.append(("退出原因多样性>=2", len(reasons) >= 2,
                       f"实际 {len(reasons)} 种 {sorted(reasons)[:5]}（仅1种退出原因+参数各异=退出逻辑未生效）"))

    # 5) 平均持有天数（时间止损口径下过低=每日循环/退出逻辑异常）
    holds = [t.get("hold_days") for t in all_trades if isinstance(t.get("hold_days"), (int, float))]
    if not holds:
        holds = [res.get("avg_hold_days") for res in results if isinstance(res.get("avg_hold_days"), (int, float))]
    if holds:
        avg = sum(holds) / len(holds)
        checks.append((f"平均持有天数>={MIN_HOLD_DAYS}", avg >= MIN_HOLD_DAYS, f"实际 {avg:.1f}"))

    # 输出
    fails = [c for c in checks if not c[1]]
    print("=" * 60)
    print("回测 sanity gate 检查结果")
    print("=" * 60)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({detail})")
    print("-" * 60)
    if fails:
        print(f"结论: FAIL — {len(fails)} 项不过。禁止引用本次回测做任何决策/优化结论，先排查根因。")
        print("排查三板斧: ①BT_DEBUG=1 插桩  ②截短窗口对照实验  ③单股单日直接调用验证")
        return 1
    print("结论: PASS — 全部通过，可进入人工评审。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
