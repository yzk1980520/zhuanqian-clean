"""
tests/test_tdx_indicators_new_factors.py — P1-O4: tdx_indicators.py 缺失 3 因子补全

Seam 定义（经 2026-10-20 老大确认）：
  S1: compute_indicators() 返回值 dict 必须含 overnight_sum20 / momentum_20 / chg5_rev 三个 key
  S2: overnight_sum20 = sum(open[i]/close[i-1]-1 for i in last-19..0) * 100  （同 factor_ic_132d_refresh.py）
  S3: momentum_20 = (close[-1] - close[-21]) / close[-21]                      （同 calculate_cross_sectional_ic.py）
  S4: chg5_rev = -chg5                                                         （同 factor_calculator.py:75）

验收断言来源：
  - factor_ic_diagnostic_132d_exact_20261015_042130.json:
      overnight_sum20 ic=+0.0428 (effective)
      momentum_20     ic=+0.0382 (ineffective 但非零)
  - factor_weights.json v2.6 权重: overnight_sum20=1.6, momentum_20=0.5, chg5_rev=0.0
  - 三者均未在 compute_indicators() 返回 dict 中出现 → z=0 → 评分零贡献（P1-O4 根因）
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from core.scoring.tdx_indicators import compute_indicators


# ─── fixture：构造最小合法 records（20 条 K 线）────────────────────────────────

def _make_records(n=25, base_close=20.0):
    """构造 n 条连续 K 线记录（含 open/high/low/close/volume/date）。"""
    records = []
    for i in range(n):
        close = base_close * (1 + 0.01 * (i % 5 - 2))  # 小幅震荡
        open_ = close * (1 + 0.002 * ((-1) ** i))      # 开盘略偏离收盘
        high = max(open_, close) * (1 + 0.005)
        low = min(open_, close) * (1 - 0.005)
        records.append({
            "date": f"2026-10-{15+i:02d}",
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "amount": 1_000_000,
            "volume": 100_000,
        })
    return records


# ─── S1: 三个新 key 必须在返回 dict 里 ────────────────────────────────────────

class TestNewFactorKeysPresent:
    """S1: compute_indicators() 返回值必须包含 overnight_sum20 / momentum_20 / chg5_rev。"""

    def test_s1_overnight_sum20_key_exists(self):
        """RED: overnight_sum20 key 不在返回 dict 中。"""
        inds = compute_indicators(_make_records(25))
        assert "overnight_sum20" in inds, (
            "tdx_indicators.compute_indicators() 返回 dict 缺少 overnight_sum20 key "
            "（P1-O4 根因：因子权重重置 1.6 但 z 值恒 0）"
        )

    def test_s1_momentum_20_key_exists(self):
        """RED: momentum_20 key 不在返回 dict 中。"""
        inds = compute_indicators(_make_records(25))
        assert "momentum_20" in inds, (
            "tdx_indicators.compute_indicators() 返回 dict 缺少 momentum_20 key "
            "（注意：chg20≠momentum_20，前者是 rms 计算中间量，后者是独立因子键）"
        )

    def test_s1_chg5_rev_key_exists(self):
        """RED: chg5_rev key 不在返回 dict 中。"""
        inds = compute_indicators(_make_records(25))
        assert "chg5_rev" in inds, (
            "tdx_indicators.compute_indicators() 返回 dict 缺少 chg5_rev key "
            "（P1-O4 根因：chg5_rev 权重 0.0 但 key 缺失，auto_trade_pipeline 读不到）"
        )


# ─── S2: overnight_sum20 公式验证 ─────────────────────────────────────────────

class TestOvernightSum20Formula:
    """S2: overnight_sum20 = sum(open[i]/close[i-1]-1, i=last-19..last) * 100。"""

    def test_s2_value_nonzero_for_trending_data(self):
        """持续上涨行情 → overnight_sum20 > 0。"""
        records = _make_records(25, base_close=10.0)
        # 手动构造一段连续上涨（每天开盘高于昨日收盘）
        for i in range(len(records)):
            records[i]["open"] = records[i]["close"] * 1.01 if i > 0 else 10.0
            if i > 0:
                records[i-1]["close"] = records[i]["open"] * 0.99  # 昨收 < 今开
        inds = compute_indicators(records)
        assert inds["overnight_sum20"] is not None, "overnight_sum20 不应为 None"
        assert inds["overnight_sum20"] > 0, (
            f"持续上涨行情下 overnight_sum20 应为正，实际={inds['overnight_sum20']}"
        )

    def test_s2_none_when_insufficient_data(self):
        """不足 20 条记录 → overnight_sum20 = None（fail-safe）。"""
        inds = compute_indicators(_make_records(15))
        # compute_indicators 本身对 <20 条返回 None，这里测 >=20 但 open/close 不合法场景
        # 用 close[-1]=0 触发上层 early return
        bad = _make_records(25, base_close=0.0)
        result = compute_indicators(bad)
        assert result is None, "close=0 应返回 None（P0 数据卫生）"


# ─── S3: momentum_20 公式验证 ─────────────────────────────────────────────────

class TestMomentum20Formula:
    """S3: momentum_20 = (close[-1] - close[-21]) / close[-21]。"""

    def test_s3_positive_for_upward_trend(self):
        """上涨 → momentum_20 > 0。"""
        records = _make_records(25, base_close=10.0)
        for i in range(25):
            records[i]["close"] = 10.0 + i * 0.5  # 线性上涨
        inds = compute_indicators(records)
        assert inds["momentum_20"] > 0, (
            f"线性上涨行情下 momentum_20 应为正，实际={inds['momentum_20']}"
        )

    def test_s3_matches_formula(self):
        """精确值验证：close 线性递增，公式可手算。"""
        closes = [10.0 + i * 0.5 for i in range(25)]  # 10, 10.5, ..., 22.0
        records = [{"date": f"2026-10-{i:02d}", "open": c, "high": c*1.01,
                     "low": c*0.99, "close": c, "amount": 1e6, "volume": 1e5}
                    for i, c in enumerate(closes)]
        inds = compute_indicators(records)
        expected = (closes[-1] - closes[-21]) / closes[-21]  # (22.0-12.0)/12.0 = 0.8333...
        assert inds["momentum_20"] == pytest.approx(expected, abs=1e-6), (
            f"momentum_20 公式偏差：expected={expected}, got={inds['momentum_20']}"
        )


# ─── S4: chg5_rev = -chg5 ────────────────────────────────────────────────────

class TestChg5RevFormula:
    """S4: chg5_rev = -chg5（反转因子）。"""

    def test_s4_chg5_rev_is_negative_of_chg5(self):
        """chg5_rev 应严格等于 -chg5。"""
        records = _make_records(25, base_close=20.0)
        inds = compute_indicators(records)
        assert inds["chg5_rev"] == pytest.approx(-inds["chg5"], abs=1e-9), (
            f"chg5_rev ≠ -chg5: chg5={inds['chg5']}, chg5_rev={inds['chg5_rev']}"
        )

    def test_s4_symmetric_in_up_and_down(self):
        """上涨时 chg5>0→chg5_rev<0；下跌时 chg5<0→chg5_rev>0。"""
        # 上涨场景
        up = _make_records(25, base_close=10.0)
        for i in range(25):
            up[i]["close"] = 10.0 + i * 0.3
        inds_up = compute_indicators(up)
        assert inds_up["chg5"] > 0
        assert inds_up["chg5_rev"] < 0

        # 下跌场景
        down = _make_records(25, base_close=10.0)
        for i in range(25):
            down[i]["close"] = 10.0 - i * 0.3
        inds_down = compute_indicators(down)
        assert inds_down["chg5"] < 0
        assert inds_down["chg5_rev"] > 0
