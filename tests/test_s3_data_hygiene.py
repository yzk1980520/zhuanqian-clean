#!/usr/bin/env python3
"""
test_s3_data_hygiene.py: 数据卫生与引擎健壮性测试 (2026-10-08 601989 摘牌股排第一 修复)

覆盖 seam:
- A: tdx_indicators.compute_indicators 对坏数据(末根 close<=0 / 全零 close) 健壮性
     -> 应返回 None (上游 `if not inds: continue` 干净跳过), 不抛 ZeroDivisionError
- B: s3_auto_pipeline 数据卫生门控纯函数 is_valid_candidate
     -> 退市/ST 名字、数据陈旧(末根K线>45天)、末根 close<=0 三类均剔除, 且理由可追溯

背景: 601989(中国重工, 2025-08 摘牌) 名字映射过期仍叫"中国重工"(无退市前缀),
     基于名字的 is_delisted 抓不到; 其数据末根K线停在 2025-08-12(422天前)。
     另有 8024 只末根 close=0 的坏数据(2026-09导入损坏) 喂进引擎必 ZDE,
     被流水线 except:continue 静默吞掉 -> 候选池从 3000 缩到 4 只(异常吞噬埋雷)。
"""
import sys
import os
from datetime import datetime, timedelta, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.scoring.tdx_indicators import compute_indicators
from scripts.s3_auto_pipeline import is_delisted, is_stale_data, is_valid_candidate


def _dates(n=120, start=date(2026, 5, 1)):
    """生成 n 个连续合法日期串 (YYYYMMDD), 供指标计算。"""
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def _rec(datestr, close, high=None, low=None, vol=1000, amt=10000):
    return {"date": datestr, "open": close, "high": high if high is not None else close * 1.05,
            "low": low if low is not None else close * 0.95, "close": close,
            "volume": vol, "amount": amt}


class TestComputeIndicatorsBadData:
    """Seam A: 引擎对坏数据健壮 (2026-10-08 ZDE 修复)"""

    def test_all_zero_close_returns_none_not_crash(self):
        """全零 close -> 返回 None (修复前: 抛 ZeroDivisionError @ tdx_indicators.py:190)"""
        dts = _dates(120)
        recs = [_rec(dts[i], 0.0, vol=1000000 + i) for i in range(120)]
        out = compute_indicators(recs)
        assert out is None

    def test_last_bar_zero_close_returns_none(self):
        """末根 close=0(前面正常) -> 返回 None, 不崩溃"""
        dts = _dates(120)
        recs = [_rec(dts[i], 10.0) for i in range(119)]
        recs.append(_rec(dts[119], 0.0))
        out = compute_indicators(recs)
        assert out is None

    def test_normal_close_still_computes(self):
        """正常 close -> 仍返回指标 dict (不回归: 修 ZDE 不能把正常评分打死)"""
        dts = _dates(120)
        recs = [_rec(dts[i], 10.0 + i * 0.01) for i in range(120)]
        out = compute_indicators(recs)
        assert out is not None
        assert isinstance(out, dict)
        assert "ma5" in out and "rsi14" in out


class TestPipelineDataHygiene:
    """Seam B: 数据卫生门控纯函数 (理由可追溯)"""

    def test_delisted_name_rejected(self):
        ok, why = is_valid_candidate(name="退市锦港", last_bar_date="2026-09-30", last_close=5.0)
        assert ok is False and why == "delisted_name"

    def test_st_stock_rejected(self):
        ok, why = is_valid_candidate(name="*ST九鼎", last_bar_date="2026-09-30", last_close=5.0)
        assert ok is False and why == "delisted_name"

    def test_stale_data_rejected(self):
        """601989 情形: 名字没带退市前缀(仍叫'中国重工')但数据停在 422 天前 -> 陈旧剔除"""
        ok, why = is_valid_candidate(name="中国重工", last_bar_date="2025-08-12", last_close=5.1,
                                    today=datetime(2026, 10, 8))
        assert ok is False and why == "stale_data"

    def test_zero_close_rejected(self):
        """末根 close=0 (2026-09 导入损坏的坏数据) -> 剔除, 不喂进引擎"""
        ok, why = is_valid_candidate(name="上证指数", last_bar_date="2026-09-30", last_close=0.0)
        assert ok is False and why == "zero_close"

    def test_clean_stock_kept(self):
        """干净活跃股 (名字无退市、数据新鲜、close>0) -> 保留"""
        ok, why = is_valid_candidate(name="招商银行", last_bar_date="2026-09-30", last_close=40.2,
                                    today=datetime(2026, 10, 8))
        assert ok is True and why == "ok"

    def test_is_stale_data_boundary(self):
        """新鲜度边界: 45天阈值(>45才算陈旧)。today=2026-10-08: 45天前=08-24(新鲜), 46天前=08-23(陈旧)"""
        today = datetime(2026, 10, 8)
        assert is_stale_data("2026-08-24", today) is False  # 45天前, 不>45 -> 新鲜
        assert is_stale_data("2026-08-23", today) is True   # 46天前 -> 陈旧
        assert is_stale_data("2026-09-30", today) is False  # 8天前 -> 新鲜


class TestStaleGateEndToEnd:
    """601989 回归: 该代码的数据经门控后必须被剔除"""

    def test_601989_rejected_by_gate(self):
        """用真实 601989 数据(末根 2025-08-12) + 过期名字(中国重工) 验证被门控拦下"""
        ok, why = is_valid_candidate(name="中国重工", last_bar_date="2025-08-12", last_close=5.1,
                                    today=datetime(2026, 10, 8))
        assert ok is False
        # 且名字关键字过滤确实抓不到它(证明必须靠数据驱动门控, 而非名字)
        assert is_delisted("中国重工") is False
