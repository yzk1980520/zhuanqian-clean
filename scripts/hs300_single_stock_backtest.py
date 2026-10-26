#!/usr/bin/env python3
"""
沪深主板单票全仓策略回测引擎

策略：
- 选股：沪深主板 3301 只
- 全仓1只：每日选股评分最高
- 止损：8%硬止损 + 移动止盈阶梯
- 止盈：浮盈10%内回撤6%，20%内8%，40%内10%，以上12%
- 时间止损：20日
- 成本：万2.5 + 滑点0.1%
"""
import os, json, sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

PROJECT = Path(r"D:\open code\zhuanqian")
DATA_DIR = PROJECT / "data" / "history_daily"

STOP_LOSS = -0.08
MAX_HOLD = 20
COST = 0.001

TP_LADDER = [
    (10, 0.06),
    (20, 0.08),
    (40, 0.10),
    (999, 0.12),
]

WEIGHTS = {
    'trend': 0.30,
    'volume': 0.25,
    'reversal': 0.25,
    'volatility': 0.20,
}


def load_stock(code: str) -> Optional[List[Dict]]:
    fpath = DATA_DIR / f"{code}.json"
    if not fpath.exists():
        return None
    try:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("data", [])
        return sorted(data, key=lambda x: x["date"])
    except Exception:
        print(f"🔴 [scripts\hs300_single_stock_backtest.py] CR-01(return): except Exception:", file=sys.stderr)
        return None
def get_all_codes() -> List[str]:
    if not DATA_DIR.exists():
        return []
    codes = []
    for f in os.listdir(DATA_DIR):
        if not f.endswith(".json"):
            continue
        code = f[:-5]
        if (code.startswith("sh60") or code.startswith("sh61") or
            code.startswith("sz000") or code.startswith("sz001") or code.startswith("sz002")):
            if "history_daily" not in code:
                codes.append(code)
    return sorted(codes)


def ma(values: List[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def compute_scores(bars: List[Dict]) -> Dict[str, float]:
    if len(bars) < 60:
        return {'total': 0}
    closes = [b["close"] for b in bars]
    volumes = [b.get("volume", 0) for b in bars]
    total = 0.0
    
    # 趋势
    ma20 = ma(closes, 20)
    ma60 = ma(closes, 60)
    if ma20 and ma60:
        trend = 0
        if closes[-1] > ma20:
            trend += 30
        if closes[-1] > ma60:
            trend += 30
        if ma20 > ma60:
            trend += 40
        total += WEIGHTS['trend'] * trend
    
    # 量能
    vol5 = ma(volumes, 5)
    vol20 = ma(volumes, 20)
    if vol5 and vol20 and vol20 > 0:
        vol_ratio = vol5 / vol20
        volume_score = min(100, vol_ratio * 50)
        total += WEIGHTS['volume'] * volume_score
    
    # 反转
    chg_5d = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
    if -8 <= chg_5d <= -3:
        reversal = 100
    elif -10 <= chg_5d < -8:
        reversal = 70
    elif -3 < chg_5d <= 0:
        reversal = 50
    else:
        reversal = 0
    total += WEIGHTS['reversal'] * reversal
    
    # 波动率
    if len(closes) >= 20:
        recent = closes[-20:]
        mean = sum(recent) / len(recent)
        var = sum((x - mean) ** 2 for x in recent) / len(recent)
        std = var ** 0.5 / mean * 100
        if 2 <= std <= 5:
            vol_score = 100
        elif std < 2:
            vol_score = 50
        else:
            vol_score = max(0, 100 - (std - 5) * 10)
        total += WEIGHTS['volatility'] * vol_score
    
    return {'total': round(min(100, max(0, total)), 2)}


if __name__ == "__main__":
    codes = get_all_codes()
    print(f"获取代码: {len(codes)}")
    
    stocks = {}
    for code in codes:
        data = load_stock(code)
        if data and len(data) >= 60:
            stocks[code] = {b["date"]: b for b in data}
    
    print(f"有效股票: {len(stocks)}")
    
    all_dates = set()
    for d in stocks.values():
        all_dates.update(d.keys())
    dates = sorted(all_dates)
    print(f"交易日: {len(dates)}")
    print(f"数据范围: {dates[0]} 至 {dates[-1]}")
