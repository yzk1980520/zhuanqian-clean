#!/usr/bin/env python3
"""
选股系统诊断脚本（2026-09-22）
诊断候选池过小、评分分布、因子有效性
"""
import os
import sys
import json
from datetime import date
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def run_diagnosis():
    """运行完整诊断"""
    print("=" * 70)
    print("选股系统诊断报告")
    print("=" * 70)
    print()
    
    # 1. 策略配置诊断
    print("【1. 策略配置诊断】")
    from tdx_strategies import STRATEGIES
    
    zonghe = STRATEGIES['综合']
    alpha101 = STRATEGIES.get('Alpha101协方差', {})
    
    # 统计非零权重
    zonghe_nonzero = {k: v for k, v in zonghe.items() if isinstance(v, (int, float)) and v != 0}
    alpha101_nonzero = {k: v for k, v in alpha101.items() if isinstance(v, (int, float)) and v != 0}
    
    print(f"综合策略非零权重: {len(zonghe_nonzero)}个")
    print(f"Alpha101协方差非零权重: {len(alpha101_nonzero)}个")
    print()
    
    # TOP5权重
    top_zonghe = sorted(zonghe_nonzero.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
    print("综合策略TOP5权重:")
    for k, v in top_zonghe:
        print(f"  {k}: {v}")
    print()
    
    top_alpha = sorted(alpha101_nonzero.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
    print("Alpha101协方差TOP5权重:")
    for k, v in top_alpha:
        print(f"  {k}: {v}")
    
    # 2. 检查关键因子
    print()
    print("【2. 关键因子权重检查】")
    critical_factors = [
        ('chg5_rev', 15, '反转因子IC=-0.33最强'),
        ('chg10_rev', 12, '反转因子IC=-0.33'),
        ('pos_vs_ma20', -15, '均线偏离回归'),
        ('unlocked_pressure', -12, '解套盘压力'),
        ('vol_ratio', 10, '量能因子'),
        ('max_ret5_low', 25, '彩票型回避'),
        ('ma_mlt', 20, '均线多头'),
        ('macd_golden_red', 15, 'MACD金叉'),
    ]
    
    all_ok = True
    for factor, expected, reason in critical_factors:
        actual = zonghe.get(factor, 'NOT_FOUND')
        status = '✅' if actual == expected else '❌'
        if actual != expected:
            all_ok = False
        print(f"  {status} {factor:20s}: 期望={expected:4d} 实际={actual}")
    
    if all_ok:
        print("  ✅ 所有关键因子权重正确")
    else:
        print("  ❌ 存在权重不匹配，需修复")
    
    # 3. 运行Dry-Run诊断
    print()
    print("【3. Dry-Run诊断】")
    
    from core.pipeline.integrated_picker import run_integrated_picker
    
    # 运行选股（dry_run=True）
    result, config, diag = run_integrated_picker(top_n=10, dry_run=True, debug=True)
    
    print()
    print(f"扫描股票数: {diag.get('scanned', 'N/A')}")
    print(f"可评分股票数: {diag.get('scoreable', 'N/A')}")
    print(f"候选池大小: {len(result)}")
    print()
    
    # 分析候选池
    if result:
        print("候选池TOP10:")
        for i, item in enumerate(result[:10]):
            code = item.get('code', 'N/A')
            name = item.get('name', 'N/A')
            score = item.get('final_score', 0)
            print(f"  TOP{i+1}: {code} {name} 评分={score}")
        
        # 分数分布
        scores = [item.get('final_score', 0) for item in result]
        print()
        print(f"分数统计:")
        print(f"  平均分: {sum(scores)/len(scores):.1f}")
        print(f"  最高分: {max(scores):.1f}")
        print(f"  最低分: {min(scores):.1f}")
        print(f"  标准差: {(sum((s-sum(scores)/len(scores))**2 for s in scores)/len(scores))**0.5:.1f}")
    else:
        print("  ❌ 候选池为空")
    
    # 4. 冷却期检查
    print()
    print("【4. 冷却期检查】")
    from holdings_checker import check_cooldown_status
    status, msg = check_cooldown_status()
    print(f"  {msg}")
    
    # 5. 诊断总结
    print()
    print("=" * 70)
    print("【诊断总结】")
    print("=" * 70)
    
    issues = []
    
    # 检查候选池大小
    if result and len(result) < 20:
        issues.append(f"候选池过小: {len(result)}只 < 20只目标")
    
    # 检查配置一致性
    if not all_ok:
        issues.append("策略配置存在不一致")
    
    if issues:
        print("❌ 发现问题:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("✅ 未发现明显问题")
    
    print()
    print("建议操作:")
    if len(result) < 20:
        print("  1. 等待冷却期满（已持4天，需5天）")
        print("  2. 或降低评分门槛（MIN_SCORE 22→18）")
        print("  3. 检查Layer 1扫描逻辑是否有过度过滤")
    
    return result, config, diag


if __name__ == "__main__":
    run_diagnosis()
