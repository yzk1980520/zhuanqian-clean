"""
公共工具函数 — 从 tdx_score.py 提取 (2026-09-23)
"""


def has_recent_gap(records, days=30, threshold=15.0):
    """H2修复: 检测最近days日内有无>threshold%跳空(除权特征)
    实盘防护: 未复权TDX数据在除权日产生假跳空, 污染断层/指标。
    刚除权的股票排除(或降权), 避免把除权当缺口。records为日线列表。
    返回 (has_gap: bool, gap_date: str|None, gap_pct: float)
    """
    if not records or len(records) < 3:
        return False, None, 0.0
    recent = records[-days:]
    for i in range(1, len(recent)):
        c0 = recent[i - 1].get("close", 0) or 0
        c1 = recent[i].get("close", 0) or 0
        if c0 > 0:
            pct = abs((c1 - c0) / c0 * 100)
            if pct > threshold:
                return True, str(recent[i].get("date", "")), round(pct, 1)
    return False, None, 0.0
