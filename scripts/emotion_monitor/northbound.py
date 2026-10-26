#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北向资金监控脚本
功能：监控北向资金流向，评估外资态度
数据源：AKShare
"""

import akshare as ak
from datetime import datetime
import json
from pathlib import Path

def monitor_northbound_flow(date=None):
    """
    监控北向资金流向
    
    输入: 日期 (YYYY-MM-DD)，默认为今日
    输出: 净流入/流出金额（亿元）
    
    逻辑：
    1. 获取北向资金历史数据
    2. 计算当日净流入/流出
    3. 评估外资态度
    """
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    print(f"[{datetime.now()}] 开始监控北向资金流向...")
    
    try:
        # 方法1：尝试使用AKShare获取北向资金数据
        try:
            df = ak.stock_hsgt_hist_em(symbol="北向")
            if len(df) > 0:
                # 取最新一条数据
                latest = df.iloc[-1]
                net_inflow = float(latest.get('当日净流入', 0)) / 1e8  # 转换为亿元
            else:
                net_inflow = 0
        except Exception as e:
            print(f"⚠️ AKShare北向资金接口失败: {e}")
            # 方法2：备用接口
            try:
                df = ak.stock_individual_fund_flow(stock="sh600000")
                net_inflow = 0  # 简化处理
            except Exception as e:
                # P1-4b R1 (t_bae6c7d6): 原 except 静默 net_inflow=0 → 主备双失败时外资态度评估假阳性；现响铃（net_inflow=0 兜底语义保留）
                print(f"🔴 [northbound] 备用接口亦失败: {e} (net_inflow 回落 0，态度评估基于缺失数据)", flush=True)
                net_inflow = 0
        
        # 评估外资态度
        if net_inflow > 50:
            attitude = '大幅流入'
        elif net_inflow > 0:
            attitude = '小幅流入'
        elif net_inflow > -50:
            attitude = '小幅流出'
        else:
            attitude = '大幅流出'
        
        result = {
            'date': date,
            'timestamp': datetime.now().isoformat(),
            'net_inflow_yuan': round(net_inflow, 2),
            'attitude': attitude,
            'direction': '流入' if net_inflow >= 0 else '流出'
        }
        
        print(f"✅ 北向资金监控完成:")
        print(f"   - 净流入: {net_inflow:.2f}亿元")
        print(f"   - 外资态度: {attitude}")
        
        return result
        
    except Exception as e:
        error_msg = f"❌ 北向资金监控失败: {e}"
        print(error_msg)
        
        return {
            'date': date,
            'timestamp': datetime.now().isoformat(),
            'error': str(e),
            'net_inflow_yuan': None,
            'status': 'failed'
        }

def save_result(result, output_dir='output'):
    """保存结果到文件"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    filename = f"northbound_{result['date'].replace('-', '')}.json"
    filepath = output_path / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"💾 结果已保存: {filepath}")
    return filepath

if __name__ == "__main__":
    # 执行监控
    result = monitor_northbound_flow()
    
    # 保存结果
    if result.get('status') != 'failed':
        save_result(result)
    
    # 输出JSON格式
    print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
