#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trading_hours.py — A股交易时段防护函数

目的：修复 09-20 永鼎盘后误操作事故根因 —— 盘后任何自动仓位动作(减仓/平仓/登记)
      -> 只告警不动仓，非交易时段返回 False 阻止后续写 holdings/trade_log

TDD 纪律：期望值只来自公开规则（A股交易时段定义），禁止从代码反抄。
          规则真源：docs/交易规则追溯矩阵-v1.md + docs/裁定落档-D1D6-20261009.md

A股交易时段（公开规则）：
  上午盘：09:30 - 11:30
  下午盘：13:00 - 15:00
  休市：  11:30-13:00, 15:00-次日09:30, 周末

P2fix (2026-10-09): 改黑名单为白名单 —— 用 risk_rules._load_trade_dates()
                    的 sh_index_history.json 日历源判定"是否交易日"，
                    日历缺失时 fail-CLOSE (返回 False)。

R0-FwdA (2026-10-09): forward-aware 前置——is_trading_hours 改用
                       data/trading_calendar.json（akshare sina 拉取，含未来日期），
                       使 is_trading_hours(今天 盘内) 能证"今天是交易日"。
                       时间段判定（09:30-11:30/13:00-15:00）不变。
                       周末判定保留（快路径+双保险）。
                       时间止损继续用 bar 日历（sh_index_history.json），不动。
"""
import sys
import json
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, date
from typing import Optional, Set

PROJECT = PROJECT_ROOT

# R0-FwdA: forward calendar 路径
_FORWARD_CALENDAR_PATH = os.path.join(PROJECT, "data", "trading_calendar.json")

# R0-FwdA: 日历陈旧告警阈值（天）
_CALENDAR_FRESHNESS_DAYS = 7

# P4fix: 日历陈旧告警进程内去重标记
_calendar_warned = False


def _load_forward_trade_dates() -> Set[date]:
    """加载 forward-aware 交易日集（白名单）。

    数据源：data/trading_calendar.json（akshare sina 拉取，含未来日期）。
    失败返回空集触发 fail-CLOSE。
    """
    try:
        if not os.path.exists(_FORWARD_CALENDAR_PATH):
            return set()
        with open(_FORWARD_CALENDAR_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        dates = []
        for item in (payload.get("data") or []):
            ds = item.get("date")
            if isinstance(ds, str):
                try:
                    dates.append(date.fromisoformat(ds))
                except ValueError:
                    print(f"⚠️ [日历解析异常] 跳过无效日期 {ds!r}", file=sys.stderr)
        return set(dates)
    except Exception as e:
        print(f"⚠️ [日历加载失败] {e}", file=sys.stderr)
        return set()


def _get_forward_pulled_at() -> Optional[str]:
    """读取 trading_calendar.json 的 pulled_at 字段（用于 freshness 检查）。"""
    try:
        if not os.path.exists(_FORWARD_CALENDAR_PATH):
            return None
        with open(_FORWARD_CALENDAR_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("pulled_at")
    except Exception as e:
        print(f"⚠️ [pulled_at读取失败] {e}", file=sys.stderr)
        return None


def _parse_dt(now, tz=None) -> datetime:
    """统一解析 now 参数为 datetime。"""
    if isinstance(now, datetime):
        dt = now
    elif isinstance(now, date):
        dt = datetime(now.year, now.month, now.day)
    elif isinstance(now, str):
        # 兼容 YYYY-MM-DD 和 YYYY-MM-DD HH:MM
        dt = datetime.strptime(now.strip(), "%Y-%m-%d %H:%M")
    else:
        raise TypeError(f"is_trading_hours: 不支持的 now 类型 {type(now).__name__}")
    return dt


def _calendar_stale_reason() -> Optional[str]:
    """纯陈旧判定：返回陈旧原因文案，None=新鲜。

    ⚠️ 每次调用都真跑三个条件，绝不受 _calendar_warned 影响 ——
    去重标记只能控制「打印」，一旦拿来短路判定，第二次调用起就会恒谎报新鲜
    （本仓库头号病史：校验存在但静默不生效）。
    """
    try:
        today = date.today()
        forward_dates = _load_forward_trade_dates()

        # 1. 日历缺失
        if not forward_dates:
            return "trading_calendar.json 不可用或未生成（系统锁死中）"

        # 2. 未覆盖今天
        max_date = max(forward_dates)
        if today > max_date:
            return f"最新 {max_date} < 今日 {today}（日历未覆盖今天）"

        # 3. pulled_at 陈旧 > 7 天
        pulled_at_str = _get_forward_pulled_at()
        if pulled_at_str:
            try:
                pulled_dt = datetime.fromisoformat(pulled_at_str)
            except ValueError:
                print(f"⚠️ [pulled_at解析异常] 无法解析 pulled_at={pulled_at_str!r}，降级为不检查陈旧",
                      file=sys.stderr)
                return None
            days_since_pull = (today - pulled_dt.date()).days
            if days_since_pull > _CALENDAR_FRESHNESS_DAYS:
                return (f"pulled_at={pulled_at_str} 距今 {days_since_pull} 天 "
                        f"> {_CALENDAR_FRESHNESS_DAYS} 天阈值（系统锁死中）")

        return None
    except Exception as e:
        # fail-close: 检查过程本身异常也判陈旧
        return f"日历检查异常: {e}"


def _calendar_is_fresh() -> bool:
    """纯新鲜度判定（无副作用的每次真跑）：True=新鲜, False=陈旧。"""
    return _calendar_stale_reason() is None


def _check_calendar_freshness() -> bool:
    """日历新鲜度监控 + 告警打印去重外壳 (R0-FwdA: forward 语义)。

    fail-close 条件（任一满足即判陈旧）:
      1. 日历文件缺失
      2. today > max(dates)（未覆盖今天）
      3. pulled_at 距今天 > 7 天

    返回 True=新鲜, False=陈旧；返回值恒等于 _calendar_is_fresh() 的真实结果，
    _calendar_warned 只控制「是否打印」，不得影响判定。
    """
    global _calendar_warned
    reason = _calendar_stale_reason()
    if reason is not None and not _calendar_warned:
        print(f"⚠️ [日历陈旧告警] {reason}", file=sys.stderr)
        print(f"    所有 weekday 盘内时段将 fail-CLOSE", file=sys.stderr)
        _calendar_warned = True
    return reason is None


def is_trading_hours(now, tz=None, holidays: Optional[Set[str]] = None) -> bool:
    """
    判断当前时间是否为 A股有效交易时段（白名单模式 + forward-aware）。

    Args:
        now: datetime | date | str(YYYY-MM-DD[ HH:MM])
        tz:  timezone 对象，None 则用系统本地时间
        holidays: 保留参数（向后兼容），实际不再使用

    Returns:
        bool: True=交易中，False=非交易时段（盘前/盘后/午休/周末/假期/日历缺失）

    A股交易时段（公开规则，禁止反抄代码）：
        上午盘：09:30 - 11:30
        下午盘：13:00 - 15:00
        休市判定：周末、法定节假日、日历缺失/陈旧 -> False（fail-CLOSE）
    """
    dt = _parse_dt(now, tz)
    day_of_week = dt.weekday()  # 0=周一, 6=周日

    # R0-FwdA: 日历新鲜度 fail-CLOSE
    # ⚠️ 2026-10-20 修: 原实现裸调用 _check_calendar_freshness() 丢弃返回值，
    #   打印了「将 fail-CLOSE（系统锁死中）」却从不 return False —— 告警纯装饰。
    #   此处必须接返回值，否则 docstring 承诺的 fail-CLOSE 不成立。
    if not _check_calendar_freshness():
        return False

    # 周末判定（快路径 + 双保险）
    if day_of_week >= 5:
        return False

    # R0-FwdA: 用 forward calendar 判定"今天是交易日"
    forward_dates = _load_forward_trade_dates()
    today = dt.date()
    if today not in forward_dates:
        return False  # 假期或日历缺失/陈旧 -> fail-CLOSE

    hour = dt.hour
    minute = dt.minute

    # 上午盘：09:30 - 11:30
    if (hour, minute) >= (9, 30) and (hour, minute) < (11, 30):
        return True

    # 下午盘：13:00 - 15:00
    if (hour, minute) >= (13, 0) and (hour, minute) < (15, 0):
        return True

    return False
