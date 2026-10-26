import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
持仓复盘工具 v2.0 — 基于 tdx_core + holdings.json (Supabase 优先)
"""
import json
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from core.pipeline.tdx_core import get_tdx_data, compute_indicators, compute_weekly_indicators, calc_trailing_stop

# P0修复(2026-09-25): 真源统一到 data/holdings.json (根目录文件是陈旧空壳, 曾致空仓门禁失效)
HOLDINGS_FILE = os.path.join(PROJECT_ROOT, "data", "holdings.json")

# 尝试导入 Supabase 数据层（失败则降级）
try:
    from supabase_data import load_holdings as sb_load_holdings, is_connected as sb_connected
    _HAS_SB = True
except ImportError:
    _HAS_SB = False


def load_holdings():
    """从 Supabase 或本地 holdings.json 读取持仓"""
    # 首选 Supabase
    if _HAS_SB and sb_connected():
        data = sb_load_holdings()
        if data:
            holdings_list = data.get("holdings", [])
            if holdings_list:
                return holdings_list, data.get("total_assets"), data.get("available_cash", 0)

    # 降级到本地文件
    if not os.path.exists(HOLDINGS_FILE):
        print("📝 首次使用，创建持仓模板 holdings.json ...")
        template = {
            "holdings": [
                {"code": "sz002415", "name": "海康威视", "cost": 0.0, "shares": 0},
            ],
            "total_assets": 0.0,
            "available_cash": 0.0,
        }
        try:
            from core.pipeline.atomic_json import atomic_dump
            atomic_dump(template, HOLDINGS_FILE)
        except Exception as _e:
            # P0-1修复: 原子写失败时不再退到裸open("w"), 打warning告知用户手动建文件
            # 此为首次初始化场景, 若atomic失败说明锁/IO有问题, 裸写并发可能覆盖后续真实持仓
            import logging as _lg
            _lg.getLogger("portfolio_review").warning(
                "【P0-1修复】holdings.json 初始化模板原子写失败, 未创建文件(避免并发覆盖风险): %s\n  请手动创建: %s",
                _e, HOLDINGS_FILE, exc_info=True)
            print(f"  ⚠️  创建失败, 请手动编辑该文件填入持仓")
            return None
        print(f"  ✅ 已创建: {HOLDINGS_FILE}")
        print(f"  ✏️  请编辑该文件，填入你的实际持仓后重新运行")
        return None
    try:
        with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"❌ 持仓文件解析失败: {e}")
        print(f"   文件: {HOLDINGS_FILE}")
        print(f"   请检查 JSON 格式是否正确")
        return None
    # 兼容两种格式：数组 或 {total_assets, available_cash, holdings:[]}
    if isinstance(data, dict):
        return data.get("holdings", []), data.get("total_assets"), data.get("available_cash", 0)
    return data, None, 0


def analyze_single_stock(code, name, cost_price, shares):
    """分析单只持仓股票"""
    print(f"\n{'='*68}")
    print(f"  📊 {code} {name}")
    print(f"  {'='*68}")

    records = get_tdx_data(code, 150)
    if not records or len(records) < 20:
        print(f"  ❌ 数据不足，无法分析")
        return None

    inds = compute_indicators(records)
    if not inds:
        print(f"  ❌ 指标计算失败")
        return None

    price = inds["price"]
    market_value = price * shares
    cost_total = cost_price * shares
    pl_amount = market_value - cost_total
    pl_pct = (price - cost_price) / cost_price * 100

    # ── 持仓盈亏 ──
    print(f"\n  💰 持仓盈亏:")
    pl_sym = "+" if pl_amount >= 0 else ""
    print(f"     成本: {cost_price:.3f} x {shares}股 = {cost_total:.2f}元")
    print(f"     现价: {price:.2f}  |  市值: {market_value:.2f}元")
    print(f"     盈亏: {pl_sym}{pl_amount:.2f}元 ({pl_sym}{pl_pct:.2f}%)")

    # ── 技术指标 ──
    print(f"\n  📈 技术指标:")
    parts = [f"MA5={inds['ma5']:.2f}", f"MA10={inds['ma10']:.2f}", f"MA20={inds['ma20']:.2f}"]
    if inds.get("ma60"):  parts.append(f"MA60={inds['ma60']:.2f}")
    if inds.get("ma120"): parts.append(f"MA120={inds['ma120']:.2f}")
    print(f"    均线: {' | '.join(parts)}")

    # 均线形态
    ma_sigs = []
    if inds["ma5"] and inds["ma10"] and inds["ma20"]:
        if inds["ma5"] > inds["ma10"] > inds["ma20"]:
            ma_sigs.append("✅ 均线多头排列")
        elif inds["ma5"] > inds["ma10"]:
            ma_sigs.append("📈 短期均线向上")
        elif inds["ma5"] < inds["ma10"] < inds["ma20"]:
            ma_sigs.append("🔻 均线空头排列")
        else:
            ma_sigs.append("⚖️ 均线交叉震荡")
    if inds["ma60"]:
        ma_sigs.append("✅ 站上MA60" if price > inds["ma60"] else "⚠️ 低于MA60")

    print(f"     MACD: DIF={inds['dif']:.3f} | DEA={inds['dea']:.3f} | 柱={inds['macd_hist']:.3f}", end="")
    d, e, h = inds["dif"], inds["dea"], inds["macd_hist"]
    if d is not None and e is not None and h is not None:
        macd_sig = "✅ 金叉+红柱" if (d > e and h > 0) else ("📈 金叉" if d > e else "🔻 死叉")
        print(f" ({macd_sig})")
    else:
        print()

    print(f"     RSI: RSI6={inds['rsi6']:.0f} | RSI14={inds['rsi14']:.0f} | RSI24={inds['rsi24']:.0f}")
    print(f"     KDJ: K={inds['kdj_k']:.0f} D={inds['kdj_d']:.0f} J={inds['kdj_j']:.0f}", end="")
    if inds["kdj_k"] > inds["kdj_d"] and inds["kdj_j"] < 100:
        print(" (📈 KDJ金叉)", end="")
    elif inds["kdj_k"] < inds["kdj_d"]:
        print(" (🔻 KDJ死叉)", end="")
    print()

    print(f"     量比: {inds['vol_ratio']:.1f}  |  偏离20日线: {inds['pos_vs_ma20']:+.1f}%")
    print(f"     涨幅: 1日{inds['chg1']:+.2f}% | 5日{inds['chg5']:+.1f}% | 10日{inds['chg10']:+.1f}%")

    # ATR
    if inds.get("atr"):
        print(f"     ATR(14): {inds['atr']:.3f}")

    # 量价形态
    vp = inds.get("vol_pattern")
    if vp:
        print(f"     量价形态: {vp} ({inds.get('vol_pattern_detail', '')})")

    # 周线
    weekly = compute_weekly_indicators(records)
    if weekly:
        w_sigs = []
        if weekly.get("w_bullish"):
            w_sigs.append("周线多头")
        if weekly.get("w_hist") and weekly["w_hist"] > 0:
            w_sigs.append("周MACD红柱")
        elif weekly.get("w_hist") and weekly["w_hist"] < 0:
            w_sigs.append("周MACD绿柱")
        if w_sigs:
            print(f"     周线: {' | '.join(w_sigs)}")

    # ── 信号汇总 ──
    print(f"\n  🔔 信号:")
    for s in ma_sigs:
        print(f"    {s}")
    if d is not None and e is not None and h is not None:
        sig = "✅ MACD金叉+红柱" if (d > e and h > 0) else ("📈 MACD金叉" if d > e else "🔻 MACD死叉")
        print(f"    {sig}")
    if inds["rsi14"] > 70:
        print(f"    ⚠️ RSI{inds['rsi14']:.0f} 超买区间")
    elif inds["rsi14"] < 30:
        print(f"    ⚠️ RSI{inds['rsi14']:.0f} 超卖区间")
    elif 45 <= inds["rsi14"] <= 75:
        print(f"    ✅ RSI{inds['rsi14']:.0f} 强势区间")
    if inds["vol_ratio"] > 1.5:
        print(f"    📊 放量{inds['vol_ratio']:.1f}倍")
    if inds["pos_vs_ma20"] > 20:
        print(f"    ⚠️ 偏离20日线+{inds['pos_vs_ma20']:.1f}%，追高风险")
    elif 0 < inds["pos_vs_ma20"] < 15:
        print(f"    ✅ 站上20日线+{inds['pos_vs_ma20']:.1f}%")

    # ── 止盈止损 ──
    rec60 = get_tdx_data(code, 60)
    ts = calc_trailing_stop(rec60, atr_multiplier=2.0) if rec60 else None
    if ts:
        print(f"\n  🎯 止盈止损参考 (以当前价{price:.2f}为基准):")
        if ts.get("atr"):
            print(f"     📐 ATR(14): {ts['atr']} (自适应波动率)")
        print(f"     🛑 固定止损: {price * 0.92:.2f} (-8%)")
        if ts.get("atr_stop"):
            print(f"     🛡️ ATR止损: {ts['atr_stop']:.2f} (高波动自动加宽)")
        print(f"     🛑 最终止损: {ts['stop_loss']:.2f} (取较宽值)")
        print(f"     📍 均线支撑: {ts['support']:.2f}")
        print(f"     🔄 移动止盈: {ts['trailing_stop']:.2f} (自高点回撤8%)")
        print(f"     🎯 TP1: {ts['tp1_5%']:.2f} +5% ->减1/3")
        print(f"     🎯 TP2: {ts['tp2_10%']:.2f} +10% ->再减1/3")
        print(f"     🎯 TP3: {ts['tp3_15%']:.2f} +15% ->余仓持有")
        print(f"     🎯 TP4: {ts['tp_final_20%']:.2f} +20% ->全部止盈")

    # ── 操作建议 ──
    print(f"\n  💡 操作建议 [{code}]:")
    if pl_pct < -10:
        print(f"     🔴 {name}浮亏超10%，需设好止损")
        print(f"     建议: 若跌破MA20/MA10考虑减仓")
    elif pl_pct < -5:
        print(f"     🟡 小幅浮亏，关注支撑位")
        print(f"     建议: 以MA10或-7%为硬止损")
    elif pl_pct < 5:
        print(f"     🟢 接近成本价，持有观察")
        print(f"     建议: 站稳MA5/MACD金叉则持有")
    elif pl_pct < 15:
        print(f"     🟢 盈利中，可启动移动止盈")
        print(f"     建议: 涨超5%后启动移动止盈")
    else:
        print(f"     🟢 盈利可观，注意锁定利润")
        print(f"     建议: 分批止盈TP1/TP2/TP3")

    return {
        "code": code, "name": name,
        "price": price, "cost_price": cost_price,
        "shares": shares, "market_value": market_value,
        "pl_amount": pl_amount, "pl_pct": pl_pct,
        "inds": inds,
    }


def main():
    print("=" * 68)
    print("   📋 实盘持仓复盘报告")
    print(f"   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 68)

    holdings, total_assets, available_cash = load_holdings()
    if holdings is None:
        return

    # 逐个分析
    results = []
    for h in holdings:
        r = analyze_single_stock(
            h["code"], h.get("name", h["code"]),
            h.get("cost", h.get("cost_price", 0)), h["shares"]
        )
        if r:
            results.append(r)

    if not results:
        print("\n❌ 没有可分析的持仓")
        return

    # ── 总体资产状况 ──
    total_market_value = sum(r["market_value"] for r in results)
    total_cost = sum(r["cost_price"] * r["shares"] for r in results)
    total_pl = sum(r["pl_amount"] for r in results)
    total_pl_pct = total_pl / total_cost * 100 if total_cost > 0 else 0

    # 如果 holdings.json 没有提供总资产，从市值+现金推算
    if total_assets is None:
        total_assets = total_market_value + available_cash

    print(f"\n{'='*68}")
    print(f"  📊 总体资产状况")
    print(f"  {'='*68}")
    print(f"     总资产: {total_assets:.2f}元")
    print(f"     可用资金: {available_cash:.2f}元")
    print(f"     持仓市值: {total_market_value:.2f}元")
    print(f"     持仓成本: {total_cost:.2f}元")
    pl_sym = "+" if total_pl >= 0 else ""
    print(f"     总盈亏: {pl_sym}{total_pl:.2f}元 ({pl_sym}{total_pl_pct:.1f}%)")
    print()

    # ── 仓位分布 ──
    print(f"  📊 仓位分布:")
    for r in results:
        pct = r["market_value"] / total_assets * 100
        ps = "+" if r["pl_amount"] >= 0 else ""
        print(f"     {r['code']} {r['name']}: {r['market_value']:.2f}元 ({pct:.1f}%) | "
              f"盈亏{ps}{r['pl_amount']:.2f}元 ({ps}{r['pl_pct']:.2f}%)")

    used_ratio = total_market_value / total_assets * 100
    print(f"     仓位占比: {used_ratio:.1f}%")
    print(f"     现金占比: {available_cash / total_assets * 100:.1f}%")
    if used_ratio > 80:
        print(f"     ⚠️ 仓位偏重，建议控制风险")
    elif used_ratio < 30:
        print(f"     📌 仓位偏轻，可适当加仓")

    # ── 多空信号汇总 ──
    print(f"\n  📋 多空信号汇总:")
    for r in results:
        i = r["inds"]
        bull = bear = 0
        if i["ma5"] and i["ma10"] and i["ma20"]:
            if i["ma5"] > i["ma10"] > i["ma20"]: bull += 2
            elif i["ma5"] < i["ma10"] < i["ma20"]: bear += 2
        if i["dif"] and i["dea"] and i["dif"] > i["dea"]: bull += 1
        elif i["dif"] and i["dea"]: bear += 1
        if i["macd_hist"] and i["macd_hist"] > 0: bull += 1
        elif i["macd_hist"] and i["macd_hist"] < 0: bear += 1
        if i["rsi14"] > 60: bull += 1
        elif i["rsi14"] < 40: bear += 1
        if i["vol_ratio"] > 1.2: bull += 1
        if i["pos_vs_ma20"] > 20: bear += 1

        sentiment = "🟢 偏多" if bull > bear else ("🔴 偏空" if bear > bull else "🟡 中性")
        print(f"     {r['code']} {r['name']}: {sentiment} (多{bull} | 空{bear})")

    print(f"\n{'='*68}")
    print(f"  ⚠️ 以上分析仅基于技术指标，不构成投资建议")
    print(f"  📌 实际交易请结合个人风险承受能力")
    print(f"{'='*68}")


if __name__ == "__main__":
    main()
