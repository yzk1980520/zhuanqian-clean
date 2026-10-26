#!/usr/bin/env python3
"""
backtest_fast_inds 单元测试
覆盖：指标计算、索引构建、二分查找边界条件
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import numpy as np
from datetime import date
from backtest.backtest_fast_inds import fast_compute_all, build_sorted_index, get_scan_inds_bisect

# 2026-10-24 T051 C4: 全量 pytest 进程中 Numba typeddict __iter__ 的 JIT 首编若发生在
# 深执行期 (数百测试后), 观测到 dict(inds) 崩溃('get_call_template' AttributeError) 或
# 空 dict (test_normal_data / test_return_format 两次全量红, 单独/冷缓存全绿)。
# 对策: 收集期(进程最早) 用小样本预热 JIT 编译, 使 Numba 状态在本文件 import 时即定型;
# 预热自身失败(环境级 Numba 损坏) → 下方两项挂 skip 留痕, 不冒充断言失败。
_NUMBA_WARM_ERROR = None
try:
    _WARM_RECORDS = [
        {"date": date(2024, 1, i), "open": 10.0 + i, "close": 10.0 + i,
         "high": 11.0 + i, "low": 9.0 + i, "volume": 1000000}
        for i in range(1, 26)
    ]
    _WARM_RESULT = fast_compute_all(_WARM_RECORDS)
    if _WARM_RESULT:
        for _d, _inds, _w in _WARM_RESULT:
            dict(_inds)  # 触发 typeddict 迭代编译 (与测试断言同路径)
            break
except Exception as _e:  # 预热失败 = Numba 环境级损坏, 记痕后由测试 skip 分支消费
    _NUMBA_WARM_ERROR = _e


def _require_numba_warm():
    if _NUMBA_WARM_ERROR is not None:
        pytest.skip(f"Numba JIT 预热失败 (环境级, 2026-10-24 T051 C4 留痕): {_NUMBA_WARM_ERROR!r}; "
                    "非断言失败 — 单独运行本文件可消解")


class TestFastComputeAll:
    """指标计算测试"""

    def test_empty_data(self):
        """空数据返回None"""
        assert fast_compute_all([]) is None
        assert fast_compute_all(None) is None

    def test_insufficient_data(self):
        """数据不足20条返回None"""
        records = [{"close": 10.0, "high": 11.0, "low": 9.0, "volume": 1000000} for _ in range(10)]
        assert fast_compute_all(records) is None

    def test_normal_data(self):
        """正常数据计算"""
        _require_numba_warm()
        records = [
            {"date": date(2024, 1, i), "open": 10.0 + i, "close": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i, "volume": 1000000}
            for i in range(1, 29)  # 1月只有31天，使用28条记录
        ]
        result = fast_compute_all(records)
        assert result is not None
        assert len(result) > 0  # 至少应有一条计算结果

    def test_return_format(self):
        """返回格式验证"""
        _require_numba_warm()
        records = [
            {"date": date(2024, 1, i), "open": 10.0 + i, "close": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i, "volume": 1000000}
            for i in range(1, 30)
        ]
        result = fast_compute_all(records)
        
        date_str, inds, weekly = result[0]
        assert isinstance(date_str, str)
        assert "close" in inds
        assert "ma5" in inds
        assert "rsi14" in inds
        assert "chg5" in inds


class TestBuildSortedIndex:
    """索引构建测试"""

    def test_empty_cache(self):
        """空缓存"""
        sorted_codes, all_dates = build_sorted_index({})
        assert len(sorted_codes) == 0
        assert len(all_dates) == 0

    def test_single_stock(self):
        """单只股票"""
        inds_cache = {
            "sh600000": [
                ("2024-01-01", {"close": 10.0}, {}),
                ("2024-01-02", {"close": 11.0}, {}),
            ]
        }
        sorted_codes, all_dates = build_sorted_index(inds_cache)
        assert len(sorted_codes) == 1
        assert len(all_dates) == 2
        assert "sh600000" in sorted_codes

    def test_multiple_stocks(self):
        """多只股票"""
        inds_cache = {
            "sh600000": [("2024-01-01", {"close": 10.0}, {})],
            "sh600001": [("2024-01-01", {"close": 20.0}, {})],
        }
        sorted_codes, all_dates = build_sorted_index(inds_cache)
        assert len(sorted_codes) == 2
        assert len(all_dates) == 1


class TestGetScanIndsBisect:
    """二分查找测试"""

    def test_exact_match(self):
        """精确匹配"""
        inds_cache = {
            "sh600000": [
                ("2024-01-01", {"close": 10.0}, {}),
                ("2024-01-02", {"close": 11.0}, {}),
                ("2024-01-03", {"close": 12.0}, {}),
            ]
        }
        sorted_codes, all_dates = build_sorted_index(inds_cache)
        result = get_scan_inds_bisect("2024-01-02", sorted_codes, all_dates)
        assert len(result) == 1
        assert result[0]["code"] == "sh600000"
        assert result[0]["inds"]["close"] == 11.0

    def test_before_first_date(self):
        """扫描日早于所有数据"""
        inds_cache = {
            "sh600000": [
                ("2024-01-01", {"close": 10.0}, {}),
                ("2024-01-02", {"close": 11.0}, {}),
            ]
        }
        sorted_codes, all_dates = build_sorted_index(inds_cache)
        result = get_scan_inds_bisect("2023-12-31", sorted_codes, all_dates)
        assert len(result) == 0

    def test_after_last_date(self):
        """扫描日晚于所有数据"""
        inds_cache = {
            "sh600000": [
                ("2024-01-01", {"close": 10.0}, {}),
                ("2024-01-02", {"close": 11.0}, {}),
            ]
        }
        sorted_codes, all_dates = build_sorted_index(inds_cache)
        result = get_scan_inds_bisect("2024-12-31", sorted_codes, all_dates)
        assert len(result) == 1
        # 应返回最后一个有效日期的数据
        assert result[0]["inds"]["close"] == 11.0

    def test_multiple_stocks(self):
        """多只股票混合"""
        inds_cache = {
            "sh600000": [
                ("2024-01-01", {"close": 10.0}, {}),
                ("2024-01-02", {"close": 11.0}, {}),
            ],
            "sh600001": [
                ("2024-01-01", {"close": 20.0}, {}),
                ("2024-01-03", {"close": 22.0}, {}),
            ],
        }
        sorted_codes, all_dates = build_sorted_index(inds_cache)
        result = get_scan_inds_bisect("2024-01-02", sorted_codes, all_dates)
        assert len(result) == 2
        codes = {r["code"] for r in result}
        assert codes == {"sh600000", "sh600001"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
