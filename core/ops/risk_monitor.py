import core.pipeline.atomic_json as atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口 | C3-3 (2026-10-24 R0裁定): 原裸import只绑定core, L79 atomic_json.atomic_dump → NameError(save_json断链); 镜像 core/ops/message_queue.py L18 修法(单行 as 绑定)
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
from datetime import date
# R0 (2026-10-09): 消费 risk_rules 唯一权威源（只读）
from risk_rules import (
    TREND_TP_LADDER,
    DEFAULT_TP_LADDER,
    TIME_STOP_TRADING_DAYS,
    TIME_STOP_WARNING_DAYS,
    count_trading_days,
)
"""
risk_monitor.py — 核心风控引擎 v1.0
========================================
A股风险监控系统：回撤监控、连续亏损检测、市场风格分类、仓位合规检查、每日风控报告

用法:
  python risk_monitor.py              # 生成风控报告并检查风险
  python risk_monitor.py --report     # 仅生成报告，不推送告警
  python risk_monitor.py --push       # 生成报告并推送告警
"""
import json
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
from datetime import datetime, date
from collections import OrderedDict

logger = logging.getLogger("risk_monitor")
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PROJECT_DIR = PROJECT_ROOT
DATA_DIR = os.path.join(PROJECT_DIR, "data")
HOLDINGS_FILE = os.path.join(PROJECT_DIR, "data", "holdings.json")
TRADE_LOG_FILE = os.path.join(DATA_DIR, "trade_log.json")
BACKTEST_FILE = os.path.join(PROJECT_DIR, "backtest_result.json")
RISK_REPORT_FILE = os.path.join(DATA_DIR, "risk_report_latest.json")

# ─── 风控阈值 ──────────────────────────────────────────────────
SINGLE_LOSS_WARN_PCT = -15.0       # 单笔亏损 > -15% 警告
SINGLE_LOSS_EMERGENCY_PCT = -20.0  # 单笔亏损 > -20% 紧急
CONSECUTIVE_LOSS_WARN = 3          # 连续3笔亏损 → 警告
CONSECUTIVE_LOSS_EMERGENCY = 5     # 连续5笔亏损 → 紧急暂停
TOTAL_DRAWDOWN_WARN_PCT = -10.0    # 总回撤 > -10% 紧急
TOTAL_DRAWDOWN_EMERGENCY_PCT = -15.0  # 总回撤 > -15% 停止新开仓
MIN_POSITION_CHECK = 3             # 至少3笔才计算连续亏损

# 仓位限制（按市场状态）
POSITION_LIMITS = {
    "弱市": 50,
    "恐慌": 50,
    "震荡": 70,
    "偏暖": 80,
    "突破": 90,
    "牛市": 90,
    "强": 90,
}

# ─── 辅助函数 ──────────────────────────────────────────────────
def load_json(path):
    """安全加载JSON文件"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            pass
    return None

def save_json(path, data):
    """保存JSON文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_json.atomic_dump(data, path, ensure_ascii=False, indent=2, encoding="utf-8")

def get_today_str():
    return date.today().strftime("%Y-%m-%d")

# ─── 核心风控函数 ──────────────────────────────────────────────

def check_drawdown(holdings_data=None):
    """
    回撤监控
    指标:
      - 单笔亏损 > -15% → 🟡 警告
      - 单笔亏损 > -20% → 🔴 紧急
      - 总回撤 > -10%   → 🔴 紧急减仓
      - 总回撤 > -15%   → 🔴 停止新开仓

    返回: {"signals": [...], "max_drawdown": float, "total_pnl_pct": float}
    """
    signals = []

    if holdings_data is None:
        holdings_data = load_json(HOLDINGS_FILE)

    if not holdings_data:
        return {"signals": [{"level": "⚪", "indicator": "无持仓数据", "suggestion": "检查 holdings.json"}],
                "max_drawdown": 0.0, "total_pnl_pct": 0.0}

    # 兼容数组格式 holdings (portfolio_review 支持 list, 此处做防御)
    if isinstance(holdings_data, list):
        holdings_list = holdings_data
    else:
        holdings_list = holdings_data.get("holdings", [])
    if not holdings_list:
        return {"signals": [], "max_drawdown": 0.0, "total_pnl_pct": 0.0}

    # 计算每只股票盈亏
    stock_pnls = []
    total_cost = 0.0
    total_market_value = 0.0

    for h in holdings_list:
        code = h.get("code", "")
        name = h.get("name", "")
        cost_price = h.get("cost", h.get("cost_price", 0))
        shares = h.get("shares", 0)
        current_price = h.get("current_price", 0) or 0
        profit_pct = h.get("profit_pct", 0)

        # 缺 current_price → 从 TDX 补现价
        if current_price <= 0 and code:
            try:
                from core.pipeline.tdx_core import get_tdx_data
                recs = get_tdx_data(code, 3)
                if recs:
                    current_price = float(recs[-1]["close"])
                    profit_pct = (current_price - cost_price) / cost_price * 100 if cost_price else 0
            except Exception as _e:
                # P0(老五 2026-10-25): 原 `except: pass` 静默吞掉TDX拉取失败, 使 current_price 沿用
                # holdings.json 旧值 → 止损/预警信号(下行 151/160)基于非最新价, 违背风控引擎职责。
                # 现改为向 stderr 记录 + 提示现价陈旧; 数值逻辑保持不变(fail-safe, 不改风控参数)。
                print(f"⚠️ [risk_monitor] {code} 现价拉取失败, 沿用持仓旧价(可能陈旧): {_e}", file=sys.stderr)

        cost_total = cost_price * shares
        market_value = current_price * shares
        total_cost += cost_total
        total_market_value += market_value

        stock_pnls.append({
            "code": code, "name": name,
            "cost_price": cost_price, "current_price": current_price,
            "shares": shares, "profit_pct": profit_pct,
            "cost_total": cost_total, "market_value": market_value,
        })

        # 单笔亏损检查
        if profit_pct <= SINGLE_LOSS_EMERGENCY_PCT:
            signals.append({
                "level": "🔴",
                "indicator": f"{name}({code}) 亏损{profit_pct:.1f}%",
                "suggestion": f"严重亏损，建议立即止损卖出",
                "severity": "emergency",
            })
        elif profit_pct <= SINGLE_LOSS_WARN_PCT:
            signals.append({
                "level": "🟡",
                "indicator": f"{name}({code}) 亏损{profit_pct:.1f}%",
                "suggestion": f"接近止损线，密切关注",
                "severity": "warning",
            })

    # 总盈亏计算
    total_pnl = total_market_value - total_cost
    total_pnl_pct = round((total_pnl / total_cost) * 100, 2) if total_cost > 0 else 0.0
    max_drawdown = min([s.get("profit_pct", 0) for s in stock_pnls] + [0])
    max_drawdown_stock = next(
        (s for s in stock_pnls if s["profit_pct"] == max_drawdown), None
    )

    # 总回撤检查
    if total_pnl_pct <= TOTAL_DRAWDOWN_EMERGENCY_PCT:
        signals.append({
            "level": "🔴",
            "indicator": f"账户总回撤 {total_pnl_pct:.1f}%",
            "suggestion": "停止新开仓，全面减仓控风险",
            "severity": "emergency",
        })
    elif total_pnl_pct <= TOTAL_DRAWDOWN_WARN_PCT:
        signals.append({
            "level": "🔴",
            "indicator": f"账户总回撤 {total_pnl_pct:.1f}%",
            "suggestion": "紧急减仓至50%以下",
            "severity": "emergency",
        })

    # 统计最大回撤
    if max_drawdown_stock:
        signals.append({
            "level": "📊",
            "indicator": f"最大回撤股票: {max_drawdown_stock['name']}({max_drawdown_stock['code']}) {max_drawdown:.2f}%",
            "suggestion": "",
            "severity": "info",
        })

    return {
        "signals": signals,
        "max_drawdown": max_drawdown,
        "total_pnl_pct": total_pnl_pct,
        "stock_pnls": stock_pnls,
        "total_cost": total_cost,
        "total_market_value": total_market_value,
    }

def check_losing_streak(trade_log=None):
    """
    连续亏损检测
    从 trade_log.json 中提取已跟进的交易，按时间排序后检测连续亏损

    返回: {"consecutive_losses": int, "signals": [...], "trade_sequence": [...]}
    """
    if trade_log is None:
        trade_log = load_json(TRADE_LOG_FILE)

    if not trade_log or "recommendations" not in trade_log:
        return {"consecutive_losses": 0, "signals": [], "trade_sequence": []}

    recs = trade_log.get("recommendations", [])

    # 筛选出已跟进且有实际收益的记录
    followed_trades = []
    for r in recs:
        if r.get("followed") is True and r.get("actual_return_pct") is not None:
            followed_trades.append({
                "date": r.get("date", r.get("timestamp", "")),
                "code": r.get("code", ""),
                "name": r.get("name", ""),
                "strategy": r.get("strategy", ""),
                "return_pct": r.get("actual_return_pct", 0),
                "max_drawdown_pct": r.get("max_drawdown_pct"),
            })

    # 按时间排序
    followed_trades.sort(key=lambda x: x["date"])

    if len(followed_trades) < MIN_POSITION_CHECK:
        return {"consecutive_losses": 0, "signals": [], "trade_sequence": followed_trades}

    # 检测最近连续亏损
    consecutive_losses = 0
    max_consecutive_losses = 0
    current_streak = []
    longest_streak = []

    for t in followed_trades:
        if t["return_pct"] < 0:
            consecutive_losses += 1
            current_streak.append(t)
            if consecutive_losses > max_consecutive_losses:
                max_consecutive_losses = consecutive_losses
                longest_streak = list(current_streak)
        else:
            consecutive_losses = 0
            current_streak = []

    # 最近一次连续亏损（从尾部往前数）
    recent_streak = 0
    recent_streak_trades = []
    for t in reversed(followed_trades):
        if t["return_pct"] < 0:
            recent_streak += 1
            recent_streak_trades.append(t)
        else:
            break

    signals = []
    if recent_streak >= CONSECUTIVE_LOSS_EMERGENCY:
        codes_info = " → ".join([f"{t['name']}({t['return_pct']:+.1f}%)" for t in reversed(recent_streak_trades)])
        signals.append({
            "level": "🔴",
            "indicator": f"连续{recent_streak}笔推荐亏损",
            "suggestion": f"建议暂停策略，检查评分公式和市场适配性\n  交易序列: {codes_info}",
            "severity": "emergency",
            "consecutive_losses": recent_streak,
        })
    elif recent_streak >= CONSECUTIVE_LOSS_WARN:
        codes_info = " → ".join([f"{t['name']}({t['return_pct']:+.1f}%)" for t in reversed(recent_streak_trades)])
        signals.append({
            "level": "🟡",
            "indicator": f"连续{recent_streak}笔推荐亏损",
            "suggestion": f"关注后续交易，如继续亏损则暂停\n  交易序列: {codes_info}",
            "severity": "warning",
            "consecutive_losses": recent_streak,
        })

    return {
        "consecutive_losses": recent_streak,
        "max_consecutive_losses": max_consecutive_losses,
        "signals": signals,
        "trade_sequence": followed_trades,
        "total_followed_trades": len(followed_trades),
        "recent_streak_trades": list(reversed(recent_streak_trades)),
    }


# ═══════════════════════════════════════════
#  R0 (2026-10-09): S3 移动止盈阶梯 + 时间止损（只读消费 risk_rules 权威源）
# ═══════════════════════════════════════════

def check_trailing_take_profit(holding):
    """
    移动止盈阶梯检查（S3 吃大肉五档）
    
    消费 risk_rules.TREND_TP_LADDER["up"] 唯一权威源：
    [(6,0.15),(10,0.05),(15,0.07),(25,0.09),(999,0.12)]
    - 每档 (激活浮盈%, 该档回撤容忍%)
    - 首档 6% 激活容忍 15%（让利润奔跑），后续浮盈越高锁越紧
    - 取持仓峰值价 peak（历史最高现价，缺 peak 字段则用当前价近似并告警）
    - 当前浮盈 = (peak - cost) / cost
    - 找浮盈命中的最高档（激活阈值 ≤ 当前浮盈的最大档）
    - 锁止盈价 = peak × (1 - 该档容忍%)
    - 现价 ≤ 锁价 → 触发分批止盈告警（含已触发档数）
    - 未达首档激活(6%) → 锁价=None、未触发
    
    返回: {
        "lock_price": float|None,      # 锁定止盈价
        "triggered_tiers": int,         # 已触发分批档数
        "current_tier": int,            # 当前命中档位（0=未达首档）
        "floating_pnl_pct": float,      # 当前浮盈%
        "peak_price": float,            # 使用的峰值价
        "alert_triggered": bool,        # 是否触发现价≤锁价告警
        "warnings": list,               # 告警列表（如 peak_fallback）
    }
    """
    warnings = []
    
    cost = holding.get("cost", 0) or holding.get("cost_price", 0)
    current_price = holding.get("current_price", 0)
    peak_price = holding.get("peak_price")
    trend = holding.get("trend", "up")
    
    if cost <= 0 or current_price <= 0:
        return {
            "lock_price": None,
            "triggered_tiers": 0,
            "current_tier": 0,
            "floating_pnl_pct": 0.0,
            "peak_price": 0.0,
            "alert_triggered": False,
            "warnings": ["invalid_price_or_cost"],
        }
    
    # 峰值价：缺 peak_price 字段则用当前价近似并告警
    if peak_price is None or peak_price <= 0:
        peak_price = current_price
        warnings.append("peak_fallback")
    
    # 当前浮盈%
    floating_pnl_pct = (peak_price - cost) / cost * 100
    
    # 获取趋势对应的阶梯
    ladder = TREND_TP_LADDER.get(trend, DEFAULT_TP_LADDER)
    
    # 找浮盈命中的最高档（激活阈值 ≤ 当前浮盈的最大档）
    # 加 1e-9 容差防浮点漏档（如 10.0→10.6 算出 5.9999999999999964 < 6）
    current_tier = 0
    lock_tolerance = None
    for i, (activate_pct, tolerance) in enumerate(ladder):
        if floating_pnl_pct + 1e-9 >= activate_pct:
            current_tier = i + 1  # 1-based
            lock_tolerance = tolerance
        else:
            break
    
    # 计算锁止盈价
    lock_price = None
    if lock_tolerance is not None:
        lock_price = round(peak_price * (1 - lock_tolerance), 2)
    
    # 已触发档数 = 激活阈值 ≤ 浮盈的档数
    triggered_tiers = current_tier
    
    # 现价 ≤ 锁价 → 触发分批止盈告警
    alert_triggered = False
    if lock_price is not None and current_price <= lock_price:
        alert_triggered = True
    
    return {
        "lock_price": lock_price,
        "triggered_tiers": triggered_tiers,
        "current_tier": current_tier,
        "floating_pnl_pct": round(floating_pnl_pct, 2),
        "peak_price": peak_price,
        "alert_triggered": alert_triggered,
        "warnings": warnings,
        "lock_tolerance": lock_tolerance,
    }


def check_time_stop(holding):
    """
    时间止损检查（120 交易日契约）
    
    消费 risk_rules.TIME_STOP_TRADING_DAYS (=120) + TIME_STOP_WARNING_DAYS (=5)
    - 按 holding.entry_date 算已持有交易日数（复用 risk_rules 交易日历）
    - 缺日历降级自然日+告警（见 risk_rules L188 既有行为）
    - 剩余 ≤ 5 日 → time_stop_warning 告警
    - 已持有 ≥ 120 日 → time_stop_reached 告警
    - 仅产生告警，**不自动卖出**
    
    返回: {
        "held_days": int,              # 已持有交易日数
        "remaining_days": int,         # 剩余交易日数
        "time_stop_warning": bool,     # 剩余≤5日
        "time_stop_reached": bool,     # 已持有≥120日
        "calendar_fallback": bool,     # 是否用自然日近似
        "entry_date": str,             # 入场日期
    }
    """
    entry_date_str = holding.get("entry_date")
    if not entry_date_str:
        return {
            "held_days": 0,
            "remaining_days": TIME_STOP_TRADING_DAYS,
            "time_stop_warning": False,
            "time_stop_reached": False,
            "calendar_fallback": False,
            "entry_date": None,
            "warnings": ["no_entry_date"],
        }
    
    try:
        if isinstance(entry_date_str, str):
            entry_date = date(int(entry_date_str[:4]), int(entry_date_str[5:7]), int(entry_date_str[8:10]))
        else:
            entry_date = entry_date_str
    except Exception:
        return {
            "held_days": 0,
            "remaining_days": TIME_STOP_TRADING_DAYS,
            "time_stop_warning": False,
            "time_stop_reached": False,
            "calendar_fallback": False,
            "entry_date": entry_date_str,
            "warnings": ["invalid_entry_date_format"],
        }
    
    today = date.today()
    if today <= entry_date:
        return {
            "held_days": 0,
            "remaining_days": TIME_STOP_TRADING_DAYS,
            "time_stop_warning": False,
            "time_stop_reached": False,
            "calendar_fallback": False,
            "entry_date": entry_date_str,
            "warnings": ["entry_date_future"],
        }
    
    # 计算已持有交易日数（复用 risk_rules 交易日历）
    calendar_fallback = False
    try:
        held_days = count_trading_days(entry_date, today)
        # count_trading_days 内部已处理日历缺失降级自然日并打印告警
        # 这里检测是否可能用了自然日近似（简单判断：若交易日历为空）
        from risk_rules import _load_trade_dates
        if not _load_trade_dates():
            calendar_fallback = True
    except Exception:
        # 最终回退：自然日近似
        held_days = (today - entry_date).days
        calendar_fallback = True
    
    remaining_days = TIME_STOP_TRADING_DAYS - held_days
    
    time_stop_warning = remaining_days <= TIME_STOP_WARNING_DAYS
    time_stop_reached = held_days >= TIME_STOP_TRADING_DAYS
    
    warnings = []
    if calendar_fallback:
        warnings.append("calendar_fallback")
    
    return {
        "held_days": held_days,
        "remaining_days": remaining_days,
        "time_stop_warning": time_stop_warning,
        "time_stop_reached": time_stop_reached,
        "calendar_fallback": calendar_fallback,
        "entry_date": entry_date_str,
        "warnings": warnings,
    }


def _fetch_mcp_index_sector_data():
    """通过 MCP mx-ds-mcp 实时查询指数/板块涨跌幅数据
    返回: {"index_10d": {...}, "sector_5d": {...}} 或 None(失败时)
    """
    try:
        import urllib.request, json, ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": "mx_index_block_finance_data",
                "arguments": {
                    "query": (
                        "沪深300、中证500、中证1000、科创50、创业板指"
                        "过去10个交易日的涨跌幅和收盘点数，"
                        "以及有色金属、半导体、煤炭、人工智能、银行、食品饮料"
                        "板块过去5个交易日的涨跌幅"
                    )
                }
            }
        }).encode()
        req = urllib.request.Request(
            "https://mxapi.eastmoney.com/mxds/mcp",
            data=payload, method="POST",
            headers={
                "em_api_key": os.environ.get("EM_API_KEY", ""),
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
                "Accept": "application/json",
                "Origin": "https://www.eastmoney.com",
                "Referer": "https://www.eastmoney.com/",
            },
        )
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        data = json.loads(resp.read().decode())
        result_content = data.get("result", {}).get("content", [])

        # 解析返回的板块/指数数据
        index_10d = {}
        sector_5d = {}
        index_names = {"沪深300", "中证500", "中证1000", "科创50", "创业板指"}
        sector_names = {"有色金属", "半导体", "煤炭", "人工智能", "银行", "食品饮料"}

        for item in result_content:
            if not isinstance(item, dict):
                continue
            text = item.get("text", "") or item.get("title", "") or ""
            name = item.get("name", "") or item.get("code", "") or ""

            # 尝试从文本中提取数值
            import re
            # 查找指数/板块名称
            for idx_name in index_names:
                if idx_name in text or idx_name in name:
                    numbers = re.findall(r'-?\d+\.?\d*', text)
                    if numbers:
                        # 取最后一个数值作为涨跌幅
                        val = float(numbers[-1])
                        # 如果数值过大(>50)可能是点数而非百分比，跳过
                        if abs(val) < 50:
                            index_10d[idx_name] = val

            for sec_name in sector_names:
                if sec_name in text or sec_name in name:
                    numbers = re.findall(r'-?\d+\.?\d*', text)
                    if numbers:
                        val = float(numbers[-1])
                        if abs(val) < 50:
                            sector_5d[sec_name] = val

        # 如果至少获取到部分数据，返回合并且补充默认值
        if index_10d or sector_5d:
            return {
                "index_10d": index_10d,
                "sector_5d": sector_5d,
            }
        return None
    except Exception:
        return None

def detect_market_style(mcp_data=None):
    """
    市场风格分类（使用 mx-ds-mcp MCP工具 查板块数据）

    风格分类:
      - 大盘价值: 沪深300 / 银行 / 食品饮料 涨幅领先
      - 小盘成长: 中证1000 / 中证500 涨幅领先
      - 资源防御: 有色金属 + 煤炭 涨幅领先
      - 科技成长: 科创50 / 半导体 / AI 涨幅领先
      - 均衡: 各风格占比接近

    当top1风格占比 > 60% → 市场高度集中，减仓提示

    返回: {"market_style": str, "style_scores": dict, "concentration": float, "concentration_warning": bool}
    """
    # 默认从已有数据判断（用MCP查询结果）
    if mcp_data is None:
        # 通过 MCP mx-ds-mcp 实时查询指数/板块数据
        mcp_data = _fetch_mcp_index_sector_data()

    # 备用默认值（MCP查询失败时的硬编码回退）
    if mcp_data is None:
        mcp_data = {
            "index_10d": {
                "沪深300": -1.667,
                "中证500": -2.607,
                "中证1000": -2.777,
                "科创50": -0.140,
                "创业板指": -2.647,
            },
            "sector_5d": {
                "有色金属": -4.715,
                "半导体": 0.588,
                "煤炭": -3.172,
                "人工智能": -2.255,
                "银行": 0.313,
                "食品饮料": -1.012,
            },
        }

    # 风格评分
    style_scores = OrderedDict()

    # 大盘价值: 沪深300 + 银行 + 食品饮料
    idx_hs300 = abs(mcp_data.get("index_10d", {}).get("沪深300", 0))
    sector_bank = abs(mcp_data.get("sector_5d", {}).get("银行", 0))
    sector_food = abs(mcp_data.get("sector_5d", {}).get("食品饮料", 0))
    # 使用跌幅的倒数来评分（跌得少=表现好）
    hs300_score = max(0, 5 + mcp_data.get("index_10d", {}).get("沪深300", 0))
    bank_score = max(0, 5 + mcp_data.get("sector_5d", {}).get("银行", 0))
    food_score = max(0, 5 + mcp_data.get("sector_5d", {}).get("食品饮料", 0))
    style_scores["大盘价值"] = round(hs300_score + bank_score + food_score, 2)

    # 小盘成长: 中证1000 + 中证500
    zz1000_score = max(0, 5 + mcp_data.get("index_10d", {}).get("中证1000", 0))
    zz500_score = max(0, 5 + mcp_data.get("index_10d", {}).get("中证500", 0))
    style_scores["小盘成长"] = round(zz1000_score + zz500_score, 2)

    # 科技成长: 科创50 + 半导体 + AI
    kc50_score = max(0, 5 + mcp_data.get("index_10d", {}).get("科创50", 0))
    bdt_score = max(0, 5 + mcp_data.get("sector_5d", {}).get("半导体", 0))
    ai_score = max(0, 5 + mcp_data.get("sector_5d", {}).get("人工智能", 0))
    style_scores["科技成长"] = round(kc50_score + bdt_score + ai_score, 2)

    # 资源防御: 有色金属 + 煤炭
    metal_score = max(0, 5 + mcp_data.get("sector_5d", {}).get("有色金属", 0))
    coal_score = max(0, 5 + mcp_data.get("sector_5d", {}).get("煤炭", 0))
    style_scores["资源防御"] = round(metal_score + coal_score, 2)

    # 找出最高分风格
    total_score = sum(style_scores.values()) or 1
    sorted_styles = sorted(style_scores.items(), key=lambda x: x[1], reverse=True)
    top_style = sorted_styles[0][0]
    top_style_pct = round((sorted_styles[0][1] / total_score) * 100, 1)

    # 浓度判断：top1占比 > 60% → 高度集中
    concentration_warning = top_style_pct > 60

    # 额外信号
    signals = []
    if concentration_warning:
        signals.append({
            "level": "🟡",
            "indicator": f"市场高度集中于「{top_style}」风格({top_style_pct}%)",
            "suggestion": "风格集中时注意轮动风险，适当分散持仓",
            "severity": "warning",
        })

    # 风格占比格式化
    style_pcts = {}
    for k, v in style_scores.items():
        style_pcts[k] = round((v / total_score) * 100, 1)

    return {
        "market_style": top_style,
        "style_scores_raw": style_scores,
        "style_pcts": style_pcts,
        "concentration": top_style_pct,
        "concentration_warning": concentration_warning,
        "signals": signals,
        "mcp_data_used": mcp_data,
    }

def check_position_limit(market_style_info=None, holdings_data=None):
    """
    仓位合规检查
    根据市场状态计算建议最大仓位，对比当前仓位

    规则:
      - 弱市/恐慌: <= 50%
      - 震荡:      <= 70%
      - 牛市/突破/强: <= 90%

    返回: {"current_position_pct": float, "max_allowed_pct": int,
           "market_state": str, "signals": [...], "compliant": bool}
    """
    if holdings_data is None:
        holdings_data = load_json(HOLDINGS_FILE)

    if not holdings_data:
        return {"current_position_pct": 0, "max_allowed_pct": 50,
                "market_state": "未知", "signals": [], "compliant": True}

    # 兼容数组格式 holdings (portfolio_review 支持 list, 此处做防御)
    if isinstance(holdings_data, list):
        holdings_list = holdings_data
        cash = 0
    else:
        holdings_list = holdings_data.get("holdings", [])
        cash = holdings_data.get("available_cash", 0)

    def _resolve_price(h):
        """优先用 current_price，缺失时从 TDX 取最新收盘价"""
        cp = h.get("current_price")
        if cp:
            return float(cp)
        code = str(h.get("code", ""))
        if not code:
            return 0
        try:
            from core.pipeline.tdx_core import get_tdx_data
            recs = get_tdx_data(code, 3)
            if recs:
                return float(recs[-1]["close"])
        except Exception:
            pass
        return 0

    total_stock_value = sum(
        _resolve_price(h) * h.get("shares", 0) for h in holdings_list
    )
    total_assets = total_stock_value + cash
    position_pct = round((total_stock_value / total_assets) * 100, 1) if total_assets > 0 else 0

    # 市场状态映射（从市场风格推导）
    if market_style_info is None:
        market_state = "震荡"  # 默认
    else:
        style = market_style_info.get("market_style", "均衡")
        concentration = market_style_info.get("concentration", 0)

        # 优先使用市场状态统一出口 (market_state_engine.get_fresh_market_state, 内置TTL)
        # 2026-08-13 方向4 单源化: 原直接读 market_state_cache.json 绕过引擎TTL(8/12早报用7h旧缓存报弱市50%)
        # 改走引擎统一出口 — 缓存过期自动重算, 各消费方口径一致
        try:
            from market_state_engine import get_fresh_market_state
            m = get_fresh_market_state(cache_ttl=300)
            ms_label = (m or {}).get("market_label", "")
            if ms_label:
                # market_state_engine label → risk_monitor market_state
                label_map = {
                    "恐慌": "恐慌",
                    "弱": "弱市",
                    "震荡": "震荡",
                    "偏暖": "偏暖",
                    "强": "强",
                    "极强": "牛市",
                }
                market_state = label_map.get(ms_label, "震荡")
        except Exception:
            pass

        # 回退: 如果缓存缺失, 用 MCP 指数数据判断
        if market_state == "震荡" and market_style_info.get("mcp_data_used"):
            mcp_data = market_style_info.get("mcp_data_used", {})
            idx_data = mcp_data.get("index_10d", {})

            # 如果主要指数近10日全面下跌且跌幅大 → 弱市
            hs300_10d = idx_data.get("沪深300", 0)
            zz1000_10d = idx_data.get("中证1000", 0)
            avg_10d = (hs300_10d + zz1000_10d) / 2

            if avg_10d < -3:
                market_state = "恐慌"
            elif avg_10d < -1.5:
                market_state = "弱市"
            elif concentration > 60 and style in ("科技成长",):
                market_state = "突破"
            elif concentration > 50:
                market_state = "震荡"
            else:
                market_state = "震荡"

    max_allowed = POSITION_LIMITS.get(market_state, 50)
    compliant = position_pct <= max_allowed

    signals = []
    if not compliant:
        over_pct = position_pct - max_allowed
        signals.append({
            "level": "🔴" if over_pct > 20 else "🟡",
            "indicator": f"仓位{position_pct}%超过{market_state}建议上限{max_allowed}%",
            "suggestion": f"当前{market_state}市场, 建议减仓至{max_allowed}%以下(需减{over_pct:.0f}个百分点)",
            "severity": "emergency" if over_pct > 20 else "warning",
        })
    else:
        signals.append({
            "level": "🟢",
            "indicator": f"仓位{position_pct}%在{market_state}市场安全范围内(≤{max_allowed}%)",
            "suggestion": "",
            "severity": "ok",
        })

    return {
        "current_position_pct": position_pct,
        "max_allowed_pct": max_allowed,
        "market_state": market_state,
        "compliant": compliant,
        "over_pct": round(position_pct - max_allowed, 1),
        "signals": signals,
        "cash": cash,
        "total_stock_value": total_stock_value,
        "total_assets": total_assets,
    }

def calculate_risk_score(all_signals):
    """
    计算风控评分 (0-100)
    初始100分，按风险信号扣分
    """
    score = 100
    deductions = []

    for s in all_signals:
        level = s.get("level", "")
        severity = s.get("severity", "")
        indicator = s.get("indicator", "")

        if level == "🔴" or severity == "emergency":
            deduction = 20
        elif level == "🟡" or severity == "warning":
            deduction = 10
        elif level == "🟢" or severity == "ok":
            deduction = 0
        else:
            deduction = 5

        if deduction > 0:
            score -= deduction
            deductions.append(f"{indicator} (-{deduction}分)")

    score = max(0, min(100, score))
    return score, deductions

# ─── 每日风控报告 ──────────────────────────────────────────────

def generate_daily_report(mcp_data=None, send_push=False):
    """
    生成每日风控报告JSON

    整合所有监控维度的结果，输出结构化JSON报告
    """
    print("=" * 60)
    print("📊 A股风险监控系统 v1.0")
    print(f"日期: {get_today_str()}")
    print("=" * 60)

    # 1. 回撤监控
    print("\n📉 1. 回撤监控")
    drawdown_result = check_drawdown()
    for s in drawdown_result.get("signals", []):
        icon = s.get("level", "📊")
        print(f"   {icon} {s['indicator']}")

    # 2. 连续亏损检测
    print("\n🔗 2. 连续亏损检测")
    streak_result = check_losing_streak()
    if streak_result.get("signals"):
        for s in streak_result["signals"]:
            print(f"   {s['level']} {s['indicator']}")
            print(f"     建议: {s['suggestion']}")
    else:
        if streak_result.get("total_followed_trades", 0) >= MIN_POSITION_CHECK:
            print(f"   ✅ 无连续亏损 (最近{streak_result['consecutive_losses']}笔)")
        else:
            print(f"   ⚪ 交易记录不足 ({streak_result.get('total_followed_trades', 0)}笔, 需≥{MIN_POSITION_CHECK}笔)")

    # 3. 市场风格检测
    print("\n🎯 3. 市场风格检测")
    style_result = detect_market_style(mcp_data)
    print(f"   当前市场风格: {style_result['market_style']}")
    print(f"   风格占比: {style_result['style_pcts']}")
    if style_result["concentration_warning"]:
        print(f"   🟡 注意: 市场高度集中于「{style_result['market_style']}」({style_result['concentration']}%)")
    for s in style_result.get("signals", []):
        print(f"   {s['level']} {s['indicator']}")

    # 4. 仓位合规检查
    print("\n💼 4. 仓位合规检查")
    position_result = check_position_limit(style_result)
    print(f"   当前仓位: {position_result['current_position_pct']}%")
    print(f"   市场状态: {position_result['market_state']}")
    print(f"   建议上限: {position_result['max_allowed_pct']}%")
    print(f"   合规状态: {'✅ 合规' if position_result['compliant'] else '🔴 超仓'}")
    for s in position_result.get("signals", []):
        print(f"   {s['level']} {s['indicator']}")
        if s.get("suggestion"):
            print(f"     建议: {s['suggestion']}")

    # 5. S3 移动止盈阶梯检查（R0-20261009）
    print("\n📈 5. 移动止盈阶梯 (S3吃大肉五档)")
    holdings_data = load_json(HOLDINGS_FILE)
    holdings_list = holdings_data.get("holdings", []) if holdings_data else []
    trailing_alerts = []
    if holdings_list:
        for h in holdings_list:
            tp_result = check_trailing_take_profit(h)
            code = h.get("code", "")
            name = h.get("name", "")
            if tp_result["lock_price"] is not None:
                print(f"   {name}({code}) 浮盈{tp_result['floating_pnl_pct']:.1f}% → 第{tp_result['current_tier']}档 锁价={tp_result['lock_price']:.2f} (峰值{tp_result['peak_price']:.2f}×{1-tp_result.get('lock_tolerance',0):.0%})")
            else:
                print(f"   {name}({code}) 浮盈{tp_result['floating_pnl_pct']:.1f}% → 未达首档激活(6%)")
            if tp_result["alert_triggered"]:
                trailing_alerts.append({
                    "level": "🟡",
                    "indicator": f"{name}({code}) 现价≤移动止盈锁价({tp_result['lock_price']:.2f})",
                    "suggestion": f"分批止盈触发，已触发{tp_result['triggered_tiers']}档",
                    "severity": "warning",
                })
            if tp_result["warnings"]:
                for w in tp_result["warnings"]:
                    trailing_alerts.append({
                        "level": "⚪",
                        "indicator": f"{name}({code}) {w}",
                        "suggestion": "",
                        "severity": "info",
                    })
    else:
        print("   无持仓，跳过移动止盈检查")

    # 6. S3 时间止损检查（R0-20261009）
    print("\n⏰ 6. 时间止损 (120交易日契约)")
    time_alerts = []
    if holdings_list:
        for h in holdings_list:
            ts_result = check_time_stop(h)
            code = h.get("code", "")
            name = h.get("name", "")
            print(f"   {name}({code}) 持有{ts_result['held_days']}日 剩余{ts_result['remaining_days']}日", end="")
            if ts_result["time_stop_reached"]:
                print(" → 🔴 已达120日时间止损")
            elif ts_result["time_stop_warning"]:
                print(" → 🟡 预警：剩余≤5日")
            else:
                print(" → ✅ 正常")
            if ts_result["time_stop_reached"]:
                time_alerts.append({
                    "level": "🔴",
                    "indicator": f"{name}({code}) 持仓已达{ts_result['held_days']}交易日，触发时间止损",
                    "suggestion": "建议评估是否清仓，120日契约硬性到期",
                    "severity": "emergency",
                })
            elif ts_result["time_stop_warning"]:
                time_alerts.append({
                    "level": "🟡",
                    "indicator": f"{name}({code}) 持仓剩余{ts_result['remaining_days']}交易日，接近时间止损",
                    "suggestion": "密切关注，准备应对120日到期",
                    "severity": "warning",
                })
            if ts_result["warnings"]:
                for w in ts_result["warnings"]:
                    time_alerts.append({
                        "level": "⚪",
                        "indicator": f"{name}({code}) {w}",
                        "suggestion": "",
                        "severity": "info",
                    })
    else:
        print("   无持仓，跳过时间止损检查")

    # 7. 综合所有风险信号
    all_signals = (
        drawdown_result.get("signals", [])
        + streak_result.get("signals", [])
        + style_result.get("signals", [])
        + position_result.get("signals", [])
        + trailing_alerts
        + time_alerts
    )

    # 过滤掉信息性信号（非风险类）
    risk_signals = [s for s in all_signals if s.get("severity") in ("emergency", "warning")]

    risk_score, deductions = calculate_risk_score(all_signals)

    # 构建报告
    # 汇总持仓级 S3 检查结果
    trailing_summary = []
    time_stop_summary = []
    if holdings_list:
        for h in holdings_list:
            tp_result = check_trailing_take_profit(h)
            trailing_summary.append({
                "code": h.get("code", ""),
                "name": h.get("name", ""),
                "lock_price": tp_result["lock_price"],
                "triggered_tiers": tp_result["triggered_tiers"],
                "current_tier": tp_result["current_tier"],
                "floating_pnl_pct": tp_result["floating_pnl_pct"],
                "peak_price": tp_result["peak_price"],
                "alert_triggered": tp_result["alert_triggered"],
                "warnings": tp_result["warnings"],
            })
            ts_result = check_time_stop(h)
            time_stop_summary.append({
                "code": h.get("code", ""),
                "name": h.get("name", ""),
                "held_days": ts_result["held_days"],
                "remaining_days": ts_result["remaining_days"],
                "time_stop_warning": ts_result["time_stop_warning"],
                "time_stop_reached": ts_result["time_stop_reached"],
                "calendar_fallback": ts_result["calendar_fallback"],
                "entry_date": ts_result["entry_date"],
                "warnings": ts_result["warnings"],
            })

    report = {
        "report_date": get_today_str(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "risk_score": risk_score,
        "risk_level": "🔴 高风险" if risk_score < 60 else ("🟡 中等风险" if risk_score < 80 else "🟢 低风险"),
        "account_status": {
            "total_assets": position_result.get("total_assets", 0),
            "stock_value": position_result.get("total_stock_value", 0),
            "cash": position_result.get("cash", 0),
            "position_pct": position_result.get("current_position_pct", 0),
            "total_pnl_pct": drawdown_result.get("total_pnl_pct", 0),
            "max_drawdown": drawdown_result.get("max_drawdown", 0),
        },
        "market": {
            "style": style_result.get("market_style", "未知"),
            "style_pcts": style_result.get("style_pcts", {}),
            "market_state": position_result.get("market_state", "未知"),
            "concentration_pct": style_result.get("concentration", 0),
            "concentration_warning": style_result.get("concentration_warning", False),
        },
        "position_control": {
            "current_pct": position_result.get("current_position_pct", 0),
            "max_allowed_pct": position_result.get("max_allowed_pct", 50),
            "market_state": position_result.get("market_state", "未知"),
            "compliant": position_result.get("compliant", True),
            "over_pct": position_result.get("over_pct", 0),
        },
        "drawdown": {
            "total_pnl_pct": drawdown_result.get("total_pnl_pct", 0),
            "max_stock_drawdown": drawdown_result.get("max_drawdown", 0),
            "stock_count": len(drawdown_result.get("stock_pnls", [])),
        },
        "losing_streak": {
            "consecutive_losses": streak_result.get("consecutive_losses", 0),
            "max_consecutive_losses": streak_result.get("max_consecutive_losses", 0),
            "total_followed_trades": streak_result.get("total_followed_trades", 0),
        },
        "trailing_take_profit": trailing_summary,      # R0-20261009 S3移动止盈
        "time_stop": time_stop_summary,                # R0-20261009 S3时间止损
        "risk_signals": risk_signals,
        "all_signals": all_signals,
        "score_deductions": deductions,
        "recommended_action": _get_recommended_action(risk_score, position_result, streak_result),
    }

    # 保存报告
    save_json(RISK_REPORT_FILE, report)
    print(f"\n{'=' * 60}")
    print(f"📋 风控报告已保存: {RISK_REPORT_FILE}")
    print(f"🏆 风控评分: {risk_score}/100 ({report['risk_level']})")
    
    # 持仓风险触发三方讨论（Ponytail: 复用debate_trigger）
    total_pnl = report.get("account_status", {}).get("total_pnl_pct", 0)
    max_dd = report.get("drawdown", {}).get("max_stock_drawdown", 0)
    streak = streak_result.get("consecutive_losses", 0)
    if total_pnl < -15 or max_dd < -20 or streak >= 5:
        from debate_trigger import trigger_debate
        trigger_debate("position_risk", {
            "total_pnl_pct": total_pnl,
            "max_drawdown": max_dd,
            "consecutive_losses": streak,
        })

    return report

def _get_recommended_action(risk_score, position_result, streak_result):
    """根据风控评分生成建议"""
    actions = []

    if streak_result.get("consecutive_losses", 0) >= CONSECUTIVE_LOSS_EMERGENCY:
        actions.append("🔴 紧急: 连续亏损达到上限, 建议暂停策略")
    elif streak_result.get("consecutive_losses", 0) >= CONSECUTIVE_LOSS_WARN:
        actions.append("🟡 警告: 连续亏损中, 关注后续交易")

    if not position_result.get("compliant", True):
        actions.append(f"🔴 仓位超限: 需减仓至{position_result['max_allowed_pct']}%以下")

    if risk_score < 60:
        actions.append("🔴 风控评分过低, 建议全面审查策略")
    elif risk_score < 80:
        actions.append("🟡 存在一定风险, 保持警惕")

    if not actions:
        actions.append("🟢 一切正常, 维持当前策略")

    return actions

# ═══════════════════════════════════════════
#  5层系统健康检查（Hermes生态参考）
# ═══════════════════════════════════════════

def health_check():
    """5层系统健康检查：Provider连通性 → MCP进程 → 系统资源 → 配置一致性 → 逻辑健康"""
    print(f"{'='*50}")
    print(f"  🏥 系统健康检查 (5层)")
    print(f"{'='*50}")
    status = {"layers": {}, "overall": "green"}
    all_ok = True

    # Layer 1: Provider连通性
    print(f"\n  L1 🔌 Provider连通性:")
    for provider in ["TDX数据", "东财行情"]:
        if provider == "TDX数据":
            from core.pipeline.tdx_core import get_tdx_data
            test = get_tdx_data("sz002415", 5)  # 用实际股票而非指数
            ok = test is not None and len(test) > 0
            print(f"     {'✅' if ok else '❌'} {provider}")
            all_ok &= ok
        elif provider == "东财行情":
            from core.pipeline.tdx_core import get_industry_heat
            try:
                heat = get_industry_heat(force_refresh=True)
                print(f"     {'✅' if heat else '⚠️(已降级)'} {provider}")
            except Exception as e:
                # P0-2修复: 补异常原因
                print(f"     ⚠️ {provider} (已降级内置数据): {e}")
    status["layers"]["L1_provider"] = "ok" if all_ok else "degraded"

    # Layer 2: 数据文件完整性
    print(f"\n  L2 📁 数据文件:")
    for f in ["holdings.json", "industries.json", "stock_names.json", "trade_log.json"]:
        size = os.path.getsize(f) if os.path.exists(f) else 0
        ok = size > 10
        print(f"     {'✅' if ok else '❌'} {f} ({size//1024}KB)")
        all_ok &= ok

    # Layer 3: 系统资源
    print(f"\n  L3 💻 系统资源:")
    try:
        import psutil
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.5)
        disk = psutil.disk_usage(".")
        mem_ok = mem.percent < 90
        cpu_ok = cpu < 80
        disk_ok = disk.percent < 90
        print(f"     {'✅' if mem_ok else '⚠️'} 内存: {mem.percent}%")
        print(f"     {'✅' if cpu_ok else '⚠️'} CPU: {cpu}%")
        print(f"     {'✅' if disk_ok else '⚠️'} 磁盘: {disk.percent}%")
        all_ok &= mem_ok & disk_ok
    except ImportError:
        print(f"     ⚠️ psutil未安装, 跳过资源检测")

    # Layer 4: 配置一致性
    print(f"\n  L4 ⚙️ 配置一致性:")
    cfg_ok = os.path.exists("config.json") and os.path.exists("backtest.py")
    print(f"     {'✅' if cfg_ok else '❌'} 核心文件完整性")
    all_ok &= cfg_ok

    # Layer 5: 逻辑健康（风控指标）
    print(f"\n  L5 🎯 逻辑健康:")
    try:
        report_json = generate_daily_report()
        signals = report_json.get("risk_signals", [])
        sig_ok = len(signals) == 0
        print(f"     {'✅' if sig_ok else '⚠️'} 风险信号: {len(signals)}个")
        # 修复: position_rate 键不存在, 实际在 position_control.current_pct
        pos = report_json.get("position_rate", 0)
        pos_ctl = report_json.get("position_control", {})
        if isinstance(pos_ctl, dict) and pos_ctl.get("current_pct") is not None:
            pos = pos_ctl.get("current_pct")
        print(f"     {'✅' if pos < 90 else '⚠️'} 仓位: {pos}%")
    except Exception as e:
        # P0-2修复: 风控失败=裸奔, 必须打WARNING(不静默)
        sig_ok = False
        logger.warning("【P0-2修复】风控报告生成失败, 健康检查降级为异常: %s", e, exc_info=True)
        print(f"     ❌ 风控报告生成失败: {e}")
    all_ok &= sig_ok

    status["overall"] = "green" if all_ok else "yellow"
    print(f"\n  {'='*30}")
    print(f"  🟢 系统健康" if all_ok else "🟡 部分降级")
    print(f"  {'='*30}")
    return status

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="A股风控监控系统")
    parser.add_argument("--report", action="store_true", help="仅生成报告")
    parser.add_argument("--push", action="store_true", help="生成报告并推送告警")
    args = parser.parse_args()

    # 生成风控报告
    report = generate_daily_report(mcp_data=None, send_push=args.push)

    if args.push:
        # 如果有紧急或警告信号，推送告警
        if report.get("risk_signals"):
            print(f"\n📤 发现{len(report['risk_signals'])}个风险信号，发起推送...")
            # 这里调用 risk_alerter 来推送
            try:
                from core.ops.risk_alerter import alert_risk
                alert_risk(report)
            except ImportError:
                print("   ⚠️ risk_alerter.py 未找到，跳过推送")
        else:
            print("\n✅ 无风险信号，不推送")

    print(f"\n📁 报告文件: {RISK_REPORT_FILE}")
