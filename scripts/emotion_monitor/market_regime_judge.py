#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场环境判定脚本
功能：综合多项指标判定当前市场环境（震荡市/趋势市/门关）
输入：成交额、炸板率、涨跌比、北向资金
输出：市场状态 + 策略建议
"""

import json
from datetime import datetime
from pathlib import Path

def judge_market_regime(volume_100m=None, zhaban_rate=None, up_down_ratio=None, northbound_100m=None):
    """
    市场环境判定函数
    
    参数:
        volume_100m: 日成交额（亿元）
        zhaban_rate: 炸板率（%）
        up_down_ratio: 涨跌比
        northbound_100m: 北向资金净流入（亿元）
    
    返回:
        dict: 市场状态判定结果
    """
    signals = []
    
    print(f"[{datetime.now()}] 开始市场环境判定...")
    print(f"   输入: 成交额={volume_100m}亿, 炸板率={zhaban_rate}%, 涨跌比={up_down_ratio}, 北向={northbound_100m}亿")
    
    # 1. 成交额判定
    if volume_100m is not None:
        if volume_100m >= 20000:
            signals.append('成交量充足')
        elif volume_100m < 15000:
            signals.append('成交量不足')
        else:
            signals.append('成交量正常')
    
    # 2. 炸板率判定
    if zhaban_rate is not None:
        if zhaban_rate < 15:
            signals.append('情绪稳定')
        elif zhaban_rate < 20:
            signals.append('情绪正常')
        elif zhaban_rate < 25:
            signals.append('情绪过热')
        else:
            signals.append('情绪极端')
    
    # 3. 涨跌比判定
    if up_down_ratio is not None:
        if up_down_ratio > 2.0:
            signals.append('强势上涨')
        elif up_down_ratio > 1.5:
            signals.append('偏强震荡')
        elif up_down_ratio > 0.5:
            signals.append('弱势震荡')
        else:
            signals.append('弱势下跌')
    
    # 4. 北向资金判定
    if northbound_100m is not None:
        if northbound_100m > 50:
            signals.append('外资流入')
        elif northbound_100m > 0:
            signals.append('外资小幅流入')
        elif northbound_100m > -50:
            signals.append('外资小幅流出')
        else:
            signals.append('外资流出')
    
    # 5. 综合判定
    regime = '震荡市'
    confidence = 0.5
    
    if '成交量不足' in signals and '情绪极端' in signals:
        regime = '门关'
        confidence = 0.8
    elif '成交量充足' in signals and ('情绪稳定' in signals or '情绪正常' in signals):
        regime = '趋势市'
        confidence = 0.7
    elif '外资流出' in signals and '成交量不足' in signals:
        regime = '震荡市'
        confidence = 0.6
    else:
        regime = '震荡市'
        confidence = 0.5
    
    # 6. 生成策略建议
    strategy_advice = generate_strategy_advice(regime, signals)
    
    result = {
        'timestamp': datetime.now().isoformat(),
        'regime': regime,
        'confidence': confidence,
        'signals': signals,
        'strategy_advice': strategy_advice
    }
    
    print(f"\n✅ 市场判定完成:")
    print(f"   - 环境状态: {regime}")
    print(f"   - 置信度: {confidence:.0%}")
    print(f"   - 市场信号: {', '.join(signals)}")
    print(f"\n📋 策略建议:")
    for k, v in strategy_advice.items():
        print(f"   - {k}: {v}")
    
    return result

def generate_strategy_advice(regime, signals):
    """根据市场状态生成策略建议"""
    
    advice = {}
    
    if regime == '门关':
        advice = {
            '仓位建议': '≤30%',
            '入场时机': '暂停买入，等待企稳',
            '止损纪律': '-3%（收紧）',
            '持仓周期': '1-3日（快进快出）',
            '风险等级': '极高',
            '操作建议': '减仓观望，不追高'
        }
    elif regime == '趋势市':
        advice = {
            '仓位建议': '70-100%',
            '入场时机': '可积极配置',
            '止损纪律': '-8%（宽松）',
            '持仓周期': '5-10日（波段操作）',
            '风险等级': '低',
            '操作建议': '跟随主线，持有待涨'
        }
    else:  # 震荡市
        advice = {
            '仓位建议': '30-50%',
            '入场时机': 'T+2确认量能后',
            '止损纪律': '-5%（标准）',
            '持仓周期': '3-5日（短线操作）',
            '风险等级': '中',
            '操作建议': '快进快出，低吸高抛'
        }
    
    return advice

def save_result(result, output_dir='output'):
    """保存结果到文件"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    filename = f"market_regime_{datetime.now().strftime('%Y%m%d')}.json"
    filepath = output_path / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 结果已保存: {filepath}")
    return filepath

if __name__ == "__main__":
    # 测试：使用当前市场数据
    # 注：实际使用时应读取实时数据
    test_data = {
        'volume_100m': 14200,  # 节前成交额1.42万亿
        'zhaban_rate': 17.0,   # 炸板率17%
        'up_down_ratio': 1.8,  # 涨跌比1.8:1
        'northbound_100m': 12.0  # 北向资金+12亿
    }
    
    result = judge_market_regime(**test_data)
    save_result(result)
    
    print("\n" + "="*60)
    print("测试数据说明:")
    print(f"  - 成交额1.42万亿 < 1.5万亿阈值 → 成交量不足")
    print(f"  - 炸板率17% ∈ [15%, 20%) → 情绪正常")
    print(f"  - 涨跌比1.8 ∈ [1.5, 2.0] → 偏强震荡")
    print(f"  - 北向+12亿 ∈ (0, 50] → 外资小幅流入")
    print(f"\n综合判定: 震荡市（偏强）")
    print("="*60)
