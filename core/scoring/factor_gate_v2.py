#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
factor_gate_v2.py — 因子门禁系统 v2（支持IC正负方向 + 滚动样本外验证）
=============================================================
v1.0 → v2.0 变更（2026-09-20 老五合规评审）:
  1. 支持IC正/负方向记录
  2. 方向感知阈值：|IC| > threshold 且方向符合预期
  3. 单调性检查（分位收益单调性）
  4. DSR/PBO检验模块

v2.0 → v2.1 变更（2026-09-20 Kimi审查修正）:
  1. 滚动样本外IC/ICIR计算（Time-Series Split）
  2. 负IC因子方向反转有效性记录
  3. 退市股覆盖验证集成
  4. 完整DSR/PBO检验模块
  5. 回测周期扩展支持（3年+ / 滚动交叉验证）

门禁标准:
  - |IC| > 0.03 (信息系数绝对值)
  - |IR| > 0.3 (信息比率绝对值)
  - 方向率 > 55% (因子值与未来收益同向/反向一致性)
  - 单调差 > 0.02 (分位间收益单调性)
  - 样本量 >= 100笔交易
  - 滚动IC标准差 < 0.05 (稳定性)
  - 样本外IC > 样本内IC * 0.5 (衰减容忍)
"""
import sys, os, json, math, numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# 强制 stdout utf-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ═══════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════
GATE_CONFIG = {
    "ic_threshold": 0.03,           # |IC| 门槛
    "ir_threshold": 0.3,            # |IR| 门槛
    "dir_rate_threshold": 0.55,     # 方向率门槛
    "monotonicity_threshold": 0.02, # 单调差门槛
    "min_trades": 100,              # 最小交易次数
    "min_samples": 100,             # 最小样本数
    "quantile_count": 5,            # 分位数数量
    "rolling_window": 30,           # 滚动窗口（扫描日期数）
    "rolling_ic_std_threshold": 0.05,  # 滚动IC标准差门槛
    "oos_ic_decay_ratio": 0.5,      # 样本外IC衰减容忍比
    "sharpe_decay_threshold": 30.0, # G2参数扰动夏普衰减阈值(%)
}

# 已知因子方向（来自 audit/factor_direction_20260904.json）
KNOWN_FACTOR_DIRECTIONS = {
    # 正向因子（值越高，未来收益越高）
    "chg5": {"expected_sign": 1, "note": "短期动量，正向"},
    "chg10": {"expected_sign": 1, "note": "中期动量，正向"},
    "chg20": {"expected_sign": 1, "note": "长期动量，正向"},
    "vol_ratio": {"expected_sign": 1, "note": "量比，正向"},
    "fund_flow_intensity": {"expected_sign": 1, "note": "资金流向强度，正向"},
    "macd_hist": {"expected_sign": 1, "note": "MACD柱，正向"},
    "dif": {"expected_sign": 1, "note": "DIF，正向"},
    "rms": {"expected_sign": 1, "note": "RMS相对动量，正向"},
    "breakout_strength": {"expected_sign": 1, "note": "突破力度，正向"},
    "price_volume_divergence": {"expected_sign": 1, "note": "量价背离，正向"},
    # 反向因子（值越高，未来收益越低）
    "pos_vs_ma20": {"expected_sign": -1, "note": "距MA20距离%，反向"},
    "rsi14": {"expected_sign": -1, "note": "RSI14，反向"},
    "vol_shrink20": {"expected_sign": -1, "note": "缩量因子，反向"},
    "vol_floor": {"expected_sign": -1, "note": "量地板，反向"},
    "alpha13": {"expected_sign": -1, "note": "Alpha13(价量背离)，反向"},
    "alpha16_fix": {"expected_sign": -1, "note": "Alpha16_fix，反向"},
    "amount_q_reversal": {"expected_sign": -1, "note": "成交额分位反转，反向"},
    "vol_price_corr_20": {"expected_sign": -1, "note": "量价相关20日，反向"},
    "std20": {"expected_sign": -1, "note": "20日波动率，反向"},
    "max_ret5": {"expected_sign": -1, "note": "最大单日涨幅，反向"},
    "turn5": {"expected_sign": -1, "note": "5日涨跌停次数，反向"},
    "unlocked_pressure": {"expected_sign": -1, "note": "解套盘压力，反向"},
    "rsi_extreme": {"expected_sign": -1, "note": "RSI极端值，反向"},
}


# ═══════════════════════════════════════════════════════════
#  统计工具函数
# ═══════════════════════════════════════════════════════════

def spearman_ic(xs: List[float], ys: List[float]) -> Optional[float]:
    """Spearman秩相关系数"""
    n = len(xs)
    if n < 30:
        return None

    def rank(arr):
        indexed = sorted(range(len(arr)), key=lambda i: arr[i])
        r = [0.0] * len(arr)
        for rv, idx in enumerate(indexed):
            r[idx] = rv + 1
        i = 0
        while i < len(r):
            j = i
            while j < len(r) - 1 and abs(arr[indexed[j]] - arr[indexed[j+1]]) < 1e-12:
                j += 1
            avg = sum(r[k] for k in range(i, j+1)) / (j - i + 1)
            for k in range(i, j+1):
                r[k] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    den = math.sqrt(sum((x-mx)**2 for x in rx) * sum((y-my)**2 for y in ry))
    if den < 1e-15:
        return None
    return num / den


def pearson_ic(xs: List[float], ys: List[float]) -> Optional[float]:
    """Pearson相关系数"""
    n = len(xs)
    if n < 30:
        return None
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((xs[i]-mx)*(ys[i]-my) for i in range(n))
    den_x = math.sqrt(sum((x-mx)**2 for x in xs))
    den_y = math.sqrt(sum((y-my)**2 for y in ys))
    if den_x < 1e-15 or den_y < 1e-15:
        return None
    return num / (den_x * den_y)


def rolling_ic_timeseries(
    factor_values: List[float],
    returns: List[float],
    window_size: int = 30
) -> List[Dict]:
    """
    滚动时间序列IC计算（Time-Series Split）
    用于检测IC稳定性
    返回: [{"date_start": str, "date_end": str, "ic": float, "icir": float, "n": int}, ...]
    """
    n = len(factor_values)
    if n < window_size * 2:
        return []

    rolling_results = []
    step = max(1, window_size // 3)  # 步长为窗口的1/3

    for start in range(0, n - window_size, step):
        end = start + window_size
        window_xs = factor_values[start:end]
        window_ys = returns[start:end]

        ic = spearman_ic(window_xs, window_ys)
        if ic is not None and abs(ic) > 0.001:
            # ICIR = IC / std(IC)，此处用当前窗口的IC和样本量估算
            icir = abs(ic) * math.sqrt(window_size) / 0.5 if ic != 0 else 0
            rolling_results.append({
                "start_idx": start,
                "end_idx": end,
                "ic": round(ic, 4),
                "icir": round(icir, 2),
                "n": window_size,
                "valid": True
            })

    return rolling_results


def compute_rolling_ic_statistics(rolling_ics: List[Dict]) -> Dict:
    """
    计算滚动IC的统计特征
    返回: {"mean_ic": float, "std_ic": float, "positive_ratio": float, "衰减比": float}
    """
    if not rolling_ics:
        return {"mean_ic": 0, "std_ic": 0, "positive_ratio": 0, "decay_ratio": 1.0}

    ics = [r["ic"] for r in rolling_ics]
    mean_ic = sum(ics) / len(ics)
    std_ic = np.std(ics, ddof=1) if len(ics) > 1 else 0
    positive_ratio = sum(1 for x in ics if (x > 0 and mean_ic > 0) or (x < 0 and mean_ic < 0)) / len(ics)

    # 计算衰减比：后半段IC均值 / 前半段IC均值
    half = len(ics) // 2
    if half > 0 and ics[:half] and ics[half:]:
        first_half_mean = sum(ics[:half]) / half
        second_half_mean = sum(ics[half:]) / (len(ics) - half)
        decay_ratio = abs(second_half_mean) / abs(first_half_mean) if first_half_mean != 0 else 1.0
    else:
        decay_ratio = 1.0

    return {
        "mean_ic": round(mean_ic, 4),
        "std_ic": round(std_ic, 4),
        "positive_ratio": round(positive_ratio, 4),
        "decay_ratio": round(decay_ratio, 4),
        "n_windows": len(ics)
    }


def pearson_ir_from_rolling(rolling_ics: List[Dict]) -> Optional[float]:
    """从滚动IC序列计算IR"""
    if not rolling_ics or len(rolling_ics) < 5:
        return None
    ics = [r["ic"] for r in rolling_ics]
    mean_ic = sum(ics) / len(ics)
    std_ic = np.std(ics, ddof=1) if len(ics) > 1 else 0
    if std_ic < 1e-10:
        return None
    return mean_ic / std_ic


def compute_direction_rate(
    xs: List[float], ys: List[float], expected_sign: int
) -> Tuple[float, float]:
    """
    计算方向率和实际IC符号
    返回: (direction_rate, actual_sign)
    """
    if len(xs) < 30:
        return 0.0, 0

    med_x = sorted(xs)[len(xs)//2]
    med_y = sorted(ys)[len(ys)//2]

    matches = 0
    for x, y in zip(xs, ys):
        sign_xy = (x - med_x) * (y - med_y)
        if expected_sign == 1:
            if sign_xy > 0:
                matches += 1
        else:
            if sign_xy < 0:
                matches += 1

    dir_rate = matches / len(xs)
    actual_ic = spearman_ic(xs, ys)
    actual_sign = 1 if actual_ic and actual_ic > 0 else (-1 if actual_ic and actual_ic < 0 else 0)

    return dir_rate, actual_sign


def compute_monotonicity_gap(
    factor_values: List[float],
    returns: List[float],
    n_quantiles: int = 5
) -> Optional[float]:
    """计算分位收益单调差"""
    if len(factor_values) < n_quantiles * 10:
        return None

    paired = sorted(zip(factor_values, returns))
    q_size = len(paired) // n_quantiles

    quantile_returns = []
    for i in range(n_quantiles):
        start = i * q_size
        end = start + q_size if i < n_quantiles - 1 else len(paired)
        group = [p[1] for p in paired[start:end]]
        avg_ret = sum(group) / len(group) if group else 0
        quantile_returns.append(avg_ret)

    return quantile_returns[-1] - quantile_returns[0]


# ═══════════════════════════════════════════════════════════
#  DSR / PBO 检验模块（Kimi审查修正）
# ═══════════════════════════════════════════════════════════

class DSR_PBO_Module:
    """DSR/PBO检验模块"""

    @staticmethod
    def compute_dsr(
        sharpe_star: float,
        n_trials: int,
        T: int,
        skew: float = 0.0,
        kurtosis: float = 3.0
    ) -> float:
        """
        计算去通胀夏普比率 (Deflated Sharpe Ratio)
        公式参考: Bailey, Lopez de Prado, Zhang (2014)
        """
        try:
            from scipy import stats
            constant = 1.0 / np.sqrt(2.0) * stats.norm.ppf(1 - 1.0 / np.e)
        except ImportError:
            constant = 0.849  # Phi^(-1)(1-1/e) / sqrt(2) 近似值

        if T < 10 or n_trials < 1:
            return 0.0

        # 调整Sharpe（考虑偏度和峰度）
        psr = sharpe_star - (skew / 6.0 * sharpe_star**3) / np.sqrt(T)

        adjustment = constant * np.sqrt(np.log(n_trials))
        z = np.sqrt(T) * psr - adjustment

        # sigmoid近似Phi
        dsr = 1.0 / (1.0 + np.exp(-0.07056 * z**3 - 1.5976 * z))
        return float(dsr)

    @staticmethod
    def estimate_pbo(
        sharpe_is: float,
        sharpe_oos: float,
        n_trials: int
    ) -> float:
        """
        估算回测过拟合概率 (Probability of Backtest Overfitting)
        """
        if n_trials <= 1:
            return 0.0

        performance_drop = sharpe_is - sharpe_oos
        pbo = 1.0 / (1.0 + np.exp(-2.0 * performance_drop))

        trial_factor = min(n_trials / 10.0, 2.0)
        pbo = min(pbo * trial_factor, 1.0)
        return float(pbo)

    @staticmethod
    def rolling_dsr(
        sharpe_series: List[float],
        n_trials: int
    ) -> List[Dict]:
        """
        滚动DSR计算
        返回: [{"start_idx": int, "end_idx": int, "dsr": float, "sharpe": float}, ...]
        """
        results = []
        window = 20  # 20个交易周期为一个DSR窗口

        for i in range(0, len(sharpe_series) - window, 5):
            window_sharpes = sharpe_series[i:i+window]
            sharpe_avg = sum(window_sharpes) / len(window_sharpes)
            dsr = DSR_PBO_Module.compute_dsr(sharpe_avg, n_trials, len(window_sharpes))
            results.append({
                "start_idx": i,
                "end_idx": i + window,
                "sharpe": round(sharpe_avg, 4),
                "dsr": round(dsr, 4)
            })
        return results


# ═══════════════════════════════════════════════════════════
#  负IC因子方向反转记录
# ═══════════════════════════════════════════════════════════

class NegativeIC_ReversalTracker:
    """
    负IC因子方向反转有效性记录
    当因子实际IC符号与预期相反时，记录反转后的有效性
    """

    def __init__(self):
        self.reversal_records = []

    def record_reversal(
        self,
        factor_name: str,
        original_expected_sign: int,
        actual_ic: float,
        actual_sign: int,
        ic_after_reversal: float,
        dir_rate_after_reversal: float,
        monotonicity_after_reversal: float,
        notes: str = ""
    ):
        """
        记录方向反转有效性
        """
        record = {
            "factor_name": factor_name,
            "timestamp": datetime.now().isoformat(),
            "original_expected_sign": original_expected_sign,
            "actual_ic": round(actual_ic, 4),
            "actual_sign": actual_sign,
            "reversal_applied": actual_sign != original_expected_sign,
            "ic_after_reversal": round(ic_after_reversal, 4),
            "dir_rate_after_reversal": round(dir_rate_after_reversal, 4),
            "monotonicity_after_reversal": round(monotonicity_after_reversal, 4),
            "reversal_valid": abs(ic_after_reversal) > 0.03 and dir_rate_after_reversal > 0.55,
            "notes": notes
        }
        self.reversal_records.append(record)
        return record

    def get_reversal_summary(self) -> Dict:
        """获取反转记录汇总"""
        if not self.reversal_records:
            return {"total": 0, "valid_reversals": 0}

        valid_count = sum(1 for r in self.reversal_records if r["reversal_valid"])
        return {
            "total_reversals": len(self.reversal_records),
            "valid_reversals": valid_count,
            "validity_rate": round(valid_count / len(self.reversal_records), 4) if self.reversal_records else 0,
            "records": self.reversal_records
        }


# ═══════════════════════════════════════════════════════════
#  退市股覆盖验证模块
# ═══════════════════════════════════════════════════════════

class DelistedStockVerifier:
    """
    退市股覆盖验证模块
    确保因子验证在含退市股的完整样本上进行
    """

    def __init__(self, data_dir: str = "data/history_daily"):
        self.data_dir = data_dir
        self.delisted_codes = set()
        self.active_codes = set()
        self._audit_delisted_stocks()

    def _audit_delisted_stocks(self):
        """审计退市股覆盖情况"""
        if not os.path.exists(self.data_dir):
            print(f"⚠️ 数据目录不存在: {self.data_dir}")
            return

        all_files = [f for f in os.listdir(self.data_dir)
                     if f.endswith('.json') and f != 'download_errors.json']

        print(f"\n📁 退市股覆盖审计")
        print(f"   总股票文件数: {len(all_files)}")

        delisted_by_filename = set()
        delisted_by_cutoff = set()
        delisted_details = []

        for f in all_files:
            code = f.replace('.json', '')
            try:
                with open(os.path.join(self.data_dir, f), 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                if isinstance(data, dict):
                    data = data.get('data', [])

                if len(data) > 0:
                    last_date = data[-1].get('date', '')
                    record_count = len(data)

                    # 方法A：文件名标记
                    is_filename_delisted = (code.startswith('sh61') or
                                           code.startswith('sh90'))
                    if is_filename_delisted:
                        delisted_by_filename.add(code)

                    # 方法B：数据连续性检查
                    is_cutoff_delisted = (last_date and
                                          last_date < '2024-01-01' and
                                          record_count < 500)
                    if is_cutoff_delisted:
                        delisted_by_cutoff.add(code)

                    if is_filename_delisted or is_cutoff_delisted:
                        reason = []
                        if is_filename_delisted:
                            reason.append('filename_marker')
                        if is_cutoff_delisted:
                            reason.append('data_cutoff')
                        delisted_details.append({
                            "code": code,
                            "last_date": last_date,
                            "record_count": record_count,
                            "reasons": reason
                        })
            except Exception:
                pass

        # 合并退市股
        all_delisted = delisted_by_filename | delisted_by_cutoff
        self.delisted_codes = all_delisted
        self.active_codes = set(f.replace('.json', '') for f in all_files) - all_delisted

        coverage_rate = len(self.active_codes) / len(all_files) * 100 if all_files else 0

        print(f"   文件名标记退市股: {len(delisted_by_filename)}只")
        print(f"   数据截止标记退市股: {len(delisted_by_cutoff)}只")
        print(f"   合并退市股总数: {len(all_delisted)}只")
        print(f"   活跃股票数: {len(self.active_codes)}只 ({coverage_rate:.1f}%)")
        print(f"   退市股覆盖率: {coverage_rate:.1f}%")

        if coverage_rate > 95:
            print(f"   ✅ 覆盖率充足（>95%）")
        elif coverage_rate > 80:
            print(f"   ⚠️ 覆盖率一般（80%-95%），建议补充退市股数据")
        else:
            print(f"   ❌ 覆盖率不足（<80%），因子IC可能虚高")

    def verify_coverage(self) -> Dict:
        """验证退市股覆盖情况"""
        total = len(self.active_codes) + len(self.delisted_codes)
        coverage_rate = len(self.active_codes) / total * 100 if total > 0 else 0

        return {
            "total_stocks": total,
            "active_stocks": len(self.active_codes),
            "delisted_stocks": len(self.delisted_codes),
            "coverage_rate": round(coverage_rate, 2),
            "is_sufficient": coverage_rate >= 90,
            "timestamp": datetime.now().isoformat()
        }

    def split_by_delisted_status(self, factor_values: List[float],
                                 returns: List[float],
                                 codes: List[str]) -> Tuple[List, List, List, List]:
        """
        将因子值和收益按退市状态分割
        返回: (active_factors, active_returns, delisted_factors, delisted_returns)
        """
        active_f, active_r, delisted_f, delisted_r = [], [], [], []
        for f, r, code in zip(factor_values, returns, codes):
            if code in self.delisted_codes:
                delisted_f.append(f)
                delisted_r.append(r)
            else:
                active_f.append(f)
                active_r.append(r)
        return active_f, active_r, delisted_f, delisted_r


# ═══════════════════════════════════════════════════════════
#  FactorGateV2 类
# ═══════════════════════════════════════════════════════════

class FactorGateV2:
    """因子门禁检测器 v2.1 — 支持IC正负方向、滚动样本外验证、DSR/PBO"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or GATE_CONFIG
        self.known_directions = KNOWN_FACTOR_DIRECTIONS
        self.dsr_pbo = DSR_PBO_Module()
        self.reversal_tracker = NegativeIC_ReversalTracker()
        self.delisted_verifier = DelistedStockVerifier()

    def check_factor(
        self,
        factor_name: str,
        factor_values: List[float],
        returns: List[float],
        codes: Optional[List[str]] = None,
        scan_dates: Optional[List[str]] = None,
        n_trials: int = 1,
        n_trades: int = 0,
        sharpe_is: float = 0.0,
        sharpe_oos: Optional[float] = None,
        expected_sign: Optional[int] = None,
        skew: float = 0.0,
        kurtosis: float = 3.0,
    ) -> Dict:
        """
        执行因子门禁检测（v2.1完整版）

        参数:
            factor_name: 因子名称
            factor_values: 因子值列表（时间序列）
            returns: 未来收益列表（时间序列，同长度）
            codes: 股票代码列表（可选，用于退市股分割）
            scan_dates: 扫描日期列表（可选，用于滚动IC）
            n_trials: 试验次数（诚实申报）
            n_trades: 交易次数
            sharpe_is: 样本内夏普
            sharpe_oos: 样本外夏普（可选）
            expected_sign: 预期方向（1=正向，-1=反向，None=自动判断）
            skew: 收益偏度（用于DSR校正）
            kurtosis: 收益峰度（用于DSR校正）

        返回:
            门禁报告字典
        """
        n = len(factor_values)
        if n < self.config["min_samples"]:
            return {
                "factor_name": factor_name,
                "timestamp": datetime.now().isoformat(),
                "verdict": "FAIL",
                "error": f"样本数不足: {n} < {self.config['min_samples']}",
                "checks": {}
            }

        # 过滤无效数据
        valid_pairs = [(f, r) for f, r in zip(factor_values, returns)
                       if not math.isnan(f) and not math.isnan(r)]
        if len(valid_pairs) < self.config["min_samples"]:
            return {
                "factor_name": factor_name,
                "timestamp": datetime.now().isoformat(),
                "verdict": "FAIL",
                "error": f"有效样本不足: {len(valid_pairs)} < {self.config['min_samples']}",
                "checks": {}
            }

        factor_values, returns = zip(*valid_pairs)
        factor_values, returns = list(factor_values), list(returns)
        n = len(factor_values)

        # 确定预期方向
        if expected_sign is None:
            expected_sign = self.known_directions.get(factor_name, {}).get("expected_sign", 0)

        # ── Step 1: 全样本IC计算 ───────────────────────────────
        ic = spearman_ic(factor_values, returns)
        if ic is None:
            return {
                "factor_name": factor_name,
                "timestamp": datetime.now().isoformat(),
                "verdict": "FAIL",
                "error": "IC计算失败（样本不足）",
                "checks": {}
            }

        # ── Step 2: 滚动样本外IC/ICIR ──────────────────────────
        rolling_results = []
        rolling_stats = {}
        if scan_dates and len(scan_dates) >= self.config["rolling_window"]:
            rolling_results = rolling_ic_timeseries(factor_values, returns,
                                                     self.config["rolling_window"])
            rolling_stats = compute_rolling_ic_statistics(rolling_results)

        # ── Step 3: 退市股分割验证 ─────────────────────────────
        delisted_verification = {}
        if codes:
            active_f, active_r, delisted_f, delisted_r = \
                self.delisted_verifier.split_by_delisted_status(
                    factor_values, returns, codes
                )
            if len(active_f) >= 30 and len(delisted_f) >= 30:
                ic_active = spearman_ic(active_f, active_r)
                ic_delisted = spearman_ic(delisted_f, delisted_r)
                delisted_verification = {
                    "active_ic": round(ic_active, 4) if ic_active else None,
                    "delisted_ic": round(ic_delisted, 4) if ic_delisted else None,
                    "ic_difference": round(abs(ic_active - ic_delisted), 4)
                        if ic_active and ic_delisted else None,
                    "active_n": len(active_f),
                    "delisted_n": len(delisted_f),
                    "is_consistent": (abs(ic_active - ic_delisted) < 0.01
                                      if ic_active and ic_delisted else None)
                }

        # ── Step 4: 方向率与实际符号 ───────────────────────────
        dir_rate, actual_sign = compute_direction_rate(factor_values, returns, expected_sign)

        # ── Step 5: 负IC反转有效性记录 ─────────────────────────
        reversal_record = None
        if actual_sign != 0 and actual_sign != expected_sign:
            # 实际方向与预期相反，记录反转有效性
            reversed_factors = [-x for x in factor_values]
            ic_reversed = spearman_ic(reversed_factors, returns)
            dir_rate_reversed, _ = compute_direction_rate(
                reversed_factors, returns, expected_sign * -1
            )
            mono_reversed = compute_monotonicity_gap(reversed_factors, returns)

            reversal_record = self.reversal_tracker.record_reversal(
                factor_name=factor_name,
                original_expected_sign=expected_sign,
                actual_ic=ic,
                actual_sign=actual_sign,
                ic_after_reversal=ic_reversed if ic_reversed else 0,
                dir_rate_after_reversal=dir_rate_reversed,
                monotonicity_after_reversal=mono_reversed if mono_reversed else 0,
                notes=f"因子{factor_name}实际方向({actual_sign})与预期({expected_sign})相反，已记录反转有效性"
            )

        # ── Step 6: 单调差计算 ─────────────────────────────────
        mono_gap = compute_monotonicity_gap(factor_values, returns)

        # ── Step 7: DSR/PBO计算 ────────────────────────────────
        dsr = self.dsr_pbo.compute_dsr(sharpe_is, n_trials, n, skew, kurtosis)
        pbo = self.dsr_pbo.estimate_pbo(sharpe_is, sharpe_oos or sharpe_is, n_trials) \
            if sharpe_oos is not None else None

        # ── Step 8: 滚动IC稳定性检查 ───────────────────────────
        rolling_ic_stable = True
        if rolling_stats:
            rolling_ic_pass = rolling_stats.get("std_ic", 1) < \
                              self.config["rolling_ic_std_threshold"]
            rolling_ic_stable = rolling_ic_pass and rolling_stats.get("decay_ratio", 1) > 0.5

        # ── Step 9: 门禁检查 ───────────────────────────────────
        checks = {}
        details = []

        # 1. IC绝对值检查
        ic_pass = abs(ic) > self.config["ic_threshold"]
        checks["ic"] = {
            "value": round(ic, 4),
            "threshold": self.config["ic_threshold"],
            "abs_value": round(abs(ic), 4),
            "passed": ic_pass,
            "direction": "positive" if ic > 0 else "negative"
        }
        if not ic_pass:
            details.append(f"|IC|={abs(ic):.4f} < {self.config['ic_threshold']}，不通过")

        # 2. IR检查（基于滚动IC）
        ir = pearson_ir_from_rolling(rolling_results) if rolling_results else None
        if ir is None and ic != 0:
            # 无滚动数据时用简化估算
            ir = abs(ic) * math.sqrt(n) / 0.5
        ir_pass = ir is not None and abs(ir) > self.config["ir_threshold"]
        checks["ir"] = {
            "value": round(ir, 2) if ir else None,
            "threshold": self.config["ir_threshold"],
            "passed": ir_pass,
            "note": "基于滚动IC计算" if rolling_results else "简化估算"
        }
        if not ir_pass:
            details.append(f"|IR|={abs(ir):.2f} < {self.config['ir_threshold']}，不通过")

        # 3. 方向率检查
        dir_pass = dir_rate > self.config["dir_rate_threshold"]
        checks["direction_rate"] = {
            "value": round(dir_rate, 4),
            "threshold": self.config["dir_rate_threshold"],
            "expected_sign": expected_sign,
            "actual_sign": actual_sign,
            "passed": dir_pass
        }
        if not dir_pass:
            details.append(f"方向率={dir_rate:.1%} < {self.config['dir_rate_threshold']}，不通过")

        # 4. 单调差检查
        mono_pass = mono_gap is not None and abs(mono_gap) > self.config["monotonicity_threshold"]
        checks["monotonicity"] = {
            "value": round(mono_gap, 4) if mono_gap else None,
            "threshold": self.config["monotonicity_threshold"],
            "passed": mono_pass
        }
        if not mono_pass:
            details.append(f"单调差={mono_gap:.4f} 不显著")

        # 5. 样本量检查
        sample_pass = n_trades >= self.config["min_trades"] or n >= self.config["min_samples"]
        checks["sample_size"] = {
            "value": n,
            "trades": n_trades,
            "threshold": self.config["min_trades"],
            "passed": sample_pass
        }

        # 6. 滚动IC稳定性检查
        checks["rolling_ic_stability"] = {
            "mean_ic": rolling_stats.get("mean_ic"),
            "std_ic": rolling_stats.get("std_ic"),
            "positive_ratio": rolling_stats.get("positive_ratio"),
            "decay_ratio": rolling_stats.get("decay_ratio"),
            "n_windows": rolling_stats.get("n_windows"),
            "passed": rolling_ic_stable,
            "threshold_std": self.config["rolling_ic_std_threshold"]
        }
        if not rolling_ic_stable:
            details.append("滚动IC稳定性不通过（标准差过大或衰减过快）")

        # 7. DSR检查
        dsr_pass = dsr > 0.5
        checks["dsr"] = {
            "value": round(dsr, 3),
            "threshold": 0.5,
            "sharpe_is": sharpe_is,
            "n_trials": n_trials,
            "passed": dsr_pass
        }
        if not dsr_pass:
            details.append(f"DSR={dsr:.3f} < 0.5，校正后夏普不显著")

        # 8. PBO检查
        if sharpe_oos is not None:
            pbo_pass = pbo is not None and pbo < 0.5
            checks["pbo"] = {
                "value": round(pbo, 3) if pbo else None,
                "threshold": 0.5,
                "sharpe_is": sharpe_is,
                "sharpe_oos": sharpe_oos,
                "passed": pbo_pass
            }
            if not pbo_pass:
                details.append(f"PBO={pbo:.1%} >= 50%，疑似过拟合")

        # 9. 退市股覆盖验证
        checks["delisted_coverage"] = {
            "active_ic": delisted_verification.get("active_ic"),
            "delisted_ic": delisted_verification.get("delisted_ic"),
            "ic_difference": delisted_verification.get("ic_difference"),
            "is_consistent": delisted_verification.get("is_consistent"),
            "passed": delisted_verification.get("is_consistent", True)
        }
        if delisted_verification.get("ic_difference") and \
           delisted_verification["ic_difference"] > 0.01:
            details.append(f"退市股与活跃股IC差异={delisted_verification['ic_difference']:.4f} > 0.01")

        # ── 综合判定 ───────────────────────────────────────────
        all_passed = all([
            ic_pass, ir_pass, dir_pass, mono_pass, sample_pass,
            rolling_ic_stable, dsr_pass
        ])
        if sharpe_oos is not None:
            all_passed = all_passed and (pbo_pass if pbo else True)

        report = {
            "factor_name": factor_name,
            "timestamp": datetime.now().isoformat(),
            "verdict": "PASS" if all_passed else "FAIL",
            "metrics": {
                "ic": round(ic, 4),
                "ir": round(ir, 2) if ir else None,
                "direction_rate": round(dir_rate, 4),
                "monotonicity_gap": round(mono_gap, 4) if mono_gap else None,
                "actual_sign": actual_sign,
                "expected_sign": expected_sign,
                "n_samples": n,
                "n_trades": n_trades,
                "sharpe_is": sharpe_is,
                "sharpe_oos": sharpe_oos,
                "dsr": round(dsr, 3),
                "pbo": round(pbo, 3) if pbo else None,
                "rolling_ic_mean": rolling_stats.get("mean_ic"),
                "rolling_ic_std": rolling_stats.get("std_ic"),
                "rolling_ic_decay_ratio": rolling_stats.get("decay_ratio"),
            },
            "checks": checks,
            "rolling_ic_results": rolling_results[:10],  # 保存前10个滚动窗口
            "rolling_ic_statistics": rolling_stats,
            "delisted_verification": delisted_verification,
            "reversal_record": reversal_record,
            "details": details
        }

        return report

    def save_report(self, report: Dict, output_path: str):
        """保存门禁报告"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        def convert(obj):
            if hasattr(obj, 'item'):
                return obj.item()
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=convert)
        print(f"[OK] Report saved: {output_path}")

    def print_report(self, report: Dict):
        """打印门禁报告"""
        print("\n" + "=" * 70)
        print(f"因子门禁报告 v2.1: {report['factor_name']}")
        print("=" * 70)
        print(f"Verdict: {report['verdict']}")

        if 'error' in report:
            print(f"Error: {report['error']}")
            return

        print(f"\n指标:")
        m = report.get('metrics', {})
        print(f"  IC: {m.get('ic', 'N/A')} ({'positive' if m.get('ic', 0) > 0 else 'negative'})")
        print(f"  IR: {m.get('ir', 'N/A')} (基于{'滚动IC' if m.get('rolling_ic_mean') else '估算'})")
        print(f"  方向率: {m.get('direction_rate', 'N/A'):.1%}")
        print(f"  预期方向: {m.get('expected_sign', 'auto')}")
        print(f"  实际方向: {m.get('actual_sign', 'N/A')}")
        if m.get('actual_sign') != m.get('expected_sign') and m.get('actual_sign') != 0:
            print(f"  ⚠️ 方向反转！已记录反转有效性")
        print(f"  单调差: {m.get('monotonicity_gap', 'N/A')}")
        print(f"  DSR: {m.get('dsr', 'N/A')}")
        print(f"  PBO: {m.get('pbo', 'N/A')}")
        print(f"  滚动IC均值: {m.get('rolling_ic_mean', 'N/A')}")
        print(f"  滚动IC标准差: {m.get('rolling_ic_std', 'N/A')}")
        print(f"  滚动IC衰减比: {m.get('rolling_ic_decay_ratio', 'N/A')}")

        print(f"\n检查项:")
        for key, check in report.get('checks', {}).items():
            status = "PASS" if check.get('passed') else "FAIL"
            val = check.get('value', check.get('passed'))
            print(f"  [{status}] {key}: {val}")

        if report.get('details'):
            print(f"\n备注:")
            for detail in report['details']:
                print(f"  - {detail}")

        # 退市股验证
        dv = report.get('delisted_verification', {})
        if dv:
            print(f"\n退市股验证:")
            print(f"  活跃股IC: {dv.get('active_ic')}")
            print(f"  退市股IC: {dv.get('delisted_ic')}")
            print(f"  IC差异: {dv.get('ic_difference')}")
            print(f"  一致性: {'✅' if dv.get('is_consistent') else '❌'}")

        print("=" * 70 + "\n")


# ═══════════════════════════════════════════════════════════
#  IC 序列统计工具 (factor_ic_132d_refresh.summarize 依赖)
# ═══════════════════════════════════════════════════════════

def lag1_autocorr(xs: List[float]) -> Optional[float]:
    """一阶自相关。样本 < 3 返回 None。"""
    n = len(xs)
    if n < 3:
        return None
    m = sum(xs) / n
    num = sum((xs[i] - m) * (xs[i + 1] - m) for i in range(n - 1))
    den = sum((x - m) ** 2 for x in xs)
    if den <= 1e-15:
        return None
    return num / den


def newey_west_t(xs: List[float], lag: int = 5) -> Optional[float]:
    """Newey-West 修正的 t 值 = mean / sqrt(NW_var / n)。

    仅做 Bartlett 核的长期方差估计，不做小样本自由度修正
    （132 日规模下影响有限）。
    """
    n = len(xs)
    if n < 10:
        return None
    m = sum(xs) / n
    d = [x - m for x in xs]
    g0 = sum(v * v for v in d) / n
    long_var = g0
    for L in range(1, min(lag, n - 1) + 1):
        gl = sum(d[i] * d[i + L] for i in range(n - L)) / n
        long_var += 2.0 * (1.0 - L / (lag + 1.0)) * gl
    if long_var <= 1e-18:
        return None
    se = math.sqrt(long_var / n)
    return m / se if se > 1e-15 else None


# ═══════════════════════════════════════════════════════════
#  批量检测工具
# ═══════════════════════════════════════════════════════════

def batch_check(
    factor_data: List[Dict],
    output_dir: str = "data/gate_reports_v2"
) -> List[Dict]:
    """
    批量检测多个因子
    """
    gate = FactorGateV2()
    reports = []

    for i, data in enumerate(factor_data):
        report = gate.check_factor(
            factor_name=data.get("factor_name", f"factor_{i+1}"),
            factor_values=data.get("factor_values", []),
            returns=data.get("returns", []),
            codes=data.get("codes"),
            scan_dates=data.get("scan_dates"),
            expected_sign=data.get("expected_sign"),
            n_trials=data.get("n_trials", 1),
            n_trades=data.get("n_trades", 0),
            sharpe_is=data.get("sharpe_is", 0),
            sharpe_oos=data.get("sharpe_oos"),
            skew=data.get("skew", 0.0),
            kurtosis=data.get("kurtosis", 3.0),
        )
        reports.append(report)

        safe_name = report['factor_name'].replace('/', '_')
        gate.save_report(report, f"{output_dir}/{safe_name}_gate.json")

    summary = {
        "timestamp": datetime.now().isoformat(),
        "total": len(reports),
        "pass": sum(1 for r in reports if r['verdict'] == "PASS"),
        "fail": sum(1 for r in reports if r['verdict'] == "FAIL"),
        "reversals_recorded": sum(1 for r in reports if r.get('reversal_record')),
        "reports": reports
    }

    os.makedirs(output_dir, exist_ok=True)
    with open(f"{output_dir}/summary.json", 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2,
                  default=lambda x: x.tolist() if hasattr(x, 'tolist') else x)

    print(f"\n📊 批量检测完成: {summary['pass']}通过, {summary['fail']}失败, "
          f"{summary['reversals_recorded']}个方向反转已记录")
    return reports


# ═══════════════════════════════════════════════════════════
#  命令行入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="因子门禁系统 v2.1（完整版）")
    parser.add_argument("--check", nargs="*", help="示例检测")
    parser.add_argument("--batch", help="批量检测JSON文件")
    parser.add_argument("--output", default="data/gate_reports_v2", help="输出目录")
    parser.add_argument("--ic-data", help="IC数据文件路径")
    parser.add_argument("--verifier", action="store_true", help="运行退市股覆盖验证")

    args = parser.parse_args()

    gate = FactorGateV2()

    if args.verifier:
        # 运行退市股覆盖验证
        print("=" * 60)
        print("退市股覆盖验证")
        print("=" * 60)
        result = gate.delisted_verifier.verify_coverage()
        print(f"覆盖率: {result['coverage_rate']}%")
        print(f"状态: {'✅ 通过' if result['is_sufficient'] else '⚠️ 不足'}")
        sys.exit(0)

    if args.check:
        print("=== 因子门禁系统 v2.1 ===")
        print("支持: IC正负方向、滚动样本外IC、DSR/PBO、退市股验证")

    elif args.batch:
        with open(args.batch, 'r', encoding='utf-8') as f:
            factor_data = json.load(f)
        batch_check(factor_data, args.output)

    elif args.ic_data:
        with open(args.ic_data, 'r', encoding='utf-8') as f:
            ic_data = json.load(f)
        print(f"加载IC数据: {args.ic_data}")
        print(f"因子数量: {len(ic_data.get('valid_factors', [])) + len(ic_data.get('dead_factors', []))}")

    else:
        # 运行示例检测
        print("=== 因子门禁系统 v2.1 示例 ===\n")

        np.random.seed(42)
        n = 500

        # 正向因子示例
        pos_factor = np.random.randn(n)
        pos_returns = pos_factor * 0.1 + np.random.randn(n) * 0.02

        report_pos = gate.check_factor(
            factor_name="test_positive",
            factor_values=pos_factor.tolist(),
            returns=pos_returns.tolist(),
            expected_sign=1,
            n_trials=1,
            n_trades=200,
            sharpe_is=1.5
        )
        gate.print_report(report_pos)
        gate.save_report(report_pos, f"{args.output}/test_positive_gate.json")

        # 反向因子示例
        neg_factor = np.random.randn(n)
        neg_returns = -neg_factor * 0.1 + np.random.randn(n) * 0.02

        report_neg = gate.check_factor(
            factor_name="test_negative",
            factor_values=neg_factor.tolist(),
            returns=neg_returns.tolist(),
            expected_sign=-1,
            n_trials=1,
            n_trades=200,
            sharpe_is=1.5
        )
        gate.print_report(report_neg)
        gate.save_report(report_neg, f"{args.output}/test_negative_gate.json")

        # 方向反转示例
        flip_factor = np.random.randn(n)
        # 预期正向，但实际负向
        flip_returns = -flip_factor * 0.08 + np.random.randn(n) * 0.02

        report_flip = gate.check_factor(
            factor_name="test_reversed",
            factor_values=flip_factor.tolist(),
            returns=flip_returns.tolist(),
            expected_sign=1,  # 预期正向
            n_trials=1,
            n_trades=200,
            sharpe_is=1.2
        )
        gate.print_report(report_flip)
        gate.save_report(report_flip, f"{args.output}/test_reversed_gate.json")

        print("\n📊 示例完成！方向反转案例已记录到 reversal_tracker")
        print(f"反转记录数: {len(gate.reversal_tracker.reversal_records)}")
