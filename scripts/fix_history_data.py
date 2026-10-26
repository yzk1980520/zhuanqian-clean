#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史数据修复脚本
功能: 修复日期排序、清理过期数据、验证数据完整性
"""
import json
from pathlib import Path
from datetime import datetime, timedelta

PROJECT = Path(__file__).parent.parent
HISTORY_DIR = PROJECT / "data" / "history_daily"

def fix_data_sorting():
    """修复数据排序问题"""
    print("=" * 70)
    print("【历史数据修复】")
    print("=" * 70)
    print()
    
    fixed_count = 0
    error_count = 0
    
    for file_path in HISTORY_DIR.glob("*.json"):
        try:
            data = json.loads(file_path.read_text())
            
            if not isinstance(data, list) or len(data) == 0:
                continue
            
            # 检查是否已排序（最新在前）
            dates = [r.get('date', '') for r in data]
            is_sorted = all(dates[i] >= dates[i+1] for i in range(len(dates)-1))
            
            if not is_sorted:
                # 按日期降序排序
                sorted_data = sorted(data, key=lambda x: x.get('date', ''), reverse=True)
                file_path.write_text(json.dumps(sorted_data, ensure_ascii=False, indent=2), encoding='utf-8')
                fixed_count += 1
                print(f"  ✅ 已修复: {file_path.name}")
            
        except Exception as e:
            error_count += 1
            print(f"  ❌ 错误 {file_path.name}: {e}")
    
    print()
    print(f"修复完成: {fixed_count}个文件已修复, {error_count}个文件出错")
    print("=" * 70)
    return fixed_count, error_count

def clean_old_data():
    """清理过期数据（保留最近2年）"""
    print()
    print("【清理过期数据】")
    print()
    
    cutoff_date = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
    cleaned_count = 0
    
    for file_path in HISTORY_DIR.glob("*.json"):
        try:
            data = json.loads(file_path.read_text())
            
            if not isinstance(data, list):
                continue
            
            # 过滤掉过期数据
            filtered_data = [r for r in data if r.get('date', '') >= cutoff_date]
            
            if len(filtered_data) < len(data):
                file_path.write_text(json.dumps(filtered_data, ensure_ascii=False, indent=2), encoding='utf-8')
                cleaned_count += 1
                print(f"  🗑️  已清理: {file_path.name} ({len(data)}→{len(filtered_data)}条)")
            
        except Exception as e:
            print(f"  ❌ 清理失败 {file_path.name}: {e}")
    
    print()
    print(f"清理完成: {cleaned_count}个文件")
    print("=" * 70)
    return cleaned_count

def verify_fix():
    """验证修复结果"""
    print()
    print("【验证修复结果】")
    print()
    
    issues = []
    
    # 检查关键股票
    key_stocks = ["sh600519", "sh600000", "sz000858", "sh601318"]
    
    for code in key_stocks:
        file_path = HISTORY_DIR / f"{code}.json"
        if not file_path.exists():
            issues.append(f"{code}: 文件缺失")
            continue
        
        try:
            data = json.loads(file_path.read_text())
            
            # 检查排序
            dates = [r.get('date', '') for r in data]
            is_sorted = all(dates[i] >= dates[i+1] for i in range(len(dates)-1))
            
            if not is_sorted:
                issues.append(f"{code}: 排序错误")
            
            # 检查最新数据
            latest_date = dates[0] if dates else ''
            if latest_date:
                date_obj = datetime.strptime(latest_date, '%Y-%m-%d')
                days_lag = (datetime.now() - date_obj).days
                if days_lag > 7:
                    issues.append(f"{code}: 数据滞后{days_lag}天")
                else:
                    print(f"  ✅ {code}: 最新{latest_date} (滞后{days_lag}天)")
            
            # 检查价格有效性
            if data and data[0].get('close', 0) <= 0:
                issues.append(f"{code}: 收盘价为0")
                
        except Exception as e:
            issues.append(f"{code}: 解析错误 - {e}")
    
    print()
    if issues:
        print(f"❌ 发现 {len(issues)} 个问题:")
        for issue in issues:
            print(f"  - {issue}")
        return False
    else:
        print("✅ 所有关键股票数据验证通过")
        return True

if __name__ == "__main__":
    # 执行修复
    fixed, errors = fix_data_sorting()
    cleaned = clean_old_data()
    
    # 验证结果
    if verify_fix():
        print()
        print("🎉 数据修复成功!")
    else:
        print()
        print("⚠️  数据修复后仍有问题，请检查")
