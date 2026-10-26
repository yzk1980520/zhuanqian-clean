"""market_sentiment_integrator.py v2.1 — 市场行情感知整合模块
基于 TDX 真实指数数据计算市场情绪，不再硬编码。
整合多源数据，输出量化市场情绪，自动适配策略。
"""
import json, os, time, sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

PROJECT = PROJECT_ROOT
CACHE_FILE = os.path.join(PROJECT, "data", "market_sentiment_cache.json")
CACHE_TTL = 1800  # 30分钟缓存

# P0-1修复: 写JSON统一走原子写
try:
    from core.pipeline.atomic_json import atomic_dump
except Exception:
    atomic_dump = None

# ── 熔断机制：同花顺热点接口本地被风控，第一次失败后1小时不重试 ──
_HOT_CIRCUIT_BREAKER = {"last_fail": 0, "cooldown": 3600}


def _load_cache():
    try:
        with open(CACHE_FILE) as f:
            c = json.load(f)
            if time.time() - c.get("ts", 0) < CACHE_TTL:
                return c
    except Exception:
        pass
    return None


def _save_cache(data):
    # P0-1修复: 改为原子写
    if atomic_dump is not None:
        atomic_dump(data, CACHE_FILE)
    else:
        atomic_json.atomic_dump(data, CACHE_FILE, encoding="utf-8")


def _market_state_to_mood(market_state, index_rsi, index_chg):
    """将市场状态映射为情绪分(0-100)和标签"""
    mapping = {
        "恐慌": (15, "恐慌", "抄底", "空仓"),
        "弱":   (30, "偏弱", "抄底", "半仓"),
        "震荡": (50, "中性", "综合", "7成仓"),
        "突破": (60, "偏暖", "突破", "8成仓"),
        "强":   (70, "偏强", "综合", "满仓"),
        "牛":   (85, "乐观", "趋势", "满仓"),
    }
    score, label, strategy, pos = mapping.get(market_state, (50, "中性", "综合", "7成仓"))

    # RSI 精细调整（在基础分上微调 ±10）
    if index_rsi is not None:
        if index_rsi < 25:
            score = max(5, score - 10)  # 超卖加剧
        elif index_rsi > 75:
            score = min(95, score + 10)  # 超买加剧

    # 当日跌幅大时额外降分
    if index_chg is not None and index_chg < -2:
        score = max(5, score - 5)

    return score, label, strategy, pos


def assess_market_mood():
    """综合评估市场情绪 (0=恐慌, 50=中性, 100=乐观)
    
    基于 TDX 真实指数数据分析，不再硬编码。
    返回 dict 含 mood_score, mood_label, suggested_strategy, position_advice,
    signals, hot_sectors。
    """
    cached = _load_cache()
    if cached:
        return cached.get("data", {})

    # 默认情绪（待真实数据覆盖）
    mood = {
        "mood_score": 50,
        "mood_label": "中性",
        "suggested_strategy": "综合",
        "position_advice": "7成仓",
        "signals": [],
        "hot_sectors": [],
    }

    # ── 从 TDX 获取真实指数数据分析市场 ──
    try:
        sys.path.insert(0, PROJECT)
        from core.pipeline.tdx_core import analyze_market
        mkt = analyze_market()
        market_state = mkt.get("market_state", "震荡")
        index_rsi = mkt.get("index_rsi", 50)
        index_chg = mkt.get("index_chg", 0)

        score, label, strategy, pos = _market_state_to_mood(market_state, index_rsi, index_chg)
        mood["mood_score"] = score
        mood["mood_label"] = label
        mood["suggested_strategy"] = strategy
        mood["position_advice"] = pos

        # 生成信号
        signals = []
        if market_state in ("恐慌", "弱"):
            signals.append("市场偏弱，建议控制仓位")
        if mkt.get("breadth", "未知") != "未知":
            signals.append(f"市场宽度: {mkt['breadth']}")
        mood["signals"] = signals

    except Exception as e:
        # 如果TDX数据不可用，保持默认值
        mood["signals"] = [f"指数数据不可用({e})"]

    # ── 尝试获取热点板块（带熔断） ──
    try:
        now = time.time()
        if now - _HOT_CIRCUIT_BREAKER["last_fail"] < _HOT_CIRCUIT_BREAKER["cooldown"]:
            # 熔断中，跳过
            mood["hot_sectors"] = []
        else:
            from news_sentiment import get_market_hot_topics
            hot = get_market_hot_topics(10)
            if hot:
                mood["hot_sectors"] = [h[0] for h in hot[:5]]
                mood["signals"].append(f"热点板块: {', '.join(mood['hot_sectors'])}")
            else:
                mood["hot_sectors"] = []
    except Exception:
        _HOT_CIRCUIT_BREAKER["last_fail"] = time.time()
        mood["hot_sectors"] = []

    _save_cache({"ts": time.time(), "data": mood})
    return mood


def sentiment_enrich_stock(code, name, base_score):
    """根据市场情绪、新闻情绪、热点题材增强个股评分

    Args:
        code: 股票代码 (如 sz002415)
        name: 股票名称
        base_score: 技术评分 (0-100)

    Returns:
        (enhanced_score, bonus, details)
    """
    mood = assess_market_mood()
    bonus = 0
    details = []
    ms = mood.get("mood_score", 50)

    # 1. 市场情绪加成
    if ms < 20:
        bonus -= 5
        details.append("panic(-5)")
    elif ms > 80:
        bonus += 5
        details.append("euphoria(+5)")
    elif ms < 40:
        bonus -= 2
        details.append("weak(-2)")
    elif ms > 60:
        bonus += 3
        details.append("strong(+3)")

    # 2. 个股新闻情绪
    try:
        sys.path.insert(0, PROJECT)
        from news_sentiment import get_news_sentiment_score
        sent = get_news_sentiment_score(code, name)
        news_bonus = sent.get("score", 0)
        bonus += news_bonus * 2
        if news_bonus > 0:
            details.append(f"news+(+{news_bonus * 2})")
        elif news_bonus < 0:
            details.append(f"news-({news_bonus * 2})")
    except Exception:
        pass

    # 3. 热点题材加成（带熔断）
    try:
        now = time.time()
        if now - _HOT_CIRCUIT_BREAKER["last_fail"] >= _HOT_CIRCUIT_BREAKER["cooldown"]:
            from news_sentiment import fetch_ths_hot_topics, analyze_hot_sector_relevance
            hot = fetch_ths_hot_topics()
            if hot:
                hr = analyze_hot_sector_relevance(code, name, hot)
                hot_bonus = hr.get("score", 0)
                bonus += hot_bonus * 3
                if hot_bonus > 0:
                    details.append(f"hot(+{hot_bonus * 3})")
    except Exception:
        _HOT_CIRCUIT_BREAKER["last_fail"] = time.time()

    # 情绪增强上限：避免覆盖基础评分（最多+8分）
    MAX_BONUS = 8
    bonus = min(bonus, MAX_BONUS)
    enhanced = max(0, min(100, base_score + bonus))
    return enhanced, bonus, details


def get_market_report():
    """生成市场行情报告（供外部调用）"""
    mood = assess_market_mood()
    try:
        sys.path.insert(0, PROJECT)
        from core.pipeline.tdx_core import analyze_market
        mkt = analyze_market()
    except Exception:
        mkt = {}

    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "mood": {
            "score": mood.get("mood_score", 50),
            "label": mood.get("mood_label", "?"),
        },
        "strategy": mood.get("suggested_strategy", "?"),
        "position": mood.get("position_advice", "?"),
        "hot_sectors": mood.get("hot_sectors", []),
        "signals": mood.get("signals", []),
        "index": {
            "close": mkt.get("index_close"),
            "chg": mkt.get("index_chg"),
            "rsi": mkt.get("index_rsi"),
            "state": mkt.get("market_state"),
        } if mkt else {},
    }


if __name__ == "__main__":
    r = get_market_report()
    print(json.dumps(r, ensure_ascii=False, indent=2))
