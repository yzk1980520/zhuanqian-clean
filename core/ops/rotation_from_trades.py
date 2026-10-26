import core.pipeline.atomic_json as atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
rotation_from_trades.py — 用官方回测同源候选跑轮动状态机 (2026-08-09)
====================================================================
候选来源: backtest_analysis/trade_detail.csv (131个扫描日的综合TOP1,
         与 backtest_result.json 同源, 零候选成本, 秒级跑完)

与 backtest_rotation.py 的区别:
  backtest_rotation.py = 每次空仓重新全市场扫描选股 (慢, 15.5s/次, 6变体1小时+)
  rotation_from_trades.py = 用 trade_detail.csv 的固定候选池驱动状态机 (快, 秒级)
  两者模拟同一用户习惯: 串行单票轮动 + 移动止盈止损 + 时间止损

输出: data/rotation_from_trades_result.json (独立文件, 不污染 backtest_result.json)
"""
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys
import csv
import json
from datetime import date, datetime

SCRIPT_DIR = PROJECT_ROOT
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import backtest as BT
from backtest.backtest_rotation import (
    RotationConfig, exit_trade, buy_cost, sell_proceeds, round_lot,
    INIT_CAPITAL, summarize, compute_atr_stop_price, signal_day_chg,
    CHASE_BAN_PCT, check_tp_fade, BULL_LABELS,
    _build_ad_maps, rebound_exhausted_on,
)

TRADE_CSV = os.path.join(SCRIPT_DIR, "backtest_analysis", "trade_detail.csv")


def load_candidates(min_raw=None, raw_json_path=None):
    """读 trade_detail.csv → [(scan_date, code, name, score)] 按日期升序
    min_raw: 若提供, 只保留 raw综合分 >= min_raw 的候选
    raw 来源: ①CSV 的 raw综合分 列 (backtest.py L896-905 导出)
              ②data/trade_detail_raw_scores.json (scripts_tmp/backfill_raw_scores.py 重算)
    raw_json_path: 覆盖 raw JSON 路径 (测试/独立数据用)
    """
    # raw 分映射 {scan_date: {code: raw}}
    raw_map = {}
    try:
        if raw_json_path is None:
            raw_json_path = os.path.join(SCRIPT_DIR, "data", "trade_detail_raw_scores.json")
        if os.path.exists(raw_json_path):
            with open(raw_json_path, encoding="utf-8") as f:
                payload = json.load(f)
            for k, v in (payload.get("scores") or {}).items():
                raw_map[k] = v.get("raw", 0)
    except Exception:
        raw_map = {}

    cands = []
    with open(TRADE_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d = r["扫描日期"].strip()
            try:
                dt = date(int(d[:4]), int(d[5:7]), int(d[8:10]))
            except Exception:
                continue
            code = r["股票代码"].strip()
            name = r["股票名称"].strip()
            try:
                score = float(r["综合评分"])
            except Exception:
                score = 0.0
            if min_raw is not None:
                # 优先用重算 JSON, 回退 CSV 列
                raw = raw_map.get(d, 0) or 0
                if raw == 0:
                    try:
                        raw = float(r.get("raw综合分", "") or 0)
                    except Exception:
                        raw = 0.0
                if raw < min_raw:
                    continue
            cands.append((dt, code, name, score))
    cands.sort(key=lambda x: x[0])
    return cands


def simulate_from_trades(cands, stocks_data, sh_records, config):
    """状态机: 空仓+候选日 → 买入候选; 持仓 → 逐日检查退出"""
    timeline = [r["date"] for r in sh_records]
    if not timeline:
        return [], []

    cash = INIT_CAPITAL
    equity_curve = []
    trades = []
    holding = None

    # 候选日索引 (扫描日期集合)
    # 口径修复 (2026-08-30, P2-2): 原 {d: (c,n,s) for ...} 是"同日最后一条"覆盖,
    # 实际买入 CSV 最后一条(avg 74.35) 而非 TOP1。现改为同日按综合评分降序取 TOP1。
    # 空占位行(P0-MarketGate, 空代码/0分)不会被选中(0 分不可能是同日最高分)。
    cand_by_date = {}
    for d, c, n, s in cands:
        if d not in cand_by_date or s > cand_by_date[d][2]:
            cand_by_date[d] = (c, n, s)

    # R15 P1-3: 反弹衰竭 AD 缓存 (惰性构建)
    _ad_maps = None

    for idx, day in enumerate(timeline):
        if holding is None:
            # 空仓: 若今天是候选日, 买入该候选
            if day in cand_by_date:
                # R15 P1-3 (oversold-rebound借鉴): 反弹衰竭 → 跳过本候选日买入
                if config.rebound_exhaust_chg5 is not None:
                    if _ad_maps is None:
                        _ad_maps = _build_ad_maps(stocks_data)
                    _ex, _chg5, _ad = rebound_exhausted_on(
                        day, sh_records, _ad_maps,
                        chg5_thresh=config.rebound_exhaust_chg5,
                        ad_thresh=config.rebound_exhaust_ad)
                    if _ex:
                        if not getattr(config, "_rex_log", None):
                            config._rex_log = {"days": [], "chg5": [], "ad": []}
                        config._rex_log["days"].append(str(day))
                        config._rex_log["chg5"].append(round(_chg5, 2))
                        config._rex_log["ad"].append(round(_ad, 2))
                        continue  # 反弹衰竭: 不切换抄底/超跌反弹, 跳过买入
                code, name, score = cand_by_date[day]
                records = stocks_data.get(code)
                skip_buy = False
                if records and config.chase_ban_pct is not None:
                    _sd = signal_day_chg(records, day)
                    if _sd and _sd[1] is not None and _sd[1] > config.chase_ban_pct:
                        skip_buy = True  # P0-A 追高关闭: 信号日涨幅超阈值, 放弃该候选日
                if records and not skip_buy:
                    # 买入价: 扫描日收盘 (与 trade_detail 5日收益口径一致) 或次日开盘
                    past = BT.get_records_up_to(records, day)
                    if past:
                        buy_price = past[-1]["close"]
                    else:
                        buy_price = 0
                    # P0-B 涨停买不进: 收盘买(尾盘)时信号日涨停(>=9.8%)封板 → 买不进
                    if not config.buy_at_open and len(past) >= 2:
                        _sd = signal_day_chg(records, day)
                        if _sd and _sd[1] is not None and _sd[1] >= 9.8:
                            buy_price = 0
                    if config.buy_at_open:
                        future = BT.find_future_records(records, day, 1)
                        if future:
                            buy_price = future[0]["open"]
                            # P0-B 涨停买不进: 次日开盘相对当日收盘 >=9.8% (一字板买不进)
                            if past and past[-1]["close"] > 0:
                                if (buy_price / past[-1]["close"] - 1) * 100 >= 9.8:
                                    buy_price = 0
                    if buy_price > 0:
                        max_shares = round_lot(cash / buy_price)
                        if max_shares >= 100:
                            amount = buy_price * max_shares
                            if amount <= cash:
                                cash -= buy_cost(amount, code)
                                stop_price, atr_v = compute_atr_stop_price(
                                    records, buy_price, config, day)
                                # 市场状态 (D 规则非牛市判定用, 与 backtest_rotation 同源)
                                ms = BT._determine_market_state_at(day, sh_records) if sh_records else ""
                                holding = {
                                    "code": code, "name": name,
                                    "entry": buy_price, "shares": max_shares,
                                    "buy_date": str(day), "buy_idx": idx,
                                    "high": buy_price, "stop_price": stop_price,
                                    "score": score, "ms": ms, "rec_ptr": 0,
                                    "atr": atr_v,
                                }
        else:
            # 持仓: 逐日检查退出
            code = holding["code"]
            records = stocks_data.get(code)
            if not records:
                trades.append(exit_trade(holding, holding["entry"], "数据缺失", cash, 0))
                cash = holding.get("cash_after", cash)
                holding = None
                continue
            day_rec = None
            ptr = holding.get("rec_ptr", 0)
            n = len(records)
            while ptr < n and records[ptr]["date"] < day:
                ptr += 1
            if ptr < n and records[ptr]["date"] == day:
                day_rec = records[ptr]
            holding["rec_ptr"] = ptr
            if day_rec is None:
                continue
            o, h, l, c = day_rec["open"], day_rec["high"], day_rec["low"], day_rec["close"]
            holding["high"] = max(holding["high"], c)
            # ATR自适应止损: 每交易日按最新ATR动态重算止损价 (仅当配置了 atr_mult)
            if config.atr_mult:
                _sp, _atr = compute_atr_stop_price(records, holding["entry"], config, day)
                holding["stop_price"] = _sp
                holding["atr"] = _atr

            hold_days = idx - holding["buy_idx"]
            exit_price = None
            exit_reason = None

            if l <= holding["stop_price"]:
                exit_price = holding["stop_price"]
                exit_reason = "止损"
            else:
                # Option D 回本抛压 (enable_tp_fade, 默认False): 非牛 + 峰值浮盈≥peak + 当前浮盈≤curr → 平仓
                if exit_price is None:
                    _fade, _fr = check_tp_fade(holding, c, config)
                    if _fade:
                        exit_price = c
                        exit_reason = _fr
                # R15 P1-2 (b11借鉴): 次日急单窗口 — 首次可卖出日, 快速兑现/快速止损
                if exit_price is None and hold_days == config.next_day_hold:
                    _nd_pnl = (c / holding["entry"] - 1) * 100
                    _nd, _nr = config.next_day_exit(_nd_pnl)
                    if _nd:
                        exit_price = c
                        exit_reason = _nr
                if hold_days >= config.min_hold_days:
                    pnl_pct = (holding["high"] / holding["entry"] - 1) * 100
                    tp = config.trailing_pct(pnl_pct)
                    if tp is not None:
                        trail_price = holding["high"] * (1 - tp)
                        if c <= trail_price:
                            exit_price = c
                            exit_reason = "移动止盈(回撤%.0f%%)" % (tp * 100)
                if exit_price is None and hold_days >= config.max_hold_days:
                    exit_price = c
                    exit_reason = "时间止损(%dd)" % hold_days
                if exit_price is None and day == timeline[-1]:
                    exit_price = c
                    exit_reason = "期末平仓"

            if exit_price is not None and exit_reason is not None:
                # P0-B 跌停卖不出 (2026-08-16): 卖出日跌停 → 无法成交, 顺延(最多3日)
                _defer = holding.get("sell_defer", 0)
                prev_close = records[ptr - 1]["close"] if ptr > 0 else holding.get("entry")
                if config.limit_down_defer and prev_close and prev_close > 0:
                    _chg = (c / prev_close - 1) * 100
                    if _chg <= -9.8:
                        if _defer < 3:
                            holding["sell_defer"] = _defer + 1
                            exit_price = None
                            exit_reason = None
                        else:
                            holding["sell_defer"] = 0
                    else:
                        holding["sell_defer"] = 0
                if exit_price is not None and exit_reason is not None:
                    t = exit_trade(holding, exit_price, exit_reason, cash, hold_days)
                    trades.append(t)
                    cash = t["cash_after"]
                    holding = None

        if holding is not None:
            code = holding["code"]
            recs = stocks_data.get(code)
            val = holding["entry"] * holding["shares"]
            if recs:
                for r in reversed(recs):
                    if r["date"] <= day:
                        val = r["close"] * holding["shares"]
                        break
            equity = cash + val
        else:
            equity = cash
        equity_curve.append({"date": str(day), "equity": round(equity, 2)})

    if holding is not None:
        hold_days = len(timeline) - 1 - holding["buy_idx"]
        t = exit_trade(holding, holding["entry"], "期末平仓", cash, hold_days)
        trades.append(t)
        cash = t["cash_after"]

    return trades, equity_curve


def main():
    print("=" * 68)
    print("  🔄 轮动回测(候选同源) — 单票轮动+移动止盈")
    print("  候选: trade_detail.csv (官方回测同源 TOP1)")
    print("=" * 68)

    # 加载数据
    print("\n📡 加载数据...")
    all_stocks = BT.collect_all_stocks()
    cache = BT.load_name_cache()
    stocks_data = {}
    for code, mkt in sorted(all_stocks.items()):
        name = cache.get(code, "")
        if BT.is_st_stock(name):
            continue
        records = BT.get_extended_data(code)
        if not records:
            records = BT.get_tdx_data(code, 400)
        if records and len(records) >= 30:
            stocks_data[code] = records
    print(f"  ✅ 有效: {len(stocks_data)} 只")

    sh_records = BT._load_sh_index_records(0)
    print(f"  ✅ 指数: {len(sh_records)} 条")

    cands = load_candidates()
    print(f"  ✅ 候选: {len(cands)} 个扫描日 ({cands[0][0]} ~ {cands[-1][0]})")

    configs = [
        RotationConfig("基准-无移动止盈-止损7%-持有120d", stop_pct=0.07, trailing=None, max_hold_days=120,
                       chase_ban_pct=CHASE_BAN_PCT),
        RotationConfig("固定回撤7%-止损7%-持有120d", stop_pct=0.07, trailing={"flat": 0.07}, max_hold_days=120,
                       chase_ban_pct=CHASE_BAN_PCT),
        RotationConfig("分级回撤5/7/10/12-止损7%-120d", stop_pct=0.07,
                       trailing={"ladder": [(8, 0.05), (15, 0.07), (25, 0.10), (999, 0.12)]},
                       max_hold_days=120, chase_ban_pct=CHASE_BAN_PCT),
        RotationConfig("分级回撤-止损5%-120d", stop_pct=0.05,
                       trailing={"ladder": [(8, 0.05), (15, 0.07), (25, 0.10), (999, 0.12)]},
                       max_hold_days=120, chase_ban_pct=CHASE_BAN_PCT),
        RotationConfig("分级回撤-止损10%-120d", stop_pct=0.10,
                       trailing={"ladder": [(8, 0.05), (15, 0.07), (25, 0.10), (999, 0.12)]},
                       max_hold_days=120, chase_ban_pct=CHASE_BAN_PCT),
        RotationConfig("分级回撤-止损7%-60d", stop_pct=0.07,
                       trailing={"ladder": [(8, 0.05), (15, 0.07), (25, 0.10), (999, 0.12)]},
                       max_hold_days=60, chase_ban_pct=CHASE_BAN_PCT),
        # 收盘价买入口径 (trade_detail 同源): buy_at_open=False
        RotationConfig("分级回撤-止损7%-120d-收盘买", stop_pct=0.07,
                       trailing={"ladder": [(8, 0.05), (15, 0.07), (25, 0.10), (999, 0.12)]},
                       max_hold_days=120, buy_at_open=False, chase_ban_pct=CHASE_BAN_PCT),
    ]

    results = []
    for cfg in configs:
        print(f"\n🔄 运行: {cfg.name}")
        trades, eq = simulate_from_trades(cands, stocks_data, sh_records, cfg)
        s = summarize(trades, eq, cfg)
        results.append(s)
        if trades:
            print(f"  ✅ {len(trades)}笔 胜率{s['win_rate']:.1f}% 总收益{s['total_return_pct']:+.1f}% "
                  f"年化{s['annual_pct']:+.1f}% 回撤{s['max_drawdown_pct']:.1f}% "
                  f"盈亏比{s['profit_factor']:.2f} 平均持有{s['avg_hold_days']}日")
            print(f"     退出分布: {s['reasons']}")

    # ── P0-2 (2026-08-09): raw 阈值子集验证 (候选池质量盲区, 二轮审查: 85太严→70/75/85三档) ──
    print("\n" + "=" * 68)
    print("  🔬 P0-2: raw 阈值子集验证 (实盘 P1_MIN_RAW 敏感性)")
    print("=" * 68)
    # 只跑分级回撤主变体 (每档7个变体×3档=21次, 只保留核心对比)
    subset_cfgs = [cfg for cfg in configs if "分级回撤5/7/10/12" in cfg.name]
    for min_raw in (70, 75, 85):
        cands_hi = load_candidates(min_raw=min_raw)
        print(f"\n  📊 raw≥{min_raw}: {len(cands_hi)} 个扫描日 (全量 {len(cands)} 中)")
        if not cands_hi:
            print("  ⚠️ 候选为空, 跳过")
            continue
        for cfg in subset_cfgs:
            trades, eq = simulate_from_trades(cands_hi, stocks_data, sh_records, cfg)
            s = summarize(trades, eq, cfg)
            s["subset"] = "raw>=%d" % min_raw
            results.append(s)
            if trades:
                print(f"    [{s['subset']}] {cfg.name}: {len(trades)}笔 胜率{s['win_rate']:.1f}% "
                      f"总收益{s['total_return_pct']:+.1f}% 年化{s['annual_pct']:+.1f}% "
                      f"回撤{s['max_drawdown_pct']:.1f}% 盈亏比{s['profit_factor']:.2f} "
                      f"平均持有{s['avg_hold_days']}日")
                print(f"      退出分布: {s['reasons']}")
            else:
                print(f"    [{s['subset']}] {cfg.name}: ⚠️ 无交易")

    out = {
        "type": "rotation_from_trades",
        "generated": str(datetime.now()),
        "candidate_source": TRADE_CSV,
        "init_capital": INIT_CAPITAL,
        "results": results,
    }
    path = os.path.join(SCRIPT_DIR, "data", "rotation_from_trades_result.json")
    atomic_json.atomic_dump(out, path, ensure_ascii=False, indent=2, encoding="utf-8")
    print(f"\n💾 结果已保存: {path}")


if __name__ == "__main__":
    main()
