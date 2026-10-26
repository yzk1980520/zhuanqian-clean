import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""板块轮动分析 — 自上而下选股模块
识别热点板块→精选龙头股→结合选股系统评分
数据源: TDX行业热度 + MCP mx-ds-mcp 板块数据 + 资金流
"""
import os, sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, PROJECT_ROOT)  # P1修复(20261023): S4迁移后误插core/pipeline/, 改仓库根
from core.pipeline.tdx_core import (
    get_industry_heat,
    get_tdx_data, compute_indicators, compute_weekly_indicators,
    score_stock, load_strategy,
    load_name_cache, load_industry_map, get_industry as get_ind_name,
)

try:
    from stock_pipeline import super_stock_classify, mcp_news_sentiment
except ImportError:
    super_stock_classify = None
    mcp_news_sentiment = None

def sector_rotation_analysis(top_sectors=10, stocks_per_sector=3, strategy_name=None):
    """板块轮动分析：找热点板块→精选龙头→评分排序
    返回: [{"sector": name, "rank": N, "heat_score": float,
           "stocks": [(code, name, score, ...), ...]}, ...]
    """
    print("=" * 68)
    print(f"  🔄 板块轮动分析")
    print(f"  {'─'*64}")
    print(f"  数据源: TDX行业热度 + MCP板块数据 + 资金流")
    print(f"{'='*68}")

    # Step 1: 获取行业板块热度
    print(f"\n📡 [1/3] 行业板块热度排名...")
    heat_dict = get_industry_heat()
    if not heat_dict:
        print("  ⚠️ 板块热度数据不可用")
        return []

    # 排除别名映射
    alias = heat_dict.pop("__alias__", {})
    sectors = [(name, info) for name, info in heat_dict.items()
               if isinstance(info, dict) and "percentile" in info]
    sectors.sort(key=lambda x: x[1]["percentile"], reverse=True)
    print(f"  ✅ 获取 {len(sectors)} 个行业板块热度")
    print(f"  🔥 热门: {', '.join(s[0] for s in sectors[:5])}")
    print(f"  🧊 冷门: {', '.join(s[0] for s in sectors[-5:])}")

    # Step 2: 扫描本地股票，按行业分类
    print(f"\n📡 [2/3] 扫描本地TDX，按行业分类...")
    strategy, sn = load_strategy(strategy_name or "综合")
    cache = load_name_cache()
    ind_cache = load_industry_map()

    sector_stocks = {}
    for market in ["sh", "sz"]:
        day_dir = os.path.join(r"D:\TDX\vipdoc", market, "lday")
        if not os.path.isdir(day_dir):
            continue
        for f in os.listdir(day_dir):
            if not f.endswith(".day"):
                continue
            code = f.replace(".day", "")
            from core.pipeline.tdx_core import should_include, is_st_stock
            if not should_include(code):
                continue
            name = cache.get(code, "")
            if is_st_stock(name):
                continue
            industry = get_ind_name(code, name, ind_cache)
            if not industry or industry not in heat_dict:
                continue
            # 只关注热点板块
            heat_info = heat_dict.get(industry, {})
            if not isinstance(heat_info, dict):
                continue
            if industry not in sector_stocks:
                sector_stocks[industry] = {"heat": heat_info, "stocks": []}
            sector_stocks[industry]["stocks"].append((code, name))

    # Step 3: 对每个热点板块的股票评分
    print(f"\n🔍 [3/3] 精选龙头...")
    results = []
    for sector, info in sorted(sector_stocks.items(),
                                key=lambda x: x[1]["heat"].get("percentile", 0),
                                reverse=True)[:top_sectors]:
        scored_stocks = []
        for code, name in info["stocks"][:stocks_per_sector * 3]:  # 多取一些以备筛选
            records = get_tdx_data(code, 200)
            if not records or len(records) < 30:
                continue
            inds = compute_indicators(records)
            weekly = compute_weekly_indicators(records)
            if not inds:
                continue
            inds["industry"] = sector
            sc, sigs = score_stock(inds, weekly, strategy)
            if sc > 0:
                scored_stocks.append({
                    "code": code, "name": name, "score": sc,
                    "price": inds["price"],
                    "rsi": inds["rsi14"],
                    "chg5": inds["chg5"],
                    "vol_ratio": inds["vol_ratio"],
                })
        scored_stocks.sort(key=lambda x: x["score"], reverse=True)
        top = scored_stocks[:stocks_per_sector]
        if top:
            results.append({
                "sector": sector,
                "heat_pct": info["heat"].get("percentile", 0),
                "heat_label": _heat_label(info["heat"].get("percentile", 0.5)),
                "stocks": top,
            })

    # 输出报告
    results.sort(key=lambda x: x["heat_pct"], reverse=True)
    print(f"\n{'='*68}")
    print(f"  🏆 板块轮动推荐 (Top {len(results)} 板块)")
    print(f"{'='*68}")
    for r in results[:5]:
        print(f"\n  {r['heat_label']} {r['sector']} (热度{r['heat_pct']:.0%})")
        for s in r["stocks"][:2]:
            print(f"     {s['code']} {s['name']:>8}  "
                  f"评分{s['score']}  RSI={s['rsi']:.0f}  "
                  f"5日{s['chg5']:+.1f}%  量比{s['vol_ratio']:.1f}")

    return results

def _heat_label(pct):
    if pct >= 0.8: return "🔥🔥"
    if pct >= 0.6: return "🔥"
    if pct <= 0.2: return "🧊"
    return "📊"

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="板块轮动分析")
    parser.add_argument("--top", type=int, default=10, help="分析多少个板块")
    parser.add_argument("--per", type=int, default=3, help="每板块选几只")
    args = parser.parse_args()
    sector_rotation_analysis(top_sectors=args.top, stocks_per_sector=args.per)
