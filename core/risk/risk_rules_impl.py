import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from datetime import date, timedelta
import json, os

"""
risk_rules.py — P0风控红线模块（向后兼容层）
=========================================

【架构说明】
本文件作为新旧接口的桥梁：
1. 保留所有旧全局常量（CHASE_BAN_PCT, TIME_STOP_TRADING_DAYS等）
2. 保留所有旧函数签名（calculate_stop_loss, evaluate_exit等）
3. 内部委托给新的RiskEngine深度模块

【新架构】
- risk_rules_config.py: RiskConfig数据类（依赖注入）
- risk_rules_adapter.py: MarketStateAdapter接口+Mock实现
- risk_rules_engine.py: RiskEngine深度模块（小接口+大实现）

【调用方式】
# 旧接口（无需修改）
sl = calculate_stop_loss(100.0, "全仓", "强")

# 新接口（推荐）
engine = RiskEngine(config=RiskConfig(), market_state=MockMarketState(regime="强"))
decision = engine.evaluate_exit(position, current_price)
"""

# ========== 导入新架构 ==========
from core.risk.risk_rules_config import RiskConfig
from core.risk.risk_rules_adapter import MarketStateAdapter, MockMarketState
from core.risk.risk_rules_engine import RiskEngine, Position, ExitDecision

# ═══════════════════════════════════════════
#  止损规则
# ═══════════════════════════════════════════

# 各策略默认止损幅度 (基于入场价)
# 2026-08-20 老大拍板: 统一 8% (P17 2026-08-19 回测最优组合: 宽松A止盈8/12/18/25 + 宽松止损-8%,
# 胜率34.4%+7.1pp 均收益+0.70%+3.0pp; 原6%为 2026-08-16 P0-2 旧口径, 已被 P17 实证推翻)
# 2026-09-30 三方会签: S3主候选通过，止损8%→10%原子变更（R0+R1双重）
STRATEGY_STOP_LOSS_PCT = {
    "全仓": 0.10,     # 全仓单只:10%硬止损 (S3三方会签确认)
    "突破": 0.10,     # 突破追涨:10%
    "断层": 0.10,     # 净利润断层:10%
    "北向精选": 0.10, # 北向聪明钱:10%
    "趋势": 0.10,     # 趋势跟踪:10%
    "抄底": 0.10,     # 抄底反弹:10%
    "综合": 0.10,     # 综合均衡:10%
}

# 基于市场状态的止损调整（宽基市场差 → 收窄止损）
MARKET_STOP_ADJUST = {
    # 2026-09-09 P2-3 (三方·系数表序矛盾, 老大已拍板执行): 恐慌 0.7→0.55.
    # 原序矛盾: 震荡0.62 < 恐慌0.7, 违背"恐慌=最防御"直觉(0.55 收紧比 0.62 更紧).
    # 修复后收紧序(8%基础): 恐慌4.4% < 震荡4.96% < 偏弱6.8% < 偏暖8% < 强8.8%, 极强7.2%(防反转)
    "恐慌": 0.55,  # 市场最恐慌, 止损最紧, 本金安全第一
    "弱": 0.85,
    # 2026-09-09 P0-3 落地: 震荡市止损-5%收紧 (三方讨论牛马方向一, 老大已拍板).
    # 此前=1.0 → 基础8%×1.0=8%, 收紧未生效. 0.62 → 8%×0.62≈5%, 对齐拍板.
    # 注意: 仅止损系数对齐; 震荡市"快周转3-5日"涉及120d时间止损契约, 属P2-2三闸
    # 前置问题, 待老大拍板, 本次不动时间止损契约值.
    "震荡": 0.62,
    "偏暖": 1.0,
    "强": 1.1,     # 趋势好,允许更多波动
    "极强": 0.9,   # 极强警惕反转
}

# 基于断层/北向信号的止损奖励（信号强 → 放宽止损）
SIGNAL_BONUS_ADJUST = {
    0: 1.0,     # 无信号
    1: 1.0,     # 一般
    2: 1.05,    # 较好
    3: 1.10,    # 强信号
    4: 1.15,    # 很强
    5: 1.20,    # 极强
}

# ═══════════════════════════════════════════
#  追高关闭: 信号日涨幅>该值不买 (P0-A: 回测+14pp)
#  历史沿革:
#    2026-08-16 老大拍板: 4%硬关闭 (追高不追)
#    2026-09-05 统一管理: 迁移至risk_rules.py作为唯一权威源
# ═══════════════════════════════════════════
CHASE_BAN_PCT = 4.0   # 信号日涨幅>4%不买 (2026-09-25 WorkBuddy统一口径: 回归08-16拍板4%与CONTEXT.md契约;
                      # 原5.0为2026-09-05 v36回测结论, 但与实盘落库门禁4%冲突导致回测口径失真, 详见体检报告P1-1)

# ═══════════════════════════════════════════
#  时间止损: 交易日计数 — 契约值 = 120 (2026-09-06 老大拍板)
#  历史沿革:
#    2026-08-16 老大拍板 P0: 120→40 (依据: 固定6%止损+40日 总收益+52.3% vs 120日 +1.61%)
#    2026-08-23 P1 全员讨论: 40→60 (契约值)
#    2026-09-02 P1 修正: 60→30 (回测显示5日超额+0.32%后转负, 缩短持仓周期)
#    2026-09-04 老大拍板: 维持30天,清理注释统一
#    2026-09-06 老大拍板: 30→120 (132日回测验证: 分级回撤8/12/18/25-止损7%-持有120d 胜率44.4%/年化+10.9%/盈亏比3.93 最优)
# ═══════════════════════════════════════════
TIME_STOP_TRADING_DAYS = 120   # 2026-09-06 延长至120天,吃大波段

# 时间止损预警: 剩余≤5日时触发飞书提醒（2026-09-03 老大拍板）
TIME_STOP_WARNING_DAYS = 5

# ═══════════════════════════════════════════
#  辅助函数: 信号日涨幅计算 (独立于backtest_rotation)
#  原因: backtest_rotation依赖numba(未安装), 但signal_day_chg无需numba
#  位置: 提取至此供 integrated_picker/orchestrator 直接使用
# ═══════════════════════════════════════════
def signal_day_chg(records, day):
    """信号日(扫描日)当日涨幅%: 当日close 相对 前一交易日close。
    返回 (day_close, chg_pct) 或 None(数据不足)。用于追高关闭(P0-A)与涨停买不进(P0-B)。
    """
    from datetime import date as _date
    if isinstance(day, str):
        day = _date.fromisoformat(day)

    # 构建日期索引缓存
    cache = {}
    for i, r in enumerate(records):
        cache[r["date"]] = i

    if day not in cache:
        return None

    i = cache[day]
    # 边界检查
    if i < 0 or i >= len(records):
        return None

    r = records[i]
    prev = records[i - 1]["close"] if i > 0 else None
    if prev and prev > 0:
        return r["close"], (r["close"] / prev - 1) * 100
    return r["close"], None


# 环境门关闭时保本观察模式参数（2026-09-03 老大拍板,2026-09-05 KIMI审查-20恢复5%）
# 2026-09-25: enabled=False — 环境门已于2026-09-17 老大拍板取消 (CONTEXT.md),
# 本模式属环境门残留, 关闭以避免覆盖8%契约止损 (体检P1-4)
PROTECTIVE_MODE = {
    "enabled": False,
    "cost_stop": True,           # 跌破成本价立即清仓
    "trailing_activate_pct": 0.15,  # 2026-09-18 延迟追踪: 0.05→0.15 (老五实测紧追踪是右尾杀手)
}

_TRADE_DATES_CACHE = None

def _load_trade_dates():
    """懒加载 A股交易日历 (data/sh_index_history.json 的日期列), 失败回退工作日近似.
    返回 sorted date 列表; 空列表 = 日历不可用."""
    global _TRADE_DATES_CACHE
    if _TRADE_DATES_CACHE is not None:
        return _TRADE_DATES_CACHE
    dates = []
    try:
        import json, os
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "data", "sh_index_history.json")  # S6修复(2026-10-23): 根锚点=core/risk/上两级(仓库根), 对齐core/pipeline三层先例
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                payload = json.load(f)
            for r in (payload.get("data") or []):
                ds = r.get("date")
                if isinstance(ds, str):
                    ds = date(int(ds[:4]), int(ds[5:7]), int(ds[8:10]))
                if isinstance(ds, date):
                    dates.append(ds)
            dates.sort()
    except Exception as _cal_e:
        print(f"⚠️ 交易日历读取失败({_cal_e}), 尝试TDX回退")  # P0修复(2026-09-25): 不再静默
        dates = []
    # P0修复(2026-09-25): 日历缺失时回退TDX上证指数(参照backtest.py做法), 仍失败才用工作日近似
    if not dates:
        try:
            from tdx_data import get_tdx_data as _gtd
            _recs = _gtd("sh000001", 12000) or []
            dates = sorted(r["date"] if isinstance(r["date"], date)
                           else date.fromisoformat(str(r["date"])) for r in _recs)
            if dates:
                print(f"⚠️ 交易日历文件缺失, 已回退TDX指数日历({len(dates)}天) — 请重建 data/sh_index_history.json")
        except Exception as _tdx_e:
            print(f"⚠️ 交易日历不可用(文件缺失+TDX回退失败:{_tdx_e}), "
                  f"时间止损将按工作日近似计算(约多算9个交易日), 请尽快重建日历!")
    _TRADE_DATES_CACHE = dates
    return dates


def count_trading_days(start, end):
    """计算 (start, end] 之间的A股交易日数 (卖出日含入, 买入日不计, 与轮动回测 hold_days 口径一致).
    优先用 A股交易日历 (data/sh_index_history.json); 日历不可用时回退工作日(周一~周五)近似.
    """
    if not isinstance(start, date) or not isinstance(end, date):
        return 0
    if end <= start:
        return 0
    dates = _load_trade_dates()
    if dates:
        return sum(1 for d in dates if start < d <= end)
    # 回退: 工作日近似
    n, cur = 0, start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


# ═══════════════════════════════════════════
#  分级移动止盈 - TREND_TP_LADDER 为唯一权威源 (P17/P18 统一)
# ═══════════════════════════════════════════
# 趋势动态止盈方案: 浮盈越高, 回撤容忍越大
# 回测依据: 4趋势×4方案×5止损=80组回测 (2026-09-03 P19)
# 上升趋势→中档M2(+4.16%/45%); 下降趋势→精调T1(胜率45%)
# 震荡趋势→紧密T3(亏损最少-0.44%); 波段趋势→中档M2(+1.13%/45%)
# 2026-09-08 P18: 统一为 TREND_TP_LADDER["up"] 作为默认值
# 2026-09-18: LEGACY_FIXED_TP 已废弃，删除所有引用
TREND_TP_LADDER = {
    # ⚠️⚠️ 语义务必看清 —— 2026-10-17 老六曾误读此处并改错, 已还原, 留注为戒 ⚠️⚠️
    #   每项 = (激活涨幅%, **移动止盈回撤容忍%**), 不是"卖出比例"!
    #   一手证据: backtest_pipeline.py:478 `for threshold, trail_pct in tp_ladder:`
    #            → 浮盈达 threshold% 后, 允许回撤 trail_pct 再离场; 触发即**整笔**离场(不分批)。
    #   "每档卖多少仓位"由下方 TP_SELL_LADDER 单独表达, 两者不是一回事, 禁止混用。
    #   "up" 五档为 132 日全量回测会签值, 未经老大批准+回测复核不得改动。
    "up": [(6, 0.15), (10, 0.05), (15, 0.07), (25, 0.09), (999, 0.12)],  # S3五档(会签冻结)
    "down": [(5, 0.03), (10, 0.04), (15, 0.05), (20, 0.06), (30, 0.08), (999, 0.10)],  # 精调T1: 下降趋势
    "sideways": [(3, 0.02), (5, 0.03), (10, 0.04), (20, 0.05), (999, 0.06)],  # 紧密T3: 震荡趋势
    "swing": [(10, 0.06), (20, 0.08), (40, 0.10), (999, 0.12)],       # 中档M2: 波段趋势
    "up_contract": [(8, 0.05), (10, 0.05), (15, 0.07), (25, 0.09), (999, 0.12)],  # S2备选: 回撤敏感方
}

# 默认趋势 (对应 TREND_TP_LADDER["up"])
DEFAULT_TP_LADDER = TREND_TP_LADDER["up"]

# ═══════════════════════════════════════════
#  分批减仓阶梯 TP_SELL_LADDER — 唯一权威源 (2026-10-17 老大拍板, 从 per-position 上移)
# ═══════════════════════════════════════════
# 语义: (触发涨幅%, 该档卖出**仓位比例**)。与上面 TREND_TP_LADDER 的"回撤容忍"无关。
#
# 老大三条硬要求:
#   ① 三档
#   ② 从 per-position 上移到止盈止损策略层 —— 原写在 data/holdings.json 的
#      risk_control.tp_ladder = [[0.05,0.3],[0.1,0.3],[0.15,0.4]] 已作废。
#      (实测该字段在生产代码中**无任何消费方**, 是死数据; 且各自抄写正是契约漂移根源)
#   ③ 留一半以上仓位吃大波段 → 总卖出必须 <= 50%
#
# 旧 per-position 值的问题: +5%卖30% / +10%卖30% / +15%卖40% = 涨15%即清仓 100%,
#   与③"留一半以上吃大波段"完全相反。
#
# 新三档构成:
#   首档 (6,  0.15)  浮盈 6%  卖 15% —— 与 TREND_TP_LADDER 首档激活点对齐, 让利润奔跑
#   中档 (15, 0.15)  浮盈 15% 再卖 15%
#   末档 (999, 0.18) 阈值 999% = 不再按涨幅分批, 剩余仓位交给移动止盈接管
#   → 总卖出 48%, 留仓 52% (> 50%, ③的硬判据)
TP_SELL_LADDER = [(6, 0.15), (15, 0.15), (999, 0.18)]

# 派生量(只读, 由 tests/test_tp_ladder_contract.py 机器卡死, 防止后人改档改穿)
TP_SELL_TOTAL = round(sum(ratio for _, ratio in TP_SELL_LADDER), 4)   # 0.48
TP_KEEP_RATIO = round(1 - TP_SELL_TOTAL, 4)                            # 0.52

def get_trend_tp_ladder(trend="up", ladder=None):
    """按趋势返回对应止盈阶梯. trend: up/down/sideways/swing"""
    if ladder:
        return ladder
    return TREND_TP_LADDER.get(trend, TREND_TP_LADDER["up"])

def detect_stock_trend(closes, ma5=None, ma20=None, ma60=None):
    """简单趋势判断: 均线排列法
    closes: 近60日收盘价列表
    返回: up/down/sideways/swing
    """
    if len(closes) < 60:
        return "swing"
    if ma5 is None:
        ma5 = sum(closes[-5:]) / 5
    if ma20 is None:
        ma20 = sum(closes[-20:]) / 20
    if ma60 is None:
        ma60 = sum(closes) / len(closes)
    latest = closes[-1]
    high60 = max(closes[-60:])
    low60 = min(closes[-60:])
    amplitude = (high60 - low60) / low60 * 100 if low60 > 0 else 0
    ret20 = (latest - closes[-20]) / closes[-20] * 100 if len(closes) >= 20 and closes[-20] > 0 else 0

    if ma5 > ma20 > ma60 and latest > ma20 and ret20 > 5:
        return "up"
    elif ma5 < ma20 < ma60 and latest < ma20 and ret20 < -5:
        return "down"
    elif amplitude < 15 and ma20 > 0 and abs(latest - ma20) / ma20 < 0.05:
        return "sideways"
    else:
        return "swing"

# 遗留固定TP档位 (体系A: calculate_tp_levels 默认 7/13/20)
# ⚠️ DEPRECATED (2026-09-22): 统一使用 TREND_TP_LADDER，本字典仅保留作历史参考
# LEGACY_FIXED_TP = {"综合": (0.07, 0.13, 0.20)}  # 已废弃，请使用 TREND_TP_LADDER

# ⚠️ REMOVED (2026-09-29 T1拍板·总管代老大审批权, 09-30 因git回滚重放): GRADED_TP_LADDER 已除名
# 原值 [(10,0.08),(20,0.12),(40,0.18),(999,0.25)] —— 278日回测 -25.43%/PF0.83 全负,
# 原实盘硬编码劣组, T1裁决废止。唯一权威源 = TREND_TP_LADDER (L209). 备份 risk_rules.py.bak_20260929

# ═══════════════════════════════════════════
#  回本抛压平仓 (T-20260816-003 Option D, "扳本效应") - 已冻结
# ═══════════════════════════════════════════
# 行为金融实证: 处置效应中"扳本"约占13% — 浮亏反弹回到成本线的瞬间卖压跃升;
# 对盈利的敏感度是亏损的6.03倍 → 曾浮盈≥6% 的票回吐到成本附近时, 均值回归兑现时点已到.
# 落地: 仅非牛市(market_label="牛")生效; 参数集中便于扫描 (参考 5%/1% / 6%/1.5% / 7%/2%).
# 2026-08-16 冻结: 触发率0.8%(1/132) < 5% 验收线, 禁止启用.
TP_FADE_PEAK = 0.06    # 持仓期最高浮盈下限 (peak_pnl 基于持仓最高价)
TP_FADE_CURR = 0.015   # 当前浮盈上限 (curr 回落至 ≤1.5% 触发)
_BULL_LABELS = ("牛", "牛市", "极强")


# ═══════════════════════════════════════════
#  公共函数 - 委托给RiskEngine
# ═══════════════════════════════════════════

# 懒加载的RiskEngine实例（避免重复创建）
_engine = None

def _get_engine():
    """获取或创建RiskEngine实例（单例）"""
    global _engine
    if _engine is None:
        _engine = RiskEngine(config=RiskConfig.default())
    return _engine


# ⚠️ REMOVED (2026-10-17 老六): 此处原有一份 get_trend_tp_ladder / detect_stock_trend 的
# 重复定义(与 L250/L256 逐行等价), 已删除。同一模块内两处同名函数 = 契约漂移温床,
# 由 tests/test_no_duplicate_defs.py 机器卡死(全仓顶层重名一律红灯), 禁止再加回来。


def calculate_stop_loss(entry_price, strategy="综合", market_label="震荡",
                         gap_score=0, nb_score=0, atr=None):
    """
    计算止损价.
    
    返回:
        (stop_loss_price, stop_loss_pct, stop_loss_type, description)
    """
    if entry_price <= 0:
        return 0, 0, "ERROR", "价格无效"
    
    # 基础止损百分比 + 市场调整系数（合并为 base_adj）
    # 2026-10-17 止血（老六）: 原为 .get(strategy, **0.08**) —— 这是全仓最后一个"活着的 8%",
    #   任何未知策略名都会**静默**回落到 09-30 会签前的旧口径, 且无告警。
    #   现改为回退真源"全仓"档并 loud 提示, 消灭第二个止损口径。
    base_stop_loss_pct = STRATEGY_STOP_LOSS_PCT.get(strategy)
    if base_stop_loss_pct is None:
        base_stop_loss_pct = STRATEGY_STOP_LOSS_PCT.get("全仓", 0.10)
        print("  ⚠️ strategy=%r 不在 STRATEGY_STOP_LOSS_PCT, 已回退真源'全仓'档 %.0f%%"
              " (旧代码此处静默兜底 8%%, 与会签契约不符)" % (strategy, base_stop_loss_pct * 100))
    market_adj = MARKET_STOP_ADJUST.get(market_label, 1.0)
    base_adj = base_stop_loss_pct * market_adj

    # ATR动态止损（如果有）
    if atr and atr > 0:
        atr_stop = entry_price - 2 * atr  # 2倍ATR止损
        if atr_stop > 0:
            atr_pct = (entry_price - atr_stop) / entry_price
            # 取较保守的止损（较大的百分比）
            stop_loss_pct = max(base_adj, atr_pct)
            stop_loss_type = "ATR动态"
            desc = f"ATR={atr:.2f}, 止损{stop_loss_pct*100:.1f}%"
        else:
            stop_loss_pct = base_adj
            stop_loss_type = "固定"
            desc = f"固定止损{stop_loss_pct*100:.1f}%"
    else:
        stop_loss_pct = base_adj
        stop_loss_type = "固定"
        desc = f"固定止损{stop_loss_pct*100:.1f}%"

    # 计算止损价
    stop_loss_price = entry_price * (1 - stop_loss_pct)

    # 跌停板保护
    limit_down_price = entry_price * 0.9  # 假设-10%跌停
    if stop_loss_price < limit_down_price:
        # 止损价低于跌停价，提前止损
        stop_loss_price = limit_down_price * 0.98
        desc += " (跌停保护)"
        stop_loss_type = "跌停保护"

    return round(stop_loss_price, 2), stop_loss_pct, stop_loss_type, desc


def calculate_tp_levels(entry_price, gap_score=0, market_label="震荡",
                         strategy="综合"):
    """
    计算止盈价位 (体系A: 固定百分比止盈).
    # 2026-09-29 T1收敛: 统一使用 TREND_TP_LADDER["up"] 作为唯一权威源.
       GRADED_TP_LADDER (8/12/18/25%) 已废弃归档，本函数仅保留作历史参考.
       ⚠ 2026-10-09 D2裁定(裁定落档-D1D6): 阶梯真值 = 10-06 S3吃大肉五档
       TREND_TP_LADDER["up"] = [(6,0.15),(10,0.05),(15,0.07),(25,0.09),(999,0.12)]
       (首档6%激活容15%让利润奔跑, 总卖出≈48%), 见 L222. 本注释原"4档5/7/10/12"
       与 L222 常量矛盾, 已按 L222 磁盘真值修正, 勿再引用旧注释数值.
    
    返回:
        (tp1_price, tp1_pct, tp2_price, tp2_pct, tp3_price, tp3_pct, description)
    """
    # 防御: 非法入场价 / None 信号分
    if not isinstance(entry_price, (int, float)) or entry_price <= 0:
        raise ValueError("entry_price 必须为正数: %r" % (entry_price,))
    gap_score = gap_score or 0
    # 第一目标:止盈在关键阻力位或固定比例
    if strategy == "断层":
        # 断层策略的止盈保守一些,缺口上方运行空间
        tp1_pct = 0.08   # +8% 止盈1/2仓位
        tp2_pct = 0.15   # +15% 止盈剩余
        tp3_pct = 0.25   # +25% 全部止盈
    elif strategy == "全仓":
        tp1_pct = 0.06
        tp2_pct = 0.12
        tp3_pct = 0.20
    elif strategy == "突破":
        tp1_pct = 0.08
        tp2_pct = 0.15
        tp3_pct = 0.22
    elif strategy == "抄底":
        tp1_pct = 0.05   # 抄底反弹,见好就收
        tp2_pct = 0.10
        tp3_pct = 0.18
    else:
        tp1_pct = 0.07
        tp2_pct = 0.13
        tp3_pct = 0.20
    
    # 市场状态调整（强市放远,弱市收窄）
    if market_label in ("强", "极强"):
        tp1_pct *= 1.2
        tp2_pct *= 1.2
        tp3_pct *= 1.2
    elif market_label in ("弱", "恐慌"):
        tp1_pct *= 0.8
        tp2_pct *= 0.8
        tp3_pct *= 0.8

    # 风报比保护: TP1 不低于 5% (弱市抄底4% vs 止损6.8%会倒挂)
    tp1_pct = max(tp1_pct, 0.05)
    # 止盈上限: 防止极端拉伸导致资金长期占用
    tp3_pct = min(tp3_pct, 0.25)
    tp2_pct = min(tp2_pct, 0.20)
    
    tp1 = round(entry_price * (1 + tp1_pct), 2)
    tp2 = round(entry_price * (1 + tp2_pct), 2)
    tp3 = round(entry_price * (1 + tp3_pct), 2)
    
    desc = "TP1=+%.1f%% TP2=+%.1f%% TP3=+%.1f%%" % (tp1_pct*100, tp2_pct*100, tp3_pct*100)
    
    return tp1, tp1_pct, tp2, tp2_pct, tp3, tp3_pct, desc


def _emit_time_stop_unknown_alert(entry_info, data_quality_issue, queue_path=None):
    """时间止损日期未知：写 data/message_queue.json 走 QSP_MsgDrain 唯一出口。
    仅 print 不算告警（AGENTS.md §11）。
    异常不静默吞：读/写失败直接 raise loud fail，不允许告警丢失。

    参数:
        entry_info: 持仓入口信息 dict
        data_quality_issue: "entry_date_invalid" | "entry_date_missing"
        queue_path: 队列文件路径，默认 data/message_queue.json；测试可传 tmp 路径隔离
    """
    import time as _time
    import json as _json

    # 记录调用方是否显式指定了队列(测试传 tmp 隔离); 下方会把 None 默认成生产路径, 之后无法再区分
    _explicit_queue = queue_path is not None

    if queue_path is None:
        queue_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "message_queue.json")  # S6修复(2026-10-23): 根锚点=仓库根

    stock_code = entry_info.get("stock_code", "unknown")

    # P0(老五 2026-10-26): 合成/测试哨兵判定(无6位A股代码), 供 message_queue 守卫 + alert_log D-10 段共用。
    # 修复点: 原 C-fix 守卫只护 message_queue 侧, D-10 alert_log append 用硬编码生产路径,
    # 既不认 queue_path 测试隔离也不认合成码 → 测试/合成哨兵把假 P0 灌进生产 alert_log.jsonl。
    import re as _syn_re
    _is_synthetic = not _syn_re.search(r"\d{6}", str(stock_code))

    # C-fix (2026-10-23): defense-in-depth —— 合成/测试哨兵数据走生产默认路径时,
    # 跳过生产 P0 写入(不写 message_queue/不写 alert_log P0), 仅记本地 audit。
    # 真实持仓 stock_code 必含 6 位数字(如 600519/SH600519); unknown/TEST001/TESTDEDUP/
    # INVALID/MISSING 等合成哨兵无 6 位 → 非真实持仓。堵住测试/监控喂合成数据导致的假 P0
    # (飞书管事群 meta-P0: 时间止损日期解析失败 [entry_date_invalid] stock=unknown/TEST001)。
    # 仅当 queue_path 未显式指定(=生产默认)时生效; 测试显式传 tmp queue_path 时正常写入(隔离不变)。
    if not _explicit_queue:
        import re as _re
        if not _re.search(r"\d{6}", str(stock_code)):
            _repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            _audit_path = os.path.join(_repo_root, "data", "synthetic_alert_audit.jsonl")
            try:
                with open(_audit_path, "a", encoding="utf-8") as _af:
                    _af.write(_json.dumps({
                        "ts": int(_time.time()),
                        "level": "AUDIT",
                        "source": "risk_rules_time_stop",
                        "stock_code": stock_code,
                        "entry_date": entry_info.get("entry_date", "MISSING"),
                        "data_quality_issue": data_quality_issue,
                        "note": "合成/测试哨兵(无6位A股代码), 跳过生产 P0, 仅记 audit",
                    }, ensure_ascii=False) + "\n")
            except Exception as _ae:
                print(f"[AUDIT] synthetic_alert_audit 写入失败: {_ae}", file=sys.stderr)
            print(f"[AUDIT] 时间止损 P0 跳过生产写入: stock={stock_code} 为合成/测试哨兵(无6位代码)")
            return

    alert_item = {
        "id": "time_stop_unknown_%d_%s" % (int(_time.time()), stock_code),
        "content": "🔔 时间止损日期解析失败 [%s] 股票代码=%s entry_date=%s" % (
            data_quality_issue,
            entry_info.get("stock_code", "unknown"),
            entry_info.get("entry_date", "MISSING"),
        ),
        "platform": "feishu",
        "ts": _time.time(),
    }

    # 读现有队列：损坏路径直接抛，不静默重置为 []
    existing = []
    if os.path.exists(queue_path):
        with open(queue_path, "r", encoding="utf-8") as _f:
            existing = _json.load(_f)
        if not isinstance(existing, list):
            raise ValueError(
                f"[LOUD] message_queue.json 格式错误: 期望list，得到{type(existing).__name__}"
            )

    # 去重：同 id 不重复入队
    existing_ids = {item.get("id") for item in existing if isinstance(item, dict)}
    if alert_item["id"] in existing_ids:
        print(f"[LOUD] time_stop_unknown 告警已存在，跳过重复写入 id={alert_item['id']}")
        return

    existing.append(alert_item)

    # 写队列：atomic_dump 优先，失败走裸写，两者失败都 raise
    try:
        from atomic_json import atomic_dump
        atomic_dump(existing, queue_path, ensure_ascii=False, indent=2)
    except ImportError:
        with open(queue_path, "w", encoding="utf-8") as _f:
            _json.dump(existing, _f, ensure_ascii=False, indent=2)
    except Exception as _e:
        raise RuntimeError(f"[LOUD] 写 message_queue.json 失败: {_e}") from _e

    print(
        f"[LOUD] time_stop_unknown=True data_quality_issue={data_quality_issue} "
        f"stock={stock_code} id={alert_item['id']}"
    )

    # D-10 补 alert_log.jsonl 台账留痕（规则 11"台账须有记录"）
    # P0(老五 2026-10-26): 与 message_queue 守卫对齐——仅"真实持仓(含6位代码) + 生产默认路径
    # (非测试隔离)"才写生产 P0 台账。合成哨兵已分流 synthetic_alert_audit.jsonl;
    # 测试隔离(queue_path=tmp, _explicit_queue=True)不落生产台账。堵掉 alert_log 侧污染。
    if _is_synthetic or _explicit_queue:
        print(f"[AUDIT] alert_log.jsonl 跳过生产台账: stock={stock_code} synthetic={_is_synthetic} explicit_queue={_explicit_queue}")
    else:
        import datetime as _dt
        alert_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "alert_log.jsonl")  # S6修复(2026-10-23): 根锚点=仓库根
        _ts_human = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _alert_entry = _json.dumps({
            "timestamp": _ts_human,
            "level": "P0",
            "source": "risk_rules_time_stop",
            "message": "time_stop_unknown 日期解析失败 [%s] stock=%s entry_date=%s（告警已写 message_queue + 本台账）" % (
                data_quality_issue, stock_code, entry_info.get("entry_date", "MISSING"),
            ),
        }, ensure_ascii=False)
        try:
            with open(alert_log_path, "a", encoding="utf-8") as _af:
                _af.write(_alert_entry + "\n")
        except Exception as _ae:
            # 台账写失败不静默吞——降级 stdout（与 message_queue 写入同等 loud）
            print(f"[LOUD][WARN] alert_log.jsonl 写入失败（不阻塞主流程）: {_ae}", file=sys.stderr)


def evaluate_exit(entry_info, current_price, market_label="震荡", asof_date=None):
    """
    评估是否需要退出持仓.
    
    P1-1修复:参数化日期,支持回测场景.
    asof_date: 用于回测/历史场景评估,默认为今天.
    返回: (should_exit: bool, reason: str, exit_type: str, extra: dict) — 4元组
    extra.time_stop_unknown: entry_date 解析失败/缺失时为 True，需人工介入
    extra.data_quality_issue: "entry_date_invalid" | "entry_date_missing" | ""
    """
    if not entry_info or not current_price:
        return False, "", "", {"time_stop_unknown": False, "data_quality_issue": ""}

    entry_price = entry_info.get("entry_price", 0)
    if not entry_price or entry_price <= 0:
        return False, "", "", {"time_stop_unknown": False, "data_quality_issue": ""}
    
    strategy = entry_info.get("strategy", "综合")
    sl = entry_info.get("sl", 0)
    tp1 = entry_info.get("tp1", 0)
    tp2 = entry_info.get("tp2", 0)
    
    # 委托给RiskEngine
    engine = _get_engine()
    
    # 映射市场标签
    regime_map = {"强": "强", "偏暖": "偏暖", "震荡": "震荡", "偏弱": "弱", "恐慌": "恐慌"}
    regime = regime_map.get(market_label, "震荡")
    
    class SimpleAdapter(MarketStateAdapter):
        def __init__(self, r): self._regime = r
        def get_regime(self): return self._regime
        def get_confidence(self): return 0.85
    
    engine.market_state = SimpleAdapter(regime)
    
    # 构建Position对象
    entry_date_str = entry_info.get("entry_date")
    time_stop_unknown = False
    data_quality_issue = ""
    if entry_date_str:
        if isinstance(entry_date_str, str):
            try:
                entry_date = date(int(entry_date_str[:4]), int(entry_date_str[5:7]), int(entry_date_str[8:10]))
            except (ValueError, TypeError) as e:
                time_stop_unknown = True
                data_quality_issue = "entry_date_invalid"
                entry_date = date.today()
        else:
            entry_date = entry_date_str
    else:
        time_stop_unknown = True
        data_quality_issue = "entry_date_missing"
        entry_date = date.today()

    position = Position(
        stock_code=entry_info.get("stock_code", ""),
        entry_price=entry_price,
        entry_date=entry_date,
        quantity=entry_info.get("quantity", 100),
        strategy=strategy,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        exited_at_15=entry_info.get("exited_at_15", False),
        exited_at_25=entry_info.get("exited_at_25", False),
    )

    asof = asof_date or date.today()
    decision = engine.evaluate_exit(position, current_price, market_label=market_label, asof_date=asof)

    extra = {"time_stop_unknown": time_stop_unknown, "data_quality_issue": data_quality_issue}
    # 告警走唯一出口：写 data/message_queue.json（QSP_MsgDrain 5min 投递飞书）
    if time_stop_unknown:
        _emit_time_stop_unknown_alert(entry_info, data_quality_issue)
    if decision.should_exit:
        return True, decision.reason, decision.exit_type or "", extra

    return False, decision.reason, "", extra




def suggest_position_size(market_score, confidence_level, max_capital=23000):
    """
    建议买入仓位大小.
    
    参数:
        market_score: 0-100 市场评分
        confidence_level: "high" / "medium" / "low"
        max_capital: 最大可用资金
    
    返回:
        (suggest_amount, suggest_pct, reason)
    """
    # 市场评分决定基础仓位比例
    if market_score >= 75:
        base = 0.9
    elif market_score >= 55:
        base = 0.7
    elif market_score >= 35:
        base = 0.5
    elif market_score >= 15:
        base = 0.3
    else:
        base = 0.1
    
    # 确信度调整
    confidence_mult = {
        "high": 1.2,
        "medium": 1.0,
        "low": 0.6,
    }
    mult = confidence_mult.get(confidence_level, 1.0)
    
    final_pct = min(base * mult, 1.0)
    amount = int(max_capital * final_pct)
    
    if final_pct >= 0.8:
        reason = "重仓出击(市场%d分|确信%s)" % (market_score, confidence_level)
    elif final_pct >= 0.5:
        reason = "中等仓位(市场%d分|确信%s)" % (market_score, confidence_level)
    else:
        reason = "轻仓试探(市场%d分|确信%s)" % (market_score, confidence_level)
    
    return amount, final_pct, reason


def generate_trade_plan(entry_price, strategy, market_score, market_label,
                         gap_score, nb_score, confidence="medium", capital=23000, reasons="", trend="up"):
    """
    生成完整交易计划.

    返回:
        dict: {entry_price, stop_loss, tp1, tp2, tp3, position_size,
               risk_reward_ratio, plan_summary, rules}
    """
    # 止损
    sl_price, sl_pct, sl_type, sl_desc = calculate_stop_loss(
        entry_price, strategy, market_label, gap_score, nb_score
    )

    # 止盈 - 使用趋势动态阶梯 (2026-09-04 修复: 原硬编码GRADED_TP_LADDER导致趋势切换失效)
    _ladder = get_trend_tp_ladder(trend)
    tp1 = entry_price * (1 + _ladder[0][0] / 100)
    tp2 = entry_price * (1 + _ladder[1][0] / 100)
    tp3 = entry_price * (1 + _ladder[2][0] / 100)
    tp1_pct = _ladder[0][0] / 100
    tp2_pct = _ladder[1][0] / 100
    tp3_pct = _ladder[2][0] / 100

    # Q2 (老五审查): 移动止盈止损(trail 随股价上移) + 买卖价位模版
    TRAIL_PCT = 0.10          # 契约止损距离(P19: 10%, 动态阶梯最宽档)
    TRAIL_ACTIVATE = 0.15     # 2026-09-18 三方会签+老大拍板"执行建议"·决策2: 延迟追踪激活
                              # 0.05→0.15 (老五实测: 紧移动止损是右尾杀手, ATR追踪年化
                              # 8.0%→-3.6%/MDD反而-49%→-57%; 盈利≥15%才启动回撤保护,
                              # 早期浮盈靠分级移动止盈阶梯吃波段, 避免震荡市反复扫损)
    trailing = {
        "trail_pct": TRAIL_PCT,
        "activate_pct": TRAIL_ACTIVATE,
        "initial_stop": sl_price,
        "desc": "移动止盈止损(延迟追踪): 入场止损固定-8%; 当价较入场+15%后, 止损上移为 max(初始止损, 持仓最高价*(1-对应梯度回撤)) 并随股价上移锁定利润; 早期(0~15%)靠分级移动止盈阶梯吃波段, 跌破即离场",
    }
    price_template = {
        "buy": round(entry_price, 2),
        "buy_zone": [round(entry_price * 0.99, 2), round(entry_price * 1.01, 2)],
        "stop": round(sl_price, 2),
        "tp1": round(tp1, 2), "tp2": round(tp2, 2), "tp3": round(tp3, 2),
    }
    tp_desc = "分级移动止盈: 浮盈≥%.0f%%回撤%.0f%% / ≥%.0f%%回撤%.0f%% / ≥%.0f%%回撤%.0f%% / 更高回撤%.0f%%" % (
        _ladder[0][0], _ladder[0][1] * 100,
        _ladder[1][0], _ladder[1][1] * 100,
        _ladder[2][0], _ladder[2][1] * 100,
        _ladder[3][1] * 100)
    
    # 仓位
    amount, pos_pct, pos_reason = suggest_position_size(
        market_score, confidence, capital
    )
    
    # 风报比
    max_loss = entry_price - sl_price
    max_gain_tp1 = tp1 - entry_price
    max_gain_tp2 = tp2 - entry_price
    
    rrr_tp1 = max_gain_tp1 / max_loss if max_loss > 0 else 0
    rrr_tp2 = max_gain_tp2 / max_loss if max_loss > 0 else 0
    
    # 买入股数（全仓单只,100股整数倍）
    shares_per_lot = 100
    max_shares = 0
    if entry_price > 0:
        max_shares = int(amount / entry_price / shares_per_lot) * shares_per_lot
    actual_cost = max_shares * entry_price
    
    return {
        "entry_price": entry_price,
        "trailing": trailing,
        "price_template": price_template,
        "reasons": reasons,
        "stop_loss": sl_price,
        "stop_loss_pct": round(-sl_pct * 100, 1),
        "tp1": tp1,
        "tp1_pct": round(tp1_pct * 100, 1),
        "tp2": tp2,
        "tp2_pct": round(tp2_pct * 100, 1),
        "tp3": tp3,
        "tp3_pct": round(tp3_pct * 100, 1),
        "position_size": max_shares,
        "position_value": round(actual_cost, 2),
        "position_pct": round(pos_pct * 100, 0),
        "risk_reward_tp1": round(rrr_tp1, 2),
        "risk_reward_tp2": round(rrr_tp2, 2),
        "sl_rules": sl_desc,
        "tp_rules": tp_desc,
        "summary": "%s @ %.2f | SL=%.2f(-%.1f%%) | TP1=%.2f(+%.1f%%) | 仓位%d股(%.0f%%资本) | 风报比1:%.1f" % (
            strategy, entry_price, sl_price, sl_pct * 100,
            tp1, tp1_pct * 100,
            max_shares, pos_pct * 100,
            rrr_tp1
        ),
    }


def print_trade_plan(plan):
    """打印交易计划"""
    print("=" * 60)
    print("  📋 交易计划")
    print("=" * 60)
    print("  策略: %s" % plan["summary"].split(" | ")[0])
    print("  ── 买入 ──")
    print("  买入价: %.2f" % plan["entry_price"])
    print("  买入数量: %d股 (%.0f元, %.0f%%仓位)" % (
        plan["position_size"], plan["position_value"], plan["position_pct"]))
    print("  ── 止损 ──")
    print("  止损价: %.2f (%.1f%%)" % (plan["stop_loss"], plan["stop_loss_pct"]))
    print("  规则: %s" % plan["sl_rules"])
    print("  ── 止盈 ──")
    print("  TP1: %.2f (+%.1f%%) — 减半仓" % (plan["tp1"], plan["tp1_pct"]))
    print("  TP2: %.2f (+%.1f%%) — 清仓" % (plan["tp2"], plan["tp2_pct"]))
    print("  TP3: %.2f (+%.1f%%) — 全部止盈" % (plan["tp3"], plan["tp3_pct"]))
    print("  规则: %s" % plan["tp_rules"])
    print("  ── 风报比 ──")
    print("  风险(止损): %.1f%%" % plan["stop_loss_pct"])
    print("  收益(TP1): +%.1f%%, 风报比 1:%.1f" % (plan["tp1_pct"], plan["risk_reward_tp1"]))
    print("  收益(TP2): +%.1f%%, 风报比 1:%.1f" % (plan["tp2_pct"], plan["risk_reward_tp2"]))
    print("=" * 60)


# ═══════════════════════════════════════════
#  测试
# ═══════════════════════════════════════════



# ========== 向后兼容包装函数（返回float）==========

def calculate_stop_loss_wrapper(entry_price, strategy="综合", market_label="震荡",
                          gap_score=0, nb_score=0, atr=None):
    """向后兼容包装 - 返回float"""
    config = RiskConfig.default()
    engine = RiskEngine(config=config)
    
    regime_map = {"强": "强", "偏暖": "偏暖", "震荡": "震荡", "偏弱": "弱", "恐慌": "恐慌"}
    regime = regime_map.get(market_label, "震荡")
    
    class SimpleAdapter:
        def __init__(self, r): self._regime = r
        def get_regime(self): return self._regime
        def get_confidence(self): return 0.85
    
    engine.market_state = SimpleAdapter(regime)
    return engine.calculate_stop_loss(entry_price, strategy)


if __name__ == "__main__":
    print("=" * 60)
    print("  📊 止损止盈规则引擎 — 测试")
    print("=" * 60)
    
    # 模拟场景: 断层策略买入伊利股份
    print("\n📈 场景1: 断层策略 — 伊利股份 @ 27.31")
    plan = generate_trade_plan(
        entry_price=27.31,
        strategy="断层",
        market_score=42,
        market_label="震荡",
        gap_score=11,
        nb_score=8,
        confidence="medium",
        capital=23000
    )
    print_trade_plan(plan)
    
    print("\n📈 场景2: 全仓策略 — 强势市场")
    plan2 = generate_trade_plan(
        entry_price=50.00,
        strategy="全仓",
        market_score=78,
        market_label="强",
        gap_score=5,
        nb_score=3,
        confidence="high",
        capital=23000
    )
    print_trade_plan(plan2)
    
    print("\n📈 场景3: 抄底策略 — 弱市")
    plan3 = generate_trade_plan(
        entry_price=20.00,
        strategy="抄底",
        market_score=22,
        market_label="弱",
        gap_score=0,
        nb_score=0,
        confidence="low",
        capital=23000
    )
    print_trade_plan(plan3)


def evaluate_trailing_exit(entry_price, current_price, highest_price, hold_days=0,
                           market_label="震荡", trail_pct=0.08, max_hold_days=20,
                           entry_sl=0):
    """【已废弃 2026-09-29】移动止损止盈: 最高价回撤trail_pct触发卖出; 持仓>=max_hold_days未创新高也走.
    
    ⚠️ DEPRECATED (2026-09-29 T1收敛): 此函数已由 TREND_TP_LADDER 体系替代。
    实盘请使用 position_alerts.py（T1 后已统一引用 risk_rules.TREND_TP_LADDER 单一权威源）。
    回测请使用 evaluate_exit() 配合 TREND_TP_LADDER。
    保留此函数仅作为历史参考，不应在生产环境中调用。
    
    返回 (should_exit, reason, exit_type) — 3元组（历史参考函数，已废弃）
    """
    if not current_price or current_price <= 0:
        return False, "", ""
    pnl = (current_price / entry_price - 1) * 100
    # 硬止损 (跌超契约值8%保护本金; 2026-09-25 修复: 原写死-10%与契约背离)
    if pnl <= -STRATEGY_STOP_LOSS_PCT.get("全仓", 0.10) * 100:
        return True, "硬止损: 跌超%.0f%%(%.1f%%)" % (STRATEGY_STOP_LOSS_PCT.get("全仓", 0.10) * 100, pnl), "stop_loss"
    # 入场止损
    if entry_sl > 0 and current_price <= entry_sl:
        return True, "入场止损: 触发(%.1f%%)" % pnl, "stop_loss"
    # 移动止损: 从最高价回撤trail_pct
    if highest_price and highest_price > 0:
        drawdown = (highest_price - current_price) / highest_price
        if drawdown >= trail_pct:
            return True, "移动止损: 最高%.2f回撤%.1f%%" % (highest_price, drawdown * 100), "trailing_stop"
    # 时间止损: 持仓到期且未创新高
    if max_hold_days and hold_days >= max_hold_days:
        if highest_price and current_price < highest_price:
            return True, "时间止损: 持仓%d日未创新高" % hold_days, "time_stop"
    # 市场恶化
    if market_label == "恐慌":
        return True, "市场恐慌,无条件退出", "market_exit"
    return False, "", ""


if __name__ == "__main__":
    # 自检: 移动止损/时间止损/硬止损/正常持有
    assert evaluate_trailing_exit(10, 9.2, 10.5, hold_days=3)[0] is True      # 回撤8.6%>8%
    assert evaluate_trailing_exit(10, 9.9, 10.0, hold_days=21)[0] is True     # 时间止损(21日未创新高)
    assert evaluate_trailing_exit(10, 8.8, 10.0, hold_days=1)[0] is True      # 硬止损(-12%)
    assert evaluate_trailing_exit(10, 10.8, 11.0, hold_days=5)[0] is False    # 正常持有
    print("trailing self-check OK")
