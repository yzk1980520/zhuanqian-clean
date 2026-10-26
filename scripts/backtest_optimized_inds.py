# -*- coding: utf-8 -*-
"""
回测引擎性能优化方案（基于量化最佳实践）

来源：
1. VectorBT：Numba+Rust加速，向量化矩阵运算
2. NumPy Tricks：np.where/np.maximum.accumulate替代循环
3. Numba JIT：@njit编译Python循环→C速度

核心原则：
- 向量化优先（避免Python for循环）
- Numba JIT编译热路径（10-50x加速）
- 预计算缓存（复用而非重算）
"""

import numpy as np
from numba import njit, prange
from typing import Dict, List, Tuple, Optional
import json
import os

# ══════════════════════════════════════════════════════
# Numba JIT加速的核心指标计算函数
# ══════════════════════════════════════════════════════

@njit(cache=True)
def compute_ma_vectorized(close: np.ndarray, window: int) -> np.ndarray:
    """向量化计算移动平均（Numba加速）"""
    result = np.full(len(close), np.nan)
    for i in range(window-1, len(close)):
        s = 0.0
        for j in range(window):
            s += close[i-j]
        result[i] = s / window
    return result


@njit(cache=True)
def compute_rsi_vectorized(close: np.ndarray, window: int) -> np.ndarray:
    """向量化计算RSI（Numba加速）"""
    result = np.full(len(close), np.nan)
    
    if len(close) < window + 1:
        return result
    
    # 计算价格变化
    delta = np.empty(len(close))
    delta[0] = 0.0
    for i in range(1, len(close)):
        delta[i] = close[i] - close[i-1]
    
    # 分离涨跌
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    
    # 计算平均涨跌（简化版，使用指数移动平均）
    avg_gain = 0.0
    avg_loss = 0.0
    
    for i in range(1, window + 1):
        avg_gain += gain[i]
        avg_loss += loss[i]
    
    avg_gain /= window
    avg_loss /= window
    
    result[window] = 100.0 - (100.0 / (1.0 + avg_gain / max(avg_loss, 1e-10)))
    
    for i in range(window + 1, len(close)):
        avg_gain = (avg_gain * (window - 1) + gain[i]) / window
        avg_loss = (avg_loss * (window - 1) + loss[i]) / window
        result[i] = 100.0 - (100.0 / (1.0 + avg_gain / max(avg_loss, 1e-10)))
    
    return result


@njit(cache=True)
def compute_indicators_fast(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray
) -> Dict:
    """
    快速计算所有技术指标（Numba JIT编译）
    
    返回: dict with all indicators
    """
    length = len(close)
    
    # 预计算各类指标
    ma5 = compute_ma_vectorized(close, 5)
    ma10 = compute_ma_vectorized(close, 10)
    ma20 = compute_ma_vectorized(close, 20)
    ma60 = compute_ma_vectorized(close, 60)
    
    rsi6 = compute_rsi_vectorized(close, 6)
    rsi14 = compute_rsi_vectorized(close, 14)
    
    # MACD DIF
    dif = np.empty(length)
    for i in range(length):
        if i >= 25:
            dif[i] = np.mean(close[i-11:i+1]) - np.mean(close[i-25:i+1])
        else:
            dif[i] = np.nan
    
    # ATR (True Range)
    atr = np.empty(length)
    tr = np.empty(length)
    for i in range(length):
        if i == 0:
            tr[i] = high[i] - low[i]
        else:
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
        
        if i >= 14:
            s = 0.0
            for j in range(14):
                s += tr[i-j]
            atr[i] = s / 14
        else:
            atr[i] = np.nan
    
    # 成交量均线
    vol_ma5 = compute_ma_vectorized(volume, 5)
    vol_ratio = np.empty(length)
    for i in range(length):
        if vol_ma5[i] > 0:
            vol_ratio[i] = volume[i] / vol_ma5[i]
        else:
            vol_ratio[i] = 1.0
    
    # 涨跌幅
    chg1 = np.empty(length)
    chg5 = np.empty(length)
    chg10 = np.empty(length)
    
    for i in range(length):
        if i > 0 and close[i-1] > 0:
            chg1[i] = (close[i] - close[i-1]) / close[i-1] * 100
        else:
            chg1[i] = 0.0
        
        if i >= 5 and close[i-5] > 0:
            chg5[i] = (close[i] - close[i-5]) / close[i-5] * 100
        else:
            chg5[i] = np.nan
        
        if i >= 10 and close[i-10] > 0:
            chg10[i] = (close[i] - close[i-10]) / close[i-10] * 100
        else:
            chg10[i] = np.nan
    
    return {
        'close': close[-1] if length > 0 else 0.0,
        'ma5': ma5[-1] if length >= 5 else np.nan,
        'ma10': ma10[-1] if length >= 10 else np.nan,
        'ma20': ma20[-1] if length >= 20 else np.nan,
        'ma60': ma60[-1] if length >= 60 else np.nan,
        'rsi6': rsi6[-1] if length >= 6 else np.nan,
        'rsi14': rsi14[-1] if length >= 14 else np.nan,
        'dif': dif[-1] if length >= 25 else np.nan,
        'atr': atr[-1] if length >= 14 else np.nan,
        'vol_ratio': vol_ratio[-1] if length > 0 else 1.0,
        'chg1': chg1[-1] if length > 1 else 0.0,
        'chg5': chg5[-1] if length >= 5 else np.nan,
        'chg10': chg10[-1] if length >= 10 else np.nan,
    }


# ══════════════════════════════════════════════════════
# 批量指标计算（向量化加速）
# ══════════════════════════════════════════════════════

def fast_compute_all_batch(records_list: List[List[Dict]]) -> List[Optional[Dict]]:
    """
    批量计算所有股票的指标（向量化版本）
    
    参数:
        records_list: List of [{date, open, high, low, close, volume}, ...]
    
    返回:
        List of indicator dicts or None if insufficient data
    """
    results = []
    
    for records in records_list:
        if not records or len(records) < 20:
            results.append(None)
            continue
        
        # 转换为NumPy数组
        close = np.array([r["close"] for r in records], dtype=np.float64)
        high = np.array([r["high"] for r in records], dtype=np.float64)
        low = np.array([r["low"] for r in records], dtype=np.float64)
        volume = np.array([r["volume"] for r in records], dtype=np.float64)
        
        if len(close) < 60:
            results.append(None)
            continue
        
        # 调用Numba加速函数
        try:
            inds = compute_indicators_fast(close, high, low, volume)
            results.append(inds)
        except Exception as e:
            results.append(None)
    
    return results


# ══════════════════════════════════════════════════════
# 性能测试
# ══════════════════════════════════════════════════════

def benchmark():
    """性能基准测试"""
    import time
    
    # 生成模拟数据
    np.random.seed(42)
    n_stocks = 100
    n_days = 1000
    
    records_list = []
    for _ in range(n_stocks):
        close = 100 + np.cumsum(np.random.randn(n_days) * 0.5)
        records = []
        for i in range(n_days):
            records.append({
                "date": f"2020-01-{i%28+1:02d}",
                "open": close[i] * 0.999,
                "high": close[i] * 1.001,
                "low": close[i] * 0.999,
                "close": float(close[i]),
                "volume": float(np.random.randint(1000, 10000))
            })
        records_list.append(records)
    
    # 测试批量计算
    start = time.time()
    results = fast_compute_all_batch(records_list)
    elapsed = time.time() - start
    
    print(f"=== 性能基准测试 ===")
    print(f"股票数: {n_stocks}")
    print(f"天数: {n_days}")
    print(f"总K线数: {n_stocks * n_days:,}")
    print(f"计算耗时: {elapsed:.3f}s")
    print(f"每秒处理: {n_stocks * n_days / elapsed:,.0f} K线/秒")
    print(f"有效结果: {sum(1 for r in results if r is not None)}/{n_stocks}")
    
    # 与原始版本对比（如果有）
    print(f"\n预期加速: 10-50x（相比Python循环版本）")


if __name__ == "__main__":
    benchmark()
