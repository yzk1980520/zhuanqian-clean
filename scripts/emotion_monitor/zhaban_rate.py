#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
炸板率监控脚本
功能：计算当日炸板率，监控市场情绪
数据源：AKShare（备用：Tushare Pro）
"""

import akshare as ak
from datetime import datetime
import json
import sys
from pathlib import Path

def calculate_zhaban_rate(date=None):
    """
    计算当日炸板率
    
    输入: 日期 (YYYY-MM-DD)，默认为今日
    输出: 炸板率 (%)
    
    逻辑：
    1. 获取当日涨停股列表
    2. 获取当日全市场涨跌数据
    3. 计算涨停开板率（涨幅<9.5%视为炸板）
    """
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    print(f"[{datetime.now()}] 开始计算炸板率...")
    
    try:
        # 获取全市场实时行情
        df = ak.stock_zh_a_spot_em()
        
        # 计算涨跌家数
        up_count = len(df[df['涨跌幅'] > 0])
        down_count = len(df[df['涨跌幅'] < 0])
        flat_count = len(df[df['涨跌幅'] == 0])
        total_count = len(df)
        
        # 计算涨跌比
        up_down_ratio = up_count / down_count if down_count > 0 else float('inf')
        
        # 获取涨停股（简化：涨幅>9.5%视为涨停）
        limit_up = df[df['涨跌幅'] > 9.5]
        limit_up_count = len(limit_up)
        
        # 计算炸板率（涨停开板）
        # 简化逻辑：涨幅在5%-9.5%区间的视为炸板
        broken_limit = df[(df['涨跌幅'] >= 5) & (df['涨跌幅'] < 9.5)]
        broken_count = len(broken_limit)
        
        # 炸板率 = 炸板数 / 涨停数
        zhaban_rate = (broken_count / limit_up_count * 100) if limit_up_count > 0 else 0
        
        result = {
            'date': date,
            'timestamp': datetime.now().isoformat(),
            'zhaban_rate': round(zhaban_rate, 2),
            'limit_up_count': limit_up_count,
            'broken_count': broken_count,
            'up_count': up_count,
            'down_count': down_count,
            'flat_count': flat_count,
            'total_count': total_count,
            'up_down_ratio': round(up_down_ratio, 2)
        }
        
        print(f"✅ 炸板率计算完成:")
        print(f"   - 炸板率: {zhaban_rate:.2f}%")
        print(f"   - 涨停数: {limit_up_count}只")
        print(f"   - 炸板数: {broken_count}只")
        print(f"   - 上涨: {up_count}只, 下跌: {down_count}只")
        print(f"   - 涨跌比: {up_down_ratio:.2f}")
        
        return result
        
    except Exception as e:
        error_msg = f"❌ 炸板率计算失败: {e}"
        print(error_msg)
        
        # 返回错误结果
        return {
            'date': date,
            'timestamp': datetime.now().isoformat(),
            'error': str(e),
            'zhaban_rate': None,
            'status': 'failed'
        }

def save_result(result, output_dir='output'):
    """保存结果到文件"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    filename = f"zhaban_rate_{result['date'].replace('-', '')}.json"
    filepath = output_path / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"💾 结果已保存: {filepath}")
    return filepath

if __name__ == "__main__":
    # 执行计算
    result = calculate_zhaban_rate()
    
    # 保存结果
    if result.get('status') != 'failed':
        save_result(result)
    
    # 输出JSON格式（便于后续处理）
    print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
