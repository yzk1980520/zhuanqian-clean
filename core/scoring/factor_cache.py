# -*- coding: utf-8 -*-
"""factor_cache.py — 因子缓存层（扩展版，S0 2026-09-20）

职责：
  S0: 每股 × 全历史 → 时序指标一次算完落盘（MACD/ATR/动量/量能/换手率斜率/资金流代理/超跌/跳空）
  S1: 引擎层加载指标 → 按日切截面 → 横截面运算（排名/标准化/协方差）→ 出分

架构：
  数据层: data/scan_cache/<code>.json（每股一个文件，含全历史指标）
  引擎层: backtest_rotation.py 从缓存加载，不做时序计算

关键保证：
  - point-in-time: 指标值在计算日即固定，S1 切片不会引入未来数据
  - 增量更新: 仅重新计算新数据/变化的股票
  - data_version: 数据变更自动失效
"""
import json
import os
import hashlib
from datetime import date, datetime
import core.pipeline.atomic_json as atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 基地化S3 (2026-10-22): 根锚点(迁前=仓库根)
CACHE_DIR = os.path.join(BASE, "data", "scan_cache")
HISTORY_DIR = os.path.join(BASE, "data", "history_daily")
STOCK_CACHE_DIR = os.path.join(BASE, "data", "stock_cache")


def _dir_signature(path):
    """目录签名: 文件数 + 最大 mtime。返回稳定短哈希或 'unknown'。"""
    try:
        if not os.path.isdir(path):
            return "unknown"
        mtimes = []
        count = 0
        for f in os.listdir(path):
            p = os.path.join(path, f)
            if os.path.isfile(p) and f.endswith(".json"):
                count += 1
                try:
                    mtimes.append(os.path.getmtime(p))
                except OSError:
                    pass
        if not mtimes:
            return "unknown"
        sig = f"{count}-{max(mtimes):.6f}"
        return hashlib.md5(sig.encode("utf-8")).hexdigest()[:12]
    except Exception:
        return "unknown"


def data_version():
    """当前数据版本签名（基于目录mtime，忽略文件数量变化）。"""
    try:
        if not os.path.isdir(HISTORY_DIR):
            return "unknown"
        mtimes = []
        for f in os.listdir(HISTORY_DIR):
            p = os.path.join(HISTORY_DIR, f)
            if os.path.isfile(p) and f.endswith(".json"):
                try:
                    mtimes.append(os.path.getmtime(p))
                except OSError:
                    pass
        if not mtimes:
            return "unknown"
        return hashlib.md5(f"{max(mtimes):.6f}".encode()).hexdigest()[:12]
    except Exception:
        return "unknown"


def _day_path(day):
    return os.path.join(CACHE_DIR, f"{day}.json")


def _stock_cache_path(code):
    """S0: 每股缓存文件路径"""
    return os.path.join(STOCK_CACHE_DIR, f"{code}.json")


def sanitize(obj):
    """把 date/datetime 转为 ISO 字符串，其余原样返回。用于 JSON 可序列化。"""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, tuple):
        return [sanitize(v) for v in obj]
    return obj


class FactorCache:
    """扫描日因子缓存。

    用法:
        fc = FactorCache(use_disk=True)
        hit = fc.get_day("2024-01-05")   # (scan_inds, cross_ranks) 或 None
        fc.put_day("2024-01-05", scan_inds, cross_ranks)
    """

    _MEM = {}  # day -> {"scan_inds": [...], "cross_ranks": {...}, "version": str, "codes_sig": str}

    def __init__(self, use_disk=True, codes=None):
        self.use_disk = use_disk
        self.codes_sig = self._sig(codes)

    @staticmethod
    def _sig(codes):
        if not codes:
            return None
        try:
            return hashlib.md5("|".join(sorted(codes)).encode("utf-8")).hexdigest()[:12]
        except Exception:
            return None

    def get_day(self, day):
        """按扫描日取缓存。命中返回 (scan_inds, cross_ranks)，未命中返回 None。
        命中条件: 数据版本一致，且(本实例未绑定股票范围 或 缓存股票范围一致)。"""
        ver = data_version()
        hit = FactorCache._MEM.get(str(day))
        if hit and hit.get("version") == ver:
            if self.codes_sig is None or hit.get("codes_sig") == self.codes_sig:
                return hit["scan_inds"], hit["cross_ranks"]
        if self.use_disk:
            p = _day_path(day)
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, json.JSONDecodeError):
                    return None
                if data.get("version") == ver:
                    if self.codes_sig is not None and data.get("codes_sig") != self.codes_sig:
                        return None
                    FactorCache._MEM[str(day)] = data
                    return data["scan_inds"], data["cross_ranks"]
        return None

    def put_day(self, day, scan_inds, cross_ranks):
        """写入内存+磁盘缓存（原子）。日期自动转字符串。"""
        day_s = str(day)
        ver = data_version()
        payload = {
            "day": day_s,
            "version": ver,
            "codes_sig": self.codes_sig,
            "scan_inds": sanitize(scan_inds),
            "cross_ranks": sanitize(cross_ranks),
        }
        FactorCache._MEM[day_s] = payload
        if self.use_disk:
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                tmp = _day_path(day_s) + ".tmp"
                atomic_json.atomic_dump(payload, tmp, ensure_ascii=False, encoding="utf-8")
                os.replace(tmp, _day_path(day_s))
            except OSError:
                pass
        return True

    def invalidate(self):
        """清内存缓存（磁盘按版本自动失效）。"""
        FactorCache._MEM.clear()


# ============================================================
#  S0: 时序指标预计算（2026-09-20 新增）
# ============================================================

def _compute_temporal_indicators(records):
    """
    计算单只股票全历史的时序指标（向量化优化版）。
    
    返回: dict[date_str] -> {atr14, momentum_20, vol_ratio, turnover_slope, 
                              money_flow_proxy, rsi14, oversold, gap_up, gap_down}
    """
    import numpy as np
    
    n = len(records)
    if n < 30:
        return {}
    
    # 格式检查
    required_fields = {"date", "open", "high", "low", "close", "volume"}
    if not all(required_fields.issubset(r.keys()) for r in records[:3]):
        return {}
    
    # 提取 NumPy 数组
    closes = np.array([r.get("close", 0.0) for r in records], dtype=np.float64)
    opens = np.array([r.get("open", 0.0) for r in records], dtype=np.float64)
    highs = np.array([r.get("high", 0.0) for r in records], dtype=np.float64)
    lows = np.array([r.get("low", 0.0) for r in records], dtype=np.float64)
    volumes = np.array([r.get("volume", 0) for r in records], dtype=np.float64)
    dates = [r.get("date") for r in records]
    
    # ATR14 向量化
    tr = np.maximum(highs[1:] - lows[1:], 
                   np.maximum(abs(highs[1:] - closes[:-1]), 
                                  abs(lows[1:] - closes[:-1])))
    atr14 = np.full(n, np.nan)
    if len(tr) >= 14:
        atr = np.mean(tr[:14])
        atr14[14] = atr
        for i in range(14, len(tr)):
            atr = (atr * 13 + tr[i]) / 14
            atr14[i+1] = atr
    
    # 20日动量
    momentum_20 = np.full(n, np.nan)
    if n > 20:
        mask = closes[:-20] > 0
        momentum_20[20:] = np.where(mask, (closes[20:] / closes[:-20] - 1.0) * 100, np.nan)
    
    # 量比（5日/20日均量）
    vol_ratio = np.ones(n)
    if n > 20:
        for i in range(20, n):
            avg_5 = np.mean(volumes[max(0,i-4):i+1])
            avg_20 = np.mean(volumes[i-19:i+1])
            vol_ratio[i] = avg_5 / avg_20 if avg_20 > 0 else 1.0
    
    # RSI14 向量化
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    rsi14 = np.full(n, 50.0)
    if len(gains) >= 14:
        avg_gain = np.mean(gains[:14])
        avg_loss = np.mean(losses[:14])
        rs = avg_gain / avg_loss if avg_loss > 0 else 1e10
        rsi14[14] = 100 - 100 / (1 + rs)
        for i in range(14, len(gains)):
            avg_gain = (avg_gain * 13 + gains[i]) / 14
            avg_loss = (avg_loss * 13 + losses[i]) / 14
            rs = avg_gain / avg_loss if avg_loss > 0 else 1e10
            rsi14[i+1] = 100 - 100 / (1 + rs)
    
    # 跳空
    gap_up = np.zeros(n, dtype=bool)
    gap_down = np.zeros(n, dtype=bool)
    if n > 1:
        prev_close = closes[:-1]
        curr_open = opens[1:]
        mask = prev_close > 0
        gap_pct = np.where(mask, (curr_open / prev_close - 1.0) * 100, 0)
        gap_up[1:] = gap_pct > 2.0
        gap_down[1:] = gap_pct < -2.0
    
    # 组装
    result = {}
    for i in range(n):
        d = dates[i]
        d_str = str(d) if not isinstance(d, (date, datetime)) else d.isoformat()
        result[d_str] = {
            "atr14": float(atr14[i]) if not np.isnan(atr14[i]) else None,
            "momentum_20": float(momentum_20[i]) if not np.isnan(momentum_20[i]) else None,
            "vol_ratio": float(vol_ratio[i]),
            "rsi14": float(rsi14[i]),
            "oversold": bool(rsi14[i] < 30),
            "gap_up": bool(gap_up[i]),
            "gap_down": bool(gap_down[i]),
            "close": float(closes[i]),
            "volume": int(volumes[i]),
        }
    
    return result


def precompute_all_stocks():
    """
    S0: 全量预计算所有股票的时序指标，落盘到 data/stock_cache/<code>.json
    
    返回: {"total": int, "computed": int, "skipped": int, "errors": int}
    """
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    
    os.makedirs(STOCK_CACHE_DIR, exist_ok=True)
    
    if not os.path.isdir(HISTORY_DIR):
        print(f"❌ 历史数据目录不存在: {HISTORY_DIR}")
        return {"total": 0, "computed": 0, "skipped": 0, "errors": 1}
    
    files = [f for f in os.listdir(HISTORY_DIR) if f.endswith(".json")]
    total = len(files)
    computed = 0
    skipped = 0
    errors = 0
    
    print(f"📊 S0: 开始预计算 {total} 只股票的时序指标...")
    
    for i, f in enumerate(files, 1):
        code = f.replace(".json", "")
        cache_path = _stock_cache_path(code)
        
        # 检查缓存是否已存在且数据版本一致
        if os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as fh:
                    cached = json.load(fh)
                if cached.get("data_version") == data_version():
                    skipped += 1
                    if i % 500 == 0:
                        print(f"  进度: {i}/{total} (跳过{skipped})", flush=True)
                    continue
            except Exception:
                pass
        
        # 加载历史数据
        try:
            with open(os.path.join(HISTORY_DIR, f), encoding="utf-8") as fh:
                records = json.load(fh)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  ❌ 加载失败 {code}: {type(e).__name__}: {e}", flush=True)
            continue
        
        # 格式检查
        if not isinstance(records, list) or len(records) < 30:
            skipped += 1
            continue
        
        required_fields = {"date", "open", "high", "low", "close", "volume"}
        if not all(required_fields.issubset(r.keys()) for r in records[:3]):
            skipped += 1
            if skipped <= 3:
                print(f"  ⚠️ 格式不兼容 {code}: keys={list(records[0].keys())[:6]}", flush=True)
            continue

        # 排序防御(2026-10-15): 强制升序, 降序数据会导致时序指标反向计算
        assert records[0]["date"] <= records[-1]["date"], (
            f"{code}: history_daily 数据非升序 ({records[0]['date']} > {records[-1]['date']}), "
            f"运行 scripts/fix_sort_order.py 修复"
        )
        # 计算时序指标
        try:
            temporal = _compute_temporal_indicators(records)
            if not temporal:
                skipped += 1
                continue
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  ❌ 计算失败 {code}: {type(e).__name__}: {e}", flush=True)
            continue
        
        # 落盘（批量预计算无并发写入，直接用 json.dump 替代 atomic_dump 避免文件锁）
        try:
            payload = {
                "code": code,
                "data_version": data_version(),
                "last_updated": datetime.now().isoformat(),
                "n_records": len(records),
                "temporal": temporal,
            }
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=None, separators=(",", ":"))
            computed += 1
        except Exception:
            errors += 1
        
        if i % 500 == 0:
            print(f"  进度: {i}/{total} (计算{computed} 跳过{skipped} 错误{errors})", flush=True)
    
    print(f"✅ S0: 完成 — 总计{total} 计算{computed} 跳过{skipped} 错误{errors}")
    return {"total": total, "computed": computed, "skipped": skipped, "errors": errors}


def load_stock_temporal(code, target_date):
    cache_path = _stock_cache_path(code)
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, encoding="utf-8") as f:
            cached = json.load(f)
    except Exception:
        return None
    d_str = str(target_date) if not isinstance(target_date, (date, datetime)) else target_date.isoformat()
    return cached.get("temporal", {}).get(d_str)


def load_market_temporal(target_date, codes=None):
    """
    S1: 加载目标日期全市场的时序指标。
    
    Args:
        target_date: 目标日期
        codes: 股票代码列表（可选，None 表示加载全部）
    
    Returns:
        dict[code_str] -> {atr14, momentum_20, vol_ratio, ...}
    """
    d_str = str(target_date) if not isinstance(target_date, (date, datetime)) else target_date.isoformat()
    
    if codes is not None:
        # 加载指定股票
        result = {}
        for code in codes:
            temporal = load_stock_temporal(code, target_date)
            if temporal:
                result[code] = temporal
        return result
    
    # 加载全部
    if not os.path.isdir(STOCK_CACHE_DIR):
        return {}
    
    result = {}
    for f in os.listdir(STOCK_CACHE_DIR):
        if not f.endswith(".json"):
            continue
        code = f.replace(".json", "")
        try:
            with open(os.path.join(STOCK_CACHE_DIR, f), encoding="utf-8") as fh:
                cached = json.load(fh)
            if cached.get("data_version") != data_version():
                continue
            temporal = cached.get("temporal", {}).get(d_str)
            if temporal:
                result[code] = temporal
        except Exception:
            continue
    
    return result


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    
    print("=" * 60)
    print("S0: 时序指标预计算")
    print("=" * 60)
    
    result = precompute_all_stocks()
    
    print()
    print("结果:")
    for k, v in result.items():
        print(f"  {k}: {v}")
