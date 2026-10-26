"""TDX 评分引擎模块 — Phase C-1 拆分自 tdx_core.py (2026-08-31)

职责:
- score_stock — 多策略评分核心
- 板块热度 / 主力资金流 / 相对强弱 / 基本面奖金 (get_industry_heat /
  get_fund_flow_bonus_for_stocks / calc_relative_strength /
  get_fundamental_bonus_for_stocks)
- 截面排名与 z-score (compute_cross_section_ranks / zscores)
- 特征重要性 (calc_feature_contributions)
- 止盈止损 (calc_trailing_stop / format_stop_advice / compute_swing_analysis)
- 市场状态分析 (analyze_market / _get_position_limit / _get_stop_loss_pct /
  _get_target_pct)
- 数据辅助 (has_recent_gap)

兼容性: tdx_core.py 仍作为兼容入口 re-export 本模块所有符号。
"""

import os
import sys
import math  # P0修复(2026-09-21): 补充缺失的math导入
import struct
import urllib.request
import json
import sys
from datetime import date

import core.pipeline.atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Phase C-1: score_stock / calc_feature_contributions 默认回落到 STRATEGIES["综合"],
# STRATEGIES 现在住在 tdx_strategies 模块, 显式导入避免隐式依赖丢失。
from tdx_strategies import STRATEGIES, STRATEGY_DEFAULT  # noqa: F401

# 导入技术指标函数
from tdx_indicators import calc_atr_stop, calc_atr, calc_ema_list, calc_sma, calc_rsi, calc_macd, aggregate_weekly, analyze_volume_pattern, compute_weekly_indicators  # noqa: F401

_INDUSTRY_HEAT_CACHE = None
_INDUSTRY_HEAT_DATE = None
_INDUSTRY_HEAT_FILE = None  # 会在首次调用时设置


def has_recent_gap(records, days=30, threshold=15.0):
    """H2修复: 检测最近days日内有无>threshold%跳空(除权特征)
    实盘防护: 未复权TDX数据在除权日产生假跳空, 污染断层/指标。
    刚除权的股票排除(或降权), 避免把除权当缺口。records为日线列表。
    返回 (has_gap: bool, gap_date: str|None, gap_pct: float)
    """
    if not records or len(records) < 3:
        return False, None, 0.0
    recent = records[-days:]
    for i in range(1, len(recent)):
        c0 = recent[i - 1].get("close", 0) or 0
        c1 = recent[i].get("close", 0) or 0
        if c0 > 0:
            pct = abs((c1 - c0) / c0 * 100)
            if pct > threshold:
                return True, str(recent[i].get("date", "")), round(pct, 1)
    return False, None, 0.0


def get_industry_heat(force_refresh=False):
    """
    获取东财行业板块涨跌幅排名热度。
    返回: {industry_name: rank_percentile(0~1)}
          rank_percentile 1.0=涨幅第1名, 0.0=垫底
    行业名会做映射: '白酒'→inds['industry'] 已有值
    """
    global _INDUSTRY_HEAT_CACHE, _INDUSTRY_HEAT_DATE, _INDUSTRY_HEAT_FILE
    from datetime import date
    today = str(date.today())
    if _INDUSTRY_HEAT_FILE is None:
        _INDUSTRY_HEAT_FILE = os.path.join(os.path.dirname(__file__), "data", "industry_heat.json")
        os.makedirs(os.path.dirname(_INDUSTRY_HEAT_FILE), exist_ok=True)

    # 尝试从文件缓存加载（跨进程持久化）
    if not force_refresh and _INDUSTRY_HEAT_CACHE is None:
        try:
            with open(_INDUSTRY_HEAT_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
                if cached.get("date") == today:
                    _INDUSTRY_HEAT_CACHE = cached.get("data", {})
                    _INDUSTRY_HEAT_DATE = today
                    return _INDUSTRY_HEAT_CACHE
        except (FileNotFoundError, IOError, KeyError, json.JSONDecodeError) as e:
            pass

    if not force_refresh and _INDUSTRY_HEAT_CACHE and _INDUSTRY_HEAT_DATE == today:
        return _INDUSTRY_HEAT_CACHE

    result = {}
    try:
        import urllib.request, json
        # 东财 WAF 会屏蔽 push2.eastmoney.com (2026-08 实测 RemoteDisconnected)
        # 降级链: push2delay → 82.push2 → push2 (push2delay 实测可用)
        hosts = [
            "push2delay.eastmoney.com",
            "82.push2.eastmoney.com",
            "push2.eastmoney.com",
        ]
        params = (
            "pn=1&pz=120&po=1&np=1&fltt=2&invt=2"
            "&fs=m:90+t:2"
            "&fields=f2,f3,f4,f12,f14,f104,f105"
        )
        items = []
        last_err = None
        for host in hosts:
            url = f"https://{host}/api/qt/clist/get"
            try:
                req = urllib.request.Request(f"{url}?{params}",
                    headers={"User-Agent": "Mozilla/5.0"})
                r = urllib.request.urlopen(req, timeout=10)
                d = json.loads(r.read())
                items = d.get("data", {}).get("diff", [])
                if items:
                    break
            except Exception as e:
                last_err = e
                continue
        total = len(items)

        # 行业名映射: 我们的粗分类名 → 东财行业名中的关键词
        INDUSTRY_KEYWORD_MAP = {
            "金融":   ["银行", "保险", "证券", "多元金融"],
            "白酒":   ["白酒", "饮料"],
            "食品":   ["食品", "饮料", "调味", "乳品"],
            "建材":   ["建材", "水泥", "玻璃"],
            "汽车":   ["汽车", "汽配", "摩托车"],
            "机械":   ["机械", "专用设备", "通用设备"],
            "家电":   ["家电", "白色家电", "黑色家电"],
            "医药":   ["医药", "医疗", "生物", "化学制药"],
            "软件":   ["软件", "IT", "计算机", "互联网", "信息技术"],
            "科技":   ["半导体", "电子", "通信", "元器件", "消费电子",
                      "芯片", "计算机设备", "IT服务"],
            "房地产": ["房地产", "房产"],
            "煤炭":   ["煤炭"],
            "有色":   ["有色", "金属", "黄金"],
            "化工":   ["化工", "化学", "塑料", "橡胶"],
            "电力":   ["电力", "电气", "新能源"],
            "军工":   ["军工", "航天", "船舶"],
            "农业":   ["农业", "牧渔", "种业", "林业"],
            "传媒":   ["传媒", "广告", "影视", "游戏"],
            "纺织":   ["纺织", "服装"],
            "商贸":   ["商贸", "零售", "贸易"],
        }

        # 东财返回按板块代码(BK0xxx)升序, 必须按涨跌幅降序重排 rank
        # 修复(2026-08-01): 之前按返回顺序赋rank导致热点识别颠倒
        items_sorted = sorted(
            [it for it in items if it.get("f14") and it.get("f3") is not None],
            key=lambda x: float(x.get("f3", 0)), reverse=True
        )
        for i, item in enumerate(items_sorted):
            name = item.get("f14", "")
            change_pct = item.get("f3", 0)
            if name and change_pct is not None:
                pct = 1.0 - (i / total) if total > 0 else 0.5
                result[name] = {"rank": i+1, "total": total,
                                "percentile": round(pct, 3),
                                "change_pct": change_pct}

        # 同时生成缩写版查询: 宽泛行业名 → 最佳匹配的东财行业
        alias_map = {}
        for broad, keywords in INDUSTRY_KEYWORD_MAP.items():
            best = None
            for em_name in result:
                for kw in keywords:
                    if kw in em_name:
                        best = result[em_name]  # 取第一个匹配的
                        break
                if best:
                    break
            if best:
                alias_map[broad] = best
        if alias_map:
            result["__alias__"] = alias_map
        result["ok"] = True  # 修复M2: 标记真实数据成功
    except Exception as e:
        # 网络失败 → 降级为内置默认数据（中性估值）— 不写入文件缓存
        result = {}
        INDUSTRY_KEYWORD_MAP = {
            "金融": ["银行","保险","证券","多元金融"], "白酒": ["白酒","饮料"],
            "食品": ["食品","饮料","调味"], "建材": ["建材","水泥","玻璃"],
            "汽车": ["汽车","汽配"], "机械": ["机械","专用设备"],
            "家电": ["家电","白色家电"], "医药": ["医药","医疗","生物制药"],
            "软件": ["软件","IT","计算机"], "科技": ["半导体","电子","通信","芯片"],
            "房地产": ["房地产"], "煤炭": ["煤炭"], "有色": ["有色","金属","黄金"],
            "化工": ["化工","化学","塑料"], "电力": ["电力","电气","新能源"],
            "军工": ["军工","航天"], "农业": ["农业","牧渔"], "传媒": ["传媒","广告"],
            "纺织": ["纺织","服装"], "商贸": ["商贸","零售"],
        }
        # 所有行业默认中性热度 0.5
        alias_map = {}
        for broad, keywords in INDUSTRY_KEYWORD_MAP.items():
            alias_map[broad] = {"rank": 60, "total": 120, "percentile": 0.5, "change_pct": 0}
        result["__alias__"] = alias_map

    _INDUSTRY_HEAT_CACHE = result
    _INDUSTRY_HEAT_DATE = today
    # 持久化到文件缓存 — 仅当成功获取真实数据时写入 (修复M2: 降级中性数据不污染缓存)
    if result and _INDUSTRY_HEAT_FILE and "ok" in result:
        try:
            atomic_json.atomic_dump({"date": today, "data": result}, _INDUSTRY_HEAT_FILE, ensure_ascii=False, encoding="utf-8")
        except (FileNotFoundError, IOError, json.JSONDecodeError) as e:
            pass
    return result


def get_fund_flow_bonus_for_stocks(codes):
    """
    批量获取候选股主力资金流向信号。
    只请求东财push2his(120日资金流)，对每只股票做1s限流。
    codes: [(code, industry_name), ...] 最多50只
    返回: {code: {bonus: int(-5~5), signal: str, main_net_5d, main_net_20d}}
    """
    result = {}
    import time, random, urllib.request, json

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
    EM_MIN_INTERVAL = 0.5  # 批次内每只间隔0.5s
    _last_call = [0.0]

    def _em_get(url, params_str, timeout=10):
        wait = EM_MIN_INTERVAL - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.05, 0.2))
        req = urllib.request.Request(f"{url}?{params_str}",
            headers={"User-Agent": UA,
                     "Referer": "https://quote.eastmoney.com/",
                     "Origin": "https://quote.eastmoney.com"})
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            _last_call[0] = time.time()
            return json.loads(resp.read())
        except Exception:
            _last_call[0] = time.time()
            return None

    for code, _ in codes[:50]:  # 最多处理50只
        mkt = 1 if code.startswith("6") else 0
        params = (
            f"secid={mkt}.{code}"
            f"&fields1=f1,f2,f3,f7"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
            f"&lmt=120"
        )
        d = _em_get("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get", params)
        if not d or not d.get("data"):
            continue
        klines = d["data"].get("klines", [])
        if not klines:
            continue

        flows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 7:
                flows.append({
                    "date": parts[0],
                    "main_net": float(parts[1]) if parts[1] != "-" else 0,
                })

        if len(flows) < 5:
            continue

        # 计算近5日、近20日主力净流入
        recent_5 = sum(f["main_net"] for f in flows[-5:])
        recent_20 = sum(f["main_net"] for f in flows[-20:])

        # 判断趋势方向
        bonus = 0
        signal = ""
        if recent_5 > 0 and recent_20 > 0:
            bonus = 5
            signal = "🔥 主力持续净流入"
        elif recent_5 > 0 and recent_20 < 0:
            bonus = 2
            signal = "📈 近5日主力转流入"
        elif recent_5 < 0 and recent_20 < 0:
            bonus = -5
            signal = "⚠️ 主力持续净流出"
        elif recent_5 < 0 and recent_20 > 0:
            bonus = -2
            signal = "📉 近5日主力转流出"
        else:
            bonus = 0
            signal = "➖ 资金流中性"

        # 进一步细分幅度
        if recent_5 > 1e8:       # 5日净流入>1亿 → 强信号
            bonus = min(bonus + 2, 7)
            signal += " (大幅)"
        elif recent_5 < -1e8:
            bonus = max(bonus - 2, -7)
            signal += " (大幅)"

        result[code] = {
            "bonus": bonus,
            "signal": signal,
            "main_net_5d": round(recent_5 / 1e4, 0),   # 万元
            "main_net_20d": round(recent_20 / 1e4, 0),  # 万元
        }

    return result


def calc_relative_strength(inds, index_inds=None):
    """
    计算个股 vs 大盘的相对强弱比（超额收益）
    inds: 个股指标字典
    index_inds: 上证指数指标字典
    返回: (bonus: -3~+5, signal: str)
    """
    if not index_inds:
        return 0, ""
    stock_c5 = inds.get("chg5", 0) or 0
    stock_c10 = inds.get("chg10", 0) or 0
    stock_c20 = inds.get("chg20", 0) or 0
    idx_c5 = index_inds.get("chg5", 0) or 0
    idx_c10 = index_inds.get("chg10", 0) or 0
    idx_c20 = index_inds.get("chg20", 0) or 0
    x5 = stock_c5 - idx_c5
    x10 = stock_c10 - idx_c10
    x20 = stock_c20 - idx_c20
    wins = sum(1 for e in [x5, x10, x20] if e > 0)
    if wins == 3:
        if x5 > 5:
            return 5, f"🏆 持续跑赢(y{x5:.0f}/m{x10:.0f}/l{x20:.0f}%)"
        return 3, f"📈 跑赢大盘(超额{x5+x10+x20:.1f}%)"
    if wins == 2:
        if x5 + x10 + x20 > 8:
            return 3, f"📊 超额{x5+x10+x20:.0f}%"
        return 1, "↗️ 相对偏强"
    if wins <= 1:
        excess_sum = x5 + x10 + x20
        if excess_sum < -10:
            return -3, f"⬇️ 跑输大盘(超额{excess_sum:.1f}%)"
        return -1, "↘️ 相对偏弱"
    return 0, ""


def get_fundamental_bonus_for_stocks(codes_names, max_workers=5):
    """
    通过 MCP mx-ds-mcp 批量查询 Top N 候选股的北向资金/融资融券/股东户数
    codes_names: [(code, name), ...]
    返回: {code: {"bonus": int, "signal": str}}
    """
    if not codes_names:
        return {}
    result = {}
    import urllib.request, json, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    HEADERS = {
        "em_api_key": os.environ.get("EM_API_KEY", ""),
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
        "Accept": "application/json",
        "Origin": "https://www.eastmoney.com",
        "Referer": "https://www.eastmoney.com/",
    }
    for code, name in codes_names:
        try:
            cn = code[2:] if code[:2].isalpha() else code
            query = f"{name}({cn}) 的沪深股通持股占比和融资融券余额和股东户数变化 近20日"
            payload = json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "name": "mx_ashare_finance_data",
                    "arguments": {"query": query}
                }
            }).encode()
            req = urllib.request.Request(
                "https://mxapi.eastmoney.com/mxds/mcp",
                data=payload, headers=HEADERS, method="POST"
            )
            resp = urllib.request.urlopen(req, timeout=10, context=ctx)
            data = json.loads(resp.read().decode())
            content = data.get("result", {}).get("content", [])
            if not content:
                result[code] = {"bonus": 0, "signal": ""}
                continue
            # 解析资金面信号
            bonus = 0
            signals = []
            for sheet in content:
                items = sheet.get("items", [])
                name_col = sheet.get("sheetName", "")
                for row in items:
                    vals = row[1:] if len(row) > 1 else []
                    if not vals:
                        continue
                    if "持股占比" in name_col:
                        # 北向资金持股占比趋势
                        numeric = []
                        for v in vals:
                            try:
                                numeric.append(float(v.replace("%","")))
                            except (AttributeError) as e:
                                pass
                        if len(numeric) >= 3:
                            # 最近3期持续增加
                            trend = numeric[-1] - numeric[0]
                            if trend > 0.05:
                                bonus += 3
                                signals.append(f"北向增持{trend:.2f}%")
                            elif trend < -0.05:
                                bonus += -2
                                signals.append(f"北向减持{abs(trend):.2f}%")
                    elif "融资融券" in name_col:
                        # 融资余额趋势
                        numeric = []
                        for v in vals:
                            s = v.replace("亿","").replace("万","")
                            try:
                                numeric.append(float(s))
                            except (AttributeError) as e:
                                pass
                        if len(numeric) >= 3:
                            trend = numeric[-1] - numeric[0]
                            if trend > 0.5:
                                bonus += 2
                                signals.append(f"融资增加{trend:.1f}亿")
                            elif trend < -0.3:
                                bonus += -1
                                signals.append(f"融资减少{abs(trend):.1f}亿")
                    elif "股东户数" in name_col:
                        # 股东户数趋势（减少=筹码集中=利好）
                        numeric = []
                        for v in vals:
                            s = v.replace("万","").replace("户","")
                            try:
                                numeric.append(float(s))
                            except (AttributeError) as e:
                                pass
                        if len(numeric) >= 3:
                            trend = numeric[-1] - numeric[0]
                            if trend < -0.5:
                                bonus += 2
                                signals.append(f"户数减少{abs(trend):.1f}万→集中")
                            elif trend > 0.5:
                                bonus += -1
                                signals.append(f"户数增加{trend:.1f}万→分散")
            signal_str = " | ".join(signals) if signals else ""
            result[code] = {"bonus": bonus, "signal": signal_str}
        except Exception as e:
            result[code] = {"bonus": 0, "signal": f"MCP查询失败"}
    return result


def score_stock(inds, weekly=None, strategy=None, records=None, news_bonus=0, news_sigs=None,
                industry_heat=0, fund_flow_bonus=0, fund_flow_signal="",
                market_state=None, rs_bonus=0, rs_signal="",
                fundamental_bonus=0, fundamental_signal="",
                cross_rank=None, zscore=None, score_stats=None):
    """评分函数 v8.1 — 策略权重驱动 + z-score截面标准化

    调用场景:
    - 每日选股 (integrated_picker.py 主链路)
    - 回测验证 (backtest.py 扫描日评分)
    - 持仓复盘 (portfolio_review.py 诊断)

    参数说明:
    - inds: 技术指标 dict (chg5/chg20/vol_ratio/rsi14/ma_dist 等), 由 compute_indicators() 生成
    - weekly: 周线指标 (可选, 趋势策略用)
    - strategy: 策略权重 dict, None 时用 STRATEGIES["综合"]
    - cross_rank: 截面百分位 dict {因子名: 0~1}, 传了则用连续评分替代布尔分档
    - zscore: 截面z-score dict {因子名: float}, P2重构优先使用, 比百分位区分度更高
    - score_stats: 截面标准化统计 {score_mean, score_std}, P0修复: 使L1447分支生效
    - market_state: 市场状态 "牛"/"熊"/"震荡", 影响反转倾斜逻辑

    核心逻辑(v8.1):
    - zscore 优先: 用z-score替代百分位做连续评分, 保留分布信息
    - 反转倾斜: 超跌给分/追高超买重罚 (A股5-20日均值回归实证)
    - 向后兼容: 不传 zscore/cross_rank 时保持 v7 布尔逻辑

    返回:
        (score: float, signals: list[str]) — 评分 + 触发信号列表
    """
    if not inds:
        return 0, [], None  # P0-2026-09-25: 对齐3元组契约 (原2元组会让调用方 sc,_,_ 解包崩溃)

    # P0-2026-09-25: 回测快速路径(fast_compute_all)的 inds 是 numba typed dict,
    # .get(k, {}) 这类 dict 默认值会触发 numba TypingError → 评分异常 → 回测侧静默 sc=0 全零分
    # (2026-09-19 引入快速路径以来回测评分恒为0, 候选退化为字典序第一)。统一归一化为 plain dict。
    if type(inds) is not dict:
        try:
            inds = dict(inds)
        except Exception:
            pass
    if weekly is not None and type(weekly) is not dict:
        try:
            weekly = dict(weekly)
        except Exception:
            pass

    # P1-8清理(2026-08-08): 删除bonuses参数及弱/强市打折分支 — 生产无调用方(死代码)
    # 原逻辑: 弱/强市bonuses打折×0.3 + bonuses字典应用(news/北向/板块/财务/dl加分)
    # 但integrated_picker/backtest均不传bonuses → 从未生效

    # P2评分重构(2026-08-24): z-score优先于cross_rank
    use_zscore = zscore is not None
    use_cross_rank = cross_rank is not None and not use_zscore

    s = strategy or STRATEGIES["综合"]
    sigs = []
    score = 0.0

    if market_state:
        if market_state in ("牛市", "极强", "强势"):
            market_state = "牛"
        elif market_state in ("偏暖", "强势上涨"):
            market_state = "强"
        elif market_state in ("偏弱", "弱势", "极弱"):
            market_state = "弱"
        elif market_state in ("中性", "平衡"):
            market_state = "震荡"

    momentum_mode = market_state in ("牛", "强")    # 牛/强市用动量(文档: 反转无alpha)
    chase_penalty = 0.2 if momentum_mode else 1.0   # 追高惩罚缩放(牛/强市不罚)
    reversal_bonus = 0.0 if momentum_mode else 1.0  # 超跌反转奖励缩放(牛/强市关闭反转)
    weak_mode = market_state == "弱"                # 仅弱市用反转(实证+1.49%有效)

    # P0-2026-09-17: 禁用抄底策略（IC=-0.03持续负向，拖累整体区分度）
    # 历史：弱市抄底权重rsi_weak=18过高，导致评分失真
    # 修复：始终使用综合策略，不切换
    # if weak_mode and "抄底" in STRATEGIES:
    #     strategy = STRATEGIES["抄底"]
    #     s = strategy  # 同步 s (1021行已绑定原strategy)

    # ================================================================
    # 因子评分 — 从 strategy 权重读取，支持4策略差异化
    # ================================================================

    # ─── 1. 均线系统 ───
    # P0修复: 使用.get()防御性访问，避免KeyError
    # 兼容list类型测试数据: 取最后一个值
    ma5 = inds.get("ma5")
    ma10 = inds.get("ma10")
    ma20 = inds.get("ma20")
    ma60 = inds.get("ma60")
    ma120 = inds.get("ma120")
    price = inds.get("price")
    
    # 类型转换: list → 取最后一个值
    if isinstance(ma5, list): ma5 = ma5[-1]
    if isinstance(ma10, list): ma10 = ma10[-1]
    if isinstance(ma20, list): ma20 = ma20[-1]
    if isinstance(price, list): price = price[-1]
    
    is_ma_bull = (ma5 and ma10 and ma20
                  and ma5 > ma10 > ma20 > 0)
    ma_score = 0
    if is_ma_bull:
        ma_score += s.get("ma_mlt", 15); sigs.append("✅ 均线多头排列")
    elif ma5 and ma10 and ma5 > ma10:
        ma_score += s.get("ma_mlt", 15) // 2; sigs.append("📈 MA5>MA10")
    if ma60 and price and price > ma60:
        ma_score += s.get("ma_above60", 5)
    if ma120 and price and price > ma120:
        ma_score += s.get("ma_above120", 3)
    score += ma_score

    # ─── 2. MACD ───
    # P0修复: 使用.get()防御性访问
    d, e, mh = inds.get("dif"), inds.get("dea"), inds.get("macd_hist")
    if d is not None and e is not None and mh is not None:
        if d > e and mh > 0:
            score += s.get("macd_golden_red", 12); sigs.append("✅ MACD金叉+红柱")
        elif d > e:
            score += s.get("macd_golden", 7); sigs.append("📈 MACD金叉")
        if d > 0:
            score += s.get("macd_above0", 4)

    # ─── 3. RSI (v8.1: z-score截面标准化 + 反转倾斜) ───
    # P1-6(2026-08-08): rsi_weak等RSI加分累计到rsi_adj, 段末封顶±15
    # P0修复: 使用.get()防御性访问
    rsi14 = inds.get("rsi14")
    rsi_adj = 0.0
    rsi_sigs = []
    if rsi14:
        if use_zscore and zscore and zscore.get("rsi14") is not None:
            # z-score连续评分: 标准化后正值=偏强/超买, 负值=偏弱/超卖
            rz = zscore["rsi14"]  # z-score, 均值0 std=1
            if rz >= 1.0:
                # 超买重罚 (z>=1即超过均值1个标准差) - P1微调：增强极端值
                rsi_adj += s.get("kdj_overbought", -5) * 1.5 * chase_penalty * 1.2
                rsi_sigs.append(f"⚠️ RSI={rsi14:.0f} 超买(z={rz:.2f})")
            elif rz >= 0.5:
                # 偏强 - P1微调：牛强市额外加分×1.2
                extra_bonus = 1.2 if market_state in ("牛", "强") else 1.0
                rsi_adj += s.get("rsi_strong", 8) * 0.6 * extra_bonus
                rsi_sigs.append(f"📈 RSI={rsi14:.0f} 偏强(z={rz:.2f})")
            elif rz <= -1.0:
                # 超卖反转加分 — 牛市关闭(超卖=弱势), 弱市强化×1.6
                rsi_adj += s.get("rsi_weak", 5) * (1.6 if weak_mode else 1.2) * reversal_bonus
                rsi_sigs.append(f"{'🔄' if not momentum_mode else '📉'} RSI={rsi14:.0f} {'超卖反转' if not momentum_mode else '超卖弱势'}(z={rz:.2f})")
            elif rz <= -0.5:
                # 偏弱 - P1微调：震荡市均值回归加分
                mean_reversion = 0.8 if market_state == "震荡" else 1.0
                rsi_adj += s.get("rsi_weak", 5) * 0.5 * reversal_bonus * mean_reversion
                rsi_sigs.append(f"📉 RSI={rsi14:.0f} 偏弱(z={rz:.2f})")
            else:
                # 中性 - P1微调：震荡市加分×0.8
                neutral_bonus = 0.8 if market_state == "震荡" else 1.0
                rsi_adj += s.get("rsi_strong", 8) * 0.4 * neutral_bonus
                rsi_sigs.append(f"➡️ RSI={rsi14:.0f} 中性(z={rz:.2f})")
            if inds.get("rsi6") and inds["rsi6"] > rsi14:
                rsi_adj += s.get("rsi_rising", 4)
                rsi_sigs.append("📈 RSI上行")
        elif use_cross_rank and cross_rank and cross_rank.get("rsi14") is not None:
            # 百分位连续评分: 40-70强势区加分, >80超买重罚, <30超卖反转加分
            rp = cross_rank["rsi14"]  # 0~1, 越大越超买
            if 45 <= rsi14 <= 75:
                # 动量模式: RSI 60-75 强者恒强给更多分(牛市动量倾斜)
                w = s.get("rsi_strong", 8) * (0.6 + 0.4 * rp)
                if momentum_mode and rsi14 >= 60:
                    w *= 1.25  # P1微调：牛强市动量倾斜
                rsi_adj += w
                rsi_sigs.append(f"✅ RSI={rsi14:.0f} 强势区间(百分位{rp:.0%})")
            elif rsi14 > 80:
                rsi_adj += s.get("kdj_overbought", -5) * 1.5 * chase_penalty
                rsi_sigs.append(f"⚠️ RSI={rsi14:.0f} 严重超买")
            elif rsi14 > 75:
                # 2026-08-05 实证: 牛市过热RSI>75 5日-0.34%(跑输60-75的+0.82%) — 过热独立重罚
                rsi_adj += s.get("kdj_overbought", -5) * (2.0 if momentum_mode else 1.0)
                rsi_sigs.append(f"⚠️ RSI={rsi14:.0f} 超买")
            elif rsi14 < 30:
                # 反转倾斜: 超卖给分 (A股均值回归) — 牛市关闭(超卖=弱势), 弱市强化×1.6
                rsi_adj += s.get("rsi_weak", 5) * (1.6 if weak_mode else 1.2) * reversal_bonus
                rsi_sigs.append(f"{'🔄' if not momentum_mode else '📉'} RSI={rsi14:.0f} {'超卖反转' if not momentum_mode else '超卖弱势'}")
            elif rsi14 < 45:
                # P1微调：震荡市均值回归加分
                mean_reversion = 0.8 if market_state == "震荡" else 1.0
                rsi_adj += s.get("rsi_weak", 5) * 0.5 * reversal_bonus * mean_reversion
                rsi_sigs.append(f"📉 RSI={rsi14:.0f} 偏弱")
            if inds.get("rsi6") and inds["rsi6"] > rsi14:
                rsi_adj += s.get("rsi_rising", 4)
                rsi_sigs.append("📈 RSI上行")
        else:
            if 45 <= rsi14 <= 75:
                # 2026-08-05 实证: 弱市强势60-75 5日-1.42%(最差) — 弱市强势=危险, 反转强化
                if weak_mode:
                    rsi_adj += s.get("penalty_chase_high", -8) * 0.6
                    rsi_sigs.append(f"📉 RSI={rsi14:.0f} 弱市强势(风险)")
                else:
                    rsi_adj += s.get("rsi_strong", 8); rsi_sigs.append(f"✅ RSI={rsi14:.0f} 强势区间")
            elif 30 <= rsi14 < 45:
                rsi_adj += s.get("rsi_weak", 5); rsi_sigs.append(f"📉 RSI={rsi14:.0f} 偏弱")
            elif rsi14 > 75:
                rsi_adj += s.get("kdj_overbought", -5)
                rsi_sigs.append(f"⚠️ RSI={rsi14:.0f} 超买")
            elif rsi14 < 30:
                # 弱市超跌反转强化×1.6 (实证 +1.49%)
                rsi_adj += s.get("rsi_weak", 5) * (1.6 if weak_mode else 1.0); rsi_sigs.append(f"⚠️ RSI={rsi14:.0f} 超卖")
            if inds.get("rsi6") and inds["rsi6"] > rsi14:
                rsi_adj += s.get("rsi_rising", 4); rsi_sigs.append("📈 RSI上行")
    # P1-6: RSI单因子封顶 ±15 (原弱市抄底可达28.8)
    rsi_adj = max(-15.0, min(15.0, rsi_adj))
    score += rsi_adj
    sigs.extend(rsi_sigs)

    # ─── 4. KDJ ───
    # P0修复: 使用.get()防御性访问
    kdj_k, kdj_d, kdj_j = inds.get("kdj_k"), inds.get("kdj_d"), inds.get("kdj_j")
    if kdj_k and kdj_d and kdj_j and kdj_k > kdj_d and kdj_j < 100:
        score += s.get("kdj_golden", 5); sigs.append("📈 KDJ金叉")
    if inds.get("kdj_j", 0) > 100:
        score += s.get("kdj_overbought", -5)
        sigs.append(f"⚠️ KDJ超买{inds['kdj_j']:.0f}")

    # ─── 5. 成交量 (v8.1: z-score截面标准化) ───
    # P0修复: 使用.get()防御性访问
    vr = inds.get("vol_ratio")
    if use_zscore and zscore and zscore.get("vol_ratio") is not None:
        vz = zscore["vol_ratio"]
        # z-score: 正值=放量, 负值=缩量
        if vz >= 1.5:
            score += s.get("vol_dump", -6) * 0.5
            sigs.append(f"⚠️ 天量{vr:.1f}倍(z={vz:.2f})防见顶")
        elif vz >= 0.8:
            w = s.get("vol_gt2", 8) * min(1.0, vz / 1.5)
            score += w
            sigs.append(f"✅ 放量{vr:.1f}倍(z={vz:.2f})")
        elif vz >= 0.3:
            score += s.get("vol_gt1.5", 5) * 0.8
            sigs.append(f"📊 温和放量{vr:.1f}倍(z={vz:.2f})")
        elif vz <= -1.0:
            score += s.get("vol_shrink", 3)
            sigs.append(f"📉 缩量{vr:.1f}倍(z={vz:.2f})观望")
    elif use_cross_rank and cross_rank and cross_rank.get("vol_ratio") is not None:
        vp = cross_rank["vol_ratio"]  # 0~1, 越大越放量
        # 放量加分但防天量见顶: 0.7-0.9 最佳, >0.97 降温
        if vp >= 0.97:
            score += s.get("vol_dump", -6) * 0.5
            sigs.append(f"⚠️ 天量{vr:.1f}倍 防见顶")
        elif vp >= 0.7:
            w = s.get("vol_gt2", 8) * (0.7 + 0.3 * (vp - 0.7) / 0.3)
            score += w
            sigs.append(f"✅ 放量{vr:.1f}倍(百分位{vp:.0%})")
        elif vp >= 0.5:
            score += s.get("vol_gt1.5", 5) * 0.8
            sigs.append(f"📊 温和放量{vr:.1f}倍")
        elif vp <= 0.15:
            score += s.get("vol_shrink", 3)
            sigs.append(f"📉 缩量{vr:.1f}倍 观望")
    else:
        # P0修复: vol_ratio可能为None，需防御性检查
        if vr and vr > 2.0:
            score += s.get("vol_gt2", 8); sigs.append(f"✅ 放量{vr:.1f}倍")
        elif vr and vr > 1.5:
            score += s.get("vol_gt1.5", 5); sigs.append(f"📊 放量{vr:.1f}倍")
        elif vr and vr > 1.2:
            score += s.get("vol_gt1.2", 3)

    # ─── 6. 短期动量 (v8.1: z-score截面标准化 + P1动态权重) ───
    chg5 = inds["chg5"]
    chg20 = inds.get("chg20", 0)
    # P1修复-2026-09-17: 动态权重根据市场状态调整
    # 牛市/强市：动量因子加重（chg5_gt8=15, chg10_rev=0）
    # 震荡/弱市：反转因子加重（chg5_rev=-12, chg10_rev=-8）
    if momentum_mode:
        _momentum_w = s.get("chg5_gt8", 8) * 1.5  # 牛市动量权重×1.5
        _reversal_w = 0  # 牛市关闭反转
    else:
        _momentum_w = s.get("chg5_gt8", 8) * 0.5  # 震荡动量权重×0.5
        _reversal_w = abs(s.get("chg5_rev", -8)) * 1.5  # 震荡反转权重×1.5

    if use_zscore and zscore and zscore.get("chg5") is not None:
        cz = zscore["chg5"]  # z-score, 正值=涨得多, 负值=跌得多
        # 反转模式(A股均值回归): 追涨负alpha, 超跌反弹正alpha
        if cz >= 1.5:
            if momentum_mode:
                score += _momentum_w * 1.0
                sigs.append(f"🚀 5日大涨{chg5:.1f}%动量强势(z={cz:.2f})")
            else:
                score += s.get("penalty_chase_high", -8) * 1.0
                sigs.append(f"⚠️ 5日大涨{chg5:.1f}%追高风险(z={cz:.2f})")
        elif cz >= 0.8:
            w = _momentum_w * 0.8 * (1.25 if momentum_mode else 1.0)
            score += w
            sigs.append(f"📈 5日涨{chg5:.1f}%(z={cz:.2f})")
        elif cz >= 0.0:
            sigs.append(f"➡️ 5日持平{chg5:.1f}%(z={cz:.2f})")
        elif cz <= -1.0:
            score += _reversal_w * 1.0 * reversal_bonus
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 5日超跌{chg5:.1f}%(z={cz:.2f})")
        if chg5 > inds.get("chg10", 0) and chg5 > 0:
            score += s.get("chg5_accel", 0); sigs.append("🚀 短期加速")
        if chg20 > 10:
            w = _momentum_w // 2 * (2 if momentum_mode else 1)
            score += w; sigs.append(f"20日动量强劲{chg20:.0f}%")
    elif use_cross_rank and cross_rank and cross_rank.get("chg5") is not None:
        cp = cross_rank["chg5"]  # 0~1, 越大涨越多
        # 反转模式(A股均值回归): 追涨负alpha, 超跌反弹正alpha
        # 动量模式(牛/强市): 强者恒强, 追高不罚反奖, 超跌不加分
        if cp >= 0.9:
            if momentum_mode:
                score += s.get("chg5_gt8", 8) * 1.0
                sigs.append(f"🚀 5日大涨{chg5:.1f}% 动量强势")
            else:
                score += s.get("penalty_chase_high", -12)
                sigs.append(f"⚠️ 5日大涨{chg5:.1f}% 追高风险")
        elif cp >= 0.75:
            w = s.get("chg5_gt8", 8) * 0.8
            if momentum_mode:
                w *= 1.25
            score += w
            sigs.append(f"📈 5日涨{chg5:.1f}%")
        elif cp >= 0.5:
            score += s.get("chg5_gt3", 5)
            sigs.append(f"✅ 5日温和涨{chg5:.1f}%")
        elif cp <= 0.15:
            # 超跌反转 (A股均值回归) — 牛市关闭(超跌=弱势)
            score += s.get("rsi_weak", 5) * 1.0 * reversal_bonus
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 5日超跌{chg5:.1f}% {'反转机会' if not momentum_mode else '弱势'}")
        if chg5 > inds.get("chg10", 0) and chg5 > 0:
            score += s.get("chg5_accel", 3); sigs.append("🚀 短期加速")
        if chg20 > 10:
            # 牛市 20 日动量加倍(动量倾斜核心)
            w = s.get("chg5_gt8", 8) // 2 * (2 if momentum_mode else 1)
            score += w; sigs.append(f"20日动量强劲{chg20:.0f}%")
    else:
        if chg5 > 8:
            score += s.get("chg5_gt8", 8); sigs.append(f"✅ 5日涨{chg5:.1f}%")
        elif chg5 > 3:
            score += s.get("chg5_gt3", 5); sigs.append(f"📈 5日涨{chg5:.1f}%")
        if chg5 > inds.get("chg10", 0) and chg5 > 0:
            score += s.get("chg5_accel", 3); sigs.append("🚀 短期加速")
        if chg20 > 10:
            score += s.get("chg5_gt8", 8) // 2; sigs.append(f"20日动量强劲{chg20:.0f}%")

    # ─── 7. 量价形态 ───
    vp = inds.get("vol_pattern")
    if vp in ("放量突破", "放量拉升"):
        score += s.get("vol_breakout", 6); sigs.append(f"✅ {vp}")
    elif vp == "缩量回调":
        score += s.get("vol_shrink", 3); sigs.append(f"📊 {vp}")
    elif vp == "放量下跌":
        score += s.get("vol_dump", -6); sigs.append(f"⚠️ {vp}")

    # ─── 7b. T-2026-08-20: 缩量企稳因子 (vol_shrink20)
    # 近20日均量/近60日均量: 低=缩量企稳, 预期负IC
    # cross_rank: vol_shrink20 百分位越低(越缩量)→加分
    # 注: vol_shrink20_bonus 可为负(负向因子, 如三线共振=-40), 此时百分位低(缩量)→加分高
    vs_bonus = s.get("vol_shrink20_bonus", 0)
    if vs_bonus != 0 and cross_rank and cross_rank.get("vol_shrink20") is not None:
        vs_pct = cross_rank["vol_shrink20"]  # 0~1, 越小越缩量
        if vs_bonus > 0:
            # 正向因子(抄底/全仓): 缩量加分
            if vs_pct <= 0.2:
                score += vs_bonus * 1.5
                sigs.append(f"📉 缩量企稳(20/60量比={inds.get('vol_shrink20', 0):.2f})")
            elif vs_pct <= 0.35:
                score += vs_bonus * 0.8
                sigs.append(f"📊 轻度缩量(20/60量比={inds.get('vol_shrink20', 0):.2f})")
        else:
            # 负向因子(三线共振): 缩量加分(因bonus为负, 低pct→高加分), 放量扣分
            # 逻辑: bonus=-40, pct=0(最缩量)→加60分, pct=0.95(最放量)→减20分
            if vs_pct <= 0.2:
                score += abs(vs_bonus) * 1.5  # 最缩量, 加满
                sigs.append(f"📉 缩量企稳(20/60量比={inds.get('vol_shrink20', 0):.2f})")
            elif vs_pct <= 0.35:
                score += abs(vs_bonus) * 0.8
                sigs.append(f"📊 轻度缩量(20/60量比={inds.get('vol_shrink20', 0):.2f})")
            elif vs_pct > 0.85:
                score += vs_bonus * 0.5  # 最放量, 扣分
                sigs.append(f"⚠️ 放量偏高(20/60量比={inds.get('vol_shrink20', 0):.2f})")

    # ─── 7c. T-20260820: turn5 筹码松动因子 (负IC → 扣分)
    turn5 = inds.get("turn5", 0)
    turn5_pen = s.get("turn5_penalty", 0)
    if turn5_pen < 0 and turn5 > 0:
        score += turn5_pen * turn5
        sigs.append(f"🔄 筹码松动(+{turn5}次涨跌停)")

    # ─── 7d. T-20260820: 均线粘合因子 (ma_tightness)
    # 5/10/20日均线间距小 → 粘合 → 蓄势待发
    ma_tight = s.get("ma_tight_bonus", 0)
    if ma_tight > 0 and inds.get("ma5") and inds.get("ma10") and inds.get("ma20"):
        ma5, ma10, ma20 = inds["ma5"], inds["ma10"], inds["ma20"]
        price = inds.get("price", 0)
        if price > 0:
            spread = max(abs(ma5 - ma10), abs(ma10 - ma20), abs(ma5 - ma20)) / price * 100
            if spread < 3.0:
                score += ma_tight
                sigs.append(f"📐 均线粘合(spread={spread:.1f}%)")
            elif spread < 5.0:
                score += ma_tight * 0.5
                sigs.append(f"📊 均线趋合(spread={spread:.1f}%)")

    # ─── 7e. P0-1: max_ret5 彩票型回避因子 (IC=-0.173 强负向)
    # 近20日最大单日涨幅过高 → 彩票型股票 → 未来收益低
    max_ret5 = inds.get("max_ret5", 0)
    max_ret5_bonus = s.get("max_ret5_low", 0)
    if max_ret5_bonus > 0 and max_ret5 > 0:
        # 反转逻辑: 低最大涨幅偏好 (回避彩票型)
        if max_ret5 > 15:
            score -= max_ret5_bonus * 1.5  # 彩票型重罚
            sigs.append(f"⚠️ 彩票型回避(+{max_ret5:.1f}%)")
        elif max_ret5 > 10:
            score -= max_ret5_bonus * 0.8
            sigs.append(f"📊 高风险(+{max_ret5:.1f}%)")
        else:
            score += max_ret5_bonus * 0.3  # 温和奖励稳定型

    # ─── 7f. P4: 反转因子 (IC=-0.22/-0.21/-0.17 强负向)
    # 短期到中期都存在显著反转效应，过去涨多的股票未来跌
    chg5 = inds.get("chg5", 0)
    chg10 = inds.get("chg10", 0)
    chg20 = inds.get("chg20", 0)
    chg5_rev = s.get("chg5_rev", 0)
    chg10_rev = s.get("chg10_rev", 0)
    chg20_rev = s.get("chg20_rev", 0)
    
    # P0-2026-09-13: 删除chg5/chg10直接权重计分块（双重计分bug）
    # 原因：chg5/chg10已通过z-score路径(L686-709)计分，此处直接权重块导致三重计分
    # chg5/z-score路径: max ±8pts; chg5/直接权重: max ±30pts; temporal_delta: max ±6pts
    # 合计：~44pts momentum bias out of ~150 total → 分数过度集中
    # 修复：删除直接权重块，保留z-score路径；策略权重chg5/chg10设为0（见tdx_strategies.py）
    # chg5_weight = s.get("chg5", 0)  # 已删除
    # chg10_weight = s.get("chg10", 0)  # 已删除

    # ─── 7h. P4: 波动率因子 (2026-09-04 P1反转: 奖励高波动突破票) ───
    # std20: 20日收盘价标准差，高值=高波动=真突破潜力
    # 反转逻辑: 之前惩罚高波动(-25), 现在奖励高波动(+15)
    volatility20 = inds.get("std20", 0)
    volatility_bonus = s.get("volatility20", 0)
    # P1-2026-09-04: 反转权重方向, 高波动票加分
    if volatility_bonus > 0 and volatility20 > 0:
        score += volatility_bonus * min(volatility20 / 20.0, 1.0)  # 归一化到0-1
        if volatility20 > 15:
            sigs.append(f"🚀 高波动突破(std20={volatility20:.2f})")
    elif volatility_bonus < 0:
        score += volatility_bonus * 1.0
        sigs.append(f"⚡ 波动率回避(std20={volatility20:.2f})")

    # ─── 7i. P0-2026-09-20: unlocked_pressure 解套盘压力因子 (IC=-0.1696 强负向) ───
    # unlocked_pressure: 近250日最高价与当前价的距离%，越高=越多解套盘压力=未来下跌
    _up = inds.get("unlocked_pressure", 0)
    _up_w = s.get("unlocked_pressure", 0)
    if _up_w != 0 and _up is not None and isinstance(_up, (int, float)) and math.isfinite(_up):
        if _up > 50:
            score += _up_w * 1.0  # 强压力，扣分
            sigs.append(f"⚠️ 解套盘压力大({_up:.0f}%)")
        elif _up > 30:
            score += _up_w * 0.6
            sigs.append(f"📊 解套盘偏高({_up:.0f}%)")
        elif _up > 10:
            score += _up_w * 0.3
        else:
            score += abs(_up_w) * 0.3  # 低压力，反向加分

    # ─── 7j. P0-2026-09-20: vol_ratio 量比因子 (IC=+0.1045 强正向) ───
    # vol_ratio: 当日量/5日均量，越高=放量=有资金关注
    _vr = inds.get("vol_ratio", 0)
    _vr_w = s.get("vol_ratio", 0)
    if _vr_w != 0 and _vr is not None and isinstance(_vr, (int, float)) and math.isfinite(_vr):
        if _vr >= 3.0:
            score += _vr_w * 0.5  # 天量警惕
            sigs.append(f"⚠️ 天量({_vr:.1f}倍)")
        elif _vr >= 2.0:
            score += _vr_w * 0.8
            sigs.append(f"✅ 放量({_vr:.1f}倍)")
        elif _vr >= 1.5:
            score += _vr_w * 0.5
            sigs.append(f"📊 温和放量({_vr:.1f}倍)")
        elif _vr >= 1.2:
            score += _vr_w * 0.3

    # ─── 7k. P0-2026-09-20: pos_vs_ma20 直接权重 (IC=-0.2263 最强负向) ───
    # pos_vs_ma20: 价格偏离MA20的百分比，正值=追高，负值=超跌
    _pv = inds.get("pos_vs_ma20", 0)
    _pv_w = s.get("pos_vs_ma20", 0)
    if _pv_w != 0 and _pv is not None and isinstance(_pv, (int, float)) and math.isfinite(_pv):
        if _pv > 15:
            score += _pv_w * 1.0  # 严重追高
            sigs.append(f"🚫 追高严重({_pv:+.0f}%)")
        elif _pv > 10:
            score += _pv_w * 0.7
            sigs.append(f"⚠️ 偏离均线({_pv:+.0f}%)")
        elif _pv > 5:
            score += _pv_w * 0.3
        elif _pv < -10:
            score += abs(_pv_w) * 0.5  # 超跌机会
            sigs.append(f"🔄 超跌({_pv:+.0f}%)")
        elif _pv < -5:
            score += abs(_pv_w) * 0.2

    # ─── 7l. P0-2026-09-20: std20 波动率因子 (IC=-0.3349 极强负向) ───
    # std20: 20日收盘价标准差，高值=高波动=风险大
    _sd = inds.get("std20", 0)
    _sd_w = s.get("std20", 0)
    if _sd_w != 0 and _sd is not None and isinstance(_sd, (int, float)) and math.isfinite(_sd):
        if _sd > 10:
            score += _sd_w * 0.8
            sigs.append(f"⚡ 高波动(std20={_sd:.2f})")
        elif _sd > 5:
            score += _sd_w * 0.4
        else:
            score += abs(_sd_w) * 0.2  # 低波动，反向加分

    # ─── 7h. P1: LHB龙虎榜因子 (2026-09-04): IC=0.0991 全场最强 ───
    # lhb_signal: +1=机构净买(加分), -1=机构净卖(扣分), 0=未上榜
    lhb_signal = inds.get("lhb_signal", 0)
    lhb_weight = s.get("lhb_signal", 0)
    if lhb_weight != 0 and lhb_signal != 0:
        if lhb_signal > 0:
            score += lhb_weight
            sigs.append(f"🐉 龙虎榜机构净买(lhb={lhb_signal:+.0f})")
        else:
            score -= lhb_weight
            sigs.append(f"🐉 龙虎榜机构净卖(lhb={lhb_signal:+.0f})")

    # ─── 7h. P4: RSI超卖反弹因子 (IC=+0.07 正向)
    # RSI超卖后反弹是好信号
    rsi14 = inds.get("rsi14", 50)
    rsi_oversold = s.get("rsi_oversold", 0)
    if rsi_oversold > 0 and rsi14 < 30:
        score += rsi_oversold
        sigs.append(f"📈 RSI超卖反弹(rsi14={rsi14:.0f})")

    # ─── 7j. P0: 结构信号因子 (2026-09-06): 回调后重新启动 & 突破后回踩再启动 ───
    # 新增的两类可执行结构信号，通过价量行为识别
    # 1. 回调后重新启动：健康回调后量能配合重新启动上涨
    # 2. 突破后回踩再启动：突破关键位置后回踩确认再次启动
    structure_bonus = 0.0
    structure_desc = ""
    if records is not None and len(records) >= 5:
        try:
            from signals.structure_integration import compute_structure_signals_score, get_structure_signals_description
            structure_bonus = compute_structure_signals_score(records)
            structure_desc = get_structure_signals_description(records)
        except ImportError:
            # 备用方案：如果模块导入失败，使用简化版本
            structure_bonus = 0.0
            structure_desc = ""
    
    # P0-2026-09-08: 结构信号降级为报告标注层，不纳入评分加分
    # 原因：回测胜率36%，平均收益-0.98%，未过门禁标准（胜率≥55%且收益>0）
    # 保留代码供未来牛市中验证，当前仅作报告参考
    if structure_desc and structure_desc != "【结构信号】无明显结构信号":
        sigs.append(f"🏗️ 结构信号: {structure_desc}")
    # 不再加分：score += structure_bonus * 0.5
    # alpha13: close-vol 5日协方差 (IC=+0.0341, IR=0.38, ✅ 132日过门禁)
    # vol_price_corr_20: 20日量价相关 (IC=-0.0566, IR=0.51, 替换alpha15噪声 2026-09-04)
    # alpha16_fix: alpha16单调性修复 (IC=+0.0556, IR=0.53, 方向率68%, ✅ 132日过门禁)
    # 设计: 高值加分(正向信号), 低值扣分(反向信号); 分档 ±0.15 / ±0.05
    # 注意: compute_indicators 中 alpha13/vol_price_corr_20 已取负号, 存储值越高→未来5日收益越好
    # 权重方向: 正权重=偏好高alpha(与正IC一致); 负权重=偏好低alpha(反向使用)
    # P0-2026-09-12: alpha13/alpha16_fix已淘汰(IC翻转失效)，以下代码注释保留
    # alpha13_w = s.get("alpha13", 0)  # 2026-09-12: IC翻转，已淘汰
    # alpha13_v = inds.get("alpha13")
    # if alpha13_w != 0 and alpha13_v is not None:
    #     if alpha13_v < -0.15:
    #         score += alpha13_w
    #         sigs.append(f"📐 alpha13={alpha13_v:+.2f} 反转强(✅)")
    #     elif alpha13_v < 0.0:
    #         score += alpha13_w * 0.5
    #         sigs.append(f"📊 alpha13={alpha13_v:+.2f} 反转温和")
    #     elif alpha13_v > 0.15:
    #         score -= alpha13_w
    #         sigs.append(f"📉 alpha13={alpha13_v:+.2f} 协方差弱(⚠️)")
    #     elif alpha13_v > 0.0:
    #         score -= alpha13_w * 0.5
    #         sigs.append(f"📉 alpha13={alpha13_v:+.2f} 协方差偏弱")

    # vol_price_corr_20: 20日量价相关 (IC=-0.0566, IR=0.51, 负向因子 2026-09-04)
    # 替代 alpha15 (IC≈0 噪声)
    vol_price_corr_20_w = s.get("vol_price_corr_20", 0)
    vol_price_corr_20_v = inds.get("vol_price_corr_20")
    if vol_price_corr_20_w != 0 and vol_price_corr_20_v is not None:
        if vol_price_corr_20_v < -0.15:  # 强负向 = 涨放量强 → 反转预期强 → 加分
            score += abs(vol_price_corr_20_w)
            sigs.append(f"📐 vol_price_corr_20={vol_price_corr_20_v:+.2f} 量价相关强(✅)")
        elif vol_price_corr_20_v < -0.05:
            score += abs(vol_price_corr_20_w) * 0.5
            sigs.append(f"📊 vol_price_corr_20={vol_price_corr_20_v:+.2f} 量价相关温和")
        elif vol_price_corr_20_v > 0.15:  # 强正向 = 跌放量 → 加分
            score -= abs(vol_price_corr_20_w)
            sigs.append(f"📉 vol_price_corr_20={vol_price_corr_20_v:+.2f} 量价相关反向(⚠️)")
        elif vol_price_corr_20_v > 0.0:
            score -= abs(vol_price_corr_20_w) * 0.5
            sigs.append(f"📉 vol_price_corr_20={vol_price_corr_20_v:+.2f} 量价相关偏弱")
    
    # momentum_reversal: 动量反转因子 (IC=+0.62, 短期动量×中期反转 2026-09-15)
    mr_w = s.get("momentum_reversal", 0)
    mr_v = inds.get("momentum_reversal")
    if mr_w != 0 and mr_v is not None:
        if mr_v > 0.05:
            score += mr_w
            sigs.append(f"📈 momentum_reversal={mr_v:.4f} 动量反转强(✅)")
        elif mr_v > 0.02:
            score += mr_w * 0.5
            sigs.append(f"📊 momentum_reversal={mr_v:.4f} 动量反转温和")
    
    # volume_abnormal: 成交量异常度 (IC=-0.70, 高分=高风险 2026-09-15)
    va_w = s.get("volume_abnormal", 0)
    va_v = inds.get("volume_abnormal")
    if va_w != 0 and va_v is not None:
        if va_v > 0.5:
            score += va_w  # 负权重，所以是扣分
            sigs.append(f"⚠️ volume_abnormal={va_v:.2f} 成交异常度高(风险)")
        elif va_v > 0.3:
            score += va_w * 0.5
            sigs.append(f"⚡ volume_abnormal={va_v:.2f} 成交轻度异常")

    # rsi_extreme: RSI极端值因子 (IC=-0.0567, 负相关 2026-09-16)
    # 超买(RSI>70)或超卖(RSI<30)后反转信号
    rsi_ext_w = s.get("rsi_extreme", 0)
    rsi_ext_v = inds.get("rsi_extreme")
    if rsi_ext_w != 0 and rsi_ext_v is not None:
        if rsi_ext_v == 1:
            score += rsi_ext_w  # 负权重，所以是扣分
            sigs.append(f"⚠️ rsi_extreme={rsi_ext_v} RSI极端值(反转风险)")

    # price_volume_divergence: 量价背离因子 (IC=+0.0871, 正相关 2026-09-16)
    # 价格与成交量方向背离后趋势延续
    pvd_w = s.get("price_volume_divergence", 0)
    pvd_v = inds.get("price_volume_divergence")
    if pvd_w != 0 and pvd_v is not None:
        if pvd_v == 1:
            score += pvd_w
            sigs.append(f"📊 price_volume_div={pvd_v} 量价背离(趋势延续)")


    # alpha16_fix: alpha16单调性修复 (Phase D-2新增, 2026-08-31)
    # 原alpha16: IC=+0.0411, IR=0.48, 但单调差-0.236(⚠️部分通过, 方向率67%);
    # 修复后 alpha16_fix: IC=+0.0556, IR=0.53, 方向率68%, 单调差+0.229 ✅ 全过门禁
    # 分档阈值沿用 alpha13/alpha15 (±0.15)
    # 注意: 指标计算模块 tdx_indicators.py 输出键为 "alpha16_fix"(见 L265+L326),
    #       alpha16_fix 用原始 volume 算法(非 rank), 与过门禁验证一致;
    #       alpha16(旧)用 rank(volume) 算法, 单调差-0.236 未过门禁, 仅供兼容保留。
    # P0-2026-09-12: alpha16_fix已淘汰(IC翻转失效)，以下代码注释保留
    # alpha16fix_w = s.get("alpha16_fix", 0)
    # alpha16fix_v = inds.get("alpha16_fix")
    # if alpha16fix_w != 0 and alpha16fix_v is not None:
    #     if alpha16fix_v < -0.15:
    #         score += alpha16fix_w
    #         sigs.append(f"📐 alpha16_fix={alpha16fix_v:+.2f} 反转强(✅)")
    #     elif alpha16fix_v < 0.0:
    #         score += alpha16fix_w * 0.5
    #         sigs.append(f"📊 alpha16_fix={alpha16fix_v:+.2f} 反转温和")
    #     elif alpha16fix_v > 0.15:
    #         score -= alpha16fix_w
    #         sigs.append(f"📉 alpha16_fix={alpha16fix_v:+.2f} 协方差弱(⚠️)")
    #     elif alpha16fix_v > 0.0:
    #         score -= alpha16fix_w * 0.5
    #         sigs.append(f"📉 alpha16_fix={alpha16fix_v:+.2f} 协方差偏弱")

    # ─── 7j. Phase C-2: vol_floor 低波动筛选因子 (IC=-0.0375 IR=-0.359 ✅过门禁) ───
    # vol_floor = 今日成交量 / 近20日最低成交量
    # IC负向: vol_floor 值越低(量缩至地量) → 未来收益越好
    # 门禁数据源: data/audit/new_factor_ic_20260830.json (第三个强因子)
    vol_floor_w = s.get("vol_floor", 0)
    vol_floor_v = inds.get("vol_floor")
    if vol_floor_w != 0 and vol_floor_v is not None:
        # 阈值分档: vol_floor≈1.0(极缩量) → 强正向; vol_floor>2.0(放量) → 负向
        if vol_floor_v <= 1.0:
            # 极缩量(地量) — 低波异象最强信号
            score += vol_floor_w * 1.5  # 放大奖励(核心因子)
            sigs.append(f"💎 vol_floor={vol_floor_v:.2f}(地量) 低波异象强(✅)")
        elif vol_floor_v <= 1.5:
            score += vol_floor_w * 1.0
            sigs.append(f"💎 vol_floor={vol_floor_v:.2f}(缩量) 低波异象")
        elif vol_floor_v <= 2.0:
            score += vol_floor_w * 0.5
            sigs.append(f"📊 vol_floor={vol_floor_v:.2f}(温和放量) 中性")
        elif vol_floor_v <= 3.0:
            score -= vol_floor_w * 0.5
            sigs.append(f"📉 vol_floor={vol_floor_v:.2f}(放量) 回避")
        else:
            score -= vol_floor_w * 1.0
            sigs.append(f"📉 vol_floor={vol_floor_v:.2f}(爆量) 重罚")

    # ─── 7k. Phase A (2026-09-02): amount_q_reversal 成交额分位数切割反转 ───
    # IC=-0.0502, IR=0.51, 方向率69%(全场最高), 单调差-0.304, walk_forward样本外-0.0420(退化率0.026)
    # 因子=高成交组平均日涨幅 - 低成交组平均日涨幅(最近20日)
    # 量纲: 小数差值(0.025=2.5%), 与门禁 IC=-0.0502 同量纲
    # 负值=反转信号(高成交日涨幅大→未来跌→加分)
    # 分档阈值: ±0.010 温和, ±0.015 强(参考132日IC分布)
    aqr_w = s.get("amount_q_reversal", 0)
    aqr_v = inds.get("amount_q_reversal")
    if aqr_w != 0 and aqr_v is not None:
        if aqr_v < -0.015:
            score += aqr_w
            sigs.append(f"🔷 amount_q_rev={aqr_v:+.4f} 成交反转强(✅)")
        elif aqr_v < -0.010:
            score += aqr_w * 0.7
            sigs.append(f"🔶 amount_q_rev={aqr_v:+.4f} 成交反转中")
        elif aqr_v < 0.0:
            score += aqr_w * 0.4
            sigs.append(f"📊 amount_q_rev={aqr_v:+.4f} 反转温和")
        elif aqr_v < 0.010:
            score += aqr_w * 0.2
            sigs.append(f"📈 amount_q_rev={aqr_v:+.4f} 高成交日涨幅低(中性偏正)")
        elif aqr_v < 0.015:
            score -= aqr_w * 0.5
            sigs.append(f"📉 amount_q_rev={aqr_v:+.4f} 无反转(⚠️)")
        else:
            score -= aqr_w
            sigs.append(f"📉 amount_q_rev={aqr_v:+.4f} 动量主导(避开)")


    # ─── 7l. Phase E (2026-09-13): sector_correlation 板块联动度因子 ───
    # IC=+0.0819, IR=0.43, 方向率64%, 部分通过门禁（单调性失败，需非线性变换）
    # 逻辑: 个股与创业板指收益率滚动相关系数，高联动→跟随板块→短期趋势延续
    sector_corr_w = s.get("sector_correlation", 0)
    sector_corr_v = inds.get("sector_correlation")
    if sector_corr_w != 0 and sector_corr_v is not None:
        # 非线性变换: 分段函数（避免单调性问题）
        # 高联动区(+0.5以上)→强正向; 中联动区(+0.2~+0.5)→中等正向; 低联动区(<+0.2)→中性
        if sector_corr_v >= 0.5:
            score += sector_corr_w * 1.5
            sigs.append(f"🔗 板块高联动(sector_corr={sector_corr_v:.3f})")
        elif sector_corr_v >= 0.2:
            score += sector_corr_w * 1.0
            sigs.append(f"📊 板块中联动(sector_corr={sector_corr_v:.3f})")
        elif sector_corr_v >= 0.0:
            score += sector_corr_w * 0.5
            sigs.append(f"➡️ 板块弱联动(sector_corr={sector_corr_v:.3f})")
        else:
            score -= sector_corr_w * 0.5
            sigs.append(f"📉 板块负联动(sector_corr={sector_corr_v:.3f})")

    # ─── 7m. Phase F-2026-09-16: 差异化因子组（区分度提升） ───
    # 目标：解决TOP5方差=0.0问题，提升评分区分度
    # 5个新因子总权重: 10+12+15+8+10=55分

    # 7m-1: sector_heat_persistence 板块热度持续性 (权重10, IC≈0.04)
    # 短期(3日)热度/中期(10日)热度比率, >1加速, <0.5衰减
    shtp_w = s.get("sector_heat_persistence", 0)
    shtp_v = inds.get("sector_heat_persistence")
    if shtp_w != 0 and shtp_v is not None:
        if shtp_v == 1:
            score += shtp_w
            sigs.append(f"🔥 sector_heat_persist=1 热度加速(✅)")
        elif shtp_v == -1:
            score += shtp_w * -0.5
            sigs.append(f"📉 sector_heat_persist=-1 热度衰减")
        else:
            sigs.append(f"➡️ sector_heat_persist=0 热度中性")

    # 7m-2: fund_flow_intensity 资金流向强度 (权重12, IC≈0.05)
    # 价格动量+成交量放大确认, 机构资金认可度
    ffi_w = s.get("fund_flow_intensity", 0)
    ffi_v = inds.get("fund_flow_intensity")
    if ffi_w != 0 and ffi_v is not None:
        if ffi_v == 1:
            score += ffi_w
            sigs.append(f"💰 fund_flow_intensity=1 资金流入强(✅)")
        elif ffi_v == -1:
            score += ffi_w * -0.5
            sigs.append(f"📉 fund_flow_intensity=-1 资金流出")
        else:
            sigs.append(f"➡️ fund_flow_intensity=0 资金中性")

    # 7m-3: breakout_strength 突破力度指数 (权重15, IC≈0.06)
    # (收盘价-20日低点)/20日波动率, 标准化到[-1,1]
    bs_w = s.get("breakout_strength", 0)
    bs_v = inds.get("breakout_strength")
    if bs_w != 0 and bs_v is not None:
        if bs_v >= 0.5:
            score += bs_w
            sigs.append(f"🚀 breakout_strength={bs_v:.2f} 强势突破(✅)")
        elif bs_v >= 0.0:
            score += bs_w * 0.5
            sigs.append(f"📈 breakout_strength={bs_v:.2f} 温和突破")
        elif bs_v >= -0.5:
            score += bs_w * -0.3
            sigs.append(f"📉 breakout_strength={bs_v:.2f} 弱势反弹")
        else:
            score += bs_w * -0.8
            sigs.append(f"⚠️ breakout_strength={bs_v:.2f} 下跌趋势")

    # 7m-4: upside_volatility_ratio 上行波动比率 (权重8, IC≈0.03)
    # 上涨日标准差/下跌日标准差, >1健康上涨, <1脆弱上涨
    uv_rat_w = s.get("upside_vol_ratio", 0)
    uv_rat_v = inds.get("upside_vol_ratio")
    if uv_rat_w != 0 and uv_rat_v is not None:
        if uv_rat_v >= 0.3:
            score += uv_rat_w
            sigs.append(f"📊 upside_vol_ratio={uv_rat_v:.2f} 健康上涨(✅)")
        elif uv_rat_v >= 0:
            score += uv_rat_w * 0.5
            sigs.append(f"➡️ upside_vol_ratio={uv_rat_v:.2f} 中性波动")
        else:
            score += uv_rat_w * -0.5
            sigs.append(f"⚠️ upside_vol_ratio={uv_rat_v:.2f} 脆弱上涨")

    # 7m-5: support_distance 支撑位距离 (权重10, IC≈0.04)
    # (当前价-MA20)/MA20, 标准化到[-1,1], 安全边际评估
    sd_w = s.get("support_distance", 0)
    sd_v = inds.get("support_distance")
    if sd_w != 0 and sd_v is not None:
        if sd_v >= 0.5:
            score += sd_w
            sigs.append(f"📐 support_distance={sd_v:.2f} 远离均线上方(✅)")
        elif sd_v >= 0:
            score += sd_w * 0.5
            sigs.append(f"➡️ support_distance={sd_v:.2f} 均线附近")
        elif sd_v >= -0.5:
            score += sd_w * -0.3
            sigs.append(f"📉 support_distance={sd_v:.2f} 接近支撑")
        else:
            score += sd_w * -0.8
            sigs.append(f"⚠️ support_distance={sd_v:.2f} 跌破支撑")


    # ─── 8. 扣分项：远离均线/追高 (v8.1: z-score截面标准化) ───
    # P0修复: 使用.get()防御性访问
    pos20 = inds.get("pos_vs_ma20")
    if use_zscore and zscore and zscore.get("pos_vs_ma20") is not None:
        pz = zscore["pos_vs_ma20"]  # 正值=偏离均线上方, 负值=低于均线
        if pz >= 1.5:
            score += s.get("penalty_chase_high", -8) * 1.5 * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"🚫 严重追高({pos20:+.0f}%, z={pz:.2f})")
        elif pz >= 1.0:
            score += s.get("penalty_chase_high", -8) * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"⚠️ 追高{pos20:+.0f}%(z={pz:.2f})")
        elif pz >= 0.5:
            score += s.get("penalty_chase_high", -8) * 0.5 * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"⚠️ 偏高{pos20:+.0f}%(z={pz:.2f})")
        elif pz <= -1.5:
            score += s.get("rsi_weak", 5) * 0.5 * reversal_bonus * (1.6 if weak_mode else 1.0)
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 严重超跌{pos20:+.0f}%(z={pz:.2f})")
        elif pz <= -1.0:
            score += s.get("rsi_weak", 5) * 0.6 * reversal_bonus * (1.6 if weak_mode else 1.0)
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 温和回落{pos20:+.0f}%(z={pz:.2f})")
    elif use_cross_rank and cross_rank and cross_rank.get("pos_vs_ma20") is not None:
        pp = cross_rank["pos_vs_ma20"]  # 0~1, 越大越远离均线上方
        # v8.1 收紧: 0.95/0.85/0.75 → 0.90/0.80/0.70 (普涨日百分位虚高, 更早触发惩罚)
        if pp >= 0.90:
            # 2026-08-05 实证: 动量模式选股平均乖离+10%, 追高惩罚被chase_penalty(0.2)稀释失效 → 动量模式不稀释
            score += s.get("penalty_chase_high", -12) * 1.5 * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"🚫 严重追高({pos20:+.0f}%)")
        elif pp >= 0.80:
            score += s.get("penalty_chase_high", -12) * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"⚠️ 追高{pos20:+.0f}%")
        elif pp >= 0.70:
            score += s.get("penalty_chase_high", -12) * 0.5 * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"⚠️ 偏高{pos20:+.0f}%")
        elif pp <= 0.1:
            # 严重超跌: 统一为反转逻辑 — 牛市关闭(超跌=弱势), 弱市强化
            score += s.get("rsi_weak", 5) * 0.5 * reversal_bonus * (1.6 if weak_mode else 1.0)
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 严重超跌{pos20:+.0f}% {'双面信号' if not momentum_mode else '弱势'}")
        elif pp <= 0.2:
            # 温和偏低 - 反转机会 — 牛市关闭, 弱市强化
            score += s.get("rsi_weak", 5) * 0.6 * reversal_bonus * (1.6 if weak_mode else 1.0)
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 温和回落{pos20:+.0f}% {'机会' if not momentum_mode else '弱势'}")
    else:
        # v8.1 收紧: 15%/12% 触发, 惩罚加重 (从大到小判断)
        # P0修复: pos20可能为None，需防御性检查
        if pos20 and pos20 > 20:
            score += s.get("penalty_far", -10); sigs.append("⚠️ 远离均线")
        elif pos20 and pos20 > 15:
            score += s.get("penalty_chase_high", -12); sigs.append(f"🚫 追高{pos20:.0f}%")
        elif pos20 and pos20 > 12:
            score += s.get("penalty_far", -10); sigs.append(f"⚠️ 偏离{pos20:.0f}%")
        elif pos20 and pos20 < -10:
            score += s.get("penalty_far", -10); sigs.append(f"⚠️ 偏低{pos20:.0f}%")

    # ─── 9. 周线/多周期共振 ───
    if weekly:
        w_bull = weekly.get("w_bullish", False)
        w_hist = weekly.get("w_hist", 0)
        if w_bull and is_ma_bull:
            score += s.get("weekly_bullish", 6); sigs.append("⏫ 多周期共振")
        elif w_bull:
            score += s.get("weekly_bullish", 6); sigs.append("📈 周线多头")
        if w_hist and w_hist > 0 and is_ma_bull:
            score += s.get("weekly_macd_red", 3); sigs.append("⏫ 周线MACD红柱+日线多头")

    # ─── 10. 🏭 板块轮动 ───
    heat_penalty = s.get("industry_cold_bottom5", -3)
    if industry_heat and isinstance(industry_heat, dict):
        heat = industry_heat.get("percentile", 0.5)
        if heat >= 0.8:
            score += s.get("industry_hot_top5", 5); sigs.append(f"🔥 板块热点 TOP{(1-heat)*100:.0f}%")
        elif heat <= 0.2:
            score += heat_penalty; sigs.append("❄️ 板块弱势")

    # ─── 11. 💰 主力资金流 ───
    if fund_flow_bonus:
        fb_max = max(abs(s.get("fund_flow_pos", 5)), abs(s.get("fund_flow_neg", -5)))
        fb = min(abs(fund_flow_bonus), fb_max) * (1 if fund_flow_bonus > 0 else -1)
        score += fb
        if fund_flow_signal: sigs.append(f"{fund_flow_signal}")

    # ─── 12. 🏛️ 技术形态加分 ───
    if inds.get("pattern_found"):
        pscore = inds.get("pattern_score", 0)
        pdesc = inds.get("pattern_desc", "")
        bonus = min(pscore, s.get("pattern_bonus", 5))
        score += bonus
        sigs.append(f"🏆 {pdesc[:30]}")

    # ─── 动态前置封顶：不同策略的总分上限随权重浮动 ───
    # 上限 = min(90, 正权重总和×0.75)
    # 给增强因子(资金流/新闻/相对强弱等)留10分空间
    positive_keys = ["ma_mlt", "ma_above60", "ma_above120", "macd_golden_red",
                     "macd_golden", "macd_above0", "rsi_strong", "rsi_weak",
                     "rsi_rising", "kdj_golden", "vol_gt2", "vol_gt1.5",
                     "vol_gt1.2", "chg5_gt8", "chg5_gt3", "chg5_accel",
                     "vol_breakout", "vol_shrink", "weekly_bullish",
                     "weekly_macd_red", "industry_hot_top5", "fund_flow_pos",
                     "pattern_bonus"]
    base_max_possible = sum(max(0, s.get(k, 0)) for k in positive_keys)
    # 2026-08-04 评分区分度优化v3: 封顶系数 0.4→0.7 (187权重→基础上限130→cap90)
    # 原因: 0.4封顶导致62%股票挤在65-80分无区分度, 0.7恢复顶部区分(模拟验证41只≥80)
    # P1-1修复(2026-08-07): 0.7→0.85 (标准差4.21<8, 评分仍压缩65-75 → 放宽封顶让高分更高)
    # 增强因子(资金/财务/新闻/RS各10分, 最多40分)仍能推到 90+40=130, 但被 min(100) 截断
    # P0-2026-08-24 T-003: cap=90把头部削平→TOP同分堆积(std=2.85主因) → 放开到100
    #   基础分187×0.85=159>100, 等效不截断, 头部90-100自然展开, 由末尾min(100)兜底
    # P2-2026-09-14: 修复区分度不足(1.16pp<2.0pp) → 动态封顶+移除硬上限
    # 根因: cap=120导致高分票聚集，mid25%收益反而高于top25%
    # 方案: 改用动态封顶（基础分×1.0），保留增强因子加分空间
    cap = int(base_max_possible * 1.0)  # 动态封顶，不再硬限制120
    if score > cap > 0:
        score = cap
        sigs.append(f"📊 基础分达{cap}上限")

    # ─── 13. 相对强弱 ───
    if rs_bonus:
        score += min(abs(rs_bonus), 10) * (1 if rs_bonus > 0 else -1)

    # ─── 14. 资金面因子 ───
    if fundamental_bonus:
        score += min(abs(fundamental_bonus), 10) * (1 if fundamental_bonus > 0 else -1)

    # ─── 14b. P1-2026-09-08: 基本面因子（激进版：硬过滤+技术排序）──
    # 方案：基本面作为硬门槛，不通过则返回0分（跳过该股票）
    # 根因：原方案基本面权重过低，无法修正技术因子排序偏差
    # P1-fix 2026-09-09: 默认值归0 — 仅显式定义门槛的策略(基本面+)启用硬过滤
    # 原默认0.05/0.60导致未定义门槛的策略(综合/Alpha101等)全市场0候选→0交易回归
    fund_min_roe = s.get("fund_min_roe", 0.0)
    fund_min_profit = s.get("fund_min_profit_growth", 0.0)
    fund_min_rev = s.get("fund_min_revenue_growth", 0.0)
    fund_min_margin = s.get("fund_min_net_margin", 0.0)
    fund_max_debt = s.get("fund_max_debt_ratio", 0.0)
    fund_min_cf = s.get("fund_min_cashflow", 0.0)

    # 检查是否需要基本面过滤（仅"基本面+"策略启用）
    if any([fund_min_roe, fund_min_profit, fund_min_rev, fund_min_margin, fund_max_debt, fund_min_cf]):
        fin_ind = inds.get("_fin_indicators", {})
        if fin_ind:
            # ROE门槛
            roe = fin_ind.get('roe', 0)
            if isinstance(roe, (int, float)) and roe < fund_min_roe:
                score = 0
                sigs.append(f"❌ ROE={roe:.2%}低于门槛{fund_min_roe:.2%}")
                return score, sigs, None
            # 利润增长门槛
            profit_yoy = fin_ind.get('net_profit_yoy', 0)
            if isinstance(profit_yoy, (int, float)) and profit_yoy < fund_min_profit:
                score = 0
                sigs.append(f"❌ 利润增长{profit_yoy:.2%}低于门槛{fund_min_profit:.2%}")
                return score, sigs, None
            # 营收增长门槛
            rev_yoy = fin_ind.get('revenue_yoy', 0)
            if isinstance(rev_yoy, (int, float)) and rev_yoy < fund_min_rev:
                score = 0
                sigs.append(f"❌ 营收增长{rev_yoy:.2%}低于门槛{fund_min_rev:.2%}")
                return score, sigs, None
            # 净利率门槛
            net_margin = fin_ind.get('net_margin', 0)
            if isinstance(net_margin, (int, float)) and net_margin < fund_min_margin:
                score = 0
                sigs.append(f"❌ 净利率{net_margin:.2%}低于门槛{fund_min_margin:.2%}")
                return score, sigs, None
            # 负债率门槛
            debt_ratio = fin_ind.get('debt_ratio', 0.5)
            if isinstance(debt_ratio, (int, float)) and 0 < debt_ratio < 1:
                if debt_ratio > fund_max_debt:
                    score = 0
                    sigs.append(f"❌ 负债率{debt_ratio:.2%}高于门槛{fund_max_debt:.2%}")
                    return score, sigs, None
            # 现金流门槛
            cf = fin_ind.get('cashflow_per_share', 0)
            if isinstance(cf, (int, float)) and cf < fund_min_cf:
                score = 0
                sigs.append(f"❌ 现金流{cf:.2f}低于门槛{fund_min_cf:.2f}")
                return score, sigs, None
            # 通过所有门槛，添加基本面优质信号
            sigs.append(f"💰 基本面优质(ROE{roe:.2%}+增长{profit_yoy:.2%})")
        else:
            # P0修复(2026-09-19): 无财务数据时不直接返回0，继续用技术指标评分
            # 早期历史数据可能缺少财务数据，但不应该完全排除
            sigs.append("⚠️ 无财务数据，仅用技术面评分")
            # P0修复(2026-09-23): 不再在此处 return，让时序增强继续执行
            # return score, sigs, None  # 已删除，时序增强必须在财务检查后执行

    # ─── 14b. P1-2026-09-18: 基本面硬门槛（主板单票策略）───
    # 硬性过滤：ROE≥10%, 利润增长>5%, 负债率≤55%, 净利率>5%
    # 通过门槛后给予额外加分（非硬门槛只加分，本方案改为硬过滤）
    fund_min_roe = s.get("fund_min_roe", 0.10)
    fund_min_profit = s.get("fund_min_profit_growth", 0.05)
    fund_min_margin = s.get("fund_min_net_margin", 0.05)
    fund_max_debt = s.get("fund_max_debt_ratio", 0.55)
    fund_min_cf = s.get("fund_min_cashflow", 0.5)
    
    # 仅当策略配置了基本面参数时才启用（避免影响其他策略）
    if any([fund_min_roe, fund_min_profit, fund_min_margin, fund_min_cf]):
        fin_ind = inds.get("_fin_indicators", {})
        if fin_ind:
            # ROE硬性门槛：低于10%直接拦截
            roe = fin_ind.get('roe', 0)
            if isinstance(roe, (int, float)):
                if roe < fund_min_roe:
                    sigs.append(f"❌ ROE={roe:.1%} 不达标(≥{fund_min_roe:.0%})")
                    return score, sigs, None  # 硬门槛不通过
                else:
                    score += 8
                    sigs.append(f"✅ ROE={roe:.1%} 盈利质量高(≥{fund_min_roe:.0%})")
            
            # 利润增长硬性门槛：低于5%直接拦截
            profit_yoy = fin_ind.get('net_profit_yoy', 0)
            if isinstance(profit_yoy, (int, float)):
                if profit_yoy < fund_min_profit:
                    sigs.append(f"❌ 利润增长={profit_yoy:.1%} 不达标(≥{fund_min_profit:.0%})")
                    return score, sigs, None
                else:
                    score += 5
                    sigs.append(f"📈 利润增长{profit_yoy:.1%} 加速")
            
            # 负债率硬性门槛：高于55%直接拦截
            debt_ratio = fin_ind.get('debt_ratio', 1.0)
            if isinstance(debt_ratio, (int, float)):
                if debt_ratio > fund_max_debt:
                    sigs.append(f"❌ 负债率={debt_ratio:.1%} 过高(≤{fund_max_debt:.0%})")
                    return score, sigs, None
                else:
                    score += 4
                    sigs.append(f"💰 负债率{debt_ratio:.1%} 财务稳健")
            
            # 净利率硬性门槛：低于5%直接拦截
            net_margin = fin_ind.get('net_margin', 0)
            if isinstance(net_margin, (int, float)):
                if net_margin < fund_min_margin:
                    sigs.append(f"❌ 净利率={net_margin:.1%} 不达标(≥{fund_min_margin:.0%})")
                    return score, sigs, None
                else:
                    score += 3
                    sigs.append(f"💵 净利率{net_margin:.1%} 盈利能力强")
            
            # 现金流加分项
            cf = fin_ind.get('cashflow_per_share', 0)
            if isinstance(cf, (int, float)) and cf >= fund_min_cf:
                score += 2
                sigs.append(f"💸 现金流为正")
    
    # ─── 15. 新闻情绪 ───
    if news_bonus:
        adj = min(abs(news_bonus), 10) * (1 if news_bonus > 0 else -1)
        score += adj

    # ─── 16. 深度学习GRU (P1-8清理: dl_bonus来自bonuses死代码, 一并删除) ───

    # ─── v8.1 区分度增强: 时序相对强弱 (双轨评分, sigmoid连续映射 2026-08-06) ───
    # 问题: 截面百分位在普涨日失效(80%股票都在涨, 百分位都高) → TOP5同分72
    # PATCH-2: 阶梯式(±3/0) → sigmoid连续映射, 温和票也获得±1~2分增强
    # PATCH-4 (2026-08-06, 验证指标2): 作用区间 62-78 → 40-95
    #   实测: 62-78 区间仅覆盖 1.8% 股票(51/2795) → 时序增强覆盖率必过项<60%
    #   扩大后: 40-95 覆盖绝大多数候选, 边界区间(40-62/78-95)半幅温和增强防噪声
    # 位置: 市场折扣之前 — 折扣会把分数压出聚集区, 时序增强必须用原始分判断
    temporal_delta = 0.0
    if 40 <= score <= 95:
        _ts_scale = 0.5 if (score < 62 or score > 78) else 1.0  # 边界温和, 聚集区全幅
        import math as _math
        _chg5_v = inds.get("chg5")
        _chg20_v = inds.get("chg20", 0)
        if _chg5_v is not None and _chg20_v is not None:
            # 时序Z-score近似: 短期动量vs中期动量的标准化差
            _z_mom = (_chg5_v - _chg20_v * 0.5) / (abs(_chg20_v) + 2.0)
            _delta_mom = 6.0 * _math.tanh(_z_mom * 0.5)   # P1-1修复: 5.0→6.0 (提升区分度)
            temporal_delta += _delta_mom * _ts_scale
            # 修复(PATCH-5): 原abs()判断导致负delta显示"短期加速" — 必须区分方向
            # P0修复(2026-09-23): 降低阈值至0.3，提升时序增强覆盖率
            # 注意：条件顺序必须从严格到宽松，避免高阶条件拦截低阶信号
            if _delta_mom * _ts_scale >= 1.0:
                sigs.append("🚀 短期加速(时序+%.1f)" % (_delta_mom * _ts_scale))
            elif _delta_mom * _ts_scale <= -1.0:
                sigs.append("📉 短期减速(时序%+.1f)" % (_delta_mom * _ts_scale))
            elif _delta_mom * _ts_scale >= 0.5:
                sigs.append("📈 短期偏强(时序%+.1f)" % (_delta_mom * _ts_scale))
            elif _delta_mom * _ts_scale <= -0.5:
                sigs.append("📉 短期偏弱(时序%+.1f)" % (_delta_mom * _ts_scale))
            elif _delta_mom * _ts_scale >= 0.3:  # P0修复: 新增阈值，捕获温和信号
                sigs.append("📈 短期偏强(时序%+.1f)" % (_delta_mom * _ts_scale))
            elif _delta_mom * _ts_scale <= -0.3:  # P0修复: 新增阈值，捕获温和信号
                sigs.append("📉 短期偏弱(时序%+.1f)" % (_delta_mom * _ts_scale))
            elif _delta_mom * _ts_scale >= 0.15:  # P0修复: 更宽松的阈值
                sigs.append("📈 短期偏强(时序%+.1f)" % (_delta_mom * _ts_scale))
            elif _delta_mom * _ts_scale <= -0.15:  # P0修复: 更宽松的阈值
                sigs.append("📉 短期偏弱(时序%+.1f)" % (_delta_mom * _ts_scale))
        _vr_v = inds.get("vol_ratio")
        if _vr_v:
            _z_vr = (_vr_v - 1.0) / 0.5
            _delta_vr = 3.0 * _math.tanh(_z_vr)           # 1.5倍量→+2.2; 0.7倍量→-1.5
            temporal_delta += _delta_vr * _ts_scale
            if _delta_vr * _ts_scale >= 1.0:
                sigs.append("📊 放量确认(时序+%.1f)" % (_delta_vr * _ts_scale))
            elif _delta_vr * _ts_scale <= -1.0:
                sigs.append("📉 缩量观望(时序%+.1f)" % (_delta_vr * _ts_scale))
            elif _delta_vr * _ts_scale >= 0.5:
                sigs.append("📈 量能温和(时序+%.1f)" % (_delta_vr * _ts_scale))
            elif _delta_vr * _ts_scale <= -0.5:
                sigs.append("📉 量能偏弱(时序%+.1f)" % (_delta_vr * _ts_scale))
        score += temporal_delta

    # ─── P1: 截面z-score标准化 (解决市场状态差异) ───
    # 问题: 绝对阈值在不同市场状态下失效（普涨日80%股票都在涨，百分位都高）
    # 方案: 截面z-score标准化 + Sigmoid映射到0-100
    # 位置: 市场折扣之前 — 折扣会把分数压出聚集区, 标准化必须用原始分判断
    # 设计: z-score = (raw_score - market_mean) / market_std
    #       final_score = 50 + 20 * (2/(1+exp(-z)) - 1)  [sigmoid映射到0-100]
    # 验证: P1回测前需先验证截面标准化是否改善区分度
    # P0修复: 支持两种score_stats来源
    #   1. zscore["score_stats"] (旧格式，兼容)
    #   2. score_stats 参数 (新格式，推荐)
    effective_score_stats = score_stats
    if not effective_score_stats and zscore and isinstance(zscore, dict):
        effective_score_stats = zscore.get("score_stats")

    if use_zscore and effective_score_stats:
        _mean = effective_score_stats.get("score_mean", 50)
        _std = effective_score_stats.get("score_std", 20)
        if _std > 0:
            _z = (score - _mean) / _std
            # Sigmoid映射到0-100
            _z_clipped = max(min(_z, 5), -5)  # 防止溢出
            # P0-2026-09-13: Sigmoid压缩导致区分度趋近0，改为线性映射保留spread
            # Sigmoid: z=±3 → 26/74 (spread=48pt), 但头部尾部压缩严重
            # 线性: z=±3 → 5/95 (spread=90pt), 分布均匀
            score = int(50 + _z_clipped * 25)
            score = max(0, min(100, score))
            sigs.append(f"📊 截面标准化(z={_z:.2f}→{score})")

    # ─── 最后修正：市场状态折扣 (2026-08-05 修正) ───
    # 原: 弱市×0.7/恐慌×0.5 — 回测实证弱市72.7%胜率是策略alpha来源,
    #     7折削弱区分度导致弱市Top1选择变差(72.7%→54.5%), 故弱市不打折
    # 恐慌(真崩盘)保留防御折扣
    if market_state and market_state == "恐慌":
        discount = 0.6
        score = int(score * discount)
        sigs.append(f"📉 市场恐慌×{discount}")
    # 2026-08-05 实证: 震荡市全RSI组5日负收益(无alpha) — 评分整体压缩, 降低震荡市选股积极性
    elif market_state == "震荡":
        score = int(score * 0.85)
        sigs.append("📊 震荡市×0.85")

    # 评分保留原始值(不再硬截断), 由调用方做截面归一化
    # 修复: 原max/min截断导致高分票全压到100, TOP5方差=0
    score = int(round(score))

    # P0修复(2026-09-23): 将raw_score写回inds供截面标准化使用
    # inds是参数，可以直接修改
    if inds is not None and isinstance(inds, dict):
        inds["raw_score"] = float(score)

    return score, sigs, None


def compute_cross_section_ranks(inds_list):
    """
    计算所有股票关键因子的截面百分位。

    Args:
        inds_list: [{code: str, inds: dict}, ...] 所有候选股票的 indicators

    Returns:
        {code: {因子名: 百分位0~1, ...}}  因子包括 chg5/vol_ratio/rsi14/pos_vs_ma20
    """
    import math

    # 收集每个因子的原始值
    # T-20260816-002 Option A: 加入 max_ret5 (MAX回避/彩票型, T2: IC=-0.173 强负向因子)
    # T-2026-08-20: 加入 vol_shrink20 (缩量企稳因子, IC=-0.056 通过门禁)
    factor_values = {
        "chg5": {}, "vol_ratio": {}, "rsi14": {}, "pos_vs_ma20": {},
        "max_ret5": {}, "vol_shrink20": {},
    }
    for item in inds_list:
        code = item["code"]
        inds = item["inds"]
        for f in factor_values:
            v = inds.get(f)
            if v is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
                if math.isfinite(v):
                    factor_values[f][code] = v

    # 计算百分位 (越小值 rank 越低, 百分位 = 排名/总数)
    ranks = {}
    for f, vals in factor_values.items():
        if not vals:
            continue
        sorted_codes = sorted(vals.keys(), key=lambda c: vals[c])
        n = len(sorted_codes)
        for i, code in enumerate(sorted_codes):
            pct = (i + 1) / n  # 0~1, 最小值为接近0, 最大值为接近1
            ranks.setdefault(code, {})[f] = pct

    return ranks


def build_cross_rank(code, cross_ranks):
    """
    从 compute_cross_section_ranks 的结果中取单只股票的 rank dict。
    缺失 code 返回空 dict, score_stock 自动走布尔逻辑。
    """
    return cross_ranks.get(code, {}) if cross_ranks else None


def compute_cross_section_zscores(inds_list):
    """
    计算所有股票关键因子的截面z-score标准化值。

    z-score = (value - mean) / std, 标准化后均值为0, 标准差为1
    相比百分位: 保留原始分布信息, 极端值区分度更高

    Args:
        inds_list: [{code: str, inds: dict}, ...] 所有候选股票的 indicators

    Returns:
        {code: {因子名: z-score float, ...}} + {"score_stats": {"score_mean": float, "score_std": float}}
    """
    import math

    factor_values = {
        "chg5": {}, "vol_ratio": {}, "rsi14": {}, "pos_vs_ma20": {},
        "max_ret5": {}, "vol_shrink20": {}, "chg20": {}, "std20": {},
        "unlocked_pressure": {},  # P0-2026-09-20: 新增截面z-score
    }
    raw_scores = {}  # P0修复: 收集raw_score用于计算score_stats
    for item in inds_list:
        code = item["code"]
        inds = item["inds"]
        for f in factor_values:
            v = inds.get(f)
            if v is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
                if math.isfinite(v):
                    factor_values[f][code] = v
        # P0修复: 收集raw_score
        if "raw_score" in inds:
            rs = inds["raw_score"]
            if isinstance(rs, (int, float)) and math.isfinite(rs):
                raw_scores[code] = rs

    zscores = {}
    for f, vals in factor_values.items():
        if len(vals) < 3:
            continue
        vlist = list(vals.values())
        mean_v = sum(vlist) / len(vlist)
        std_v = (sum((x - mean_v) ** 2 for x in vlist) / (len(vlist) - 1)) ** 0.5
        if std_v < 1e-10:
            continue  # 无区分度
        for code, v in vals.items():
            zscores.setdefault(code, {})[f] = (v - mean_v) / std_v

    # P0修复: 计算score_stats
    score_stats = None
    if len(raw_scores) >= 3:
        score_list = list(raw_scores.values())
        score_mean = sum(score_list) / len(score_list)
        score_std = (sum((x - score_mean) ** 2 for x in score_list) / (len(score_list) - 1)) ** 0.5
        if score_std > 1e-10:
            score_stats = {"score_mean": score_mean, "score_std": score_std}

    return {"zscores": zscores, "score_stats": score_stats}


def build_zscore(code, zscores_result):
    """从 compute_cross_section_zscores 结果取单只股票的 z-score dict。
    P0修复: 同时返回 score_stats 供调用方使用截面标准化。
    """
    if not zscores_result:
        return None
    # P0修复: 兼容新旧返回值格式
    # 旧格式: {code: {因子: z-score}}
    # 新格式: {"zscores": {code: {因子: z-score}}, "score_stats": {...}}
    if isinstance(zscores_result, dict) and "zscores" in zscores_result:
        zscores = zscores_result["zscores"]
        score_stats = zscores_result.get("score_stats")
    else:
        zscores = zscores_result
        score_stats = None

    # 返回单个股票的z-score字典（供score_stock使用）
    single_zscore = zscores.get(code, {}) if zscores else None

    # P0修复: 同时返回score_stats（供调用方做截面标准化）
    # 调用方示例：
    #   result = build_zscore(code, zscores_result)
    #   zscore = result["zscore"]  # {因子: z值}
    #   score_stats = result["score_stats"]  # {"score_mean": ..., "score_std": ...}
    return {
        "zscore": single_zscore,
        "score_stats": score_stats
    }


def calc_feature_contributions(inds, weekly=None, strategy=None):
    """
    计算每个评分维度对总分的贡献（用于特征重要性分析）。
    返回: {feature_name: score_contribution}
    """
    if not inds:
        return {}
    s = strategy or STRATEGIES["综合"]
    contribs = {}

    # 1. 均线
    ma_score = 0
    if inds["ma5"] and inds["ma10"] and inds["ma20"]:
        if inds["ma5"] > inds["ma10"] > inds["ma20"]:
            ma_score += s["ma_mlt"]
        elif inds["ma5"] > inds["ma10"]:
            ma_score += s["ma_mlt"] // 2
    if inds["ma60"] and inds["price"] > inds["ma60"]: ma_score += s["ma_above60"]
    if inds["ma120"] and inds["price"] > inds["ma120"]: ma_score += s["ma_above120"]
    contribs["均线"] = ma_score

    # 2. MACD
    macd_score = 0
    d, e, h = inds["dif"], inds["dea"], inds["macd_hist"]
    if d is not None and e is not None and h is not None:
        if d > e and h > 0:
            macd_score += s["macd_golden_red"]
        elif d > e:
            macd_score += s["macd_golden"]
        if d > 0: macd_score += s["macd_above0"]
    contribs["MACD"] = macd_score

    # 3. RSI
    rsi_score = 0
    if 45 <= inds["rsi14"] <= 75:
        rsi_score += s["rsi_strong"]
    elif 30 <= inds["rsi14"] < 45:
        rsi_score += s["rsi_weak"]
    if inds["rsi6"] > inds["rsi14"]: rsi_score += s["rsi_rising"]
    contribs["RSI"] = rsi_score

    # 4. KDJ
    kdj_score = 0
    if inds["kdj_k"] > inds["kdj_d"] and inds["kdj_j"] < 100:
        kdj_score += s["kdj_golden"]
    contribs["KDJ"] = kdj_score

    # 5. 成交量
    vol_score = 0
    vr = inds["vol_ratio"]
    if vr > 2.0: vol_score += s["vol_gt2"]
    elif vr > 1.5: vol_score += s["vol_gt1.5"]
    elif vr > 1.2: vol_score += s["vol_gt1.2"]
    contribs["成交量"] = vol_score

    # 6. 短期趋势
    trend_score = 0
    if inds["chg5"] > 8: trend_score += s["chg5_gt8"]
    elif inds["chg5"] > 3: trend_score += s["chg5_gt3"]
    if inds["chg5"] > inds["chg10"] and inds["chg5"] > 0: trend_score += s["chg5_accel"]
    contribs["短期趋势"] = trend_score

    # 7. 量价形态
    vp_score = 0
    vp = inds.get("vol_pattern")
    if vp in ("放量突破", "放量拉升"): vp_score += s["vol_breakout"]
    elif vp == "缩量回调": vp_score += s["vol_shrink"]
    elif vp == "放量下跌": vp_score += s["vol_dump"]
    contribs["量价形态"] = vp_score

    # 8. 周线
    wk_score = 0
    if weekly and weekly.get("w_bullish"): wk_score += s["weekly_bullish"]
    if weekly and weekly.get("w_hist") and weekly["w_hist"] > 0: wk_score += s["weekly_macd_red"]
    contribs["周线"] = wk_score

    # 9. 扣分
    penalty = 0
    if inds["pos_vs_ma20"] > 20: penalty += s["penalty_far"]
    if inds["kdj_j"] > 100: penalty += s["penalty_kdj_ob"]
    if inds.get("vol_pattern") == "放量下跌": penalty += s["penalty_vol_dump"]
    contribs["扣分"] = penalty

    # 10. 板块热度 (v4.2)
    contribs["板块热度"] = inds.get("industry_heat_bonus", 0)
    # 11. 资金流 (v4.2)
    contribs["资金流"] = inds.get("fund_flow_bonus", 0)

    return contribs


def calc_trailing_stop(records, trail_drawdown=0.08, atr_multiplier=2.0):
    if not records or len(records) < 5:
        return None
    c = [r["close"] for r in records]
    h = [r["high"] for r in records]
    l = [r["low"] for r in records]
    entry = c[-1]
    # P0-2026-08-23 老大拍板: 止损统一8%, 修正hardcode 7% → 读config
    from config_loader import load_contract
    contract = load_contract()
    stop_pct = contract.get("stop_loss_pct", 0.08)
    fixed = entry * (1 - stop_pct)
    atr_s, atr_v = calc_atr_stop(records, atr_multiplier)
    final = max(fixed, atr_s) if atr_s else fixed
    rh = max(h[-20:]) if len(h) >= 20 else max(h)
    rl = min(l[-20:]) if len(l) >= 20 else min(l)
    ts = rh * (1 - trail_drawdown)
    m10 = calc_sma(c, 10)
    sup = max(m10 or 0, rl * 0.98, final)
    return {
        "entry": entry, "stop_loss": round(final, 2),
        "fixed_stop": round(fixed, 2),
        "atr_stop": round(atr_s, 2) if atr_s else None,
        "atr": round(atr_v, 3) if atr_v else None,
        "support": round(sup, 2),
        "trailing_stop": round(max(ts, sup), 2),
        "tp1_5%": round(entry * 1.05, 2), "tp2_10%": round(entry * 1.10, 2),
        "tp3_15%": round(entry * 1.15, 2), "tp_final_20%": round(entry * 1.20, 2),
        "resistance": round(rh, 2),
    }


def format_stop_advice(ts, inds):
    if not ts:
        return "数据不足"
    entry, sl = ts["entry"], ts["stop_loss"]
    risk = (entry - sl) / entry * 100
    reward = (ts["tp3_15%"] - entry) / entry * 100
    ratio = reward / risk if risk > 0 else 0
    trend = "上升趋势"
    if inds and inds["ma10"] and inds["ma20"]:
        trend = "强势上升" if inds["ma10"] > inds["ma20"] else "弱势震荡"

    lines = [
        f"  📊 趋势判断: {trend}",
        f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"  💰 买入参考: {entry:.2f} (当前价)",
        f"  ───────────────────────────────────",
    ]
    if ts.get("atr"):
        lines.append(f"  📐 ATR(14): {ts['atr']} (波动率自适应)")
    if ts.get("atr_stop"):
        lines.append(f"  🛡️ ATR止损: {ts['atr_stop']:.2f}")
    lines += [
        f"  🛑 最终止损: {sl:.2f} ({abs(risk):.1f}%)",
        f"  📍 均线支撑: {ts['support']:.2f}",
        f"  🔄 移动止盈: {ts['trailing_stop']:.2f} (自高点回撤8%)",
        f"  ───────────────────────────────────",
        f"  🎯 目标: TP1(+5%)={ts['tp1_5%']:.2f} →减1/3",
        f"         TP2(+10%)={ts['tp2_10%']:.2f} →减1/3",
        f"         TP3(+15%)={ts['tp3_15%']:.2f} →持有",
        f"         TP4(+20%)={ts['tp_final_20%']:.2f} →全部止盈",
        f"  ───────────────────────────────────",
        f"  📈 风报比: 1:{ratio:.1f} | 止损{abs(risk):.1f}% 看{reward:.0f}%",
        f"  📊 压力位: {ts['resistance']:.2f}",
    ]
    if ratio >= 2:
        lines += [f"  ───────────────────────────────────",
                   f"  💡 建议: 风报比优良，可分批(50%)建仓"]
    elif ratio >= 1.5:
        lines += [f"  ───────────────────────────────────",
                   f"  💡 建议: 风报比尚可，轻仓(30%)参与"]
    else:
        lines += [f"  ───────────────────────────────────",
                   f"  💡 建议: 等待更好入场点，<20%试探"]
    return "\n".join(lines)


def compute_swing_analysis(inds, weekly, records):
    """波段深度分析 — 多维度评分 + 决策判断 + 风险提示

    统一接口，供 pick_stock() / swing_pick() 等共用。

    参数:
        inds: compute_indicators() 返回的指标字典
        weekly: compute_weekly_indicators() 返回的周线字典
        records: 原始日线数据列表

    返回 dict:
    {
        "daily_trend": int,       # 趋势方向分 (-2~2)
        "week_align": int,        # 日周同向 (0/1)
        "week_conflict": bool,    # 日周冲突
        "entry_score": int,       # 入场位置分 (-2~2)
        "rsi_score": int,         # RSI评分 (-1~1)
        "vol_score": int,         # 量价评分 (-2~1)
        "macd_score": int,        # MACD评分 (-1~1)
        "total_score": int,       # 综合得分
        "weekly_bearish": bool,   # 周线空头
        "decision": str,          # "买入"/"轻仓"/"观望"/"不适合"
        "decision_icon": str,     # ✅/⚠️/🔄/❌
        "trailing_stop": dict,    # calc_trailing_stop() 结果（或 None）
        "risk_pct": float,        # 亏损百分比
        "reward_pct": float,      # 目标盈利百分比
        "rr": float,              # 风报比
        "risks": [str],           # 风险提示列表
        "patterns": dict,         # v5.0 技术形态识别结果
    }
    """
    # 1. 趋势方向
    daily_trend = 0
    if inds["ma5"] and inds["ma10"] and inds["ma20"]:
        if inds["ma5"] > inds["ma10"] > inds["ma20"]:
            daily_trend = 2
        elif inds["ma5"] > inds["ma10"]:
            daily_trend = 1
        elif inds["ma5"] < inds["ma10"] < inds["ma20"]:
            daily_trend = -2

    # 2. 日周同向
    week_align = 1 if (weekly and weekly.get("w_bullish") and daily_trend > 0) else 0
    week_conflict = bool(weekly and not weekly.get("w_bullish") and daily_trend > 0)

    # 3. 入场位置
    p20 = inds["pos_vs_ma20"]
    if 0 < p20 < 10:
        entry_score = 2
    elif -3 < p20 <= 0:
        entry_score = 1
    elif p20 > 15:
        entry_score = -2
    elif p20 < -5:
        entry_score = -1
    else:
        entry_score = 0

    # 4. RSI
    rsi = inds["rsi14"]
    rsi_score = 1 if 40 <= rsi <= 65 else (0 if 65 < rsi <= 75 or (30 <= rsi < 40) else -1)

    # 5. 量价
    vp = inds.get("vol_pattern")
    vol_score = 1 if vp in ("放量突破", "放量拉升", "缩量回调") else (-2 if vp == "放量下跌" else 0)

    # 6. MACD
    macd_score = 0
    d, e, hh = inds["dif"], inds["dea"], inds["macd_hist"]
    if d is not None and e is not None and hh is not None:
        macd_score = 1 if d > e and hh > 0 else (-1 if d < e else 0)

    # v5.0: 技术形态识别
    patterns = {"found": False, "pattern": "", "score": 0, "desc": ""}
    try:
        from pattern_recognition import identify_all_patterns
        patterns = identify_all_patterns(records)
    except ImportError:
        pass
    pattern_bonus = patterns.get("score", 0) if patterns.get("found") else 0
    # 形态加分（最高+20，但以+5为加权上限避免喧宾夺主）
    pattern_weighted = min(pattern_bonus // 3, 5)

    # 综合得分（含形态加分）
    total_score = daily_trend + week_align - (1 if week_conflict else 0) + entry_score + rsi_score + vol_score + macd_score + pattern_weighted

    # 周线空头降档
    weekly_bearish = bool(weekly and not weekly.get("w_bullish"))
    if weekly_bearish and total_score >= 4:
        total_score = min(total_score, 3)

    # 止盈止损
    ts = calc_trailing_stop(records, atr_multiplier=2.0)
    price = inds["price"]
    if ts:
        risk_pct = (price - ts["stop_loss"]) / price * 100
        reward_pct = (ts["tp3_15%"] - price) / price * 100
        rr = reward_pct / risk_pct if risk_pct > 0 else 0
    else:
        risk_pct = reward_pct = rr = 0

    # 决策
    if total_score >= 4 and inds.get("score", 0) >= 60:
        decision, decision_icon = "买入", "✅"
    elif total_score >= 1:
        decision, decision_icon = "轻仓", "⚠️"
    elif total_score <= -2:
        decision, decision_icon = "不适合", "❌"
    else:
        decision, decision_icon = "观望", "🔄"

    # 风险提示
    risks = []
    if daily_trend < 2:
        risks.append("日线趋势未完全转多, 可能是反弹而非反转")
    if week_conflict:
        risks.append("周线偏弱, 日线上涨持续性存疑")
    if inds.get("ma10") and price > inds["ma10"] * 1.08:
        risks.append("股价高于MA10超8%, 短线乖离偏大")
    if rsi > 70:
        risks.append(f"RSI={rsi:.0f}偏高, 短线可能回调")
    if p20 > 15:
        risks.append(f"股价偏离20日线+{p20:.0f}%, 追高回撤风险大")
    if vol_score == -2:
        risks.append("放量下跌, 资金出逃信号")
    if rr < 2:
        risks.append("风报比不足")
    # v5.0: 形态风险提示
    if patterns.get("found"):
        risks.append(f"形态:{patterns['pattern']}(+{pattern_weighted})")
    else:
        risks.append("无明显技术形态支撑")

    return {
        "daily_trend": daily_trend,
        "week_align": week_align,
        "week_conflict": week_conflict,
        "entry_score": entry_score,
        "rsi_score": rsi_score,
        "vol_score": vol_score,
        "macd_score": macd_score,
        "total_score": total_score,
        "pattern_score": pattern_weighted,
        "pattern_info": patterns.get("desc", ""),
        "weekly_bearish": weekly_bearish,
        "decision": decision,
        "decision_icon": decision_icon,
        "trailing_stop": ts,
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "rr": rr,
        "risks": risks,
        "patterns": patterns,
    }


def analyze_market(scored_results=None):
    """
    分析当前市场行情，推荐最佳选股策略。
    scored_results: 可选，本次扫描的评分结果列表，用于判断市场宽度。

    返回 dict:
    {
        "market_state": str,       # 市场状态标签
        "recommended_strategy": str,  # 建议策略名
        "index_close": float,      # 上证收盘价
        "index_chg": float,        # 上证涨跌幅
        "index_trend": str,        # 上证趋势
        "index_rsi": float,        # 上证RSI
        "breadth": str,            # 市场宽度描述
        "reason": str,             # 推理说明
    }
    """
    # ── 1. 上证指数分析 ─────────────────
    sh_records = get_tdx_data("sh000001", 120)  # P1-12: 明确指数格式(原"000001"落空)
    result = {
        "market_state": "震荡",     # 默认震荡而非未知
        "recommended_strategy": "综合",
        "index_close": 0,
        "index_chg": 0,
        "index_trend": "未知",
        "index_rsi": 50,
        "breadth": "未知",
        "reason": "默认震荡市, 综合策略均衡配置",
    }

    # ── 降级方案：TDX无数据时用评分分布推断 ──
    if not sh_records or len(sh_records) < 30 or not compute_indicators(sh_records):
        if scored_results and len(scored_results) >= 50:  # 降低阈值: 100→50
            total = len(scored_results)
            high = sum(1 for item in scored_results if item[0] >= 60)
            low = sum(1 for item in scored_results if item[0] <= 20)
            high_ratio = high / total
            low_ratio = low / total
            if high_ratio > 0.25:
                result["market_state"] = "强"
                result["recommended_strategy"] = "综合"
                result["reason"] = f"市场宽度强势(>60分占{high_ratio*100:.0f}%), 综合策略配置"
            elif low_ratio > 0.5:
                result["market_state"] = "弱"
                result["recommended_strategy"] = "抄底"
                result["reason"] = f"市场宽度弱势(<20分占{low_ratio*100:.0f}%), 抄底策略小仓位"
            else:
                result["market_state"] = "震荡"
                result["reason"] = f"市场宽度分化(高{high}中{total-high-low}低{low}), 综合策略均衡配置"
            result["breadth"] = f"强势>{high_ratio*100:.0f}%/弱势>{low_ratio*100:.0f}%"
        return result

    sh_inds = compute_indicators(sh_records)

    sh_close = sh_inds["price"]
    sh_chg = sh_inds["chg1"]
    sh_rsi = sh_inds["rsi14"]
    sh_ma5 = sh_inds["ma5"]
    sh_ma10 = sh_inds["ma10"]
    sh_ma20 = sh_inds["ma20"]
    sh_ma60 = sh_inds["ma60"]
    sh_dif = sh_inds["dif"]
    sh_dea = sh_inds["dea"]
    sh_macd_hist = sh_inds["macd_hist"]
    sh_pos20 = sh_inds["pos_vs_ma20"]
    sh_vol_ratio = sh_inds["vol_ratio"]

    # ── 2. 指数趋势判定 ────────────────
    # 均线形态
    ma_bullish = bool(sh_ma5 and sh_ma10 and sh_ma20 and sh_ma5 > sh_ma10 > sh_ma20)
    ma_bearish = bool(sh_ma5 and sh_ma10 and sh_ma20 and sh_ma5 < sh_ma10 < sh_ma20)
    above_ma60 = bool(sh_ma60 and sh_close > sh_ma60)
    far_above = sh_pos20 > 15 if sh_pos20 else False
    far_below = sh_pos20 < -10 if sh_pos20 else False

    # MACD
    macd_bullish = bool(sh_dif and sh_dea and sh_dif > sh_dea and sh_macd_hist and sh_macd_hist > 0)
    macd_bearish = bool(sh_dif and sh_dea and sh_dif < sh_dea)

    # 量能
    heavy_volume = sh_vol_ratio > 1.8 if sh_vol_ratio else False
    low_volume = sh_vol_ratio < 0.6 if sh_vol_ratio else False

    # ── 3. 市场宽度（从评分结果推断） ──
    breadth_desc = "未知"
    high_score_ratio = 0  # 评分>60的比例
    low_score_ratio = 0   # 评分<30的比例
    if scored_results and len(scored_results) > 100:
        total = len(scored_results)
        high = sum(1 for item in scored_results if item[0] >= 60)
        low = sum(1 for item in scored_results if item[0] <= 20)
        mid = total - high - low
        high_score_ratio = high / total
        low_score_ratio = low / total
        if high_score_ratio > 0.3:
            breadth_desc = f"强势(>60分占{high_score_ratio*100:.0f}%)"
        elif low_score_ratio > 0.4:
            breadth_desc = f"弱势(<20分占{low_score_ratio*100:.0f}%)"
        else:
            breadth_desc = f"分化(高{high}中{mid}低{low})"

    # ── 4. 综合判定市场状态 ────────────
    # 牛市: 多头排列 + 站上MA60 + MACD金叉
    if ma_bullish and above_ma60 and macd_bullish and not far_above:
        market_state = "牛"
        rec = "趋势"
        reason = f"上证均线多头+MACD金叉+站上MA60, 趋势行情首选趋势策略跟踪主升浪"

    # 强势震荡: 站上MA60, MACD偏多, 但均线未完美多头
    elif above_ma60 and (macd_bullish or sh_rsi > 55) and not far_above:
        market_state = "强"
        rec = "综合"
        reason = f"上证偏强震荡, 均衡配置用综合策略, 关注突破信号可切换突破策略"

    # 突破前夜: 缩量回调后放量, MACD即将金叉, RSI中性
    elif heavy_volume and sh_rsi and 40 <= sh_rsi <= 60 and not ma_bullish:
        market_state = "突破"
        rec = "突破"
        reason = f"上证放量+RSI中性, 变盘信号明显, 突破策略捕捉爆发点"

    # 超卖/恐慌: 远离MA20, RSI低, 量缩
    elif far_below and sh_rsi and sh_rsi < 35:
        market_state = "恐慌"
        rec = "抄底"
        reason = f"上证超卖(RSI{sh_rsi:.0f})+远离均线, 恐慌后往往反弹, 抄底策略捕捉超跌机会"

    # 弱市: 均线空头/低于MA60
    elif ma_bearish or (sh_ma60 and sh_close < sh_ma60):
        market_state = "弱"
        rec = "抄底"
        if sh_rsi and sh_rsi < 40:
            reason = f"上证偏弱但RSI已低({sh_rsi:.0f}), 超跌反弹机会用抄底策略"
        else:
            reason = f"上证趋势偏弱, 建议轻仓观望或抄底策略小仓位试错"

    # 中性震荡: 其余情况
    else:
        market_state = "震荡"
        rec = "综合"
        reason = f"上证无明显方向, 综合策略均衡配置, 等待趋势明朗"

    result = {
        "market_state": market_state,
        "recommended_strategy": rec,
        "index_close": round(sh_close, 2),
        "index_chg": round(sh_chg, 2),
        "index_trend": "多头" if ma_bullish else ("空头" if ma_bearish else "震荡"),
        "index_rsi": round(sh_rsi, 0),
        "macd": f"{'金叉' if macd_bullish else '死叉' if macd_bearish else '中性'}",
        "breadth": breadth_desc,
        "pos_vs_ma20": round(sh_pos20, 1),
        "vol_ratio": round(sh_vol_ratio, 1),
        "reason": reason,
        # 市场状态仓位建议（联网搜索验证优化）
        "max_position": _get_position_limit(market_state),
        "stop_loss_pct": _get_stop_loss_pct(market_state),
        "target_pct": _get_target_pct(market_state),
        "strategies": {
            "综合": {"suit": "中", "note": "震荡市通用"},
            "趋势": {"suit": "高" if rec == "趋势" else ("低" if market_state in ("恐慌","弱") else "中"), "note": "单边行情"},
            "突破": {"suit": "高" if rec == "突破" else "中", "note": "变盘信号时"},
            "抄底": {"suit": "高" if rec == "抄底" else "低", "note": "超卖/恐慌后"},
        }
    }
    return result


def _get_position_limit(market_state):
    """仓位上限: 铁律全仓1只，不按市场状态调整(2026-08-11 老大决策)"""
    return 100


def _get_stop_loss_pct(market_state):
    """止损幅度: risk_rules 统一8%，不按市场状态调整"""
    return 8


def _get_target_pct(market_state):
    """根据市场状态返回建议目标收益"""
    return {
        "牛": 25, "强": 20, "突破": 15,
        "震荡": 15, "弱": 10, "恐慌": 0,
    }.get(market_state, 15)
# P0-2026-09-12: 已淘汰因子标记
# alpha13: IC=-0.0169 (2026年失效，原IC=+0.0341)
# alpha16_fix: IC=-0.0147 (2026年失效，原IC=+0.0556)
# 根因: 市场regime翻转，协方差类因子失效，动量因子崛起
# 状态: 已注释掉评分逻辑，等待新因子替代

