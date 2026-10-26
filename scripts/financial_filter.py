# P2-1b t_d5806dfc: 归位 scripts/ — 注入 sys.path(项目根 + scripts/) 头部, 任意 CWD/导入方式可解析兄弟模块(非静默: 失败即抛)
import os as _os_p21b, sys as _sys_p21b
_p21b_dir = _os_p21b.path.dirname(_os_p21b.path.abspath(__file__))
_p21b_root = _os_p21b.path.dirname(_p21b_dir)
for _p21b_x in (_p21b_root, _p21b_dir):
    if _p21b_x not in _sys_p21b.path:
        _sys_p21b.path.insert(0, _p21b_x)
del _p21b_dir, _p21b_root, _p21b_x

import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
financial_filter.py — 基本面财务过滤引擎 v1.0
==============================================
A股财务健康评分 + 舞弊检测 + 行业对标

数据源: AKShare（同花顺/东方财富接口）
缓存: 本地JSON，每日自动刷新

评分体系（源自 cn-financial-deep-analysis）：
  - 五维财务健康评分 (0~40)：盈利能力35%·成长25%·营运15%·偿债15%·现金流10%
  - 舞弊检测扣分 (-30~0)：70+预警信号，3项警告/6项扣分/11项一票否决
  - 行业对标调整：相对行业中位数偏离度

集成方式：通过 score_stock() bonuses dict 注册为 financial_health_bonus / fraud_penalty

用法:
    from financial_filter import score_financial_health, detect_fraud
    health = score_financial_health("600519")
    fraud = detect_fraud("600519")
"""

import os, json, time, logging
from datetime import datetime

logger = logging.getLogger("financial_filter")

PROJECT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(PROJECT, "data")
CACHE_FILE = os.path.join(CACHE_DIR, "financial_cache.json")

# P0-1修复: 写JSON统一走原子写(FileLock + tempfile replace), 防cron并发覆盖
try:
    from atomic_json import atomic_dump
except Exception:
    atomic_dump = None
CACHE_TTL = 86400  # 24小时

# ============================================================
#  数据采集层 — AKShare
# ============================================================

_HAS_AKSHARE = False
try:
    import akshare as ak
    _HAS_AKSHARE = True
    # 禁用 akshare 的进度条输出
    logging.getLogger("akshare").setLevel(logging.WARNING)
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="akshare")
    # 禁用 tqdm 进度条
    os.environ["TQDM_DISABLE"] = "1"
except ImportError:
    logger.warning("akshare 未安装，使用缓存模式（无实时刷新能力）")

# ============================================================
#  东财直连降级层 (P0-4, 2026-08-05)
#  akshare 失败时降级到东财 datacenter-web RPT_F10_FINANCE_MAINFINADATA
#  实测(2026-08-05): datacenter-web 未被 WAF 屏蔽, 年报字段齐全
# ============================================================

EM_FIN_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# 东财年报字段 → financial_filter indicators 映射
# 数值语义与同花顺路径对齐: 金额=元, 百分比字段÷100, 产权比率=原始比率(勾稽 er/(1+er) 自洽)
_EM_IND_MAP = {
    "TOTALOPERATEREVE": "revenue",            # 营业总收入(元)
    "TOTALOPERATEREVETZ": "revenue_yoy",      # 营业总收入同比增长(%)
    "PARENTNETPROFIT": "net_profit",          # 归母净利润(元)
    "PARENTNETPROFITTZ": "net_profit_yoy",    # 归母净利润同比增长(%)
    "KCFJCXSYJLR": "deducted_profit",         # 扣非净利润(元)
    "XSMLL": "gross_margin",                  # 销售毛利率(%)
    "XSJLL": "net_margin",                    # 销售净利率(%)
    "ROEJQ": "roe",                           # 加权净资产收益率(%)
    "ZCFZL": "debt_ratio",                    # 资产负债率(%)
    "LD": "current_ratio",                    # 流动比率
    "SD": "quick_ratio",                      # 速动比率
    "CQBL": "equity_ratio",                   # 产权比率(原始比率)
    "BPS": "bvps",                            # 每股净资产
    "EPSJB": "basic_eps",                     # 基本每股收益
    "MGJYXJJE": "cashflow_per_share",         # 每股经营现金流
    "CHZZL": "inv_turnover",                  # 存货周转率
    "CHZZTS": "inv_turnover_days",            # 存货周转天数
    "YSZKZZTS": "ar_turnover_days",           # 应收账款周转天数
    "TOAZZL": "asset_turnover",               # 总资产周转率
}
_EM_PCT_FIELDS = {"revenue_yoy", "net_profit_yoy", "gross_margin", "net_margin",
                  "roe", "debt_ratio"}

def _to_secucode(code):
    """6位A股代码 → 东财 SECUCODE (600519 → 600519.SH, 000002 → 000002.SZ)
    兼容输入: 600519 / sh600519 / 600519.SH / SH600519"""
    c = str(code).strip().lower()
    # 先剥离交易所后缀 (.sh/.sz/.bj) 和前缀 (sh/sz/bj)
    for suf in (".sh", ".sz", ".bj"):
        if c.endswith(suf):
            c = c[:-3]
            break
    if c[:2] in ("sh", "sz", "bj"):
        c = c[2:]
    c = c[-6:]
    # 长度/数字校验: 非法代码入口阻断
    if not (c.isdigit() and len(c) == 6):
        return None
    if c[0] in ("6", "9"):
        return "%s.SH" % c
    if c[0] in ("0", "2", "3"):
        return "%s.SZ" % c
    return "%s.BJ" % c  # 4/8 开头 → 北交所

def _em_http_get(url, params, headers, timeout=15):
    """东财 HTTP 获取: curl_cffi(chrome指纹) → requests → urllib 三级降级

    2026-08-02 实测: 东财按 TLS 指纹屏蔽 urllib/httpx(空body/断开),
    curl_cffi impersonate=chrome 可穿透; datacenter-web 本身未被 WAF 屏蔽。
    """
    # 1. curl_cffi (优先, 穿透 WAF)
    try:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(url, params=params, headers=headers, timeout=timeout,
                              impersonate="chrome")
        text = r.text or ""
        if len(text) >= 50:
            return text
    except Exception:
        pass
    # 2. requests
    try:
        import requests
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        text = r.text or ""
        if len(text) >= 50:
            return text
    except Exception:
        pass
    # 3. urllib 兜底
    import urllib.request, urllib.parse
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(url + "?" + qs, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    if len(text) < 50:
        raise RuntimeError("eastmoney http body too short: %d" % len(text))
    return text

def _fetch_financial_eastmoney(code):
    """东财直连降级路径: RPT_F10_FINANCE_MAINFINADATA (仅年报)

    与 _fetch_akshare_ths 返回结构一致:
        {code, latest_year, prev_year, indicators, fraud, error}
    """
    result = {"code": code, "latest_year": None, "prev_year": None,
              "indicators": {}, "fraud": {}, "error": None}
    secucode = _to_secucode(code)
    if not secucode:
        result["error"] = "invalid code: %r" % (code,)
        return result
    params = {
        "reportName": "RPT_F10_FINANCE_MAINFINADATA",
        "columns": "ALL",
        "filter": '(SECUCODE="%s")' % secucode,
        "pageNumber": 1, "pageSize": 6,
        "sortTypes": -1, "sortColumns": "REPORT_DATE",
        "source": "HSF10", "client": "PC",
    }
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
        "Referer": "https://emweb.securities.eastmoney.com/",
    }
    try:
        text = _em_http_get(EM_FIN_URL, params, headers)
        data = json.loads(text)
        rows = (data.get("result") or {}).get("data") or []
        # 只取年报(与同花顺"按年度"语义一致)
        annual = [r for r in rows if str(r.get("REPORT_TYPE", "")) == "年报"]
        if not annual:
            result["error"] = "eastmoney no annual rows"
            return result
        latest, prev = annual[0], (annual[1] if len(annual) > 1 else {})

        ind = {}
        for em_key, ind_key in _EM_IND_MAP.items():
            v = latest.get(em_key)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if ind_key in _EM_PCT_FIELDS:
                fv = fv / 100.0
            ind[ind_key] = fv

        # 上年金额(供同比计算, 与同花顺路径一致)
        for em_key, ind_key in (("TOTALOPERATEREVE", "revenue_prev"),
                                ("PARENTNETPROFIT", "net_profit_prev"),
                                ("KCFJCXSYJLR", "deducted_profit_prev")):
            v = prev.get(em_key)
            if v is not None:
                try:
                    ind[ind_key] = float(v)
                except (TypeError, ValueError):
                    pass

        np_val = ind.get("net_profit", 0) or 0
        dp_val = ind.get("deducted_profit", 0) or 0
        ind["non_recurring"] = np_val - dp_val
        ind["non_recurring_ratio"] = ind["non_recurring"] / np_val if np_val and abs(np_val) > 0 else 0

        result["latest_year"] = str(latest.get("REPORT_YEAR") or str(latest.get("REPORT_DATE", ""))[:4])
        result["prev_year"] = str(prev.get("REPORT_YEAR") or str(prev.get("REPORT_DATE", ""))[:4]) if prev else None
        result["indicators"] = ind

        # 舞弊检测字段(与同花顺路径同构)
        fraud = {}
        ar_prev = _parse_num(prev.get("YSZKZZTS")) or 0
        ar_curr = _parse_num(latest.get("YSZKZZTS")) or 0
        fraud["ar_growth"] = (ar_curr - ar_prev) / ar_prev if ar_prev and ar_prev > 0 else 0
        rev_prev = ind.get("revenue_prev", 0) or 0
        rev_curr = ind.get("revenue", 0) or 0
        fraud["revenue_growth_rate"] = (rev_curr - rev_prev) / rev_prev if rev_prev > 0 else (ind.get("revenue_yoy", 0) or 0)
        gm_prev = _parse_pct(prev.get("XSMLL"), 0) or 0
        gm_curr = _parse_pct(latest.get("XSMLL"), 0) or 0
        fraud["gross_margin_change"] = gm_curr - gm_prev
        cf_ps = ind.get("cashflow_per_share", 0) or 0
        eps = ind.get("basic_eps", 1) or 1
        fraud["opcf_to_profit"] = cf_ps / eps if eps != 0 else 0
        inv_prev = _parse_num(prev.get("CHZZTS")) or 0
        inv_curr = _parse_num(latest.get("CHZZTS")) or 0
        fraud["inv_growth"] = (inv_curr - inv_prev) / inv_prev if inv_prev and inv_prev > 0 else 0
        fraud["non_recurring_ratio"] = ind.get("non_recurring_ratio", 0)
        dr_safe = ind.get("debt_ratio") or 0
        cf_safe = ind.get("cashflow_per_share") or 0
        fraud["debt_high_with_cash"] = dr_safe > 0.7 and cf_safe > 0
        fraud["low_rnd_high_intangible"] = False
        result["fraud"] = fraud
    except Exception as e:
        import traceback
        tb = traceback.format_exc()[-300:]
        logger.warning("东财降级获取 %s 失败: %s" % (code, e))
        result["error"] = "%s | %s" % (e, tb[:150])
    return result

def _parse_num(v, default=None):
    """解析数值，支持'亿' '万' 后缀"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace(" ", "")
    if not s or s in ("--", "-", "", "False", "None"):
        return default
    multiplier = 1.0
    if "万亿" in s:
        multiplier = 1e12
        s = s.replace("万亿", "")
    elif "亿" in s:
        multiplier = 1e8
        s = s.replace("亿", "")
    elif "万" in s:
        multiplier = 1e4
        s = s.replace("万", "")
    # 百分比去掉 % 符号，让 _parse_pct 处理除以100的逻辑
    is_pct = "%" in s
    if is_pct:
        s = s.replace("%", "")
    try:
        return float(s) * multiplier
    except (ValueError, TypeError):
        return default

def _parse_pct(v, default=None):
    """解析百分比"""
    v = _parse_num(v)
    if v is None:
        return default
    # 兼容"32.53%"→0.3253 和 0.3253; 负数百分比(-539 = -539%)也要转换
    return v / 100.0 if abs(v) > 1 else v

def _fetch_akshare_ths(code):
    """同花顺(akshare)路径 — 原 fetch_financial_data 主体（P0-4 拆分为降级链第1级）

    Args:
        code: 6位A股代码，如 '600519'

    Returns:
        dict: {latest_year, prev_year, indicators: {...}, fraud: {...}, error}
    """
    result = {"code": code, "latest_year": None, "prev_year": None,
              "indicators": {}, "fraud": {}, "error": None}

    if not _HAS_AKSHARE:
        result["error"] = "akshare not available"
        return result

    try:
        # === 1. 核心财务摘要（按年度）===
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
        if df is None or df.empty:
            result["error"] = "no data"
            return result

        # 只保留最近3年有数据的行，按年份降序（最新在前）
        df = df[df["报告期"].astype(str).str.match(r"202[2-6]")].copy()
        if df.empty:
            result["error"] = "no recent data"
            return result
        df = df.sort_values("报告期", ascending=False).reset_index(drop=True)

        # 解析每一行的指标
        def _row_to_dict(row):
            d = {}
            for col in df.columns:
                d[col] = row[col]
            return d

        years = df["报告期"].tolist()
        result["latest_year"] = str(years[0]) if years else None
        result["prev_year"] = str(years[1]) if len(years) > 1 else None

        latest = _row_to_dict(df.iloc[0])
        prev = _row_to_dict(df.iloc[1]) if len(df) > 1 else {}

        # === 整合指标 ===
        ind = {}
        # 盈利能力
        ind["revenue"] = _parse_num(latest.get("营业总收入"))
        ind["revenue_yoy"] = _parse_pct(latest.get("营业总收入同比增长率"))
        ind["net_profit"] = _parse_num(latest.get("净利润"))
        ind["net_profit_yoy"] = _parse_pct(latest.get("净利润同比增长率"))
        ind["deducted_profit"] = _parse_num(latest.get("扣非净利润"))
        ind["gross_margin"] = _parse_pct(latest.get("销售毛利率"))
        ind["net_margin"] = _parse_pct(latest.get("销售净利率"))
        ind["roe"] = _parse_pct(latest.get("净资产收益率"))
        # 上一年的营收/利润（供同比比较）
        ind["revenue_prev"] = _parse_num(prev.get("营业总收入"))
        ind["net_profit_prev"] = _parse_num(prev.get("净利润"))
        ind["deducted_profit_prev"] = _parse_num(prev.get("扣非净利润"))
        # 偿债能力
        ind["debt_ratio"] = _parse_pct(latest.get("资产负债率"))
        # 从 abstract 已有数据提取更多指标
        if latest.get("存货周转率"):
            ind["inv_turnover"] = _parse_num(latest.get("存货周转率"))
        if latest.get("应收账款周转天数"):
            ind["ar_turnover_days"] = _parse_num(latest.get("应收账款周转天数"))
        if latest.get("存货周转天数"):
            ind["inv_turnover_days"] = _parse_num(latest.get("存货周转天数"))
        if latest.get("流动比率"):
            ind["current_ratio"] = _parse_num(latest.get("流动比率"))
        if latest.get("速动比率"):
            ind["quick_ratio"] = _parse_num(latest.get("速动比率"))
        if latest.get("每股经营现金流"):
            ind["cashflow_per_share"] = _parse_num(latest.get("每股经营现金流"))
        if latest.get("基本每股收益"):
            ind["basic_eps"] = _parse_num(latest.get("基本每股收益"))
        if latest.get("每股净资产"):
            ind["bvps"] = _parse_num(latest.get("每股净资产"))
        if latest.get("产权比率"):
            # 产权比率 akshare 返回百分数('40.18'=40.18%) 用 _parse_num 保留百分数
            # 勾稽时 er/(1+er) 自动抵消单位(40.18/41.18=0.9757), 勿改 _parse_pct
            ind["equity_ratio"] = _parse_num(latest.get("产权比率"))

        # === 3. 利润表（费用结构）- 跳过因为太慢 ===
        # 非经常性损益直接从摘要计算
        np_val = ind.get("net_profit", 0) or 0
        dp_val = ind.get("deducted_profit", 0) or 0
        ind["non_recurring"] = np_val - dp_val
        ind["non_recurring_ratio"] = ind["non_recurring"] / np_val if np_val and abs(np_val) > 0 else 0

        # === 舞弊检测专用指标 ===
        fraud = {}
        # 应收账款增长率 vs 营收增长率
        ar_prev = _parse_num(prev.get("应收账款周转天数"))
        ar_curr = _parse_num(latest.get("应收账款周转天数"))
        if ar_prev and ar_prev > 0:
            fraud["ar_growth"] = (ar_curr - ar_prev) / ar_prev
        else:
            fraud["ar_growth"] = 0

        rev_prev = ind.get("revenue_prev", 0) or 0
        rev_curr = ind.get("revenue", 0) or 0
        if rev_prev > 0:
            fraud["revenue_growth_rate"] = (rev_curr - rev_prev) / rev_prev
        else:
            fraud["revenue_growth_rate"] = ind.get("revenue_yoy", 0) or 0

        # 毛利率稳定性
        gm_prev = _parse_pct(prev.get("销售毛利率"), 0) or 0
        gm_curr = _parse_pct(latest.get("销售毛利率"), 0) or 0
        fraud["gross_margin_change"] = gm_curr - gm_prev

        # 经营现金流/净利润
        cf_ps = ind.get("cashflow_per_share", 0) or 0
        eps = ind.get("basic_eps", 1) or 1
        fraud["opcf_to_profit"] = cf_ps / eps if eps != 0 else 0

        # 存货增长率 vs 营收增长率
        inv_prev = _parse_num(prev.get("存货周转天数"))
        inv_curr = _parse_num(latest.get("存货周转天数"))
        if inv_prev and inv_prev > 0:
            fraud["inv_growth"] = (inv_curr - inv_prev) / inv_prev if inv_prev else 0
        else:
            fraud["inv_growth"] = 0

        # 非经常性损益占比
        fraud["non_recurring_ratio"] = ind.get("non_recurring_ratio", 0)

        # 大存大贷判断（简化：负债率高+现金多=可疑）
        dr_safe = (ind.get("debt_ratio") or 0)
        cf_safe = (ind.get("cashflow_per_share") or 0)
        fraud["debt_high_with_cash"] = dr_safe > 0.7 and cf_safe > 0

        # 研发资本化率（简化：如果没有研发费用但有大量无形资产）
        rnd = ind.get("rnd_expense", 0) or 0
        fraud["low_rnd_high_intangible"] = rnd == 0  # placeholder

        result["indicators"] = ind
        result["fraud"] = fraud

    except Exception as e:
        import traceback
        tb = traceback.format_exc()[-500:]
        logger.error(f"获取 {code} 财务数据失败: {e}\n{tb}")
        result["error"] = f"{e} | {tb[:200]}"

    return result

def fetch_financial_data(code):
    """获取单只股票的财务数据，返回结构化 dict（P0-4 降级链）

    降级链: ① akshare(同花顺) → ② 东财直连(datacenter-web RPT_F10) → ③ error 记录

    Args:
        code: 6位A股代码，如 '600519'

    Returns:
        dict: {latest_year, prev_year, indicators: {...}, fraud: {...},
               error, source(akshare/eastmoney)}
    """
    result = {"code": code, "latest_year": None, "prev_year": None,
              "indicators": {}, "fraud": {}, "error": None}

    # 1. 东财直连主路径 (P1-13优化 2026-08-08: akshare同花顺接口页面结构变化持续失败
    #    原顺序 akshare→东财 每次浪费一次快速失败+请求; 反转: 东财稳定优先, akshare降级)
    try:
        em = _fetch_financial_eastmoney(code)
    except Exception as e:
        em = {"error": str(e)[:200]}
    if em and not em.get("error"):
        em["source"] = "eastmoney"
        return em
    if em:
        result["eastmoney_error"] = em.get("error")

    # 2. akshare 降级路径
    data = _fetch_akshare_ths(code)
    if data and not data.get("error"):
        data["source"] = "akshare"
        return data
    result["akshare_error"] = (data or {}).get("error") or "akshare failed"

    # 3. 全部失败 → error 记录（保持原行为: 失败也缓存, 下次重试）
    errs = [x for x in (result.get("akshare_error"), result.get("eastmoney_error")) if x]
    result["error"] = " | ".join(errs) if errs else "fetch failed"
    logger.warning(f"P1-13: {code} 财务数据获取失败, 已缓存error下次重试 | {result['error'][:200]}")
    return result

# ============================================================
#  缓存管理
# ============================================================

def _load_cache():
    """加载财务数据缓存"""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 检查时效性
        ts = data.get("_timestamp", 0)
        if time.time() - ts > CACHE_TTL:
            logger.info("财务缓存已过期，将刷新")
        stocks = data.get("stocks", {})
        # P0-4 (2026-08-08): 百分比字段值域防御归一化 — 历史混入 abs(v)>1 的百分数原值一律÷100,
        # 与 _parse_pct 语义统一(东财路径恒÷100 / 同花顺路径启发式, 两套并存曾导致 9 只股票舞弊误判)
        for s in stocks.values():
            ind = s.get("indicators") if isinstance(s, dict) else None
            if not isinstance(ind, dict):
                continue
            for fld in _EM_PCT_FIELDS:
                v = ind.get(fld)
                if isinstance(v, (int, float)) and abs(v) > 1:
                    ind[fld] = round(v / 100.0, 6)
        return stocks
    except Exception:
        return {}

def _save_cache(stocks_data):
    """保存财务数据缓存 — P0-1修复: 改为原子写, 防并发覆盖"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    data = {
        "_timestamp": time.time(),
        "_date": datetime.now().strftime("%Y-%m-%d"),
        "stocks": stocks_data,
    }
    if atomic_dump is not None:
        atomic_dump(data, CACHE_FILE, ensure_ascii=False, indent=2)
    else:
        atomic_json.atomic_dump(data, CACHE_FILE, ensure_ascii=False, indent=2, encoding="utf-8")

def get_or_fetch(code, force_refresh=False):
    """获取财务数据（缓存优先）

    Args:
        code: 6位A股代码
        force_refresh: 强制刷新缓存

    Returns:
        dict: 财务数据结构
    """
    cache = _load_cache()
    code_key = str(code)

    if not force_refresh and code_key in cache:
        data = cache[code_key]
        if data and not data.get("error"):
            # 字段完整性校验(2026-08-02): 旧缓存缺 bvps/equity_ratio → 勾稽校验不生效
            # 缺失时视为过期重抓(仅一次刷新机会, 避免无限重抓)
            ind = data.get("indicators", {})
            if "bvps" not in ind or "equity_ratio" not in ind:
                data = fetch_financial_data(code)
                if data and not data.get("error"):
                    cache[code_key] = data
                    _save_cache(cache)
                return data
            return data

    # 实时获取
    data = fetch_financial_data(code)

    # 更新缓存
    cache[code_key] = data
    _save_cache(cache)

    return data

def batch_fetch(codes, force_refresh=False):
    """批量获取财务数据（只获取未缓存或过期的）

    Args:
        codes: 股票代码列表
        force_refresh: 强制刷新

    Returns:
        dict: {code: data, ...}
    """
    cache = _load_cache()
    results = {}
    need_fetch = []

    for code in codes:
        code_key = str(code)
        if not force_refresh and code_key in cache:
            data = cache[code_key]
            if data and not data.get("error"):
                results[code_key] = data
                continue
        need_fetch.append(code)

    if need_fetch:
        logger.info(f"批量获取 {len(need_fetch)} 只股票财务数据...")
        # P0-4: 不再依赖 _HAS_AKSHARE 门控, 批量路径同样走
        # fetch_financial_data 降级链(akshare→东财直连)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(len(need_fetch), 5)) as pool:
            fut_map = {pool.submit(fetch_financial_data, c): c for c in need_fetch}
            for fut in as_completed(fut_map):
                code = fut_map[fut]
                try:
                    data = fut.result(timeout=30)
                    results[str(code)] = data
                    cache[str(code)] = data
                    # P1-13: 返回了结果但内部是 error → 明确记录(原: 静默写入)
                    if data and data.get("error"):
                        logger.warning(f"P1-13: batch_fetch {code} 无财务结果(error={str(data['error'])[:120]})")
                except Exception as e:
                    # P1-13: 异常跳过 → 含代码+原因(原: 无P1-13标记)
                    logger.warning(f"P1-13: batch_fetch 跳过 {code}, 无财务结果, error={e}")

        _save_cache(cache)

    return results

# ============================================================
#  五维财务健康评分 (0~40分)
# ============================================================

def score_financial_health(data):
    """五维财务健康评分"""
    if not data or data.get("error"):
        return 0, ["⚠️ 无财务数据"]

    ind = data.get("indicators", {})
    sigs = []
    score = 0.0

    # 安全取值
    def _v(key, default=0.0):
        v = ind.get(key)
        return v if v is not None else default

    roe = _v("roe")
    gm = _v("gross_margin")
    nm = _v("net_margin")
    dp = _v("deducted_profit")
    np = _v("net_profit")

    # ROE评分 (5分)
    if roe >= 0.20:
        score += 5
        sigs.append("✅ ROE>20%")
    elif roe >= 0.15:
        score += 4
        sigs.append("📈 ROE=%.1f%%" % (roe * 100))
    elif roe >= 0.10:
        score += 2
        sigs.append("📊 ROE=%.1f%%" % (roe * 100))
    elif roe <= 0:
        score -= 2
        sigs.append("⚠️ ROE<0")

    # 毛利率评分 (4分)
    if gm >= 0.60:
        score += 4
        sigs.append("✅ 毛利率%.1f%%" % (gm * 100))
    elif gm >= 0.30:
        score += 2.5
        sigs.append("📈 毛利率%.1f%%" % (gm * 100))
    elif gm >= 0.15:
        score += 1
    else:
        score -= 1
        sigs.append("⚠️ 毛利率<15%")

    # 净利率评分 (3分)
    if nm >= 0.20:
        score += 3
    elif nm >= 0.10:
        score += 2
        sigs.append("📈 净利率%.1f%%" % (nm * 100))
    elif nm >= 0.05:
        score += 1
    elif nm <= 0:
        score -= 2
        sigs.append("🔴 净利率<0")

    # 扣非净利润检查 (2分)
    if np and dp and abs(np) > 0:
        non_rec_ratio = (np - dp) / abs(np)
        if abs(non_rec_ratio) < 0.1:
            score += 2
        elif abs(non_rec_ratio) > 0.3:
            score -= 2
            sigs.append("⚠️ 非经常性损益>30%")
        else:
            score += 0.5

    # ─── 维度2: 成长能力 (权重25%→10分) ───
    rev_yoy = _v("revenue_yoy")
    np_yoy = _v("net_profit_yoy")

    # 营收增长 (5分)
    if rev_yoy >= 0.25:
        score += 5
        sigs.append("📈 营收增长%.1f%%" % (rev_yoy * 100))
    elif rev_yoy >= 0.15:
        score += 4
    elif rev_yoy >= 0.05:
        score += 2.5
    elif rev_yoy >= 0:
        score += 1
    else:
        score -= 1
        sigs.append("📉 营收负增长%.1f%%" % (rev_yoy * 100))

    # 利润增长 (5分)
    if np_yoy >= 0.30:
        score += 5
        sigs.append("📈 利润增长%.1f%%" % (np_yoy * 100))
    elif np_yoy >= 0.15:
        score += 4
    elif np_yoy >= 0.05:
        score += 2
    elif np_yoy >= 0:
        score += 1
    else:
        score -= 2
        sigs.append("📉 利润负增长")
        if np_yoy < -0.3:
            score -= 2
            sigs.append("🔴 利润大跌")

    # ─── 维度3: 营运能力 (权重15%→6分) ───
    ar_days = _v("ar_turnover_days")
    inv_days = _v("inv_turnover_days")
    at = _v("asset_turnover")

    # 应收账款周转 (3分)
    if ar_days < 30:
        score += 3
        sigs.append("✅ 应收周转快(%d天)" % ar_days)
    elif ar_days < 90:
        score += 2
    elif ar_days < 180:
        score += 0.5
    else:
        score -= 1
        sigs.append("⚠️ 应收周转慢(%d天)" % ar_days)

    # 总资产周转率 (3分)
    if at >= 1.0:
        score += 3
    elif at >= 0.5:
        score += 2
    elif at >= 0.2:
        score += 1
    else:
        score += 0  # 重资产行业容差

    # ─── 维度4: 偿债能力 (权重15%→6分) ───
    dr = _v("debt_ratio")
    cr = _v("current_ratio")

    # 资产负债率 (3分)
    if dr < 0.30:
        score += 3
        sigs.append("✅ 低负债%.1f%%" % (dr * 100))
    elif dr < 0.50:
        score += 2
    elif dr < 0.65:
        score += 1
    elif dr < 0.80:
        score += 0
    else:
        score -= 2
        sigs.append("🔴 高负债>80%")

    # 流动比率 (3分)
    if cr > 2.0:
        score += 3
    elif cr > 1.5:
        score += 2
    elif cr > 1.0:
        score += 1
    elif cr > 0.7:
        score += 0
    else:
        score -= 1
        sigs.append("⚠️ 流动比率<0.7")

    # ─── 维度5: 现金流质量 (权重10%→4分) ───
    cf_ps = _v("cashflow_per_share")
    eps = _v("basic_eps", 1)
    opcf_to_np = cf_ps / eps if eps else 0

    if opcf_to_np >= 1.2:
        score += 4
        sigs.append("✅ 经营现金流充沛")
    elif opcf_to_np >= 0.8:
        score += 3
    elif opcf_to_np >= 0.5:
        score += 1.5
    elif opcf_to_np >= 0:
        score += 0.5
    else:
        score -= 2
        sigs.append("🔴 经营现金流为负")

    final = max(0, min(40, int(round(score))))
    return final, sigs

# ============================================================
#  舞弊检测 (-30~0分)
# ============================================================

def detect_fraud(data, industry_benchmark=None):
    """舞弊信号检测

    参考: cn-financial-deep-analysis/references/core/fraud-detection.md

    70+ 预警信号，返回综合扣分和触发信号列表。

    Args:
        data: fetch_financial_data 返回的 dict
        industry_benchmark: 行业基准数据（可选）

    Returns:
        (penalty, signals, is_fatal): 
            penalty: int -30~0, 扣分数
            signals: list[str], 触发信号
            is_fatal: bool, 是否一票否决
    """
    if not data or data.get("error"):
        return 0, [], False

    ind = data.get("indicators", {})
    fd = data.get("fraud", {})
    signals = []
    penalty = 0
    fatal = False

    # ─── 一级: 盈利能力预警 (6项) ───
    # 安全取值
    def _fv(key, default=0.0):
        v = ind.get(key)
        return v if v is not None else default
    def _ff(key, default=0.0):
        v = fd.get(key)
        return v if v is not None else default

    # 1. 扣非净利润<0
    dp = _fv("deducted_profit")
    if dp < 0:
        penalty -= 5
        signals.append("🔴 扣非净利润亏损(%.0f亿)" % (dp / 1e8))

    # 2. 净利率<3%
    nm = _fv("net_margin")
    if 0 < nm < 0.03:
        penalty -= 3
        signals.append(f"⚠️ 净利率<3%（{nm*100:.2f}%）")

    # 3. ROE<6%
    roe = _fv("roe")
    if 0 < roe < 0.06:
        penalty -= 2
        signals.append(f"⚠️ ROE<6%（{roe*100:.1f}%）")

    # 4. 毛利率异常偏离（依赖行业基准）
    if industry_benchmark:
        gm = _fv("gross_margin")
        ind_gm = industry_benchmark.get("gross_margin", 0) or 0
        if ind_gm > 0 and abs(gm - ind_gm) > 0.15:
            penalty -= 4
            signals.append("⚠️ 毛利率偏离行业%.1f%%" % (abs(gm - ind_gm) * 100))

    # 5. 非经常性损益占比>20%
    non_rec = _ff("non_recurring_ratio")
    if non_rec > 0.20:
        penalty -= 4
        signals.append("⚠️ 非经常性损益占比%.0f%%" % (non_rec * 100))

    # ─── 二级: 现金流预警 (5项) ───
    # 7. 经营现金流/净利润<0.5
    opcf_to_np = _ff("opcf_to_profit")
    if 0 < opcf_to_np < 0.5:
        penalty -= 4
        signals.append("⚠️ 经营现金流/利润<0.5(%.2f)" % opcf_to_np)
    elif opcf_to_np <= 0:
        penalty -= 6
        signals.append("🔴 经营现金流/利润<=0(%.2f)" % opcf_to_np)

    # 9. 销售现金率<70%（简化: 用经营现金流/营收代替）
    opcf_to_rev = _fv("op_cf_to_revenue", None)
    if opcf_to_rev is not None and 0 < opcf_to_rev < 0.7:
        penalty -= 3
        signals.append("⚠️ 销售现金率<70%")

    # ─── 三级: 偿债能力预警 (5项) ───
    # 12. 资产负债率>80%
    dr = _fv("debt_ratio")
    if dr > 0.80:
        penalty -= 4
        signals.append(f"🔴 资产负债率>80%（{dr*100:.1f}%）")

    # 13. 流动比率<1
    cr = _fv("current_ratio")
    if 0 < cr < 1.0:
        penalty -= 3
        signals.append("⚠️ 流动比率<1(%.2f)" % cr)

    # ─── 四级: 舞弊特征预警 (核心16项) ───
    # 17. 应收账款增长率 > 营收增长率×1.5
    ar_g = _ff("ar_growth")
    rev_g = _ff("revenue_growth_rate")
    if rev_g > 0 and ar_g > rev_g * 1.5:
        penalty -= 5
        signals.append("🔴 应收增长(%.0f%%)>营收(%.0f%%)×1.5" % (ar_g * 100, rev_g * 100))
    elif rev_g <= 0 and ar_g > 0.2:
        penalty -= 3
        signals.append("⚠️ 营收下滑但应收增(%.0f%%)" % (ar_g * 100))

    # 19. 存货增长率 > 营收增长率×1.3
    inv_g = _ff("inv_growth")
    if rev_g > 0 and inv_g > rev_g * 1.3:
        penalty -= 3
        signals.append("⚠️ 存货增长(%.0f%%)>营收(%.0f%%)×1.3" % (inv_g * 100, rev_g * 100))

    # 20. 毛利率剧烈波动 > 10%
    gm_chg = _ff("gross_margin_change")
    if abs(gm_chg) > 0.10:
        penalty -= 3
        signals.append("⚠️ 毛利率波动%.1f%%" % (abs(gm_chg) * 100))

    # 23. 应收账款周转率连续下降（简化：周转天数>180天）
    ar_days = _fv("ar_turnover_days")
    if ar_days > 180:
        penalty -= 2
        signals.append("⚠️ 应收周转>180天(%d天)" % ar_days)

    # 27. 存货周转天数 > 行业均值×1.5（简化：>365天）
    inv_days = _fv("inv_turnover_days")
    if inv_days > 365:
        penalty -= 2
        signals.append("⚠️ 存货周转>365天(%d天)" % inv_days)

    # 30. 大存大贷
    if _ff("debt_high_with_cash", False):
        penalty -= 3
        signals.append("⚠️ 高负债率高现金并存")

    # ─── 五级: 财务勾稽校验 (参考 ashare-mcp) ───
    # 勾稽关系是财务造假的"硬伤"：报表内部自相矛盾 → 强烈预警
    # 注: stock_financial_abstract_ths 无总资产/负债绝对额, 用每股指标推导
    # 31. 净资产勾稽: 每股净资产 ≈ 净资产/股本 (用 ROE 与 EPS 交叉验证)
    #     ROE = EPS/每股净资产 → 若 ROE 与 EPS、每股净资产不匹配 → 数据矛盾
    roe_x = _fv("roe", None)
    bvps = _fv("bvps", None)  # 每股净资产
    eps_x = _fv("basic_eps", None)
    if roe_x and bvps and eps_x and bvps > 0:
        implied_roe = eps_x / bvps
        if roe_x > 0 and abs(implied_roe - roe_x) / max(roe_x, 1e-9) > 0.35:
            penalty -= 4
            signals.append("⚠️ ROE勾稽不符(报表%.1f%% vs EPS/BVPS %.1f%%)" % (roe_x * 100, implied_roe * 100))

    # 32. 净利率勾稽: 净利率 ≈ 净利润/营收 (偏差>30% 提示数据矛盾)
    nm2 = _fv("net_margin", None)
    np2 = _fv("net_profit", None)
    rev2 = _fv("revenue", None)
    if nm2 and np2 and rev2 and rev2 > 0:
        implied = np2 / rev2
        if abs(implied - nm2) / max(abs(nm2), 1e-9) > 0.30:
            penalty -= 4
            signals.append("⚠️ 净利率勾稽不符(报表%.2f%% vs 计算%.2f%%)" % (nm2 * 100, implied * 100))

    # 33. 负债率与产权比率一致性: 资产负债率 = 负债/(负债+权益)
    #     产权比率 = 负债/权益 → 资产负债率 = 产权比率/(1+产权比率)
    dr2 = _fv("debt_ratio", None)
    er = _fv("equity_ratio", None)  # 产权比率
    if dr2 and er and er > 0:
        implied_dr = er / (1 + er)
        if abs(implied_dr - dr2) > 0.12:
            penalty -= 4
            signals.append("⚠️ 负债率勾稽不符(报表%.1f%% vs 产权比率推导%.1f%%)" % (dr2 * 100, implied_dr * 100))

    # 34. 利润增速 vs 现金流增速背离 (盈利无现金支撑)
    np_yoy = _fv("net_profit_yoy", None)
    cf_ps = _fv("cashflow_per_share", 0) or 0
    eps = _fv("basic_eps", 0) or 0
    if np_yoy and np_yoy > 0.5 and eps > 0 and cf_ps < eps * 0.3:
        penalty -= 3
        signals.append("⚠️ 利润增%.0f%%但每股现金流<EPS×0.3" % (np_yoy * 100))

    # 35. 利润大跌 (v8.1新增: 利润同比跌>10% 直接致命信号)
    # 修复: "利润大跌"信号此前只在health_signals, detect_fraud自己的signals匹配不到fatal_signals
    if np_yoy is not None and np_yoy < -0.10:
        penalty -= 5
        signals.append("🔴 利润大跌(%.0f%%)" % (np_yoy * 100))

    # ─── 扣分惩罚上限 ───
    penalty = max(-30, penalty)

    # ─── 一票否决判定 (v8.1: 单个致命信号即否决, 此前需≥2个) ───
    # v8.1 收紧: 应收/存货异常、毛利率剧烈波动、利润大跌 直接剔除
    fatal_signals = [
        "扣非净利润亏损",
        "资产负债率>80%",
        "经营现金流/利润<=0",
        "经营现金流/利润<0.5",   # v8.1新增: 现金流持续弱
        "应收增长",              # v8.1新增: 应收增长>营收×1.5 (利润注水特征)
        "存货增长",              # v8.1新增: 存货增长>营收×1.3 (库存积压特征)
        "毛利率波动",            # v8.1新增: 毛利率单季波动>10%
        "利润大跌",              # v8.1新增: 利润大幅下滑
    ]
    triggered_fatal = [s for fs in fatal_signals for s in signals if fs in s]
    if penalty <= -20 or len(triggered_fatal) >= 1:   # v8.1: 单个致命信号即否决
        fatal = True

    return penalty, signals, fatal

# ============================================================
#  行业对标
# ============================================================

# 申万行业代码映射（简化版）
INDUSTRY_CODES = {
    "白酒": "SW410000",
    "银行": "SW480000",
    "证券": "SW490000",
    "保险": "SW500000",
    "房地产": "SW430000",
    "半导体": "SW720000",
    "医药": "SW370000",
    "消费电子": "SW330000",
    "汽车": "SW280000",
    "新能源": "SW630000",
}

def get_industry_benchmark(code, industry=None):
    """获取行业基准数据

    占位 (2026-08-13 任务3评估): 本文件主链路(score_financial_health/detect_fraud/
    fetch_financial_data)均已完整实现, 唯一占位是行业对标本函数 → 当前返回 None。
    全系统唯一调用点 detect_fraud L832 仅在 industry_benchmark 非空时才启用
    "毛利率偏离行业"信号, 且实际调用方从不传该参数 → 保留占位不影响任何行为。
    补建建议: 需维护申万成分→日级财务均值缓存, 属独立增量功能, 建议等
    cn-financial-deep-analysis 接入时一并实现, 不值得现在单独补。

    Returns:
        dict: {gross_margin, net_margin, roe, debt_ratio, ...} | None
    """
    # 简化版：当前不做跨行业全量扫描（太慢）
    # 后续可以通过缓存行业成分股的财务数据实现
    return None

# ============================================================
#  统一评分入口
# ============================================================

def score_stock_financial(code, force_refresh=False):
    """统一财务评分入口

    对单只股票执行完整的财务健康评分+舞弊检测。

    Args:
        code: 6位A股代码
        force_refresh: 强制刷新数据

    Returns:
        dict: {
            "financial_health": int (0~40),
            "fraud_penalty": int (-30~0),
            "fraud_fatal": bool,
            "health_signals": [str],
            "fraud_signals": [str],
            "total_bonus": int (-30~40),
            "data_status": str,
        }
    """
    data = get_or_fetch(code, force_refresh=force_refresh)
    if data.get("error"):
        # P1-13: 缺数据=未知风险 → 显著降权(-20)而非0分, 不否决(fatal=False)
        logger.warning(f"P1-13: {code} 财务数据缺失, error={data['error']}")
        return {
            "financial_health": -20,
            "fraud_penalty": 0,
            "fraud_fatal": False,
            "health_signals": ["🔴 财务数据缺失-降权(%s)" % data["error"]],
            "fraud_signals": [],
            "total_bonus": -10,
            "data_status": "missing",
        }

    # P1-13: 隐蔽缺数据路径 — 无 error 但 indicators 为空(解析失败静默通过)同样降权
    _ind_check = data.get("indicators") if isinstance(data, dict) else None
    if not isinstance(_ind_check, dict) or not _ind_check:
        logger.warning(f"P1-13: {code} 财务数据为空(indicators缺失), 降权处理")
        return {
            "financial_health": -20,
            "fraud_penalty": 0,
            "fraud_fatal": False,
            "health_signals": ["🔴 财务数据缺失-降权(indicators为空)"],
            "fraud_signals": [],
            "total_bonus": -10,
            "data_status": "missing",
        }

    try:
        health_score, health_sigs = score_financial_health(data)
        fraud_penalty, fraud_sigs, fraud_fatal = detect_fraud(data)
    except Exception as e:
        logger.error(f"P1-13: {code} 财务评分异常, error={e}")
        return {
            "financial_health": -20,
            "fraud_penalty": 0,
            "fraud_fatal": False,
            "health_signals": [f"🔴 财务评分异常-降权({e})"],
            "fraud_signals": [],
            "total_bonus": -10,
            "data_status": "missing",
        }

    # 净加分 = 健康分 - 舞弊扣分（调整至 -10~+20 范围）
    raw_bonus = health_score + fraud_penalty
    total_bonus = max(-10, min(20, raw_bonus))

    return {
        "financial_health": health_score,
        "fraud_penalty": fraud_penalty,
        "fraud_fatal": fraud_fatal,
        "health_signals": health_sigs,
        "fraud_signals": fraud_sigs,
        "total_bonus": total_bonus,
        "data_status": "ok",
    }

def batch_score_financial(codes, force_refresh=False):
    """批量评分

    Args:
        codes: [code, ...] 股票代码列表
        force_refresh: 强制刷新

    Returns:
        dict: {code: score_result_dict, ...}
    """
    batch_data = batch_fetch(codes, force_refresh=force_refresh)
    results = {}
    for code_key, data in batch_data.items():
        results[code_key] = score_stock_financial(code_key, force_refresh=False)
    return results

# ============================================================
#  自测
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("=" * 50)
    print("  🔧 financial_filter 自测")
    print("=" * 50)

    test_codes = [
        ("600519", "贵州茅台(优质)"),
        ("002415", "海康威视(优质)"),
        ("000002", "万科A(困境)"),
    ]

    for code, desc in test_codes:
        print(f"\n📊 {code} {desc}")
        print("-" * 50)
        result = score_stock_financial(code, force_refresh=True)

        print(f"  财务健康: {result['financial_health']}/40")
        if result["health_signals"]:
            for s in result["health_signals"][:5]:
                print(f"    {s}")

        print(f"  舞弊扣分: {result['fraud_penalty']}")
        print(f"  致命风险: {'⚠️一票否决!' if result['fraud_fatal'] else '✅ 无'}")
        if result["fraud_signals"]:
            for s in result["fraud_signals"]:
                print(f"    {s}")

        print(f"  净加分: {result['total_bonus']:+d}")
