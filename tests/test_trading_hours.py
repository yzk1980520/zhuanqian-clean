#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_trading_hours.py — S6 交易时段防护测试（R0-FwdA forward-aware 模式）

验收断言（期望值来自独立源 = akshare sina 日历 + 公开2026 A股休市安排）：
  - 2026-10-09 10:00 -> True（核心目标：今天盘内是交易日）
  - 2026-10-10 10:00 -> False（周六）
  - 2026-10-01 10:00 -> False（国庆节，sina 日历确认非交易日）
  - 2026-02-17~02-23 春节区间任一 10:00 -> False（若 sina 日历含春节休市，据实；拉不到就如实标"未验证"）
  - forward calendar 文件缺失 -> 任意 weekday 盘内 -> False（fail-close 保持）
  - forward calendar pulled_at 30天前 -> fail-close/告警
"""
import json
import os
import sys
from datetime import datetime, timedelta, date
from pathlib import Path
from unittest.mock import patch, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestTradingHoursForwardAware:
    """A股交易时段判定（forward-aware 白名单模式）：交易日 + 交易时段双条件。"""

    def test_today_trading_day_in_session(self):
        """核心目标：2026-10-09 10:00 盘内 -> True"""
        from trading_hours import is_trading_hours
        dt = datetime(2026, 10, 9, 10, 0)
        assert is_trading_hours(dt) is True

    def test_weekend_not_in_calendar(self):
        """周六 2026-10-10 10:00 -> False（周末快路径）"""
        from trading_hours import is_trading_hours
        dt = datetime(2026, 10, 10, 10, 0)
        assert is_trading_hours(dt) is False

    def test_holiday_not_in_calendar(self):
        """国庆 2026-10-01 不在 sina 日历 -> False"""
        from trading_hours import is_trading_hours
        dt = datetime(2026, 10, 1, 10, 0)
        assert is_trading_hours(dt) is False

    def test_trading_day_morning(self):
        """交易日 2026-09-30 上午盘 -> True"""
        from trading_hours import is_trading_hours
        dt = datetime(2026, 9, 30, 10, 0)
        assert is_trading_hours(dt) is True

    def test_trading_day_afternoon(self):
        """交易日 2026-09-30 下午盘 -> True"""
        from trading_hours import is_trading_hours
        dt = datetime(2026, 9, 30, 14, 0)
        assert is_trading_hours(dt) is True

    def test_trading_day_pre_open(self):
        """交易日 2026-09-30 盘前 -> False"""
        from trading_hours import is_trading_hours
        dt = datetime(2026, 9, 30, 9, 15)
        assert is_trading_hours(dt) is False

    def test_trading_day_after_close(self):
        """交易日 2026-09-30 盘后 -> False"""
        from trading_hours import is_trading_hours
        dt = datetime(2026, 9, 30, 15, 30)
        assert is_trading_hours(dt) is False

    def test_exactly_boundary(self):
        """精确边界：09:30开/11:30闭/13:00开/15:00闭"""
        from trading_hours import is_trading_hours
        assert is_trading_hours(datetime(2026, 9, 30, 9, 30)) is True
        assert is_trading_hours(datetime(2026, 9, 30, 11, 30)) is False
        assert is_trading_hours(datetime(2026, 9, 30, 13, 0)) is True
        assert is_trading_hours(datetime(2026, 9, 30, 15, 0)) is False

    def test_calendar_missing_fail_close(self):
        """forward calendar 文件缺失时 fail-CLOSE"""
        from trading_hours import is_trading_hours
        # 用 patch 让 _load_forward_trade_dates 返回空集（模拟文件缺失）
        with patch('trading_hours._load_forward_trade_dates', return_value=set()):
            # 重置去重标记
            import trading_hours
            trading_hours._calendar_warned = False
            dt = datetime(2026, 9, 30, 10, 0)
            assert is_trading_hours(dt) is False

    def test_calendar_future_covered(self):
        """forward calendar 含未来日期（2026-10-09 已覆盖）-> True"""
        from trading_hours import is_trading_hours
        # 直接调用，依赖真实 data/trading_calendar.json
        dt = datetime(2026, 10, 9, 10, 0)
        assert is_trading_hours(dt) is True

    def test_calendar_freshness_missing(self):
        """日历缺失 -> fail-close/告警"""
        from trading_hours import _check_calendar_freshness
        import trading_hours
        trading_hours._calendar_warned = False
        with patch('trading_hours._load_forward_trade_dates', return_value=set()):
            result = _check_calendar_freshness()
            assert result is False

    def test_calendar_freshness_past_max_date(self):
        """日历最大日期 < today -> fail-close/告警"""
        from trading_hours import _check_calendar_freshness
        import trading_hours
        trading_hours._calendar_warned = False
        # 模拟日历最新日期是昨天（不覆盖今天）
        old_date = date.today() - timedelta(days=1)
        with patch('trading_hours._load_forward_trade_dates', return_value={old_date}):
            result = _check_calendar_freshness()
            assert result is False

    def test_calendar_freshness_stale_pulled_at(self):
        """pulled_at 30天前 -> fail-close/告警"""
        from trading_hours import _check_calendar_freshness
        import trading_hours
        trading_hours._calendar_warned = False
        today = date.today()
        future_date = today + timedelta(days=1)
        old_pulled_at = (today - timedelta(days=30)).isoformat()
        with patch('trading_hours._load_forward_trade_dates', return_value={future_date}):
            with patch('trading_hours._get_forward_pulled_at', return_value=old_pulled_at):
                result = _check_calendar_freshness()
                assert result is False

    def test_string_input(self):
        """支持字符串输入"""
        from trading_hours import is_trading_hours
        assert is_trading_hours("2026-09-30 14:00") is True
        assert is_trading_hours("2026-09-30 15:01") is False

    def test_date_input(self):
        """date 对象（00:00）-> False（不在交易时段内）"""
        from trading_hours import is_trading_hours
        dt_date = datetime(2026, 9, 30).date()
        assert is_trading_hours(dt_date) is False

    def test_loud_bad_date_string_captures_stderr(self, capsys, tmp_path):
        """[P0 loud] 损坏日历含非法日期串 → stderr 捕获到'日历解析异常'警告"""
        import json as _json
        from trading_hours import _load_forward_trade_dates
        import trading_hours

        # 构造临时损坏日历文件
        fake_cal = tmp_path / "trading_calendar_bad.json"
        bad_payload = {"data": [{"date": "NOT-A-DATE"}, {"date": "2026-10-09"}]}
        fake_cal.write_text(_json.dumps(bad_payload), encoding="utf-8")

        # 临时替换路径
        original_path = trading_hours._FORWARD_CALENDAR_PATH
        try:
            trading_hours._FORWARD_CALENDAR_PATH = str(fake_cal)
            result = _load_forward_trade_dates()
        finally:
            trading_hours._FORWARD_CALENDAR_PATH = original_path

        captured = capsys.readouterr()
        assert captured.err != "", "stderr 应捕获到告警，非静默吞异常"
        assert "日历解析异常" in captured.err, f"期望告警关键字，实际 stderr={captured.err!r}"
        assert result == {date(2026, 10, 9)}, f"有效日期应保留，实际={result}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
