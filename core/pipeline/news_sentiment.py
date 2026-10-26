import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
news_sentiment.py — 新闻情绪评分模块 v1.0
============================================
从同花顺热点 + 东财个股新闻获取市场情绪数据，
产生量化情绪分数，融入选股评分体系。

用法:
  from news_sentiment import get_news_sentiment_score
  
  score, details = get_news_sentiment_score(code="002415", name="海康威视")
  # → score 范围 -3 到 +5, 可直接加到总评分上
"""
import json, os, sys, urllib.request, time, random, re, requests
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
from collections import Counter

# P0-1修复: 写JSON统一走原子写
try:
    from core.pipeline.atomic_json import atomic_dump
except Exception:
    atomic_dump = None

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]

CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "news_sentiment_cache.json")
CACHE_TTL_HOURS = 4  # 缓存有效期

# 熔断机制：同花顺热点接口失败后1小时内不再重试
_THS_CIRCUIT_BREAKER = {"last_fail": 0.0, "cooldown": 3600}

def _check_ths_breaker():
    """检查同花顺热点接口是否在熔断中"""
    return time.time() - _THS_CIRCUIT_BREAKER["last_fail"] < _THS_CIRCUIT_BREAKER["cooldown"]

def _trip_ths_breaker():
    """触发熔断"""
    _THS_CIRCUIT_BREAKER["last_fail"] = time.time()

def em_get(url, params=None, headers=None, timeout=15, **kwargs):
    """东财统一请求入口（内置限流）"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()

def _load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_cache(cache):
    # P0-1修复: 改为原子写
    if atomic_dump is not None:
        atomic_dump(cache, CACHE_FILE, ensure_ascii=False, indent=2)
    else:
        atomic_json.atomic_dump(cache, CACHE_FILE, ensure_ascii=False, indent=2, encoding="utf-8")

def _cache_get(code):
    """读取缓存（如果未过期）"""
    cache = _load_cache()
    entry = cache.get(code)
    if entry:
        ts = entry.get("timestamp", "")
        if ts and (time.time() - float(ts)) < CACHE_TTL_HOURS * 3600:
            return entry.get("data")
    return None

def _cache_set(code, data):
    cache = _load_cache()
    cache[code] = {"timestamp": time.time(), "data": data}
    _save_cache(cache)

# ========== 同花顺热点题材分析 ==========

def fetch_ths_hot_topics():
    """获取当日同花顺热点，返回题材-个股映射（带熔断）"""
    if _check_ths_breaker():
        return []
    today = date.today().strftime("%Y-%m-%d")
    url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{today}/orderby/date/orderway/desc/charset/GBK/"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        data = r.json()
        if data.get("errocode", 0) != 0:
            return {}
        rows = data.get("data") or []
        return rows
    except Exception as e:
        _trip_ths_breaker()
        return []

def analyze_hot_sector_relevance(code, name, hot_stocks):
    """
    分析个股所属热点题材的配合度。
    返回: {score: int, details: str, hot_tags: list}
    score 范围 0~3
    """
    if not hot_stocks:
        return {"score": 0, "details": "暂无热点数据", "hot_tags": [], "in_hot_list": False}

    # 1. 检查代码是否出现在热点榜
    target_code = code[-6:] if len(code) > 6 else code
    in_hot = False
    related_tags = []
    for s in hot_stocks:
        sc = str(s.get("code", ""))
        if sc == target_code:
            in_hot = True
            reason = s.get("reason", "")
            if reason:
                related_tags = [t.strip() for t in reason.split("+") if t.strip()]
            break

    # 2. 统计热门股票的题材分布（Top 20 题材）
    all_tags = []
    for s in hot_stocks[:50]:  # 只看前50只
        reason = s.get("reason", "")
        if reason:
            all_tags.extend([t.strip() for t in reason.split("+") if t.strip()])

    tag_counts = Counter(all_tags)
    top_tags = tag_counts.most_common(15)

    score = 0
    details = []

    if in_hot:
        score += 2
        details.append(f"🔥 出现在今日热点榜 ({len(related_tags)} 个题材)")

    if related_tags:
        details.append(f"   热门题材: {'+'.join(related_tags)}")
        score += 1
    elif not in_hot:
        details.append("   未出现在今日热点榜")

    return {
        "score": score,
        "details": "; ".join(details),
        "hot_tags": related_tags,
        "in_hot_list": in_hot,
        "top_market_tags": top_tags[:5],
    }

# ========== 东财个股新闻情绪分析 ==========

def fetch_eastmoney_news(code):
    """获取东财个股新闻，返回标题列表（curl_cffi 穿透 WAF 优先，requests 降级）"""
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    cb = "jQuery_news"
    inner_params = json.dumps({
        "uid": "", "keyword": code[-6:] if len(code) > 6 else code,
        "type": ["cmsArticleWebOld"], "client": "web",
        "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {
            "searchScope": "default", "sort": "default",
            "pageIndex": 1, "pageSize": 20,
            "preTag": "", "postTag": ""
        }},
    }, separators=(",", ":"))
    params = {"cb": cb, "param": inner_params}
    headers = {"User-Agent": UA, "Referer": "https://so.eastmoney.com/"}
    # 2026-08-05: 东财 search-api 按 TLS 指纹屏蔽 requests（返回空 body），
    # curl_cffi impersonate=chrome 可穿透（详见 a-share-picker skill）
    try:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(url, params=params, headers=headers, timeout=15,
                              impersonate="chrome")
        text = r.text or ""
        if len(text) < 100:
            raise ValueError(f"curl_cffi body 异常: len={len(text)}")
    except Exception:
        try:
            r = em_get(url, params=params, headers=headers, timeout=15)
            text = r.text or ""
        except Exception:
            return []
    try:
        json_str = text[text.index("(") + 1: text.rindex(")")]
        d = json.loads(json_str)
        articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
        return [{"title": re.sub(r"<[^>]+>", "", a.get("title", "")),
                 "time": a.get("date", ""),
                 "source": a.get("mediaName", "")} for a in articles]
    except Exception:
        return []

# 情绪关键词词典
_POSITIVE_KEYWORDS = {
    "涨停": 2, "大涨": 2, "突破": 1, "利好": 2, "中标": 2, "订单": 1,
    "签约": 1, "回购": 1, "增持": 2, "新高": 1, "预增": 1, "扭亏": 2,
    "放量": 1, "金叉": 1, "反转": 1, "补贴": 1, "政策": 0, "龙头": 1,
    "出海": 1, "扩张": 0, "推荐": 1, "买入": 1, "看好": 1, "受益": 1,
    "需求": 0, "涨价": 1, "高增长": 2, "突破瓶颈": 2, "战略合作": 1,
}

_NEGATIVE_KEYWORDS = {
    "跌停": -2, "大跌": -2, "暴跌": -2, "利空": -2, "减持": -2,
    "解禁": -1, "亏损": -2, "st": -3, "退市": -3, "警示": -2,
    "调查": -2, "处罚": -2, "诉讼": -1, "违约": -2, "爆雷": -3,
    "延期": -1, "下调": -1, "评级下调": -2, "预警": -1, "预警": -1,
    "现金流": -1, "债务": -1, "抛售": -1, "做空": -2, "崩盘": -3,
}

# ========== 本地 LLM 情绪分类增强 (P1-1, 2026-08-05) ==========
# 用本地 Qwen3.5-4B (llama.cpp, OpenAI 兼容) 批量分类新闻标题情绪，
# 规则方法降级兜底。LLM 不可用/超时/JSON 失败时静默回退纯规则。

LLM_API_URL = "http://127.0.0.1:8080/v1/chat/completions"
LLM_MODEL = r"D:\models\Qwen3.5-4B-GGUF\Qwen3.5-4B-Q4_K_M.gguf"
LLM_TIMEOUT = 30          # 单次请求超时（秒）
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 200
# 实测(llama.cpp Q4_K_M, 本机): 单批 5 条真实标题需 55s(超30s 超时)、2 条需 ~14s。
# 为满足 30s 超时规范并保证稳定，批大小取 2 条/批；一次 llm_classify_titles 调用
# 仍最多处理 10 条（analyze_news_sentiment 传入上限），内部自动分批。
LLM_BATCH_SIZE = 2
LLM_RETRY = 1             # JSON 解析失败重试次数

# LLM 三分类情绪 → 分数（与规则单条量纲一致：±2 强烈 / 0 中性）
_LLM_SENTIMENT_SCORE = {"positive": 2, "negative": -2, "neutral": 0}

_LLM_PROMPT_TEMPLATE = (
    "你是一个严格的金融新闻标题情绪分类器。对下面每条新闻标题，判断情绪方向，"
    "只输出 JSON 数组：[{{\"title\": \"<原标题>\", \"sentiment\": \"positive|negative|neutral\", "
    "\"confidence\": 0-1}}]。规则：只看标题字面信息，不推测背景；无法判断则为 neutral。\n"
    "输入标题：\n{numbered}"
)

def _llm_chat(prompt):
    """调用本地 LLM chat completions，返回 assistant 原始文本。异常向上抛。
    2026-08-17: 本地模型已卸载(Ollama/qwen2.5:7b 全清)，本函数停用，直接返回 None 走规则兜底。
    """
    return None
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": LLM_TEMPERATURE,
    }
    req = urllib.request.Request(
        LLM_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    return data["choices"][0]["message"]["content"]

def _parse_llm_json(text):
    """从容错文本中提取 JSON 数组（容忍 ```json 围栏 / 前后缀 / 截断）。失败抛异常。"""
    text = (text or "").strip()
    # 去 markdown 围栏
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    # 取第一个 [ 到最后一个 ]（容忍前后说明文字）
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        text = text[start:end + 1]
    arr = json.loads(text)
    if not isinstance(arr, list):
        raise ValueError("LLM 输出不是 JSON 数组")
    return arr

def _align_llm_results(titles, items):
    """将 LLM 返回条目按输入标题顺序对齐（容忍模型微调标题空格/标点）。
    缺失条目补 neutral(conf=0)，保证与输入等长同序。"""
    norm = lambda s: re.sub(r"\s+", "", s or "")
    out = [None] * len(titles)
    used = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        t = norm(it.get("title", ""))
        idx = None
        if t:
            for j, orig in enumerate(titles):
                if j in used:
                    continue
                no = norm(orig)
                if no and (t == no or t in no or no in t):
                    idx = j
                    break
        if idx is None:
            for j in range(len(titles)):
                if j not in used:
                    idx = j
                    break
        if idx is not None:
            used.add(idx)
            sent = str(it.get("sentiment", "neutral")).lower()
            if sent not in _LLM_SENTIMENT_SCORE:
                sent = "neutral"
            try:
                conf = float(it.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            out[idx] = {"title": titles[idx], "sentiment": sent,
                        "confidence": max(0.0, min(1.0, conf))}
    for j in range(len(titles)):
        if out[j] is None:
            out[j] = {"title": titles[j], "sentiment": "neutral", "confidence": 0.0}
    return out

def llm_classify_titles(titles):
    """
    用本地 Qwen3.5-4B 批量分类新闻标题情绪。
    titles: list[str]，每次最多 10 条（内部按 LLM_BATCH_SIZE=5 分批）。
    返回: list[dict]（与输入同序）:
          [{"title": str, "sentiment": "positive|negative|neutral", "confidence": float}]
    失败（服务不可用/超时/JSON 解析重试后仍失败）返回 None，调用方回退规则。
    """
    if not titles:
        return []
    results = []
    for i in range(0, len(titles), LLM_BATCH_SIZE):
        batch = titles[i:i + LLM_BATCH_SIZE]
        numbered = "\n".join(f"{j + 1}. {t}" for j, t in enumerate(batch))
        prompt = _LLM_PROMPT_TEMPLATE.format(numbered=numbered)
        arr = None
        for attempt in range(LLM_RETRY + 1):  # 首次 + 重试 1 次
            try:
                content = _llm_chat(prompt)
                arr = _parse_llm_json(content)
                if arr:
                    break
            except Exception:
                arr = None
        if not arr:
            return None  # 任一批失败 → 整体放弃，调用方静默回退规则
        results.extend(arr)
    return _align_llm_results(titles, results)

def _calc_title_sentiment(title):
    """计算单条新闻标题的情绪分数"""
    score = 0
    hits = {"positive": [], "negative": []}
    title_lower = title.lower()
    for word, val in _POSITIVE_KEYWORDS.items():
        if word in title_lower:
            score += val
            hits["positive"].append(word)
    for word, val in _NEGATIVE_KEYWORDS.items():
        if word in title_lower:
            score += val
            hits["negative"].append(word)
    return score, hits

def analyze_news_sentiment(code, name):
    """
    分析个股新闻情绪（规则打分 + 本地 LLM 增强修正）。
    返回: {score: int (-2~+2), details: str, news_count: int,
           norm_score: int, top_news: list, llm_enhanced: bool}
    LLM 不可用/超时/JSON 失败时静默回退纯规则，主链路绝不失败。
    """
    news = fetch_eastmoney_news(code)
    if not news:
        return {"score": 0, "details": "暂无新闻数据", "news_count": 0,
                "norm_score": 0, "top_news": [], "llm_enhanced": False}

    # 1. 规则打分照旧
    rule_scores = []
    for n in news[:10]:
        s, _hits = _calc_title_sentiment(n["title"])
        rule_scores.append(s)

    # 2. LLM 批量分类（任何异常都静默回退，绝不抛给主链路）
    llm_used = False
    llm_items = None
    try:
        llm_items = llm_classify_titles([n["title"] for n in news[:10]])
        if llm_items:
            llm_used = True
    except Exception:
        llm_items = None

    # 3. 融合打分：LLM confidence>=0.5 时以 LLM 为准，否则用规则
    scores = []
    positive_count = 0
    negative_count = 0
    top_news = []
    for i, n in enumerate(news[:10]):
        s = rule_scores[i]
        if llm_items and i < len(llm_items):
            item = llm_items[i]
            if item.get("confidence", 0) >= 0.5:
                sent = item.get("sentiment", "neutral")
                s = _LLM_SENTIMENT_SCORE.get(sent, 0)
        scores.append(s)
        if s > 0:
            positive_count += 1
        if s < 0:
            negative_count += 1
        top_news.append((n["title"], n["time"], s))

    avg_score = sum(scores) / len(scores) if scores else 0

    # 标准化到 -2~+2
    if avg_score > 1.5: norm = 2
    elif avg_score > 0.5: norm = 1
    elif avg_score < -1.5: norm = -2
    elif avg_score < -0.5: norm = -1
    else: norm = 0

    sentiment_word = {2: "📰 强烈正面", 1: "📰 偏正面", 0: "📰 中性",
                      -1: "📰 偏负面", -2: "📰 强烈负面"}

    recent_news = top_news[:3]
    news_summary = "; ".join([f"{t[:30]}...({s:+.0f})" for t, tm, s in recent_news])

    # LLM 增强标注
    llm_tag = "🤖LLM增强 " if llm_used else ""

    return {
        "score": norm,
        "details": f"{llm_tag}{sentiment_word.get(norm, '中性')} ({positive_count}正/{negative_count}负, {len(news)}条)",
        "news_count": len(news),
        "top_news": top_news[:5],
        "norm_score": norm,
        "llm_enhanced": llm_used,
    }

# ========== 复合评分 ==========

def get_news_sentiment_score(code, name=""):
    """
    复合情绪评分：整合热点题材 + 个股新闻
    返回: {score: int (-3~+5), details: dict}
    score 可直接加到选股总评分上
    """
    # 检查缓存
    cached = _cache_get(code)
    if cached:
        return cached

    # 1. 热点题材分析
    hot_stocks = fetch_ths_hot_topics()
    hot_result = analyze_hot_sector_relevance(code, name, hot_stocks)

    # 2. 个股新闻情绪
    news_result = analyze_news_sentiment(code, name)

    # 3. 复合分数（热点: 0~3, 新闻: -2~+2）
    total = hot_result["score"] + news_result["norm_score"]
    total = max(-3, min(5, total))

    result = {
        "score": total,
        "details": {
            "hot_sector": hot_result,
            "news_sentiment": news_result,
            "composite": f"情绪总分: {total:+d} (热点{hot_result['score']:+d} + 新闻{news_result['norm_score']:+d})",
        }
    }

    _cache_set(code, result)
    return result

def get_sector_bonus_for_all(scored_stocks):
    """
    批量给一组已评分的股票加情绪分。
    scored_stocks: [(score, code, ...), ...] 同 stock_picker_v3 格式
    返回: [(adjusted_score, code, ...), ...]
    """
    if not scored_stocks:
        return scored_stocks

    today = date.today().strftime("%Y-%m-%d")
    result = []

    # 先拉一次热点（批量共享，避免重复调用）
    hot_stocks = fetch_ths_hot_topics()

    for item in scored_stocks:
        sc, code = item[0], item[1]
        name = item[3] if len(item) > 3 else ""

        # 只查热点（批量场景不做个股新闻，太耗时）
        hot_result = analyze_hot_sector_relevance(code, name, hot_stocks)
        bonus = hot_result["score"]
        new_score = max(0, min(100, sc + bonus * 3))  # 热点分3倍权重

        # 复制原 tuple，修改第一项
        new_item = list(item)
        new_item[0] = new_score
        if len(new_item) > 5:
            # 在 signals 中加入情绪标记
            signals = list(new_item[5] if len(new_item) > 5 else [])
            if bonus > 0:
                signals.append(f"🔥 热点题材+{bonus}")
            new_item[5] = tuple(signals)
        result.append(tuple(new_item))

    return result

def get_market_hot_topics(top_n=10):
    """获取当日全市场最热题材（供行情报告使用）"""
    hot_stocks = fetch_ths_hot_topics()
    all_tags = []
    for s in hot_stocks:
        reason = s.get("reason", "")
        if reason:
            all_tags.extend([t.strip() for t in reason.split("+") if t.strip()])
    counter = Counter(all_tags)
    return counter.most_common(top_n)

# ========== CLI ==========
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        code = sys.argv[1]
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        result = get_news_sentiment_score(code, name)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("用法: python news_sentiment.py <股票代码> [股票名称]")
        print()
        print("当日热点题材 Top 10:")
        for tag, n in get_market_hot_topics(10):
            print(f"  {tag}: {n} 只")
