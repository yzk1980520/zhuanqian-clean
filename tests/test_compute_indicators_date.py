# -*- coding: utf-8 -*-
"""test_compute_indicators_date.py — 故障③ date 格式 bug (RED→GREEN)

根因: data/history_daily/*.json 的 date 字段 100% 是 'YYYY-MM-DD'(带连字符),
但 tdx_indicators.aggregate_weekly 用 strptime(date, '%Y%m%d')(8位无连字符)解析
+ except 只接 AttributeError 漏接 ValueError → 每只票 compute_indicators 崩
→ 被 run_stock_selection 的 except:continue 吞掉 → 0 候选。

RED: compute_indicators(真实 ISO 数据) 抛 ValueError。
seam: compute_indicators 对 ①真实 YYYY-MM-DD 数据 ②旧 YYYYMMDD 数据 都应出指标 dict。
"""
import sys, json, datetime
from pathlib import Path

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))


def _ymd8_records(n=120):
    base = datetime.date(2024, 1, 1)
    out = []
    for i in range(n):
        d = base + datetime.timedelta(days=i)
        out.append({"date": d.strftime("%Y%m%d"), "open": 10.0,
                   "close": 10.0 + (i % 3) * 0.1, "high": 11.0, "low": 9.0,
                   "volume": 1_000_000, "amount": 10_000_000})
    return out


def test_compute_indicators_real_iso_date():
    """真实 sh600000.json (date='YYYY-MM-DD') 必须能算出指标 dict, 不崩"""
    from core.scoring.tdx_indicators import compute_indicators
    data = json.load(open(BASE / "data" / "history_daily" / "sh600000.json", encoding="utf-8"))
    inds = compute_indicators(data)
    assert isinstance(inds, dict), "compute_indicators 应返回指标 dict"
    assert "price" in inds, "指标 dict 必须含 price 键 (当前崩在 weekly 周线聚合)"
    assert inds["price"] > 0


def test_compute_indicators_legacy_ymd8_date():
    """旧格式 YYYYMMDD 向后兼容 (修复不得破坏 8 位数据, 零行为变化)"""
    from core.scoring.tdx_indicators import compute_indicators
    recs = _ymd8_records()
    inds = compute_indicators(recs)
    assert isinstance(inds, dict)
    assert "price" in inds
    # worked example: 构造数据 close[-1] 固定, 独立断言 price=该 close
    last_close = recs[-1]["close"]
    assert abs(inds["price"] - last_close) < 1e-6, "price 必须=末根 close (独立值, 非重算)"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
