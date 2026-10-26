import core.pipeline.atomic_json as atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
优化版选股系统 v4.2 — TDX全量扫描 + 行业热度 + 资金流 + 华泰数据 + 情绪评分 + 交易日志 + 多Agent并行模式
⚠️ 备用选股器, 主链路用integrated_picker
"""
import os, time, json, csv
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, date
from core.pipeline.tdx_core import (
    get_tdx_data, get_latest_tdx_date, should_include, is_st_stock,
    load_name_cache, batch_fetch_names,
    compute_indicators, compute_weekly_indicators,
    score_stock, load_strategy, fetch_realtime_prices,
    get_industry, load_industry_map,
    calc_trailing_stop, format_stop_advice,
    analyze_market, compute_swing_analysis,
    get_industry_heat, get_fund_flow_bonus_for_stocks,
    VIPDOC, ALLOWED_PREFIXES_SH, ALLOWED_PREFIXES_SZ, STRATEGIES,
)
def validate_lot(shares):
    if shares % 100 != 0:
        shares = (shares // 100 + 1) * 100
    return shares

try:
    from core.pipeline.parallel_workers import parallel_enrich, merge_and_rerank
    _HAS_PARALLEL = True
except ImportError:
    _HAS_PARALLEL = False
try:
    from core.ops.trade_tracker import auto_log_recommendation
    _HAS_TRADE_LOG = True
except ImportError:
    _HAS_TRADE_LOG = False
try:
    from news_sentiment import get_sector_bonus_for_all
    _HAS_NEWS_SENTIMENT = True
except ImportError:
    _HAS_NEWS_SENTIMENT = False

try:
    from market_sentiment_integrator import assess_market_mood, sentiment_enrich_stock
    _HAS_SENTIMENT = True
except ImportError:
    _HAS_SENTIMENT = False
try:
    from huatai_data import huatai_enrich_stocks, get_remaining_calls
    _HAS_HUATAI = True
except ImportError:
    _HAS_HUATAI = False

# ── 申万行业映射加载 ──
_sw_industry_map = None
def load_sw_industry_map():
    global _sw_industry_map
    if _sw_industry_map is not None:
        return _sw_industry_map
    map_file = os.path.join(PROJECT_ROOT, "sw_industry_map.json")  # P1修复(20261023): S4迁移锚点漂移, sw_industry_map.json在仓库根
    if os.path.exists(map_file):
        try:
            with open(map_file, "r", encoding="utf-8") as f:
                _sw_industry_map = json.load(f)
            print(f"  ✅ 申万行业映射已加载: 精确映射{len(_sw_industry_map.get('exact', {}))}只, 偏好板块{len(_sw_industry_map.get('preferred', []))}个")
        except Exception as e:
            print(f"  ⚠️ 申万行业映射加载失败: {e}")
            _sw_industry_map = {"exact": {}, "prefix_rules": {}, "preferred": [], "excluded": []}
    else:
        _sw_industry_map = {"exact": {}, "prefix_rules": {}, "preferred": [], "excluded": []}
    return _sw_industry_map

def get_sw_industry(code):
    """获取股票的申万二级行业"""
    sw_map = load_sw_industry_map()
    exact = sw_map.get("exact", {})
    if code in exact:
        return exact[code]
    if code[-6:] in exact:
        return exact[code[-6:]]
    # 前缀推断
    prefix_rules = sw_map.get("prefix_rules", {})
    for prefix, industry in prefix_rules.items():
        if code.startswith(prefix):
            return industry
    return "其他"

def is_preferred_industry(industry):
    """判断是否为用户偏好板块"""
    sw_map = load_sw_industry_map()
    preferred = sw_map.get("preferred", [])
    for p in preferred:
        if p in industry:
            return True
    return False

def is_excluded_industry(industry):
    """判断是否为排除板块"""
    sw_map = load_sw_industry_map()
    excluded = sw_map.get("excluded", [])
    for e in excluded:
        if e in industry:
            return True
    return False

# ── 超级股票分类模型（回退实现） ──
try:
    # 优先从stock_pipeline导入（如果存在）
    from stock_pipeline import super_stock_classify, check_data_quality
    _HAS_SUPER_MODEL = True
except Exception:
    # 本地定义回退实现
    def super_stock_classify(code, name, records):
        """超级股票分类模型（回退实现）"""
        return {"model": "综合型", "score": 70, "drawdown_pct": 12.0, "alignment": "震荡"}
    
    def check_data_quality(code, records):
        """数据质量检查（基础实现）- 返回列表形式的(sev, msg)元组"""
        if not records or len(records) < 30:
            return [("warning", "数据条数不足30天")]
        return []  # 无问题，返回空列表
    
    _HAS_SUPER_MODEL = False

CACHE_FILE = os.path.join(PROJECT_ROOT, "data", "scan_cache.json")  # P1修复(20261023): S4迁移锚点漂移, 改仓库根


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_cache(data):
    atomic_json.atomic_dump(data, CACHE_FILE, ensure_ascii=False, default=str, encoding="utf-8")


def export_csv(scored, filename=None):
    if not filename:
        top_code = scored[0][1] if scored else "all"
        filename = f"选股结果_{top_code}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    path = os.path.join(PROJECT_ROOT, filename)  # P1修复(20261023): 选股结果CSV写仓库根(原语义)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["排名", "代码", "名称", "评分", "行业", "现价", "MA5", "MA10",
                     "MA20", "MA60", "MACD", "RSI14", "KDJ", "量比",
                     "5日%", "10日%", "量价形态", "周线", "ATR"])
        for i, item in enumerate(scored, 1):
            sc, code, mkt, name, inds, sigs = item[:6]
            ma_str = f"{inds['dif']:.3f}" if inds.get("dif") else "-"
            weekly = "多" if any("周线" in s for s in sigs) else "-"
            vp = inds.get("vol_pattern") or "-"
            w.writerow([i, code, name[:10], sc, inds.get("industry",""),
                        f"{inds['price']:.2f}",
                        f"{inds['ma5']:.2f}" if inds.get("ma5") else "-",
                        f"{inds['ma10']:.2f}" if inds.get("ma10") else "-",
                        f"{inds['ma20']:.2f}" if inds.get("ma20") else "-",
                        f"{inds['ma60']:.2f}" if inds.get("ma60") else "-",
                        ma_str, f"{inds['rsi14']:.0f}",
                        f"{inds['kdj_k']:.0f}/{inds['kdj_d']:.0f}/{inds['kdj_j']:.0f}",
                        f"{inds['vol_ratio']:.1f}",
                        f"{inds['chg5']:+.1f}%", f"{inds['chg10']:+.1f}%",
                        vp, weekly,
                        f"{inds.get('atr',0):.3f}"])
    print(f"\n  📁 已导出: {path}")
    return path


def pick_stock(strategy_name=None):
    # ── 自动策略选择：如未指定策略，从市场情绪推荐 ──
    if strategy_name is None:
        try:
            from market_sentiment_integrator import assess_market_mood
            mood = assess_market_mood()
            recommended = mood.get("strategy", None)
            if recommended and recommended in STRATEGIES:
                strategy_name = recommended
                print(f"  🌡️ 市场情绪推荐策略: {strategy_name}")
        except Exception as e:
            print(f"  ⚠️ 市场情绪感知异常: {e}")
    strategy, sn = load_strategy(strategy_name)
    print("=" * 68)
    print(f"  🚀 选股系统 v4.2  |  策略: {sn}")
    print(f"  数据源: TDX + 新浪 | 行业 + 实时 + CSV导出 + 缓存 | 板块热度 + 资金流 (v4.2)")
    print("=" * 68)

    cache_data = load_cache()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if cache_data and cache_data.get("date") == now[:10]:
        scored = cache_data.get("results", [])
        print(f"\n📦 使用今日缓存: {len(scored)} 只 (如需刷新请删除 scan_cache.json)")
        scored = [tuple(x) for x in scored]
    else:
        print(f"\n📡 Step 1: 扫描本地TDX...")
        all_stocks = {}
        max_date = None
        stale_limit_days = 5
        for market, mname, prefixes in [
            ("sh", "上海", ALLOWED_PREFIXES_SH),
            ("sz", "深圳", ALLOWED_PREFIXES_SZ),
        ]:
            day_dir = os.path.join(VIPDOC, market, "lday")
            if os.path.isdir(day_dir):
                for f in os.listdir(day_dir):
                    if f.endswith(".day"):
                        code = f.replace(".day", "")
                        if should_include(code):
                            all_stocks[code] = mname
                            ld = get_latest_tdx_date(code)
                            if ld and (max_date is None or ld > max_date):
                                max_date = ld
            print(f"  [{mname}] {sum(1 for v in all_stocks.values() if v==mname)} 只")
        print(f"  ✅ 合计: {len(all_stocks)} 只 | 最新交易日: {max_date}")

        print(f"\n🔤 Step 2: 获取股票名称 + 行业...")
        cache = load_name_cache()
        ind_cache = load_industry_map()
        need_fetch = [c for c in all_stocks if c not in cache]
        if need_fetch:
            print(f"  📡 需要获取 {len(need_fetch)} 个...")
            batch_fetch_names(need_fetch, cache)
        cache = load_name_cache()
        print(f"  ✅ 已有 {len(cache)} 个股票名称")

        print(f"\n📈 Step 3: 技术评分 ({len(all_stocks)} 只, 策略={sn})...")
        scored = []
        t0 = time.time()
        excluded_st = 0
        excluded_stale = 0
        industry_counts = {}

        for i, (code, mkt) in enumerate(sorted(all_stocks.items()), 1):
            name = cache.get(code, "")
            if is_st_stock(name):
                excluded_st += 1
                if excluded_st == 1:
                    print(f"  🚫 排除ST股: {code}({name})...")
                continue
            ld = get_latest_tdx_date(code)
            if ld and max_date and (max_date - ld).days > stale_limit_days:
                excluded_stale += 1
                if excluded_stale == 1:
                    print(f"  排除停牌股: {code}({name}, 最新{ld})...")
                continue
            records = get_tdx_data(code, 200)
            if records and len(records) >= 30:
                            inds = compute_indicators(records)
                            weekly = compute_weekly_indicators(records)
                            if inds:
                                inds["industry"] = get_industry(code, name, ind_cache)

                                # P0-2: 基本面硬筛选 (PE/ROE/营收增速) - 使用华泰数据若可用
                                fundamental_ok = True
                                if _HAS_HUATAI and inds.get("huatai_available"):
                                    pe = inds.get("pe_ttm", 999)
                                    roe = inds.get("roe", 0)
                                    revenue_growth = inds.get("revenue_growth", 0)
                                    industry_pe_median = inds.get("industry_pe_median", 30)
                                    if pe > industry_pe_median * 1.5 or roe < 10 or revenue_growth < 0:
                                        fundamental_ok = False

                                if fundamental_ok:
                                    industry_counts[inds["industry"]] = industry_counts.get(inds["industry"], 0) + 1
                                    sc, sigs = score_stock(inds, weekly, strategy)
                                    if sc > 0:
                                        scored.append((sc, code, mkt, name, inds, sigs))
            if i % 500 == 0 or i == len(all_stocks):
                e = time.time() - t0
                print(f"   进度: {i}/{len(all_stocks)} | 已选{len(scored)}只 | {i/e:.0f}只/秒")

        scored.sort(key=lambda x: x[0], reverse=True)
        elapsed = time.time() - t0
        print(f"\n  ✅ 完成! 耗时{elapsed:.0f}s | {len(all_stocks)}只→筛选{len(scored)}只")
        print(f"  🚫 排除ST: {excluded_st}只 | ⏸️ 停牌/退市: {excluded_stale}只")

        try:
            def serialize_inds(d):
                r = {}
                for k, v in d.items():
                    if isinstance(v, date):
                        r[k] = v.isoformat()
                    else:
                        r[k] = v
                return r
            save_cache({"date": now[:10], "time": now, "strategy": sn,
                        "results": [[x[0], x[1], x[2], x[3],
                                     serialize_inds(x[4]),
                                     x[5]] for x in scored]})
        except Exception as e:
            print(f"    ⚠️ 缓存写入失败: {e}")

    if _HAS_NEWS_SENTIMENT and scored:
        try:
            scored_before = len(scored)
            if len(scored) > 20:
                try:
                    top20 = get_sector_bonus_for_all(scored[:20])
                except Exception:
                    top20 = scored[:20]
                scored_top = [(sc, code, mkt, name, inds, sigs) for sc, code, mkt, name, inds, sigs in top20]
                scored = scored_top + scored[20:]
            else:
                top_all = get_sector_bonus_for_all(scored)
                scored = [(sc, code, mkt, name, inds, sigs) for sc, code, mkt, name, inds, sigs in top_all]
            scored.sort(key=lambda x: x[0], reverse=True)
            print(f"  🔥 热点题材评分加成完成 (Top{min(20, scored_before)}只)")
        except Exception as e:
            print(f"  ⚠️ 热点题材评分异常 (不影响选股): {e}")

    if _HAS_SENTIMENT:
        try:
            from market_sentiment_integrator import sentiment_enrich_stock
            top_n = min(15, len(scored))
            print(f"  🌡️  KIMI情绪增强 (Top{top_n}只: 市场情绪+个股新闻)...")
            enhanced = 0
            for idx in range(top_n):
                item = list(scored[idx])
                sc, code, mkt, name, inds, sigs = item[:6]
                enh_sc, bonus, details = sentiment_enrich_stock(code, name, sc)
                if enh_sc != sc:
                    scored[idx] = (enh_sc, code, mkt, name, inds, sigs)
                    enhanced += 1
            if enhanced:
                scored.sort(key=lambda x: x[0], reverse=True)
                detail_str = details[0] if details else ''
                print(f"  ✅ 增强完成: {enhanced}只评分调整 {detail_str}")
        except Exception as e:
            print(f"  ⚠️ 情绪增强异常 (不影响选股): {e}")

    _market = analyze_market()
    _market_state = _market.get("market_state", "")
    try:
        heat_dict = get_industry_heat()
        if heat_dict:
            matched = 0
            alias = heat_dict.get("__alias__", {})
            for idx in range(len(scored)):
                item = list(scored[idx])
                sc, code, mkt, name, inds, sigs = item
                ind_name = inds.get("industry", "")
                if ind_name and ind_name in heat_dict:
                    heat_info = heat_dict[ind_name]
                    inds["industry_heat_bonus"] = heat_info["percentile"]
                    matched += 1
                elif ind_name and ind_name in alias:
                    heat_info = alias[ind_name]
                    inds["industry_heat_bonus"] = heat_info["percentile"]
                    matched += 1
                else:
                    inds["industry_heat_bonus"] = 0.5
            print(f"  🏭 板块热度匹配: {matched}/{len(scored)} 只")
        else:
            print(f"  ⚠️ 板块热度数据不可用")

        if len(scored) > 50:
            top50_codes = [(item[1], item[4].get("industry", "")) for item in scored[:50]]
        else:
            top50_codes = [(item[1], item[4].get("industry", "")) for item in scored]

        print(f"  📡 获取主力资金流向 (Top {len(top50_codes)} 只)...")
        fund_flow = get_fund_flow_bonus_for_stocks(top50_codes)
        flow_matched = 0
        for idx in range(min(50, len(scored))):
            item = list(scored[idx])
            sc, code, mkt, name, inds, sigs = item
            if code in fund_flow:
                fb = fund_flow[code]
                inds["fund_flow_bonus"] = fb["bonus"]
                inds["fund_flow_signal"] = fb["signal"]
                inds["fund_flow_5d"] = fb["main_net_5d"]
                inds["fund_flow_20d"] = fb["main_net_20d"]
                flow_matched += 1
        if flow_matched:
            print(f"  💰 资金流匹配: {flow_matched}/{len(top50_codes)} 只")

        rescored = 0
        for idx in range(min(50, len(scored))):
            item = list(scored[idx])
            sc, code, mkt, name, inds, sigs = item[:6]
            heat = inds.get("industry_heat_bonus", 0.5)
            heat_info = {"percentile": heat}
            fb = inds.get("fund_flow_bonus", 0)
            fs = inds.get("fund_flow_signal", "")
            new_sc, new_sigs = score_stock(
                inds, weekly=None, strategy=strategy,
                market_state=_market_state,
                bonuses={
                    "industry_heat": heat_info,
                    "fund_flow_bonus": fb,
                    "fund_flow_signal": fs,
                },
            )
            if new_sc > 0:
                scored[idx] = (new_sc, code, mkt, name, inds, new_sigs)
                rescored += 1

        scored.sort(key=lambda x: x[0], reverse=True)
        print(f"  🔄 重新评分: Top {rescored} 只 (含板块+资金流加分)")
    except Exception as e:
        print(f"  ⚠️ 板块/资金流评分异常 (不影响选股): {e}")

    if _HAS_HUATAI:
        try:
            remaining = get_remaining_calls()
            if remaining > 10:
                scored = huatai_enrich_stocks(scored, top_n=10, strategy_name=sn)
                enriched = sum(1 for item in scored[:10] if item[4].get("huatai_available"))
                after = get_remaining_calls()
                used = remaining - after
                print(f"  🏢 华泰数据: 丰富Top10 ({enriched}只有数据) | 今日剩余{after}次")
            else:
                print(f"  ⚠️ 华泰数据跳过: 今日剩余仅{remaining}次")
        except Exception as e:
            print(f"  ⚠️ 华泰数据异常 (不影响选股): {e}")
    else:
        print(f"  📡 华泰数据未安装 (huatai_data.py)")

    market = analyze_market(scored)
    print(f"\n{'='*68}")
    reason = market.get('reason', '数据不足')
    print(f"  📊 市场行情分析  |  {reason}")
    print(f"  {'─'*64}")
    idx_close = market.get('index_close', '?')
    idx_chg = market.get('index_chg', 0)
    idx_trend = market.get('index_trend', '?')
    idx_rsi = market.get('index_rsi', 0)
    macd_str = market.get('macd', '?')
    print(f"     上证: {idx_close}  ({idx_chg:+.2f}%)  "
          f"趋势={idx_trend}  RSI={idx_rsi:.0f}  "
          f"MACD={macd_str}")
    market_state = market.get('market_state', '未知')
    breadth = market.get('breadth', '未知')
    rec_strategy = market.get('recommended_strategy', '综合')
    print(f"     市场状态: {market_state}  |  宽度: {breadth}")
    print(f"     🏆 推荐策略: 【{rec_strategy}】— {reason}")
    print(f"  {'─'*64}")
    print(f"     策略适合度: ", end="")
    strategies_info = market.get("strategies", {"综合": {"suit": "中", "note": "默认"}})
    for sname, sinfo in strategies_info.items():
        icon = {"高": "✅", "中": "📊", "低": "⬜"}
        suit_val = sinfo.get('suit', '?') if isinstance(sinfo, dict) else '?'
        print(f"{icon.get(suit_val,'❓')}{sname}({suit_val}) ", end="")
    print()
    print(f"{'='*68}")

    ind_dist = {}
    for item in scored:
        ind = item[4].get("industry", "其他")
        ind_dist[ind] = ind_dist.get(ind, 0) + 1

    print(f"\n{'='*68}")
    print(f"  🏆 Top 3 最优推荐 (策略: {sn})")
    print(f"{'='*68}")

    for rank, item in enumerate(scored[:3], 1):
        sc, code, mkt, name, inds, sigs = item
        price = inds["price"]
        medal = ["🥇", "🥈", "🥉"][rank - 1]
        sl = "沪" if mkt == "上海" else "深"

        print(f"\n  {medal} [{rank}] {code} {name} ({sl})")
        print(f"  {'─'*64}")
        print(f"    评分: {sc}/100 | 行业: {inds.get('industry','?')}")
        print(f"    日期: {inds['latest_date']} | 现价: {price:.2f}")
        print()

        parts = [f"MA5={inds['ma5']:.2f}", f"MA10={inds['ma10']:.2f}", f"MA20={inds['ma20']:.2f}"]
        if inds.get("ma60"):  parts.append(f"MA60={inds['ma60']:.2f}")
        if inds.get("ma120"): parts.append(f"MA120={inds['ma120']:.2f}")
        print(f"    均线: {' | '.join(parts)}")
        print(f"    MACD: DIF={inds['dif']:.3f} | DEA={inds['dea']:.3f} | 柱={inds['macd_hist']:.3f}")
        print(f"    RSI: {inds['rsi14']:.0f} | KDJ: {inds['kdj_k']:.0f}/{inds['kdj_d']:.0f}/{inds['kdj_j']:.0f}")
        print(f"    量比: {inds['vol_ratio']:.1f} | ATR: {inds.get('atr','-')}")

        vp = inds.get("vol_pattern")
        if vp:
            print(f"    量价形态: {vp}")

        print(f"\n  🔔 信号 ({len(sigs)}条):")
        for s in sigs[:7]:
            print(f"    {s}")

        records60 = get_tdx_data(code, 60)
        ts = calc_trailing_stop(records60, atr_multiplier=2.0) if records60 else None
        print(f"\n{format_stop_advice(ts, inds)}")
        print(f"  {'─'*64}")

    print(f"\n📡 Step 4: 获取实时行情 (Top 10)...")
    top_codes = [item[1] for item in scored[:10]]
    rt = fetch_realtime_prices(top_codes)
    if rt:
        for item in scored[:10]:
            code = item[1]
            if code in rt:
                r = rt[code]
                item[4]["realtime"] = r
        print(f"  ✅ 获取 {len(rt)} 只实时数据")
    else:
        print(f"  ⚠️ 实时行情不可用")

    print(f"\n{'='*68}")
    print(f"  📋 排行榜 (Top 15)")
    print(f"{'='*68}")
    h = f"  {'#':>3} {'代码':>9} {'名称':>10} {'行业':>6} {'评分':>4} {'现价':>8}"
    h += f" {'RSI':>4} {'量比':>4} {'5日%':>6}"
    h += f" {'形态':>8} {'实时%':>6}" if rt else ""
    print(h)
    print(f"  {'─'*62 if not rt else '─'*68}")
    for i, item in enumerate(scored[:15], 1):
        sc, code, mkt, name, inds, sigs = item
        n8 = (name or "未知")[:8]
        ind = (inds.get("industry", "") or "")[:4]
        vr = inds['vol_ratio']
        vp = (inds.get("vol_pattern") or "")[:6]
        rt_str = ""
        if rt and code in rt:
            cp = rt[code]["chg_pct"]
            rt_str = f"{cp:+.2f}%"
        line = f"  {i:>3} {code:>9} {n8:>10} {ind:>6} {sc:>4} {inds['price']:>8.2f}"
        line += f" {inds['rsi14']:>4.0f} {vr:>4.1f} {inds['chg5']:>+5.1f}%"
        line += f" {vp:>8}" + (f" {rt_str:>6}" if rt else "")
        print(line)

    print(f"\n  📊 行业分布:")
    sorted_ind = sorted(ind_dist.items(), key=lambda x: -x[1])
    for ind, cnt in sorted_ind:
        bar = "█" * cnt
        print(f"     {ind:>6}: {bar} {cnt}")

    csv_path = export_csv(scored)
    print(f"\n  📁 CSV: {csv_path}")

    if _HAS_TRADE_LOG and scored:
        best = scored[0]
        sc, code, mkt, name, inds, sigs = best
        records60 = get_tdx_data(code, 60)
        ts = calc_trailing_stop(records60) if records60 else None
        if ts:
            from core.ops.trade_tracker import auto_log_recommendation as _log_rec
            _log_rec(
                code=code, name=name, score=sc, strategy=sn,
                entry_price=ts["entry"], stop_loss=ts["stop_loss"],
                tp1=ts["tp1_5%"], tp2=ts["tp2_10%"],
                tp3=ts["tp3_15%"], tp4=ts["tp_final_20%"],
                market_state=market.get("market_state", "未知"),
                reason=f"选股Top1: {sn}策略, {len(sigs)}条信号, 行情{market_state}",
            )
        else:
            from core.ops.trade_tracker import auto_log_recommendation as _log_rec2
            _log_rec2(
                code=code, name=name, score=sc, strategy=sn,
                entry_price=inds["price"], stop_loss=0,
                tp1=0, tp2=0, tp3=0, tp4=0,
                market_state=market.get("market_state", "未知"),
                reason=f"选股Top1: {sn}策略, {len(sigs)}条信号",
            )

    print(f"\n{'='*68}")
    print(f"  📌 策略: {sn}")
    print(f"  🛑 止损: 固定-8% / ATR×2 (取较宽值)")
    print(f"  🔄 移动止盈: 高点回撤8% | 分批: TP1/TP2/TP3")
    print(f"  ⚠️ 仅技术指标分析，不构成投资建议")
    print(f"  📐 交易规则: 1手=100股, 整手交易")
    print(f"{'='*68}")

    try:
        append_backtest_record(scored, sn)
    except Exception as e:
        print("  ⚠ 回测记录异常: " + str(e)[:50])

    if _HAS_TRADE_LOG and scored:
        try:
            top = scored[0]
            from core.ops.trade_tracker import auto_log_recommendation as _log_rec3
            _log_rec3(
                code=top[1], name=top[3] if len(top) > 3 else "",
                score=top[0], strategy=sn,
                entry_price=top[4].get("price", 0) if len(top) > 4 else 0,
                stop_loss=None, tp1=None, tp2=None, tp3=None, tp4=None,
                market_state="偏弱",
                reason="系统自动推荐"
            )
        except Exception as e:
            print("  ⚠ 跟踪记录异常: " + str(e)[:50])


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--swing":
        swing_pick()
    else:
        sn = None
        if len(sys.argv) > 1 and sys.argv[1] in ("综合", "趋势", "突破", "抄底"):
            sn = sys.argv[1]
    only_best = '--only-best' in sys.argv
    if only_best: sys.argv.remove('--only-best')
    brief_mode = '--brief' in sys.argv
    if brief_mode: sys.argv.remove('--brief')
    """
    波段交易模式 — 只选一只最优票, 1天~6个月持仓角度分析
    诚实评估: 适合做 / 等回调 / 风险过高
    """
    strategy, sn = load_strategy("趋势")
    print("=" * 68)
    print("  🎯 波段交易推荐系统  |  策略: 趋势")
    print("  持仓: 1天~6个月 | 只选一只最优标的")
    print("  原则: 趋势为王 | 回调入场 | 移动止盈")
    print("=" * 68)

    try:
        holdings_file = os.path.join(PROJECT_ROOT, "data", "holdings.json")  # P1修复(20261023): S4迁移锚点漂移, data/在仓库根
        if os.path.exists(holdings_file):
            import json
            with open(holdings_file) as f:
                hd = json.load(f)

            # 兼容新旧两种格式
            # 新格式: total_assets / available_cash
            # 旧格式: cash (仅有现金字段)
            holdings_list = hd.get("holdings", [])
            total_assets = hd.get("total_assets")
            available_cash = hd.get("available_cash")

            # 如果新字段缺失，从旧字段推算
            if total_assets is None:
                total_assets = sum(
                    h.get("current_price", h.get("cost", h.get("cost_price", 0))) * h.get("shares", 0)
                    for h in holdings_list
                )
            if available_cash is None:
                available_cash = hd.get("cash", 0)
            # 加上现金算总资产（如果total_assets没包含现金的话）
            cash_included = hd.get("available_cash") is not None  # 新格式已包含现金
            if not cash_included:
                total_assets += available_cash

            cash_pct = available_cash / total_assets * 100 if total_assets > 0 else 100
            if cash_pct < 5:
                print(f"\n  🔴 满仓预警: 现金仅{cash_pct:.1f}% ({available_cash:.0f}元)")
                market = analyze_market()
                ms = market.get("market_state", "")
                print(f"  📊 市场: {ms}")
                print(f"  💡 建议: 先减仓腾出资金再买入, 但下面仍然输出今日扫描结果供参考")
                print(f"  {'─'*64}")
                # 满仓时不返回，继续执行扫描（只警告不阻断）
    except Exception as e:
        print(f"  ⚠ 持仓检查异常: {e}")

    cache_data = load_cache()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if cache_data and cache_data.get("date") == now[:10]:
        scored_raw = cache_data.get("results", [])
        scored = [tuple(x) for x in scored_raw]
        print(f"\n📦 使用今日缓存: {len(scored)} 只")
    else:
        print(f"\n📡 扫描本地TDX...")
        all_stocks = {}
        max_date = None
        for market, mname, prefixes in [
            ("sh", "上海", ALLOWED_PREFIXES_SH),
            ("sz", "深圳", ALLOWED_PREFIXES_SZ),
        ]:
            day_dir = os.path.join(VIPDOC, market, "lday")
            if os.path.isdir(day_dir):
                for f in os.listdir(day_dir):
                    if f.endswith(".day"):
                        code = f.replace(".day", "")
                        if should_include(code):
                            all_stocks[code] = mname
                            ld = get_latest_tdx_date(code)
                            if ld and (max_date is None or ld > max_date):
                                max_date = ld
        print(f"  ✅ 合计: {len(all_stocks)} 只 | 最新交易日: {max_date}")

        cache = load_name_cache()
        ind_cache = load_industry_map()
        need_fetch = [c for c in all_stocks if c not in cache]
        if need_fetch:
            batch_fetch_names(need_fetch, cache)
        cache = load_name_cache()

        scored = []
        t0 = time.time()
        stale = 0
        for code, mkt in sorted(all_stocks.items()):
            name = cache.get(code, "")
            if is_st_stock(name):
                continue
            ld = get_latest_tdx_date(code)
            if ld and max_date and (max_date - ld).days > 5:
                stale += 1
                continue
            recs = get_tdx_data(code, 200)
            if recs and len(recs) >= 30:
                inds = compute_indicators(recs)
                weekly = compute_weekly_indicators(recs)
                if inds:
                    inds["industry"] = get_industry(code, name, ind_cache)
                    sc, sigs = score_stock(inds, weekly, strategy)
                    if sc > 0:
                        scored.append((sc, code, mkt, name, inds, sigs, recs))
        scored.sort(key=lambda x: x[0], reverse=True)
        print(f"  筛选: {len(scored)}/{len(all_stocks)} 只有评分 | ST跳过 | 停牌跳过{stale}")

    _market = analyze_market()
    _market_state = _market.get("market_state", "")
    try:
        heat_dict = get_industry_heat()
        if heat_dict:
            alias = heat_dict.get("__alias__", {})
            for idx in range(len(scored)):
                item = list(scored[idx])
                inds = item[4]
                ind_name = inds.get("industry", "")
                if ind_name and ind_name in heat_dict:
                    inds["industry_heat_bonus"] = heat_dict[ind_name]["percentile"]
                elif ind_name and ind_name in alias:
                    inds["industry_heat_bonus"] = alias[ind_name]["percentile"]
                else:
                    inds["industry_heat_bonus"] = 0.5

        top_n = min(50, len(scored))
        top_codes = [(scored[i][1], scored[i][4].get("industry", "")) for i in range(top_n)]
        fund_flow = get_fund_flow_bonus_for_stocks(top_codes)
        for idx in range(top_n):
            item = list(scored[idx])
            code, inds = item[1], item[4]
            if code in fund_flow:
                fb = fund_flow[code]
                inds["fund_flow_bonus"] = fb["bonus"]
                inds["fund_flow_signal"] = fb["signal"]
                inds["fund_flow_5d"] = fb["main_net_5d"]
                inds["fund_flow_20d"] = fb["main_net_20d"]

        rescored = 0
        for idx in range(top_n):
            item = list(scored[idx])
            sc, code, mkt, name, inds, sigs = item[:6]
            heat = inds.get("industry_heat_bonus", 0.5)
            heat_info = {"percentile": heat}
            fb = inds.get("fund_flow_bonus", 0)
            fs = inds.get("fund_flow_signal", "")
            new_sc, new_sigs = score_stock(
                inds, weekly=None, strategy=strategy,
                market_state=_market_state,
                bonuses={
                    "industry_heat": heat_info,
                    "fund_flow_bonus": fb,
                    "fund_flow_signal": fs,
                },
            )
            if new_sc > 0:
                scored[idx] = (new_sc, code, mkt, name, inds, new_sigs)
                rescored += 1
        scored.sort(key=lambda x: x[0], reverse=True)
        print(f"  🔄 重新评分: Top {rescored} 只 (含板块+资金流加分)")
    except Exception as e:
        print(f"  ⚠️ 板块/资金流评分异常 (不影响选股): {e}")

    if _HAS_HUATAI:
        try:
            remaining = get_remaining_calls()
            if remaining > 10:
                scored = huatai_enrich_stocks(scored, top_n=10, strategy_name=sn)
                enriched = sum(1 for item in scored[:10] if item[4].get("huatai_available"))
                after = get_remaining_calls()
                print(f"  🏢 华泰数据: 丰富Top10 ({enriched}只有数据) | 今日剩余{after}次")
            else:
                print(f"  ⚠️ 华泰数据跳过: 今日剩余仅{remaining}次")
        except Exception as e:
            print(f"  ⚠️ 华泰数据异常 (不影响选股): {e}")
    else:
        print(f"  📡 华泰数据未安装 (huatai_data.py)")

    if _HAS_NEWS_SENTIMENT and scored:
        try:
            scored_before = len(scored)
            if len(scored) > 20:
                try:
                    top20 = get_sector_bonus_for_all(scored[:20])
                except Exception:
                    top20 = scored[:20]
                scored_top = [(sc, code, mkt, name, inds, sigs) for sc, code, mkt, name, inds, sigs in top20]
                scored = scored_top + scored[20:]
            else:
                top_all = get_sector_bonus_for_all(scored)
                scored = [(sc, code, mkt, name, inds, sigs) for sc, code, mkt, name, inds, sigs in top_all]
            scored.sort(key=lambda x: x[0], reverse=True)
            print(f"  🔥 热点题材评分加成完成 (Top{min(20, scored_before)}只)")
        except Exception as e:
            print(f"  ⚠️ 热点题材评分异常 (不影响选股): {e}")

    if _HAS_SENTIMENT:
        try:
            from market_sentiment_integrator import sentiment_enrich_stock
            top_n = min(15, len(scored))
            print(f"  🌡️  KIMI情绪增强 (Top{top_n}只: 市场情绪+个股新闻)...")
            enhanced = 0
            for idx in range(top_n):
                item = list(scored[idx])
                sc, code, mkt, name, inds, sigs = item[:6]
                enh_sc, bonus, details = sentiment_enrich_stock(code, name, sc)
                if enh_sc != sc:
                    scored[idx] = (enh_sc, code, mkt, name, inds, sigs)
                    enhanced += 1
            if enhanced:
                scored.sort(key=lambda x: x[0], reverse=True)
                detail_str = details[0] if details else ''
                print(f"  ✅ 增强完成: {enhanced}只评分调整 {detail_str}")
        except Exception as e:
            print(f"  ⚠️ 情绪增强异常 (不影响选股): {e}")

    print(f"\n{'='*68}")
    print(f"  📊 市场分析 + 波段评估...")
    print(f"  {'─'*64}")
    market = analyze_market(scored)
    print(f"  市场: {market.get('market_state', '未知')} | 推荐: {market.get('recommended_strategy', '综合')}")
    print(f"  {'─'*64}")

    top_data = []
    for item in scored[:10]:
        sc, code, mkt, name, inds, sigs = item[:6]
        weekly = compute_weekly_indicators(records) if (records := get_tdx_data(code, 200)) else None
        sa = compute_swing_analysis(inds, weekly, records or [])
        super_c = super_stock_classify(code, name, records)
        dq = check_data_quality(code, records)
        entry = {"rank": len(top_data)+1, "code": code, "name": name,
                 "market": mkt, "score": sc, "industry": inds.get("industry", ""),
                 "price": inds["price"], "swing": sa,
                 "super_model": super_c["model"], "super_score": super_c["score"],
                 "drawdown": super_c.get("drawdown_pct"),
                 "alignment": super_c.get("alignment"),
                 "data_quality": dq, "signals": list(sigs)}
        top_data.append(entry)

    if _HAS_PARALLEL:
        print(f"\n🔗 [2.5+3/4] 多Agent并行增强...")
        enriched = parallel_enrich(top_data, use_delegate=True)  # 启用多agent并行
        merged = merge_and_rerank(top_data, enriched)
        if "fund" in enriched:
            fcnt = sum(1 for e in merged if e.get("fundamental_bonus", 0) != 0)
            print(f"  💹 资金面信号: {fcnt} 只")
        if "sentiment" in enriched or "news" in enriched:
            print(f"  📰 情绪/新闻增强: 合并完成")
        if "sector" in enriched:
            sd = enriched["sector"]
            print(f"  🔄 板块轮动: {sd.get('rotation_direction','?')}")
        top_data = merged
    else:
        print(f"\n💹 [2.5/4] 资金面扫描 (Top{min(20, len(top_data))})...")
        fund_codes = [(e["code"], e["name"]) for e in top_data[:20]]

    print(f"\n📊 [3/4] 波段路径分析 + 风险评估...")
    top5_summary = []
    for entry in top_data[:5]:
        sa = entry["swing"]
        code = entry["code"]
        name = entry["name"]
        price = entry["price"]
        ts = calc_trailing_stop(get_tdx_data(code, 60), atr_multiplier=2.0) if get_tdx_data(code, 60) else None
        rr = sa["rr"]
        stop_loss = ts["stop_loss"] if ts else 0
        tp3 = ts["tp3_15%"] if ts else 0
        decision = sa["decision"]
        top5_summary.append({
            "code": code, "name": name, "score": entry["score"],
            "price": price, "decision": decision, "stop": stop_loss,
            "tp": tp3, "rr": round(rr, 1),
            "risks": sa["risks"][:2], "sig": entry["signals"][:2],
        })

        # 交易日志
        if _HAS_TRADE_LOG:
            try:
                from core.ops.trade_tracker import auto_log_recommendation as _log_rec4
                _log_rec4(code=code, name=name, score=entry["score"],
                    strategy="趋势(波段)", entry_price=price, stop_loss=stop_loss,
                    tp1=ts["tp1_5%"] if ts else None, tp2=ts["tp2_10%"] if ts else None,
                    tp3=tp3 if ts else None, tp4=ts["tp_final_20%"] if ts else None,
                    market_state=market.get("market_state", "未知"),
                    reason=f"波段Top{entry['rank']}: {code}, 评分{entry['score']}")
            except Exception:
                pass

    # ── 紧凑TOON格式输出 ──
    print(f"\n📋 TOP 5  市场:{market.get('market_state','未知')}")
    print(f"# code|name|score|decision|price|stop|tp|rr|risk")
    for i, e in enumerate(top5_summary, 1):
        risk_str = e['risks'][0][:20] if e['risks'] else '-'
        print(f"{i}|{e['code']}|{e['name']}|{e['score']}|{e['decision']}|"
              f"{e['price']:.2f}|{e['stop']:.2f}|{e['tp']:.2f}|{e['rr']:.1f}|{risk_str}")

    # 行业热度（TOON格式）— 2026-08-02 修复: get_industry_heat 返回 {name:{rank,percentile}}
    try:
        from core.pipeline.tdx_core import get_industry_heat
        heat_data = get_industry_heat()
        valid = {k: v for k, v in heat_data.items()
                 if isinstance(v, dict) and "percentile" in v}
        if valid:
            sectors = sorted(valid.items(), key=lambda x: -x[1]["percentile"])
            hot = ','.join(n for n, _ in sectors[:5])
            cold = ','.join(n for n, _ in sectors[-5:])
            if hot or cold:
                print(f"板块: hot={hot}; cold={cold}")
    except Exception:
        pass

    print(f"\n{'='*50}")
    print(f"  📌 原则: 趋势为王 | 回调入场 | 移动止盈")
    print(f"  ⚠️ 仅技术分析，不构成投资建议")
    print(f"{'='*50}")
    return top_data


def append_backtest_record(scored, strategy_name):
    """Improve 1: 自动追加回测记录到 backtest_result.json"""
    f = os.path.join(PROJECT_ROOT, "backtest_result.json")  # P1修复(20261023): 回测记录追加到仓库根(原语义)
    r = {"扫描次数": 0, "历史记录": []}
    if os.path.exists(f):
        try:
            r = json.load(open(f, encoding="utf-8"))
        except Exception:
            r = {"扫描次数": 0, "历史记录": []}
    r["扫描次数"] = r.get("扫描次数", 0) + 1
    if scored and len(scored) > 0:
        top1 = scored[0]
        r.setdefault("历史记录", []).append({
            "日期": date.today().strftime("%Y-%m-%d"),
            "代码": top1[1], "名称": top1[3] if len(top1) > 3 else "",
            "评分": top1[0], "策略": strategy_name
        })
        atomic_json.atomic_dump(r, f, ensure_ascii=False, indent=2, encoding="utf-8")
    count = r.get("扫描次数", 0)
    print(f"  📊 已追加回测记录 #{count}")


if __name__ == "__main__":
    main()
