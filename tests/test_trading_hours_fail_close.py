#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_trading_hours_fail_close.py — G13 日历新鲜度 fail-close 行为级测试

背景 (10-20 回滚事故审查认定的高危缺口):
  G13 修复 (提交 ee9c799e) 前, trading_hours 存在"告警纯装饰"问题:
    1. _check_calendar_freshness() 开头 `if _calendar_warned: return True` ——
       告警去重标记被拿来短路判定, 第 2 次调用起恒谎报"新鲜";
    2. is_trading_hours() 裸调用丢弃返回值 —— 打印了"将 fail-CLOSE"却从不 return False。
  既有 16 条 tests/test_trading_hours.py 用例在修复前的代码上实测全绿 (审查记录),
  即对该问题零检测能力, 唯一防线是 guard 源码正则。本文件专补行为级防线:
    - 陈旧态真锁死: 工作日盘中必须返回 False (修调用点丢弃返回值);
    - 二次调用不短路: 陈旧态下连续判定每次都判陈旧 (专防 _calendar_warned 短路复活);
    - 新鲜态不误伤: 真实日历下工作日盘中仍返回 True;
    - 告警打印去重仍生效: 不得因修 fail-close 而刷屏。

  降级自证 (2026-10-21 已完成): 用 git ee9c799e^ 的修复前 trading_hours.py 在 temp
  复跑本文件, "陈旧态真锁死/二次调用不短路"等断言全部转红; 恢复后全绿
  (原始输出见交付报告)。

实现要点:
  - 经 monkeypatch 替换 trading_hours._get_forward_pulled_at / _load_forward_trade_dates
    构造陈旧态 (pulled_at 30 天前, 新鲜度阈值 7 天), 不改生产 data/trading_calendar.json。
  - 探测时间避开周末快路径 (周末 False 与 fail-close 无关, 会稀释测试强度)。
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import trading_hours


@pytest.fixture(autouse=True)
def _reset_calendar_warned(monkeypatch):
    """每条用例重置告警去重标记, 防跨用例状态泄漏 (monkeypatch 自动复原)。"""
    monkeypatch.setattr(trading_hours, "_calendar_warned", False)


def _weekday_probe() -> datetime:
    """最近一个工作日 10:00 (避开周末快路径; 今天若为周末则回退到上周五)。"""
    d = date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return datetime(d.year, d.month, d.day, 10, 0)


def _fresh_trading_day_probe() -> datetime:
    """真实日历中"最近的一个交易日" 10:00 —— 保证探测日确实在日历白名单内。

    从真实 trading_calendar.json 取 <= 今天的最大日期, 避免节假日/周末误判。
    """
    dates = sorted(trading_hours._load_forward_trade_dates())
    today = date.today()
    past = [d for d in dates if d <= today]
    d = past[-1] if past else today
    return datetime(d.year, d.month, d.day, 10, 0)


@pytest.fixture
def stale_calendar(monkeypatch):
    """构造陈旧态: pulled_at 改为 30 天前 (新鲜度阈值 7 天)。

    日历覆盖集含探测日与今天, 精准触发条件3 (pulled_at 陈旧), 不触发条件2。
    """
    today = date.today()
    probe = _weekday_probe()
    covered = {today, probe.date()}
    monkeypatch.setattr(trading_hours, "_load_forward_trade_dates", lambda: set(covered))
    monkeypatch.setattr(
        trading_hours, "_get_forward_pulled_at",
        lambda: (today - timedelta(days=30)).isoformat())
    return probe


class TestStaleCalendarFailClose:
    """陈旧态: 判定必须 fail-CLOSE (False), 且每次调用都真判, 不被去重标记短路。"""

    def test_stale_locks_down_is_trading_hours(self, stale_calendar):
        """陈旧态真锁死: 工作日盘中 10:00 -> False。

        修复前裸调用 _check_calendar_freshness() 丢弃返回值 -> 恒 True, 本条专防。
        """
        assert trading_hours.is_trading_hours(stale_calendar) is False

    def test_repeated_freshness_checks_never_short_circuit(self, stale_calendar):
        """二次调用不短路 (最关键): 陈旧态下连续判定 3 次, 每次都返回 False。

        专防 `if _calendar_warned: return True` 复活 —— 该短路第 2 次调用起恒 True。
        """
        results = [trading_hours._check_calendar_freshness() for _ in range(3)]
        assert results == [False, False, False], (
            f"重复判定被短路/谎报新鲜: {results} (预期全 False)")

    def test_repeated_is_trading_hours_never_short_circuit(self, stale_calendar):
        """is_trading_hours 层重复调用同样不得放行 (调用点接返回值的回归)。"""
        results = [trading_hours.is_trading_hours(stale_calendar) for _ in range(3)]
        assert results == [False, False, False], (
            f"is_trading_hours 重复调用被放行: {results} (预期全 False)")


class TestFreshCalendarNotHarmed:
    """新鲜态: 不得误伤 —— 真实日历下工作日盘中仍为 True。

    注: 直读仓库真实 data/trading_calendar.json, 依赖 cron 刷新保持新鲜
    (当前覆盖至 2026-12-31, pulled_at 2026-10-20); 若未来日历超 7 天未刷新,
    本条按 fail-close 语义转红属预期 (提醒该刷日历)。
    """

    def test_fresh_trading_day_in_session_returns_true(self):
        probe = _fresh_trading_day_probe()
        # 前置确认真实日历处于新鲜态, 避免"因日历陈旧而误红"归因错误
        assert trading_hours._check_calendar_freshness() is True, "前置: 真实日历应为新鲜态"
        assert trading_hours.is_trading_hours(probe) is True


class TestWarningDedupStillWorks:
    """告警打印去重: 修 fail-close 不得导致告警刷屏。"""

    def test_stale_warning_printed_once(self, stale_calendar, capsys):
        """陈旧态触发 5 次, stderr 告警只打印 1 次 (去重), 且判定每次仍 fail-close。"""
        for _ in range(5):
            assert trading_hours._check_calendar_freshness() is False
        captured = capsys.readouterr()
        warn_count = captured.err.count("日历陈旧告警")
        assert warn_count == 1, f"告警去重失效: 打印 {warn_count} 次 (应为 1 次)"
