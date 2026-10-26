#!/usr/bin/env python3
"""
S3-10 P2 (2026-10-01): tdx_indicators 新增4指标单测
任务单: docs/S3-10-P2回测任务单-20261001.md 第4条
覆盖: calc_boll_width / calc_drawdown_60 / calc_downside_vol / calc_max_consec_down
确定性锚点: 手工可算的小样本 + 边界(数据不足/零值)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import math

from core.scoring.tdx_indicators import (
    calc_boll_width, calc_drawdown_60, calc_downside_vol, calc_max_consec_down,
)


def mkrecs(closes):
    """closes -> records(仅close, 其余键给合理默认)"""
    out = []
    for i, c in enumerate(closes):
        out.append({"date": "2026-01-%02d" % (i % 28 + 1), "close": c,
                    "open": c, "high": c, "low": c, "volume": 1e6})
    return out


# ═══ calc_boll_width ═══

class TestBollWidth:
    def test_manual(self):
        # 20个值: 100±1 交替 → std=1(总体), MA=100, k=2 → 带宽=4/100=0.04
        closes = [100 + (1 if i % 2 == 0 else -1) for i in range(20)]
        w = calc_boll_width(mkrecs(closes))
        assert w is not None
        assert math.isclose(w, 0.04, rel_tol=1e-9)

    def test_constant_zero(self):
        assert math.isclose(calc_boll_width(mkrecs([100.0] * 20)), 0.0, abs_tol=1e-12)

    def test_insufficient(self):
        assert calc_boll_width(mkrecs([100.0] * 19)) is None
        assert calc_boll_width([]) is None

    def test_k_parameter(self):
        closes = [100 + (1 if i % 2 == 0 else -1) for i in range(20)]
        w1 = calc_boll_width(mkrecs(closes), k=1.0)
        w2 = calc_boll_width(mkrecs(closes), k=2.0)
        assert math.isclose(w2, 2 * w1, rel_tol=1e-9)


# ═══ calc_drawdown_60 ═══

class TestDrawdown60:
    def test_manual(self):
        # 61根close: 前31日 100→130(涨, 峰=130), 后30日 130→104(回落-20%)
        # 近60日窗口内: 峰=130, 末=104 → dd = 1 - 104/130 = 0.2
        closes = [100 + i * 1.0 for i in range(31)] + [130 - i * (26 / 30) for i in range(1, 31)]
        assert len(closes) == 61
        dd = calc_drawdown_60(mkrecs(closes))
        assert math.isclose(dd, 0.2, rel_tol=1e-9)

    def test_monotonic_up_zero(self):
        assert math.isclose(calc_drawdown_60(mkrecs([100 + i for i in range(60)])), 0.0, abs_tol=1e-12)

    def test_peak_not_first(self):
        # 先跌后涨再跌: 峰在中间
        closes = [120 - i for i in range(10)] + [110 + i * 2 for i in range(10)] + [129 - i * 3 for i in range(40)]
        # 峰=129 (第19日), 末=129-39*3=12 → dd=1-12/129
        dd = calc_drawdown_60(mkrecs(closes))
        assert math.isclose(dd, 1 - 12 / 129, rel_tol=1e-9)

    def test_window_is_last_60(self):
        # 前100日深回撤, 近60日单调上行 → 窗口内dd=0
        closes = [200 - i * 2 for i in range(100)] + [5.0 + i * 0.1 for i in range(60)]
        assert math.isclose(calc_drawdown_60(mkrecs(closes)), 0.0, abs_tol=1e-12)

    def test_insufficient(self):
        assert calc_drawdown_60(mkrecs([100.0] * 59)) is None


# ═══ calc_downside_vol ═══

class TestDownsideVol:
    def test_manual(self):
        # 构造: 近20日收益固定序列 → 负收益[-2,-4,-6] → mean=-4, std(ddof=1)=2
        # closes: 从100起, 交替+1%与-2%/-4%/-6%
        rets = [0.01, -0.02, 0.01, -0.04, 0.01, -0.06, 0.01, 0.01, 0.01, 0.01,
                0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]
        closes = [100.0]
        for r in rets:
            closes.append(closes[-1] * (1 + r))
        dv = calc_downside_vol(mkrecs(closes))
        assert dv is not None
        neg = [-2.0, -4.0, -6.0]
        m = sum(neg) / 3
        expect = (sum((x - m) ** 2 for x in neg) / 2) ** 0.5
        assert math.isclose(dv, expect, rel_tol=1e-9)

    def test_all_up_none(self):
        # 全涨 → 无负收益观测 → None (无下行风险可测)
        assert calc_downside_vol(mkrecs([100 * (1.01 ** i) for i in range(30)])) is None

    def test_insufficient(self):
        assert calc_downside_vol(mkrecs([100.0] * 20)) is None

    def test_min_neg_obs(self):
        # 20个收益中仅2个负收益 → 低于默认min_neg_obs=3 → None
        rets = [0.01] * 18 + [-0.01, -0.02]
        closes = [100.0]
        for r in rets:
            closes.append(closes[-1] * (1 + r))
        assert calc_downside_vol(mkrecs(closes)) is None
        # 放宽阈值则可算
        assert calc_downside_vol(mkrecs(closes), min_neg_obs=2) is not None


# ═══ calc_max_consec_down ═══

class TestMaxConsecDown:
    def test_manual(self):
        # 61根close(60次比较), 含一段5连阴 + 一段2连阴 → 5
        closes = [100.0] * 53
        for i in range(5):
            closes.append(closes[-1] * 0.98)
        closes.append(closes[-1] * 1.02)  # 阳线断链
        closes.append(closes[-1] * 0.99)
        closes.append(closes[-1] * 0.99)  # 2连阴
        assert len(closes) == 61
        assert calc_max_consec_down(mkrecs(closes)) == 5

    def test_all_up_zero(self):
        assert calc_max_consec_down(mkrecs([100 * (1.01 ** i) for i in range(61)])) == 0

    def test_window_is_last_60(self):
        # 早段8连阴, 近60日单调上行 → 0
        closes = [100.0]
        for i in range(8):
            closes.append(closes[-1] * 0.97)
        for i in range(70):
            closes.append(closes[-1] * 1.005)
        assert calc_max_consec_down(mkrecs(closes)) == 0

    def test_flat_is_not_down(self):
        # 持平(close==prev)不算连阴
        closes = [100.0] * 61
        assert calc_max_consec_down(mkrecs(closes)) == 0

    def test_insufficient(self):
        assert calc_max_consec_down(mkrecs([100.0] * 60)) is None
