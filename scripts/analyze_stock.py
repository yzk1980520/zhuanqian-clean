# -*- coding: utf-8 -*-
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""个股查询工具 (只读, 不影响系统运行)
用法: python analyze_stock.py 600267 [600276 ...]
数据: TDX本地日线(技术面) + 新浪实时行情 + 财务联网强制刷新 + FTShare资金流 + 估值
不写 trade_log / 不触发 cron / 不改系统配置。查询结果标注数据时效。
"""
import sys, io, os, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.pipeline.tdx_core import get_tdx_data, compute_indicators, compute_weekly_indicators, fetch_realtime_prices

def prefix_code(c):
    c = str(c).strip().lower()
    if c.startswith(("sh", "sz", "bj")):
        return c
    if c.startswith("6"):
        return "sh" + c
    if c.startswith(("0", "3")):
        return "sz" + c
    if c.startswith(("4", "8")):
        return "bj" + c
    return "sh" + c

def f(v, nd=2):
    return "None" if v is None else f"{v:.{nd}f}"

def analyze_one(raw_code):
    code = prefix_code(raw_code)
    print("=" * 64)
    print(f"📊 个股查询: {raw_code} ({code})  时间 {datetime.datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 64)

    # ── 1. 实时行情 (新浪, 联网) ──
    try:
        rt = fetch_realtime_prices([code]).get(code, {})
        if rt.get("price"):
            print(f"\n🟢 实时行情: 现价 {rt['price']:.2f}  ({rt['chg_pct']:+.2f}%)  "
                  f"开 {rt.get('open', 0):.2f} 高 {rt.get('high', 0):.2f} 低 {rt.get('low', 0):.2f}  昨收 {rt.get('prev_close', 0):.2f}")
        else:
            print("\n🟢 实时行情: 无数据(盘前/停牌, 视同昨收)")
    except Exception as e:
        print(f"\n⚠️ 实时行情失败: {e}")

    # ── 2. 技术面 (TDX本地日线) ──
    recs = get_tdx_data(code, 120)
    if not recs:
        print("\n❌ TDX 无本地数据 (该股可能新股/次新, 尝试扩展库)")
        from backtest import get_extended_data
        recs = get_extended_data(code)
    if not recs:
        print("❌ 无法获取K线, 跳过技术面")
        return
    inds = compute_indicators(recs)
    print(f"\n── 技术面 (TDX日线 {len(recs)}条, 最新 {recs[-1]['date']}) ──")
    if inds:
        for k in ["ma5", "ma10", "ma20", "ma60", "dif", "dea", "r6", "r14", "r24",
                  "c1", "c5", "c10", "c20", "vr", "std20", "max_ret5"]:
            if k in inds:
                print(f"  {k:>8} = {f(inds[k])}")
    c = [r["close"] for r in recs]
    cur = c[-1]
    h20 = max(r["high"] for r in recs[-20:])
    h60 = max(r["high"] for r in recs[-60:]) if len(recs) >= 60 else h20
    print(f"  现价 {cur:.2f} | 20日高 {h20:.2f} (回撤 {(1-cur/h20)*100:.1f}%) | 60日高 {h60:.2f} (回撤 {(1-cur/h60)*100:.1f}%)")
    print("  近5日:", " ".join(f"{r['date']}:{r['close']:.2f}" for r in recs[-5:]))
    wk = compute_weekly_indicators(recs) or {}
    print(f"  周线: bullish={wk.get('weekly_bullish')} macd_red={wk.get('weekly_macd_red')} "
          f"w_ma5={f(wk.get('w_ma5'))} w_ma10={f(wk.get('w_ma10'))}")

    # ── 3. 财务 (联网强制刷新, 只读缓存写入=刷新该股条目) ──
    print("\n── 财务 (联网强制刷新) ──")
    try:
        from financial_filter import score_stock_financial
        fin = score_stock_financial(str(raw_code).zfill(6), force_refresh=True)
        print(f"  health={fin.get('financial_health')} fraud={fin.get('fraud_penalty')} "
              f"fatal={fin.get('fraud_fatal')} total={fin.get('total_bonus')} status={fin.get('data_status')}")
        for s in fin.get("health_signals", [])[:10]:
            print(f"    {s}")
        for s in fin.get("fraud_signals", [])[:10]:
            print(f"    {s}")
        if fin.get("data_status") == "missing":
            print("  ⚠️ 财务数据缺失(接口失败) — 评分降权处理")
    except Exception as e:
        print(f"  ⚠️ 财务评分失败: {e}")

    # ── 4. 资金流 (FTShare, 拉分页本地匹配 — 带symbol单查会超时) ──
    print("\n── 资金流 (FTShare) ──")
    try:
        from ft_adapter import ft_capital_flows
        digits = str(raw_code).zfill(6)
        ext_sym = f"{digits}.SH" if code.startswith("sh") else (f"{digits}.SZ" if code.startswith("sz") else f"{digits}.BJ")
        found = None
        for pg in (1, 2, 3):
            cap = ft_capital_flows(page=pg, page_size=50)
            items = cap.get("items", []) if isinstance(cap, dict) else []
            if not items:
                break
            for it in items:
                if it.get("symbol") == ext_sym:
                    found = it
                    break
            if found:
                break
        if found:
            def wan(v):
                try:
                    return f"{float(v)/1e8:.2f}亿"
                except Exception:
                    return str(v)
            print(f"  主力净流入: {wan(found.get('net_inflow_main'))}")
            print(f"    超大单: {wan(found.get('net_inflow_extra_large'))}  大单: {wan(found.get('net_inflow_large'))}")
            print(f"    中单: {wan(found.get('net_inflow_medium'))}  小单: {wan(found.get('net_inflow_small'))}")
        else:
            print(f"  (该股不在主力净流入 TOP150, 资金面弱或数据延迟)")
    except Exception as e:
        print(f"  ⚠️ 资金流失败: {e}")

    # ── 5. 估值 (FTShare eastmoney-stock-valuation) ──
    print("\n── 估值 (FTShare) ──")
    try:
        from ft_adapter import ft_stock_valuation
        info = ft_stock_valuation(str(raw_code).zfill(6))
        rec = None
        if isinstance(info, dict):
            d = info.get("data") or {}
            recs_ = d.get("records") or []
            for r in recs_:
                if str(r.get("stock_code")).zfill(6) == str(raw_code).zfill(6):
                    rec = r
                    break
            if rec is None and recs_:
                rec = recs_[0]
        if rec:
            print(f"  PE(TTM): {rec.get('pe_ttm')}  PB: {rec.get('pb_mrq')}  PS(TTM): {rec.get('ps_ttm')}")
            print(f"  市值: {float(rec.get('total_market_cap', 0) or 0)/1e8:.1f}亿  换手/涨幅: {rec.get('change_rate')}%  ({rec.get('trade_date')})")
        else:
            print("  (无估值数据)")
    except Exception as e:
        print(f"  ⚠️ 估值失败: {e}")

    print("\n  ⚠️ 时效说明: 技术面=TDX本地最新收盘; 实时=新浪联网; 财务=联网刷新(可能仍缺最新季报); 资金/估值=FTShare")
    print()

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    codes = sys.argv[1:]
    if not codes:
        print("用法: python analyze_stock.py 600267 [600276 ...]")
        sys.exit(0)
    for c in codes:
        analyze_one(c)
