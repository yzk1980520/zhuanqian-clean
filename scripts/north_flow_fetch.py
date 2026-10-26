# -*- coding: utf-8 -*-
"""
north_flow_fetch.py — 北向资金数据获取脚本
========================================================================
功能:
1. 获取北向资金（沪深港通）净流入数据
2. 使用akshare替代已失效的东方财富API
3. 存储到data/north_flow/*.json

执行方式: python scripts/north_flow_fetch.py

数据源:
- akshare.stock_hsgt_hist_em(symbol="北向资金") (北向资金历史净流入)
- akshare.stock_hsgt_hold_stock_em(market="沪股通/深股通") (持股明细)

注意: stock_hsgt_north_net_flow_in_em 和 stock_hsgt_hold_stock_info_sh/sz 已不存在
"""
import os
import sys
import json
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

# 项目根目录
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT, "data")
NORTH_FLOW_DIR = os.path.join(DATA_DIR, "north_flow")

def fetch_north_flow_net():
    """获取北向资金净流入数据"""
    if not AKSHARE_AVAILABLE:
        return None
    
    try:
        pass
        # 使用正确的API: stock_hsgt_hist_em
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        
        if df is None or len(df) == 0:
            return None
        
        # 转换为字典列表，处理日期类型
        data = []
        for _, row in df.iterrows():
            record = {}
            for col in df.columns:
                val = row[col]
                # 处理日期类型
                if hasattr(val, 'isoformat'):
                    val = val.isoformat()
                elif pd.isna(val):
                    val = None
                record[col] = val
            data.append(record)
        
        # 保存
        today = datetime.now().strftime("%Y%m%d")
        output_file = os.path.join(NORTH_FLOW_DIR, f"north_flow_{today}.json")
        
        os.makedirs(NORTH_FLOW_DIR, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                "date": today,
                "source": "akshare",
                "api": "stock_hsgt_hist_em",
                "data": data,
                "count": len(data)
            }, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 北向资金数据已保存: {output_file}")
        print(f"   记录数: {len(data)}")
        
        return data
        
    except Exception as e:
        print(f"❌ 获取北向资金数据失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def fetch_north_flow_hold():
    """获取北向资金持股明细"""
    if not AKSHARE_AVAILABLE:
        return None
    
    try:
        pass
        # 尝试获取持股数据（API可能不稳定）
        sh_df = None
        sz_df = None
        
        try:
            sh_df = ak.stock_hsgt_hold_stock_em(market="沪股通")
            if sh_df is None or len(sh_df) == 0:
                sh_df = None
        except Exception as e:
            print(f"  ⚠️ 沪股通持股获取失败: {e}")
        
        try:
            sz_df = ak.stock_hsgt_hold_stock_em(market="深股通")
            if sz_df is None or len(sz_df) == 0:
                sz_df = None
        except Exception as e:
            print(f"  ⚠️ 深股通持股获取失败: {e}")
        
        if sh_df is None and sz_df is None:
            return None
        
        # 保存
        today = datetime.now().strftime("%Y%m%d")
        output_file = os.path.join(NORTH_FLOW_DIR, f"north_flow_hold_{today}.json")
        
        os.makedirs(NORTH_FLOW_DIR, exist_ok=True)
        
        result = {
            "date": today,
            "source": "akshare",
            "api": "stock_hsgt_hold_stock_em",
            "sh_count": len(sh_df) if sh_df is not None else 0,
            "sz_count": len(sz_df) if sz_df is not None else 0
        }
        
        if sh_df is not None:
            # 处理日期类型
            sh_data = []
            for _, row in sh_df.iterrows():
                record = {}
                for col in sh_df.columns:
                    val = row[col]
                    if hasattr(val, 'isoformat'):
                        val = val.isoformat()
                    elif pd.isna(val):
                        val = None
                    record[col] = val
                sh_data.append(record)
            result["sh_data"] = sh_data
        
        if sz_df is not None:
            sz_data = []
            for _, row in sz_df.iterrows():
                record = {}
                for col in sz_df.columns:
                    val = row[col]
                    if hasattr(val, 'isoformat'):
                        val = val.isoformat()
                    elif pd.isna(val):
                        val = None
                    record[col] = val
                sz_data.append(record)
            result["sz_data"] = sz_data
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 北向持股数据已保存: {output_file}")
        print(f"   沪股通: {result['sh_count']}只, 深股通: {result['sz_count']}只")
        
        return {
            "sh": sh_df,
            "sz": sz_df
        }
        
    except Exception as e:
        print(f"❌ 获取北向持股数据失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def check_data_freshness(hours=24):
    """检查数据新鲜度"""
    if not os.path.exists(NORTH_FLOW_DIR):
        print(f"⚠️ 数据目录不存在: {NORTH_FLOW_DIR}")
        return False
    
    # 查找最新的JSON文件
    json_files = list(Path(NORTH_FLOW_DIR).glob("north_flow_*.json"))
    
    if not json_files:
        print(f"⚠️ 未找到北向资金数据文件")
        return False
    
    # 按修改时间排序
    latest_file = max(json_files, key=lambda x: x.stat().st_mtime)
    mtime = datetime.fromtimestamp(latest_file.stat().st_mtime)
    age_hours = (datetime.now() - mtime).total_seconds() / 3600
    
    if age_hours > hours:
        print(f"⚠️ 数据过期: {latest_file.name} ({age_hours:.1f}小时前)")
        return False
    else:
        print(f"✅ 数据新鲜: {latest_file.name} ({age_hours:.1f}小时前)")
        return True

def main():
    """主函数"""
    
    # 检查akshare
    if not AKSHARE_AVAILABLE:
        return 1
    
    print(f"✅ akshare版本: {ak.__version__}")
    
    # 获取数据
    net_data = fetch_north_flow_net()
    hold_data = fetch_north_flow_hold()
    
    # 检查新鲜度
    check_data_freshness()
    
    
    return 0 if (net_data or hold_data) else 1

if __name__ == "__main__":
    sys.exit(main())
