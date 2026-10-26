#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
refresh_financial.py — 财务数据刷新脚本
cron: 每日盘后 16:00（与 akshare_daily_pull.py 并行）

功能:
  1. 从 AKShare/东财拉取最新财务指标
  2. 写入 data/financial_cache.json
  3. 更新 updated_at 时间戳

用法:
  python refresh_financial.py [--force]
"""
import os, sys, json, time
from datetime import datetime, date

PROJECT = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(PROJECT) == 'scripts':
    PROJECT = os.path.dirname(PROJECT)
sys.path.insert(0, PROJECT)

from financial_filter import batch_fetch, _load_cache, _save_cache, CACHE_FILE, CACHE_TTL

TODAY = date.today()
TODAY_STR = TODAY.strftime("%Y%m%d")

def main(force=False):
    """刷新财务数据"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] refresh_financial: 开始")
    
    # 检查缓存是否过期
    if not force:
        try:
            with open(CACHE_FILE) as f:
                cache = json.load(f)
            cached_at = cache.get('_timestamp', 0)
            age = time.time() - cached_at
            if age < CACHE_TTL:
                print(f"  缓存新鲜 (age={age/3600:.1f}h)，跳过")
                return True
        except FileNotFoundError:
            pass
    
    print(f"  拉取财务数据...")
    try:
        # 获取全量股票列表
        import csv
        codes = []
        tdx_path = os.path.join(PROJECT, "data", "tdx_all_stocks.csv")
        if os.path.exists(tdx_path):
            with open(tdx_path, encoding='utf-8') as f:
                reader = csv.DictReader(f)
                codes = [row['code'] for row in reader]
        else:
            # 降级：从 stock_names.json 读取（根目录）
            names_path = os.path.join(PROJECT, "stock_names.json")
            if os.path.exists(names_path):
                with open(names_path, encoding='utf-8') as f:
                    names_data = json.load(f)
                    codes = list(names_data.keys())
            else:
                # 最后降级：从缓存加载已有代码
                cache = _load_cache()
                codes = list(cache.keys()) if cache else []
    
        if not codes:
            print("  ⚠️ 无股票代码，跳过刷新")
            return True
    
        print(f"  准备拉取 {len(codes)} 只股票...")
        data = batch_fetch(codes, force_refresh=True)
        if not data:
            return False
        
        # 写入缓存
        _save_cache(data)
        
        print(f"  ✅ 写入 {len(data)} 只财务数据 -> {CACHE_FILE}")
        return True
    except Exception as e:
        print(f"  ❌ 刷新失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    force = '--force' in sys.argv
    success = main(force=force)
    sys.exit(0 if success else 1)
