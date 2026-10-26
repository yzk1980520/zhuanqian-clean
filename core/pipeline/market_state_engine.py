import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
market_state_engine.py — 市场状态量化引擎 v1.0
==============================================
多维度连续评分系统，替代简单的强/震荡/弱三态。

评分维度 (0-100):
  趋势维度:   大盘均线系统 + 指数动量 (权重30%)
  赚钱效应:   涨跌家数比 + 涨停跌停比 (权重25%)  
  量能维度:   成交额趋势 + 量比 (权重20%)
  资金维度:   主力资金净流入/akshare (权重15%, 2026-08-13北向停发后换源)
  板块维度:   热点持续性 + 板块轮动 (权重10%)

输出:
  - market_score: 0-100 连续值
  - market_label: 恐慌/弱/震荡/偏暖/强/极强
  - strategy_weights: {strategy_name: weight, ...}
  - position_advice: 仓位建议
  - sub_scores: 各维度详细评分
"""

import os, json, time
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

PROJECT = PROJECT_ROOT

# P0-1修复: 写JSON统一走原子写, 防cron并发覆盖
# 2026-09-25 修复 (体检P1-12): 原兜底分支引用未导入的 atomic_json → NameError 被吞,
# 缓存可能从未写入且无告警。改为 sys.path 兜底后重试, 仍失败才降级为普通写并告警。
try:
    from core.pipeline.atomic_json import atomic_dump
except Exception:
    atomic_dump = None
    import sys as _sys
    _sys.path.insert(0, PROJECT)
    try:
        from core.pipeline.atomic_json import atomic_dump
    except Exception as _e:
        print("⚠️ atomic_json 导入失败, 缓存将退化为普通json写: %s" % _e, file=_sys.stderr)
        atomic_dump = None

# ── 市场区间划分 ──
MARKET_ZONES = [
    (0, 15, "恐慌", "❌ 系统性风险，减仓或空仓"),
    (15, 35, "弱", "⚠️ 弱势市场，防御为主"),
    (35, 55, "震荡", "📊 中性震荡，精选个股"),
    (55, 75, "偏暖", "📈 回暖行情，适度进攻"),
    (75, 90, "强", "🔥 强势市场，积极做多"),
    (90, 100, "极强", "🚀 极端亢奋，警惕见顶"),
]

# ── 策略-市场匹配矩阵 ──
# 每个策略在每种市场评分区间的推荐权重
# 权重和为1，表示该市场区间下的策略配置
STRATEGY_WEIGHT_MATRIX = {
    "恐慌": {
        "抄底": 0.50,    # 抄底博反弹
        "北向精选": 0.20, # 北向逆势加仓
        "综合": 0.15,    # 综合防御
        "断层": 0.10,    # 业绩确定性
        "趋势": 0.05,
        "突破": 0.00,
        "全仓": 0.00,
    },
    "弱": {
        "抄底": 0.30,
        "北向精选": 0.25,
        "综合": 0.20,
        "断层": 0.15,
        "趋势": 0.05,
        "突破": 0.05,
        "全仓": 0.00,
    },
    "震荡": {
        "趋势": 0.25,    # 震荡市趋势最优(胜率58.6%超收益+2.36%)
        "断层": 0.20,    # 次选断层精选
        "北向精选": 0.15,
        "突破": 0.15,
        "综合": 0.10,
        "全仓": 0.10,
        "抄底": 0.05,
    },
    "偏暖": {
        # P1-9修复(2026-08-08): 偏暖(55-75)权重中性化 — 独立于"强"的进攻配置
        # 原配置(趋势0.20+断层0.20+突破0.20=60%进攻)系统性偏差:
        #   回测证明"强"市胜率38.9%最差, "震荡"市趋势58.6%最优
        #   偏暖介于两者之间 → 应均衡配置而非进攻配置
        "趋势": 0.20,    # 保留: 震荡市证明有效(58.6%胜率)
        "断层": 0.20,    # 保留: 事件驱动
        "北向精选": 0.15, # 升: 防御性聪明钱
        "综合": 0.15,    # 升: 均衡分散
        "突破": 0.10,    # 降: 突破是强市专属
        "全仓": 0.10,    # 降: 不重仓押注
        "抄底": 0.10,    # 升: 防御性
    },
    "强": {
        "全仓": 0.25,    # 强势全仓出击
        "突破": 0.20,
        "断层": 0.20,
        "趋势": 0.15,
        "北向精选": 0.10,
        "综合": 0.10,
        "抄底": 0.00,
    },
    "极强": {
        "全仓": 0.20,
        "突破": 0.15,
        "趋势": 0.15,
        "断层": 0.15,
        "综合": 0.15,
        "北向精选": 0.10,
        "抄底": 0.10,    # 极强也可能跳水
    },
}

# ── 仓位建议 ──
# v8.2 强市降仓位 (Kimi框架审查): 回测强市胜率38.9%<弱市55.1%, 强市不该高仓位
# 55-70(偏暖/强): 0.80→0.65; 70-85(牛): 保持0.90 (牛市58.6%胜率最高可进攻)
POSITION_MAP = [
    (0, 15, 0.10, "空仓观望"),
    (15, 30, 0.30, "轻仓防御"),
    (30, 45, 0.50, "半仓防守"),
    (45, 55, 0.65, "中等仓位"),
    (55, 70, 0.65, "较重仓位"),
    (70, 85, 0.90, "重仓进攻"),
    (85, 100, 0.95, "满仓(警惕)"),
]


def get_market_zone(score):
    """根据评分返回市场区间"""
    for lo, hi, label, desc in MARKET_ZONES:
        if lo <= score < hi:
            return label, desc
    return "震荡", "默认"


def get_position_advice(score):
    """根据评分返回仓位建议
    2026-09-17 老大拍板: 环境门已取消，仓位建议不再受门状态影响。
    本函数仅为状态引擎内部使用，统一返回全仓。
    注意：apply_gate_enforcement 已删除门闭 cap 逻辑（T2 2026-09-29 清理）。
    """
    return 1.0, "全仓1只"


def apply_gate_enforcement(result):
    """门禁强制执行：读 daily_signal.json，环境门已取消（T2 2026-09-29）。
    P0 fix 2026-09-02 — AGENTS.md §七优先级链：daily_signal > market_state_cache。
    2026-09-17 老大拍板取消环境门后，本函数仅作日志记录，不覆盖 position_ratio。
    """
    ds_path = os.path.join(PROJECT, "data", "daily_signal.json")
    try:
        if not os.path.exists(ds_path):
            result.setdefault("reason", []).append("门禁未覆盖: daily_signal.json 不存在")
            return result
        ds = json.load(open(ds_path, encoding="utf-8"))
    except Exception as e:
        result.setdefault("reason", []).append(f"门禁读取失败: {e}")
        return result
    # ── 环境门已取消 (2026-09-17 老大拍板): 不再cap position_ratio ──
    # 仅保留gate状态读取，供前端展示和日志记录，不影响出票逻辑
    _gd = ds.get("gate_detail", {}) if isinstance(ds.get("gate_detail"), dict) else {}
    _gate_open = _gd.get("gate_open")
    if _gate_open is None:
        _gate_open = (ds.get("gate") in ("开", "open"))
    # 环境门仅作提示，不降级仓位建议 (全仓1只为主旨)
    return result


def get_strategy_weights(score):
    """根据市场评分返回各策略的推荐权重"""
    zone, _ = get_market_zone(score)
    weights = STRATEGY_WEIGHT_MATRIX.get(zone, STRATEGY_WEIGHT_MATRIX["震荡"])
    
    # 在边界区域做线性平滑插值，防止权重突变
    # 例如 score=36（弱边界）和 score=34（震荡边界）不应差异太大
    zones_bounds = [(0, "恐慌"), (15, "弱"), (35, "震荡"), (55, "偏暖"), (75, "强"), (90, "极强")]
    
    # 找到当前区间和相邻区间
    current_idx = None
    for i, (bound, name) in enumerate(zones_bounds):
        if bound <= score:
            current_idx = i
    
    if current_idx is None or current_idx <= 0:
        return weights  # 在底部区间，不需要插值
    
    current_bound, current_zone = zones_bounds[current_idx]
    prev_bound, prev_zone = zones_bounds[current_idx - 1]
    
    # 计算在区间内的位置比例
    if current_bound <= prev_bound:  # 边界配置非法时直接返回当前权重
        return weights
    zone_width = current_bound - prev_bound
    zone_pos = (score - prev_bound) / zone_width  # 0=靠近上一区间, 1=靠近下一区间
    zone_pos = max(0, min(1, zone_pos))
    
    # 如果在区间中间（0.2~0.8之间），不需要插值
    if 0.2 < zone_pos < 0.8:
        return weights
    
    # 靠近边界时做线性插值
    current_weights = STRATEGY_WEIGHT_MATRIX.get(current_zone, {})
    prev_weights = STRATEGY_WEIGHT_MATRIX.get(prev_zone, {})
    
    if not current_weights or not prev_weights:
        return weights
    
    # 获取所有策略的并集
    all_strategies = set(list(current_weights.keys()) + list(prev_weights.keys()))
    
    # 边界混合系数
    if zone_pos <= 0.2:
        # 靠近上一区间：75%上一区间 + 25%当前区间
        blend = {s: prev_weights.get(s, 0) * 0.75 + current_weights.get(s, 0) * 0.25 
                 for s in all_strategies}
    else:  # zone_pos >= 0.8
        # 靠近当前区间：25%上一区间 + 75%当前区间
        blend = {s: prev_weights.get(s, 0) * 0.25 + current_weights.get(s, 0) * 0.75
                 for s in all_strategies}
    
    # 归一化
    total = sum(blend.values())
    if total > 0:
        blend = {k: v/total for k, v in blend.items()}
    
    return blend


# ═══════════════════════════════════════════
#  多维度市场评分
# ═══════════════════════════════════════════

def score_trend_dimension():
    """
    趋势维度评分 (权重30%)
    
    因子:
      - 上证5日均线斜率
      - 指数价格相对20/60日线位置
      - 短期动量 (5日涨跌幅)
    
    返回: 0-100 分
    """
    score = 50  # 默认中性
    signals = []
    
    try:
        from core.pipeline.tdx_core import get_tdx_data, compute_indicators
        
        # 上证指数
        sh_recs = get_tdx_data("sh000001", 80)
        if sh_recs and len(sh_recs) > 60:
            inds = compute_indicators(sh_recs)
            if inds:
                price = inds.get("price", 0)
                ma20 = inds.get("ma20", 0)
                ma60 = inds.get("ma60", 0)
                chg5 = inds.get("chg5", 0)
                chg20 = inds.get("chg20", 0)
                
                # 对20日线的位置
                if price and ma20:
                    pos_vs_ma20 = (price / ma20 - 1) * 100
                    if pos_vs_ma20 > 5:
                        score += 20
                        signals.append(f"上证MA20上{pos_vs_ma20:.1f}%")
                    elif pos_vs_ma20 > 2:
                        score += 10
                    elif pos_vs_ma20 < -5:
                        score -= 20
                        signals.append(f"上证MA20下{abs(pos_vs_ma20):.1f}%")
                    elif pos_vs_ma20 < -2:
                        score -= 10
                
                # 对60日线的位置（长期趋势）
                if price and ma60:
                    pos_vs_ma60 = (price / ma60 - 1) * 100
                    if pos_vs_ma60 > 3:
                        score += 10
                    elif pos_vs_ma60 < -3:
                        score -= 10
                        signals.append(f"上证MA60下{abs(pos_vs_ma60):.1f}%")
                
                # 短期动量
                if chg5 > 3:
                    score += 15
                    signals.append(f"5日涨{chg5:.1f}%")
                elif chg5 > 1:
                    score += 5
                elif chg5 < -3:
                    score -= 15
                    signals.append(f"5日跌{chg5:.1f}%")
                elif chg5 < -1:
                    score -= 5
                
                # 中期动量
                if chg20 > 8:
                    score += 10
                    signals.append(f"20日涨{chg20:.1f}%")
                elif chg20 < -8:
                    score -= 10
                    signals.append(f"20日跌{chg20:.1f}%")
                
                # 均线多头排列（最强信号）
                if inds.get("ma5") and inds.get("ma10") and inds.get("ma20"):
                    if inds["ma5"] > inds["ma10"] > inds["ma20"]:
                        score += 10
                        signals.append("上证均线多头")
                        
    except Exception as e:
        signals.append(f"趋势维异常:{e}")
    
    score = max(0, min(100, score))
    return score, signals


def score_money_effect_dimension():
    """
    赚钱效应维度评分 (权重25%)
    
    因子:
      - 涨跌家数比
      - 涨停跌停比
      - 市场宽度
    
    返回: 0-100 分
    """
    score = 50
    signals = []
    
    try:
        from core.pipeline.tdx_core import get_tdx_data
        
        # 用深证成指作为参考
        sz_recs = get_tdx_data("sz399001", 30)
        if sz_recs and len(sz_recs) > 5:
            prices = [r["close"] for r in sz_recs[-5:]]
            highs = [r["high"] for r in sz_recs[-5:]]
            lows = [r["low"] for r in sz_recs[-5:]]
            
            chg5 = (prices[-1] / prices[0] - 1) * 100
            
            # 波动率（赚钱效应重要指标）
            if highs[-1] and lows[-1]:
                daily_range = (highs[-1] - lows[-1]) / lows[-1] * 100
                if daily_range > 3:
                    score -= 5  # 波动大说明分歧大
                    signals.append(f"振幅{daily_range:.1f}%")
            
            if chg5 > 2:
                score += 15
                signals.append(f"深证5日涨{chg5:.1f}%")
            elif chg5 < -2:
                score -= 15
                signals.append(f"深证5日跌{chg5:.1f}%")
        
        # 创业板参考
        cy_recs = get_tdx_data("sz399006", 20)
        if cy_recs and len(cy_recs) > 5:
            cy_high = max(r["close"] for r in cy_recs[-5:])
            cy_low = min(r["close"] for r in cy_recs[-5:])
            if cy_low > 0:
                cy_chg5 = (cy_high / cy_low - 1) * 100
                if cy_chg5 > 5:
                    score += 10
                    signals.append("创业板活跃")
                elif cy_chg5 < 2:
                    score -= 5
                    signals.append("创业板低迷")
        
    except Exception as e:
        signals.append(f"赚钱效应异常:{e}")
    
    score = max(0, min(100, score))
    return score, signals


def score_volume_dimension():
    """
    量能维度评分 (权重20%)
    
    因子:
      - 成交额趋势（相对20日均量）
      - 量能持续性
    
    返回: 0-100 分
    """
    score = 50
    signals = []
    
    try:
        from core.pipeline.tdx_core import get_tdx_data
        
        sh_recs = get_tdx_data("sh000001", 30)
        if sh_recs and len(sh_recs) > 20:
            recent_vols = [r["volume"] for r in sh_recs[-5:]]
            older_vols = [r["volume"] for r in sh_recs[-21:-5]]
            
            avg_recent = sum(recent_vols) / len(recent_vols) if recent_vols else 1
            avg_older = sum(older_vols) / len(older_vols) if older_vols else 1
            
            if avg_older > 0:
                vol_ratio = avg_recent / avg_older
                if vol_ratio > 1.3:
                    score += 20
                    signals.append(f"放量{vol_ratio:.1f}倍")
                elif vol_ratio > 1.1:
                    score += 8
                elif vol_ratio < 0.7:
                    score -= 20
                    signals.append(f"缩量{vol_ratio:.1f}倍")
                elif vol_ratio < 0.9:
                    score -= 8
                    signals.append(f"缩量至{vol_ratio:.1f}")
                
                # 量能趋势（最近5日成交量是否递增）
                if len(recent_vols) >= 3:
                    vol_trend = recent_vols[-1] / recent_vols[0]
                    if vol_trend > 1.1:
                        score += 5
                        signals.append("量能递增")
                    elif vol_trend < 0.9:
                        score -= 5
                        signals.append("量能递减")
        
    except Exception as e:
        signals.append(f"量能异常:{e}")
    
    score = max(0, min(100, score))
    return score, signals


def score_capital_dimension():
    """资金维度评分 (权重15%) — 2026-08-13改用主力净流入(akshare), 替代停发的北向
    规格: 净流入为正占比 up_ratio>0.6 → +15; <0.4 → -15; 失败→50中性
    """
    score = 50
    signals = []
    try:
        import akshare as ak
        df = None
        for _attempt in range(2):  # 重试1次 (瞬时限流常见, 与integrated_picker口径一致)
            try:
                df = ak.stock_fund_flow_individual(symbol="即时")
                break
            except Exception:
                continue
        if df is None or len(df) == 0:
            raise RuntimeError("akshare 资金流获取失败")
        # 净额列转数值(可能有'亿'/'万'单位)
        def _to_float(v):
            try:
                s = str(v).strip()
                if not s:
                    return None
                factor = 1.0
                if s.endswith("亿"):
                    s, factor = s[:-1], 1e8
                elif s.endswith("万"):
                    s, factor = s[:-1], 1e4
                return float(s) * factor
            except Exception:
                return None
        up_count = 0
        total = 0
        for _v in df["净额"].map(_to_float):
            if _v is None:
                continue
            total += 1
            if _v > 0:
                up_count += 1
        if total > 0:
            up_ratio = up_count / total
            if up_ratio > 0.6:
                score += 15
            elif up_ratio < 0.4:
                score -= 15
            signals.append(f"主力净流入{up_count}只/{total}只")
    except Exception:
        # akshare 异常/超时 → 保持50中性, 不报错
        signals.append("资金数据获取失败,中性")
    score = max(0, min(100, score))
    return score, signals


def score_sector_dimension():
    """
    板块维度评分 (权重10%)
    
    因子:
      - 热点板块数量
      - 板块轮动速度
      - 涨停家数
    
    返回: 0-100 分
    """
    score = 50
    signals = []
    
    try:
        # 从industry_heat.json读取板块热度
        heat_file = os.path.join(PROJECT, "data", "industry_heat.json")
        if os.path.exists(heat_file):
            data = json.load(open(heat_file, encoding="utf-8"))
            sectors = data.get("data", {})
            valid = {k: v for k, v in sectors.items()
                     if isinstance(v, dict) and "change_pct" in v}
            
            if valid:
                # 上涨板块比例
                up_sectors = sum(1 for v in valid.values() if v.get("change_pct", 0) > 0)
                total_sectors = len(valid)
                up_ratio = up_sectors / total_sectors if total_sectors > 0 else 0.5
                
                if up_ratio > 0.7:
                    score += 15
                    signals.append(f"普涨{up_ratio:.0%}")
                elif up_ratio > 0.5:
                    score += 5
                elif up_ratio < 0.3:
                    score -= 15
                    signals.append(f"普跌{1-up_ratio:.0%}")
                elif up_ratio < 0.4:
                    score -= 5
                
                # 最强板块涨幅
                top_chg = max(v.get("change_pct", 0) for v in valid.values())
                if top_chg > 4:
                    score += 5
                    signals.append(f"最强板块+{top_chg:.1f}%")
                
    except Exception:
        pass
    
    score = max(0, min(100, score))
    return score, signals


# ═══════════════════════════════════════════
#  综合评分
# ═══════════════════════════════════════════

# 各维度权重
DIMENSION_WEIGHTS = {
    "趋势": 0.30,
    "赚钱效应": 0.25,
    "量能": 0.20,
    "资金": 0.15,
    "板块": 0.10,
}


def assess_market_full(use_cache=True, cache_ttl=300):
    """
    综合市场评分 — 五个维度加权。
    
    返回:
        {
            "market_score": 0-100,
            "market_label": str,
            "description": str,
            "sub_scores": {维度名: {score, signals}},
            "strategy_weights": {策略名: 权重},
            "position_ratio": 0-1,
            "position_advice": str,
            "primary_strategy": str,
            "timestamp": str,
        }
    """
    cache_file = os.path.join(PROJECT, "data", "market_state_cache.json")
    
    # 检查缓存
    if use_cache and os.path.exists(cache_file):
        try:
            cached = json.load(open(cache_file, encoding="utf-8"))
            if time.time() - cached.get("timestamp", 0) < cache_ttl:
                return cached.get("result", {})
        except Exception:
            pass
    
    # 各维度独立评分
    trend_score, trend_sigs = score_trend_dimension()
    money_score, money_sigs = score_money_effect_dimension()
    vol_score, vol_sigs = score_volume_dimension()
    cap_score, cap_sigs = score_capital_dimension()
    sector_score, sector_sigs = score_sector_dimension()
    
    # 加权总分
    market_score = (
        trend_score * DIMENSION_WEIGHTS["趋势"] +
        money_score * DIMENSION_WEIGHTS["赚钱效应"] +
        vol_score * DIMENSION_WEIGHTS["量能"] +
        cap_score * DIMENSION_WEIGHTS["资金"] +
        sector_score * DIMENSION_WEIGHTS["板块"]
    )
    market_score = int(round(max(0, min(100, market_score))))
    
    # 市场区间
    zone_label, zone_desc = get_market_zone(market_score)
    
    # 策略权重
    strategy_weights = get_strategy_weights(market_score)
    
    # 主策略 = 权重最大的
    primary = max(strategy_weights, key=strategy_weights.get)
    
    # 仓位建议
    pos_ratio, pos_advice = get_position_advice(market_score)
    
    # 子维度详情
    sub_scores = {
        "趋势": {"score": trend_score, "signals": trend_sigs[:3]},
        "赚钱效应": {"score": money_score, "signals": money_sigs[:3]},
        "量能": {"score": vol_score, "signals": vol_sigs[:3]},
        "资金": {"score": cap_score, "signals": cap_sigs[:3]},
        "板块": {"score": sector_score, "signals": sector_sigs[:3]},
    }
    
    result = {
        "market_score": market_score,
        "market_label": zone_label,
        "description": zone_desc,
        "sub_scores": sub_scores,
        "strategy_weights": strategy_weights,
        "position_ratio": pos_ratio,
        "position_advice": pos_advice,
        "primary_strategy": primary,
        "timestamp": time.time(),
    }
    
    # 门禁强制执行（P0 fix 2026-09-02）
    # 2026-09-25: 环境门已于 2026-09-17 老大拍板取消 (CONTEXT.md) — 停用门闭仓位覆盖,
    # 保留函数供审计回溯 (体检P1-4: 残留生效与拍板冲突)
    # apply_gate_enforcement(result)

    # 缓存 — P0-1修复: 改为原子写
    try:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        cache_data = {"timestamp": time.time(), "result": result}
        if atomic_dump is not None:
            atomic_dump(cache_data, cache_file, ensure_ascii=False, indent=2)
        else:
            with open(cache_file, "w", encoding="utf-8") as _f:
                json.dump(cache_data, _f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    
    return result


def get_market_report():
    """生成可读的市场报告"""
    m = assess_market_full()
    
    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "market": {
            "score": m["market_score"],
            "label": m["market_label"],
            "desc": m["description"],
        },
        "dimensions": m["sub_scores"],
        "strategy": {
            "primary": m["primary_strategy"],
            "weights": m["strategy_weights"],
        },
        "position": {
            "ratio": m["position_ratio"],
            "advice": m["position_advice"],
        },
    }


def get_fresh_market_state(cache_ttl=300):
    """市场状态统一出口 (2026-08-13 方向4: 单源化)
    所有消费方(risk_monitor/position_tracker等)用它替代直接读 market_state_cache.json —
    内部走 assess_market_full 的 TTL 校验, 缓存过期自动重算, 杜绝各模块各自判断freshness导致口径不一致。
    """
    return assess_market_full(use_cache=True, cache_ttl=cache_ttl)


# ═══════════════════════════════════════════
#  独立运行测试
# ═══════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 68)
    print("  📊 市场状态量化引擎 v1.0 — 多维度评分")
    print("=" * 68)
    
    m = assess_market_full(use_cache=False)
    
    print("\n  🏆 综合评分: %d/100 — %s" % (m["market_score"], m["market_label"]))
    print("  📝 %s" % m["description"])
    
    print("\n  📈 维度评分:")
    for dim, info in m["sub_scores"].items():
        sigs = " | ".join(info["signals"]) if info["signals"] else "中性"
        print("    %-8s: %3d分  (%s)" % (dim, info["score"], sigs))
    
    print("\n  🎯 推荐策略权重:")
    sorted_weights = sorted(m["strategy_weights"].items(), key=lambda x: -x[1])
    max_name_len = max(len(name) for name, _ in sorted_weights)
    for name, weight in sorted_weights:
        bar = "█" * int(weight * 30)
        star = " ← 主策略" if name == m["primary_strategy"] else ""
        print("    %-*s: %5.1f%% %s%s" % (max_name_len, name, weight * 100, bar, star))
    
    print("\n  💼 仓位建议: %s (%.0f%%)" % (m["position_advice"], m["position_ratio"] * 100))
    print("\n" + "=" * 68)
