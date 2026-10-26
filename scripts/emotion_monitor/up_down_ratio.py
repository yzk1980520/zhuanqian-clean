#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
涨跌比监控脚本
功能：计算当日市场涨跌比，评估市场情绪
数据源：AKShare
"""

import akshare as ak
from datetime import datetime
import json
from pathlib import Path

def calculate_up_down_ratio(date=None):
    """
    计算当日涨跌比
    
    输入: 日期 (YYYY-MM-DD)，默认为今日
    输出: 涨跌比及详细统计
    
    逻辑：
    1. 获取全市场实时行情
    2. 统计上涨、下跌、平盘股票数量
    3. 计算涨跌比
    """
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    print(f"[{datetime.now()}] 开始计算涨跌比...")
    
    try:
        # 获取全市场实时行情
        df = ak.stock_zh_a_spot_em()
        
        # 统计各项指标
        up_count = len(df[df['涨跌幅'] > 0])
        down_count = len(df[df['涨跌幅'] < 0])
        flat_count = len(df[df['涨跌幅'] == 0])
        limit_up = len(df[df['涨跌幅'] > 9.5])
        limit_down = len(df[df['涨跌幅'] < -9.5])
        total_count = len(df)
        
        # 计算涨跌比
        up_down_ratio = up_count / down_count if down_count > 0 else float('inf')
        
        # 计算强势股比例
        strong_ratio = (up_count + limit_up) / total_count * 100 if total_count > 0 else 0
        
        result = {
            'date': date,
            'timestamp': datetime.now().isoformat(),
            'up_down_ratio': round(up_down_ratio, 2),
            'up_count': up_count,
            'down_count': down_count,
            'flat_count': flat_count,
            'limit_up': limit_up,
            'limit_down': limit_down,
            'total_count': total_count,
            'strong_ratio': round(strong_ratio, 2)
        }
        
        print(f"✅ 涨跌比计算完成:")
        print(f"   - 涨跌比: {up_down_ratio:.2f}")
        print(f"   - 上涨: {up_count}只")
        print(f"   - 下跌: {down_count}只")
        print(f"   - 平盘: {flat_count}只")
        print(f"   - 涨停: {limit_up}只")
        print(f"   - 跌停: {limit_down}只")
        print(f"   - 强势比例: {strong_ratio:.2f}%")
        
        # 评估市场状态
        if up_down_ratio > 2.0:
            market_state = '强势上涨'
        elif up_down_ratio > 1.5:
            market_state = '偏强震荡'
        elif up_down_ratio > 0.5:
            market_state = '弱势震荡'
        else:
            market_state = '弱势下跌'
        
        result['market_state'] = market_state
        print(f"   - 市场状态: {market_state}")
        
        return result
        
    except Exception as e:
        error_msg = f"❌ 涨跌比计算失败: {e}"
        print(error_msg)
        
        return {
            'date': date,
            'timestamp': datetime.now().isoformat(),
            'error': str(e),
            'up_down_ratio': None,
            'status': 'failed'
        }

def save_result(result, output_dir='output'):
    """保存结果到文件"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    filename = f"up_down_ratio_{result['date'].replace('-', '')}.json"
    filepath = output_path / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"💾 结果已保存: {filepath}")
    return filepath

if __name__ == "__main__":
    # 执行计算
    result = calculate_up_down_ratio()
    
    # 保存结果
    if result.get('status') != 'failed':
        save_result(result)
    
    # 输出JSON格式
    print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
