"""P1修复: 真突破特征检测指标
基于KIMI审查-20诊断结果实现

真突破票特征 (2026-09-05实测):
- vol_ratio > 1.5 (成交量放大)
- ma5_ma20 > 1.05 (均线多头排列)
- chg20 > 15% (中期动量)
- close > ma20 (价格站上均线)

横盘震荡票特征:
- vol_ratio < 1.2
- ma5_ma20 ≈ 1.0
- chg20 < 5%

门禁标准: 至少满足3条(2硬+1软)
"""
import numpy as np
from typing import List, Dict, Tuple


def calc_vol_ratio(closes: List[float], volumes: List[float], period: int = 20) -> float:
    """计算成交量比(当日成交量 / 20日均量)
    
    Returns:
        vol_ratio: 当日成交量与20日均量的比值
                   >1.5 = 放量突破
                   <1.2 = 缩量横盘
    """
    if len(volumes) < period + 1:
        return 1.0
    
    # 计算20日均量(排除当日)
    avg_vol = sum(volumes[-period-1:-1]) / period
    if avg_vol == 0:
        return 1.0
    
    vol_ratio = volumes[-1] / avg_vol
    return round(vol_ratio, 2)


def calc_ma_trend(closes: List[float], fast: int = 5, slow: int = 20) -> Tuple[float, float]:
    """计算均线多头排列指标
    
    Returns:
        ma5_ma20: MA5 / MA20比值
                  >1.05 = 强势多头
                  <0.95 = 弱势空头
                  ≈1.0 = 横盘震荡
        ma_above: MA5在MA20上方的距离百分比
    """
    if len(closes) < slow + 1:
        return 1.0, 0.0
    
    # 计算MA5和MA20
    ma5 = sum(closes[-fast-1:-1]) / fast
    ma20 = sum(closes[-slow-1:-1]) / slow
    
    if ma20 == 0:
        return 1.0, 0.0
    
    ma5_ma20 = ma5 / ma20
    ma_above = (ma5 - ma20) / ma20 * 100  # 百分比
    
    return round(ma5_ma20, 3), round(ma_above, 2)


def calc_breakout_score(closes: List[float], volumes: List[float],
                       current_price: float,
                       vol_threshold: float = 1.5,
                       ma_threshold: float = 1.03) -> Dict[str, object]:
    """计算真突破综合评分
    
    Args:
        closes: 收盘价序列
        volumes: 成交量序列
        current_price: 当前价格
        vol_threshold: 成交量放大阈值(默认1.5)
        ma_threshold: 均线多头阈值(默认1.05)
    
    Returns:
        {
            'score': int,           # 综合评分(0-100)
            'breakout': bool,       # 是否真突破
            'hard_conditions': int, # 硬条件满足数
            'soft_conditions': int, # 软条件满足数
            'details': dict         # 详细指标
        }
    """
    # 计算基础指标
    vol_ratio = calc_vol_ratio(closes, volumes)
    ma5_ma20, ma_above = calc_ma_trend(closes)
    
    # 计算20日涨幅
    chg20 = 0.0
    if len(closes) >= 21:
        chg20 = (closes[-1] - closes[-21]) / closes[-21] * 100
    
    # 判断条件
    hard_conditions = 0  # 硬条件(必须满足)
    soft_conditions = 0  # 软条件(加分项)
    
    # 硬条件1: 成交量放大 (vol_ratio > 1.5)
    if vol_ratio >= vol_threshold:
        hard_conditions += 1
    
    # 硬条件2: 均线多头 (MA5 > MA20)
    if ma5_ma20 >= ma_threshold:
        hard_conditions += 1
    
    # 软条件1: 中期动量 (chg20 > 10%)
    if chg20 >= 10:
        soft_conditions += 1
    
    # 软条件2: 价格站上MA20 (close > MA20)
    if len(closes) >= 21:
        ma20 = sum(closes[-21:-1]) / 20
        if current_price > ma20:
            soft_conditions += 1
    
    # 计算综合评分
    score = hard_conditions * 30 + soft_conditions * 20
    
    # 判定是否真突破(至少满足3条: 2硬+1软 或 1硬+3软 或 1硬+2软+高分)
    breakout = (hard_conditions >= 2 and soft_conditions >= 1) or \
               (hard_conditions >= 1 and soft_conditions >= 3) or \
               (hard_conditions >= 1 and soft_conditions >= 2 and score >= 60) or \
               hard_conditions >= 3
    
    return {
        'score': score,
        'breakout': breakout,
        'hard_conditions': hard_conditions,
        'soft_conditions': soft_conditions,
        'details': {
            'vol_ratio': vol_ratio,
            'ma5_ma20': ma5_ma20,
            'chg20': round(chg20, 2),
            'ma_above': ma_above
        }
    }


def is_true_breakout(records: List[Dict], current_price: float,
                    vol_threshold: float = 1.5,
                    ma_threshold: float = 1.05) -> bool:
    """判断是否为真突破(简化接口)
    
    Args:
        records: 历史行情记录列表, 每项包含'close', 'volume', 'date'
        current_price: 当前价格
        vol_threshold: 成交量阈值
        ma_threshold: 均线阈值
    
    Returns:
        True = 真突破, False = 非真突破(横盘/震荡/下跌)
    """
    if not records or len(records) < 21:
        return False
    
    # 提取收盘价和成交量序列
    closes = [r['close'] for r in records[-25:]]
    volumes = [r['volume'] for r in records[-25:]]
    
    # 调用综合评分
    result = calc_breakout_score(closes, volumes, current_price, 
                                vol_threshold, ma_threshold)
    
    return result['breakout']


if __name__ == "__main__":
    # 测试示例
    print("=== 真突破特征检测验证 ===\n")
    
    # 模拟数据
    test_records = [
        {'close': 10.0 + i * 0.1, 'volume': 100000 + i * 1000, 'date': f"2026-09-{i:02d}"}
        for i in range(30)
    ]
    
    result = calc_breakout_score(
        closes=[r['close'] for r in test_records],
        volumes=[r['volume'] for r in test_records],
        current_price=test_records[-1]['close']
    )
    
    print(f"真突破检测结果: {result['breakout']}")
    print(f"综合评分: {result['score']}")
    print(f"硬条件满足: {result['hard_conditions']}/2")
    print(f"软条件满足: {result['soft_conditions']}/2")
    print(f"详细指标: {result['details']}")