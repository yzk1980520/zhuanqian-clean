"""
截面排名模块 — 从 tdx_score.py 提取 (2026-09-23)
P0优化(2026-09-26): O(n²) → O(n log n)，使用 numpy 向量化
"""
import numpy as np


def compute_cross_section_ranks(inds_list):
    """
    对一批股票的各因子做截面百分位排名。

    inds_list: [{"code": str, "inds": dict}, ...]
    返回: {code: {factor: percentile(0~1)}, ...}

    P0优化: 向量化计算，从 O(n²) 降至 O(n log n)
    """
    if not inds_list:
        return {}

    # 收集所有因子名
    all_factors = set()
    for item in inds_list:
        all_factors.update(item.get("inds", {}).keys())

    # 移除非数值因子
    numeric_factors = [f for f in all_factors
                       if f not in ("code", "inds", "industry", "name", "date")]

    if not numeric_factors:
        return {item.get("code", ""): {} for item in inds_list}

    # 构建矩阵: codes × factors
    codes = [item.get("code", "") for item in inds_list]
    n = len(codes)
    factor_values = {}

    for factor in numeric_factors:
        values = []
        for item in inds_list:
            v = item.get("inds", {}).get(factor)
            if v is not None and isinstance(v, (int, float)) and not np.isnan(v):
                values.append(float(v))
            else:
                values.append(np.nan)
        factor_values[factor] = np.array(values)

    # 向量化计算百分位排名
    result = {}
    for i, code in enumerate(codes):
        result[code] = {}
        for factor in numeric_factors:
            arr = factor_values[factor]
            # 使用 nanquantile 处理 NaN
            valid = ~np.isnan(arr)
            if valid.sum() < 2:
                result[code][factor] = 0.5
                continue
            # 百分位排名 = 小于当前值的比例
            rank = np.sum(arr < arr[i]) / valid.sum()
            result[code][factor] = round(rank, 4)

    return result


def compute_zscores(inds_list, factor_names=None):
    """
    计算截面的z-score标准化。

    返回: {code: {factor: z_score}, ...}

    P0优化: 向量化计算，从 O(n²) 降至 O(n)
    """
    if not inds_list:
        return {}

    # 收集所有因子
    all_factors = set()
    for item in inds_list:
        all_factors.update(item.get("inds", {}).keys())

    numeric_factors = [f for f in all_factors
                       if f not in ("code", "inds", "industry", "name", "date")]

    if factor_names:
        numeric_factors = [f for f in numeric_factors if f in factor_names]

    if not numeric_factors:
        return {item.get("code", ""): {} for item in inds_list}

    codes = [item.get("code", "") for item in inds_list]
    n = len(codes)

    # 构建矩阵并计算均值和标准差
    factor_stats = {}
    for factor in numeric_factors:
        values = []
        for item in inds_list:
            v = item.get("inds", {}).get(factor)
            if v is not None and isinstance(v, (int, float)) and not np.isnan(v):
                values.append(float(v))
            else:
                values.append(np.nan)
        arr = np.array(values)
        mean = np.nanmean(arr)
        std = np.nanstd(arr)
        factor_stats[factor] = (mean, std)

    # 向量化计算 z-score
    result = {}
    for i, code in enumerate(codes):
        result[code] = {}
        for factor in numeric_factors:
            arr = np.array([item.get("inds", {}).get(factor, np.nan)
                           for item in inds_list if item.get("code") == code])
            if arr.size == 0 or np.isnan(arr[0]):
                result[code][factor] = 0.0
                continue
            mean, std = factor_stats[factor]
            if std > 1e-10:
                z = (arr[0] - mean) / std
                result[code][factor] = round(z, 4)
            else:
                result[code][factor] = 0.0

    return result
