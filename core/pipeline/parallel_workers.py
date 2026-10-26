import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""parallel_workers.py — delegate_task 轻量多Agent并行引擎

在选股流水线的数据增强阶段，将互不依赖的子任务通过 delegate_task 并发执行：
  - fund_worker     : MCP资金面扫描 (北向/融资/股东户数/机构持股)
  - sentiment_worker: 情绪分析 + 同花顺热点 + KIMI情绪增强
  - news_worker     : 东财个股新闻检索 + 可信度验证
  - sector_worker   : 板块轮动分析 + 龙头筛选
  - anysearch_worker: AI搜索引擎增强（AnySearch）
  - expert_worker   : ★ 基本面深度分析 — cn-financial-deep-analysis 三层框架
                      五维财务评分(ROE/毛利率/负债率/现金流/成长) + 70+舞弊信号

每个 worker 返回结构化 dict，主调度器汇总合并后重排序。
"""
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys

sys.path.insert(0, PROJECT_ROOT)


# ═══════════════════════════════════════════
# Worker 定义 (供 delegate_task 使用)
# ═══════════════════════════════════════════

def build_fund_worker_prompt(top_stocks):
    """构建资金面扫描子任务 prompt"""
    stocks_str = "\n".join(
        f"  [{i+1}] {s['code']} {s['name']} 评分{s.get('score',0)}"
        for i, s in enumerate(top_stocks[:20])
    )
    return (
        f"# 任务: A股资金面因子扫描\n"
        f"对以下候选股执行资金面因子扫描:\n\n{stocks_str}\n\n"
        "## 执行步骤\n"
        "1. 导入 get_fundamental_bonus_for_stocks 函数\n"
        f"2. 调用 get_fundamental_bonus_for_stocks({top_stocks[:20]})\n"
        "3. 输出JSON结果:\n"
        '{\"task\": \"fund\", \"results\": {\"code\": {\"bonus\": int, \"signal\": str, \"details\": {...}}, ...}}\n'
        "只输出 JSON，不要其他文本。"
    )


def build_sentiment_worker_prompt(top_stocks):
    """构建情绪分析子任务 prompt"""
    stocks_str = "\n".join(
        f"  [{i+1}] {s['code']} {s['name']}"
        for i, s in enumerate(top_stocks[:15])
    )
    return (
        f"# 任务: 股票情绪分析增强\n"
        f"对以下候选股执行情绪分析:\n\n{stocks_str}\n\n"
        "## 执行步骤\n"
        "1. 如果 _HAS_NEWS_SENTIMENT → 调用 get_sector_bonus_for_all(stock_codes)\n"
        "2. 如果 _HAS_SENTIMENT → 对前15只调用 sentiment_enrich_stock(code, name, score)\n"
        "3. 输出每条股票的增补情绪分:\n"
        '{"task": "sentiment", "enrichments": [{"code": str, "name": str, "raw_score": int, '
        '"news_bonus": int, "sentiment_bonus": int, "total_bonus": int, '
        '"details": str}, ...]}\n'
        "只输出 JSON，不要其他文本。"
    )


def build_news_worker_prompt(top_stocks):
    """构建新闻检索子任务 prompt"""
    stocks_str = "\n".join(
        f"  [{i+1}] {s['code']} {s['name']}"
        for i, s in enumerate(top_stocks[:10])
    )
    return (
        f"# 任务: 个股新闻快速检索\n"
        f"对以下候选股进行新闻情绪检索:\n\n{stocks_str}\n\n"
        "## 执行步骤\n"
        "1. 对每只股票调用 mx_finance_search_news(\"{code} {name} 最新公告\")\n"
        "2. 提取: 新闻条数、正面信号数、负面信号数、综合情绪分数\n"
        "3. 使用 cross_validate_fact() 进行可信度验证\n"
        '4. 输出: {"task": "news", "news_items": [{"code": str, "news_count": int, '
        '"pos_signals": int, "neg_signals": int, "score": int, '
        '"credibility": str, "confirmed": bool}, ...]}\n'
        "只输出 JSON，不要其他文本。"
    )


def build_sector_worker_prompt():
    """构建板块轮动子任务 prompt"""
    return (
        "# 任务: 板块轮动深度分析\n\n"
        "## 执行步骤\n"
        "1. 调用 sector_rotation_analysis() 获取行业热度排名\n"
        "2. 找出当前最热 TOP 5 行业和最冷 BOTTOM 5 行业\n"
        "3. 判断市场轮动方向:\n"
        "   - 强势→弱势切换: 减仓防守\n"
        "   - 弱势→强势切换: 积极进攻\n"
        "   - 强势持续: 顺势跟随\n"
        "   - 弱势持续: 等待反转\n"
        "4. 输出:\n"
        '{"task": "sector", "hot_top5": [{"name": str, "percentile": float}], '
        '"cold_bottom5": [{"name": str, "percentile": float}], '
        '"rotation_direction": str, \"opinion_summary": str}'
    )


# ═══════════════════════════════════════════
# 纯Python本地版本 (fallback: 无法使用 delegate_task 时)
# ═══════════════════════════════════════════

def _local_fund_scan(top_stocks):
    """本地模式: 直接调用资金面扫描"""
    try:
        from core.pipeline.tdx_core import get_fundamental_bonus_for_stocks
        codes = [(s["code"], s["name"]) for s in top_stocks[:20]]
        results = get_fundamental_bonus_for_stocks(codes)
        return {"task": "fund", "results": results}
    except Exception as e:
        print(f"  ⚠️ 资金面扫描失败: {e}")
        return {"task": "fund", "results": {}, "error": str(e)}


def _local_sentiment_scan(top_stocks):
    """本地模式: 直接调用情绪增强"""
    enrichments = []
    try:
        from news_sentiment import get_sector_bonus_for_all
        if _HAS_NEWS_SENTIMENT:
            codes = [s["code"] for s in top_stocks[:15]]
            sector_scores = get_sector_bonus_for_all(codes)
            enrichments.extend(sector_scores.values())
    except Exception:
        pass

    try:
        from market_sentiment_integrator import sentiment_enrich_stock
        for idx, s in enumerate(top_stocks[:15]):
            try:
                enh_sc, bonus, details = sentiment_enrich_stock(
                    s["code"], s["name"], s.get("score", 0))
                if enh_sc != s.get("score", 0):
                    enrichments.append({
                        "code": s["code"], "name": s["name"],
                        "raw_score": s.get("score", 0),
                        "sentiment_bonus": bonus,
                        "total_bonus": enh_sc - s.get("score", 0),
                        "details": details,
                    })
            except Exception:
                pass
    except Exception:
        pass

    return {"task": "sentiment", "enrichments": enrichments}


def _local_news_scan(top_stocks):
    """本地模式: 直接调用新闻检索"""
    items = []
    try:
        from news_sentiment import get_news_sentiment_score
    except ImportError:
        get_news_sentiment_score = None
    # P1集成: cnfinancialscraper 舆情层 (2026-08-25)
    try:
        sys.path.insert(0, r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\skills\cnfinancialscraper")
        from scripts.sentiment_crawler import crawl_global_sentiment
    except ImportError:
        crawl_global_sentiment = None
    try:
        for s in top_stocks[:10]:
            try:
                if get_news_sentiment_score is None and crawl_global_sentiment is None:
                    continue
                # 优先 cnfinancialscraper
                if crawl_global_sentiment and s.get("name"):
                    try:
                        result = crawl_global_sentiment(s["name"], days=7)
                        if isinstance(result, dict):
                            score = result.get("sentiment", 0)
                            items.append({
                                "code": s["code"],
                                "news_count": len(result.get("items", [])),
                                "pos_signals": score if score > 0 else 0,
                                "neg_signals": -score if score < 0 else 0,
                                "score": score,
                                "credibility": "cnfinancialscraper",
                                "confirmed": score != 0,
                            })
                            continue
                    except Exception:
                        pass
                # 降级到 news_sentiment
                if get_news_sentiment_score:
                    result = get_news_sentiment_score(s["code"], s["name"])
                    score = result.get("score", 0) if isinstance(result, dict) else 0
                    items.append({
                        "code": s["code"],
                        "news_count": 1,
                        "pos_signals": score if score > 0 else 0,
                        "neg_signals": -score if score < 0 else 0,
                        "score": score,
                        "credibility": "local",
                        "confirmed": score != 0,
                    })
            except Exception:
                pass
    except Exception:
        pass
    return {"task": "news", "news_items": items}


def _local_sector_analysis():
    """本地模式: 直接调用板块轮动"""
    try:
        from core.pipeline.tdx_core import get_industry_heat
        heat = get_industry_heat()
        valid = {k: v for k, v in heat.items()
                 if isinstance(v, dict) and "percentile" in v}
        if not valid:
            return {"task": "sector", "hot_top5": [], "cold_bottom5": [],
                    "rotation_direction": "未知", "opinion_summary": "无板块数据"}
        sectors = sorted(valid.items(), key=lambda x: -x[1]["percentile"])
        hot = [{"name": n, "percentile": info["percentile"] * 100}
               for n, info in sectors[:5]]
        cold = [{"name": n, "percentile": info["percentile"] * 100}
                for n, info in sectors[-5:]]
        avg_hot = sum(h["percentile"] / 100.0 for h in hot) / max(len(hot), 1)
        rotation_dir = "强势持续" if avg_hot > 0.7 else "弱势持续" if avg_hot < 0.3 else "震荡轮动"
        return {
            "task": "sector",
            "hot_top5": hot,
            "cold_bottom5": cold,
            "rotation_direction": rotation_dir,
            "opinion_summary": f"当前市场热点集中度{'高' if avg_hot > 0.6 else '中'}，建议{rotation_dir}",
        }
    except Exception as e:
        print(f"  ⚠️ 板块分析失败: {e}")
        return {"task": "sector", "hot_top5": [], "cold_bottom5": [],
                "rotation_direction": "未知", "opinion_summary": str(e)}


# 标记哪些模块可用
_HAS_NEWS_SENTIMENT = False
try:
    from news_sentiment import get_sector_bonus_for_all
    _HAS_NEWS_SENTIMENT = True
except ImportError:
    pass

_HAS_SENTIMENT = False
try:
    from market_sentiment_integrator import sentiment_enrich_stock
    _HAS_SENTIMENT = True
except ImportError:
    pass

_HAS_SECTOR_ROTATION = False

_HAS_ANYSEARCH = False
try:
    from factors.anysearch_integration import anysearch_enrich_stocks
    _HAS_ANYSEARCH = True
except ImportError:
    pass


def build_anysearch_worker_prompt(top_stocks):
    """构建 AnySearch 搜索增强子任务 prompt"""
    stocks_str = "\n".join(
        f"  [{i+1}] {s['code']} {s['name']} 评分{s.get('score',0)}"
        for i, s in enumerate(top_stocks[:20])
    )
    return (
        f"# 任务: AnySearch AI 搜索引擎增强\n"
        f"对以下候选股执行 AnySearch 通用搜索获取最新新闻/公告/情绪:\n\n{stocks_str}\n\n"
        "## 执行步骤\n"
        "1. 导入 anysearch_integration 模块\n"
        f"2. 调用 anysearch_enrich_stocks({[(s['code'], s['name']) for s in top_stocks[:20]]})\n"
        "3. 输出JSON结果:\n"
        '{"task": "anysearch", "results": {"code": {"score": int, "news_count": int, "headlines": [str]}, ...}}\n'
        "只输出 JSON，不要其他文本。"
    )


def _local_anysearch_scan(top_stocks):
    """本地模式: 直接用 AnySearch 批量搜索增强"""
    try:
        stock_list = [(s["code"], s["name"]) for s in top_stocks[:20]]
        results = anysearch_enrich_stocks(stock_list)
        return {"task": "anysearch", "results": results}
    except Exception as e:
        print(f"  ⚠️ AnySearch 搜索增强失败: {e}")
        return {"task": "anysearch", "results": {}, "error": str(e)}


# ── 专家级 worker: 基本面深度分析（源自 cn-financial-deep-analysis） ──

_HAS_EXPERT = False
try:
    from core.scoring.financial_filter import batch_score_financial
    _HAS_EXPERT = True
except ImportError:
    pass


def build_expert_worker_prompt(top_stocks):
    """构建基本面深度分析子任务 prompt
    
    使用 cn-financial-deep-analysis 方法论的三层框架：
    宏观(行业/战略) → 中观(报表/指标) → 微观(科目/舞弊)
    """
    stocks_str = "\n".join(
        f"  [{i+1}] {s['code']} {s['name']} 评分{s.get('score',0)}"
        for i, s in enumerate(top_stocks[:20])
    )
    return (
        f"# 任务: 基本面专家级深度分析\n"
        f"对以下候选股执行财务健康评分+舞弊检测:\n\n{stocks_str}\n\n"
        "## 方法论（cn-financial-deep-analysis）\n"
        "三层框架: 宏观(行业/战略) → 中观(报表/指标) → 微观(科目/舞弊)\n"
        "- 五维财务评分: 盈利能力(35%权重) + 成长(25%) + 营运(15%) + 偿债(15%) + 现金流(10%)\n"
        "- 70+舞弊信号扫描: 扣非亏损/应收暴增/高负债/现金流异常/毛利率波动\n"
        "## 执行步骤\n"
        "1. 导入 financial_filter 模块\n"
        f"2. 对每只股票调用 score_stock_financial()（代码去前缀 sh/sz）\n"
        "3. 汇总: financial_health(0~40), fraud_penalty(-30~0), fraud_fatal(bool), signals\n"
        "4. 输出JSON:\n"
        '{"task": "expert", "results": {"code": {"financial_health": int, '
        '"fraud_penalty": int, "fraud_fatal": bool, '
        '"health_signals": [str], "fraud_signals": [str], "total_bonus": int}, ...}}\n'
        "只输出 JSON，不要其他文本。"
    )


def _local_expert_scan(top_stocks):
    """本地模式: 直接调用 financial_filter 批量评分"""
    if not _HAS_EXPERT:
        return {"task": "expert", "results": {}, "error": "financial_filter not available"}
    try:
        codes = [(s["code"], s["name"]) for s in top_stocks[:50]]
        clean_codes = [c[2:] if c[:2].isalpha() else c for c, _ in codes]
        results = batch_score_financial(clean_codes)
        return {"task": "expert", "results": results}
    except Exception as e:
        print(f"  ⚠️ 专家级分析失败: {e}")
        return {"task": "expert", "results": {}, "error": str(e)}


def _get_local_functions():
    """返回所有本地worker函数映射"""
    funcs = {
        "fund": _local_fund_scan,
        "sentiment": _local_sentiment_scan,
        "news": _local_news_scan,
        # sector 无条件注册: 本地模式用 get_industry_heat (2026-08-02 修复,
        # 之前 _HAS_SECTOR_ROTATION=False 导致 sector worker 永不执行)
        "sector": _local_sector_analysis,
    }
    if _HAS_ANYSEARCH:
        funcs["anysearch"] = _local_anysearch_scan
    if _HAS_EXPERT:
        funcs["expert"] = _local_expert_scan
    return funcs


# ═══════════════════════════════════════════
# 统一并行调度入口
# ═══════════════════════════════════════════

def parallel_enrich(top_stocks, use_delegate=False):
    """
    并行数据增强入口。

    Args:
        top_stocks: Top N 候选股列表 (dict, 已含基础评分)
        use_delegate: 是否尝试使用 delegate_task 并行

    Returns:
        merged_results: {task_name: result_dict, ...}
    """
    if not top_stocks:
        return {}

    available_workers = set(_get_local_functions().keys())

    print(f"\n🔧 [并行增强] 可用Worker: {', '.join(available_workers)}")

    if use_delegate:
        # 线程池并行模式 — 4个worker同时运行 I/O 任务
        return _threadpool_enrich(top_stocks, available_workers)
    else:
        # 本地同步模式 (可靠兜底)
        return _sync_enrich(top_stocks, available_workers)


def _sync_enrich(top_stocks, workers):
    """同步模式: 串行但快速执行各worker"""
    func_map = _get_local_functions()
    results = {}

    for worker_name in ["fund", "sentiment", "news", "sector", "anysearch", "expert"]:
        if worker_name not in workers:
            continue
        func = func_map[worker_name]
        print(f"  🔄 {worker_name} worker 执行中...")
        try:
            if worker_name == "fund":
                results[worker_name] = func(top_stocks)
            elif worker_name == "sentiment":
                results[worker_name] = func(top_stocks)
            elif worker_name == "news":
                results[worker_name] = func(top_stocks)
            elif worker_name == "sector":
                results[worker_name] = func()
            elif worker_name == "anysearch":
                results[worker_name] = func(top_stocks)
            elif worker_name == "expert":
                results[worker_name] = func(top_stocks)
        except Exception as e:
            print(f"  ❌ {worker_name} 执行异常: {e}")
            results[worker_name] = {"task": worker_name, "error": str(e)}

    return results


def _threadpool_enrich(top_stocks, workers):
    """线程池并行模式（当前默认）:
    使用 ThreadPoolExecutor 并行执行各 I/O-bound worker。
    未来可升级为 Hermes delegate_task 子代理模式。"""

    import traceback, time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    start_time = time.time()
    results = {}

    def run_single_worker(worker_name, **kwargs):
        func_map = _get_local_functions()
        func = func_map.get(worker_name)
        if not func:
            return (worker_name, {"task": worker_name, "error": "not available"}, False)
        
        try:
            if kwargs.get("func_arg"):
                result = func(kwargs["func_arg"])
            elif worker_name == "sector":
                result = func()
            else:
                result = func([])
            return (worker_name, result, True)
        except Exception as e:
            tb = traceback.format_exc()
            return (worker_name, {"task": worker_name, "error": str(e), "traceback": tb[:200]}, False)

    futures = {}
    with ThreadPoolExecutor(max_workers=min(len(workers), 5)) as executor:
        for worker_name in ["fund", "sentiment", "news", "sector", "anysearch", "expert"]:
            if worker_name not in workers:
                continue
            
            kw = {}
            if worker_name in ("fund", "sentiment", "news", "anysearch", "expert"):
                kw["func_arg"] = top_stocks
            elif worker_name == "sector":
                pass  # no args needed
            
            future = executor.submit(run_single_worker, worker_name, **kw)
            futures[future] = worker_name
    
    for future in as_completed(futures):
        wname = futures[future]
        try:
            wname, result, success = future.result(timeout=60)
            status = "✅" if success else "❌"
            print(f"  {status} {wname} worker 完成 ({time.time()-start_time:.1f}s)")
            results[wname] = result
        except Exception as e:
            print(f"  ❌ {wname} worker 超时或异常: {e}")
            results[wname] = {"task": wname, "error": str(e)}

    total_elapsed = time.time() - start_time
    print(f"\n  🎯 全部 worker 完成, 耗时 {total_elapsed:.1f}s")
    return results


# ═══════════════════════════════════════════
# 结果合并与评分重排序
# ═══════════════════════════════════════════

def merge_and_rerank(top_stocks, enriched_results):
    """将各 worker 的结果合并回原候选股列表并重新排序"""
    results = top_stocks.copy()
    
    # 1. 合并资金面评分
    if "fund" in enriched_results:
        fund_data = enriched_results["fund"].get("results", {})
        for entry in results:
            code = entry["code"]
            if "signals" not in entry:
                entry["signals"] = []
            fund_info = fund_data.get(code, {})
            bonus = fund_info.get("bonus", 0)
            signal = fund_info.get("signal", "")
            if bonus != 0:
                entry["score"] += bonus
                entry["signals"].append(f"💹 {signal}" if signal else f"💹 资金{bonus:+d}")
                entry["fundamental_bonus"] = bonus
    
    # 2. 合并情绪增强评分
    if "sentiment" in enriched_results:
        enrichments = enriched_results["sentiment"].get("enrichments", [])
        for enh in enrichments:
            code = enh.get("code", "")
            total_bonus = enh.get("total_bonus", 0)
            for entry in results:
                if entry["code"] == code:
                    old_score = entry["score"]
                    entry["score"] += total_bonus
                    if total_bonus != 0:
                        entry["signals"].append(f"📰 {enh.get('details', '') or ''}")
    
    # 3. 合并板块轮动信息
    if "sector" in enriched_results:
        sector_info = enriched_results["sector"]
        for entry in results:
            industry = entry.get("industry", "")
            for hot in sector_info.get("hot_top5", []):
                if hot["name"] in industry or industry in hot["name"]:
                    entry["sector_bonus"] = 2
                    break

    # 4. 合并 AnySearch AI 搜索增强
    if "anysearch" in enriched_results:
        anysearch_data = enriched_results["anysearch"].get("results", {})
        for code, info in anysearch_data.items():
            for entry in results:
                if entry["code"] == code:
                    search_score = info.get("score", 0)
                    news_count = info.get("news_count", 0)
                    headlines = info.get("headlines", [])
                    if "signals" not in entry:
                        entry["signals"] = []
                    if search_score != 0:
                        entry["score"] += search_score
                        direction = "📈" if search_score > 0 else "📉"
                        entry["signals"].append(
                            f"{direction} AI搜索: {search_score:+d} ({news_count}条)"
                        )
                        for h in headlines[:2]:
                            entry["signals"].append(f"   📰 {h[:40]}")
                    entry["anysearch_bonus"] = search_score

    # 5. 合并新闻情绪 (news worker) — 修复: 之前 news 结果被丢弃
    if "news" in enriched_results:
        news_items = enriched_results["news"].get("news_items", [])
        for item in news_items:
            code = item.get("code", "")
            nscore = item.get("score", 0)
            pos = item.get("pos_signals", 0)
            neg = item.get("neg_signals", 0)
            ncount = item.get("news_count", 0)
            for entry in results:
                entry_code = entry["code"]
                clean = entry_code[2:] if entry_code[:2].isalpha() else entry_code
                item_code = code[2:] if isinstance(code, str) and code[:2].isalpha() else code
                if clean == item_code or entry_code == code:
                    if "signals" not in entry:
                        entry["signals"] = []
                    if nscore != 0:
                        entry["score"] += nscore * 0.4  # 权重低于资金面
                    if pos > 0:
                        entry["signals"].append(f"📰 新闻正面×{pos}")
                    elif neg > 0:
                        entry["signals"].append(f"📰 新闻负面×{neg}")
                    if ncount > 0:
                        entry["news_count"] = ncount
                        entry["news_score"] = nscore
                    break

    # 6. 合并专家级基本面分析（cn-financial-deep-analysis）
    if "expert" in enriched_results:
        expert_data = enriched_results["expert"].get("results", {})
        for code, info in expert_data.items():
            for entry in results:
                entry_code = entry["code"]
                clean = entry_code[2:] if entry_code[:2].isalpha() else entry_code
                if clean == code:
                    if "signals" not in entry:
                        entry["signals"] = []
                    fin_health = info.get("financial_health", 0)
                    fin_penalty = info.get("fraud_penalty", 0)
                    fin_fatal = info.get("fraud_fatal", False)
                    fin_bonus = info.get("total_bonus", 0)
                    # 加分到总分
                    if fin_bonus > 0:
                        entry["score"] += fin_bonus * 0.5  # 权重减半以免影响太大
                        entry["signals"].append(f"🏭 财务健康+{fin_bonus}")
                    elif fin_bonus < 0:
                        entry["score"] += fin_bonus * 0.5
                        entry["signals"].append(f"🔴 基本面{fin_bonus}")
                    if fin_fatal:
                        entry["signals"].append("🚫 舞弊一票否决")
                    entry["expert_health"] = fin_health
                    entry["expert_penalty"] = fin_penalty
                    entry["expert_fatal"] = fin_fatal

    # 按最终总分重新排序
    results.sort(key=lambda x: x["score"], reverse=True)
    for i, e in enumerate(results):
        e["rank"] = i + 1

    return results


if __name__ == "__main__":
    # 测试入口
    test_stocks = [
        {"code": "sz002415", "name": "海康威视", "score": 75},
        {"code": "sz002881", "name": "美格智能", "score": 68},
        {"code": "sh600519", "name": "贵州茅台", "score": 72},
    ]
    print("=" * 60)
    print("  🔧 parallel_workers 测试")
    print("=" * 60)
    
    results = parallel_enrich(test_stocks, use_delegate=False)
    print(f"\n📊 合并结果:")
    ranked = merge_and_rerank(test_stocks, results)
    for entry in ranked:
        print(f"  #{entry['rank']} {entry['code']} {entry['name']} 评分{entry['score']}")
