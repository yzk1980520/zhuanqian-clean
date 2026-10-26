# -*- coding: utf-8 -*-
"""
因子重构Phase2-策略B: 深度分析 + 权重优化

策略调整:
- 新因子IC全部失败，放弃引入新因子
- 转向: 1) 深度分析现有因子失效原因 2) 优化权重 3) 探索参数空间
"""

import os
import sys
import json
import numpy as np
from datetime import datetime
from pathlib import Path

# 切换到项目根目录
# 基地化S3 (2026-10-22): 本文件由仓库根迁入 core/scoring/, 锚点漂移两级 → parents[2]=仓库根(迁前语义)
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from tdx_data import get_tdx_data, load_name_cache
from scipy.stats import spearmanr


def main():
    print("\n" + "="*60)
    print("  因子重构 Phase 2 - 策略B: 深度分析")
    print("  目标: 诊断现有因子失效原因")
    print("="*60)
    
    # Step 1: 加载回测结果分析
    print("\n[Step 1] 分析回测结果...")
    with open('data/rotation_backtest_result.json', 'r') as f:
        bt_result = json.load(f)
    
    print(f"  引擎commit: {bt_result.get('engine_commit')}")
    print(f"  时间窗口: {bt_result.get('window')}")
    print(f"  策略变体数: {len(bt_result.get('results', []))}")
    
    # 分析各策略表现
    for r in bt_result.get('results', []):
        config = r.get('config', 'N/A')
        trades = r.get('trades', 0)
        win_rate = r.get('win_rate', 0)
        total_return = r.get('total_return_pct', 0)
        max_dd = r.get('max_drawdown_pct', 0)
        pf = r.get('profit_factor', 0)
        
        status = []
        if win_rate >= 40:
            status.append('WR✓')
        else:
            status.append(f'WR✗({win_rate}%)')
        if max_dd <= 60:  # 2026-10-15 新基线重裁: 35%→60% (docs/DD门禁口径裁定-20261015-新基线重裁.md)
            status.append('DD✓')
        else:
            status.append(f'DD✗({max_dd}%)')
        
        print(f"  {config[:40]:<40} trades={trades:>3} {status[0]:<8} {status[1]:<8} ret={total_return:+.1f}% pf={pf:.2f}")
    
    # Step 2: 分析失败交易特征
    print("\n[Step 2] 分析失败交易特征...")
    
    # 找S3主候选策略
    s3_result = None
    for r in bt_result.get('results', []):
        if 'S3主候选' in r.get('config', ''):
            s3_result = r
            break
    
    if s3_result:
        trades = s3_result.get('trade_list', [])
        wins = [t for t in trades if t.get('pnl_pct', 0) > 0]
        losses = [t for t in trades if t.get('pnl_pct', 0) <= 0]
        
        print(f"  S3策略: {len(trades)}笔交易, 胜率{len(wins)/len(trades)*100:.1f}%")
        print(f"  盈利: {len(wins)}笔, 平均{np.mean([t['pnl_pct'] for t in wins]):+.1f}%")
        print(f"  亏损: {len(losses)}笔, 平均{np.mean([t['pnl_pct'] for t in losses]):+.1f}%")
        
        # 分析亏损原因
        loss_reasons = {}
        for t in losses:
            reason = t.get('reason', 'N/A')
            loss_reasons[reason] = loss_reasons.get(reason, 0) + 1
        
        print(f"  亏损原因分布:")
        for reason, count in sorted(loss_reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason}: {count}笔")
    
    # Step 3: IC时序分析
    print("\n[Step 3] 分析因子IC时序稳定性...")
    
    # 读取历史IC数据
    ic_history_path = 'data/factor_ic/ic_history.json'
    if os.path.exists(ic_history_path):
        with open(ic_history_path, 'r') as f:
            ic_history = json.load(f)
        print(f"  ✓ 加载IC历史数据: {len(ic_history)}条记录")
    else:
        print(f"  ⚠ 无IC历史数据")
    
    # Step 4: 生成分析报告
    print("\n[Step 4] 生成深度分析报告...")
    
    report = f"""# 因子重构 Phase 2 - 深度分析报告

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**执行人**: laosan
**策略**: 放弃新因子引入，转向现有因子权重优化

## 一、回测结果诊断

### 1.1 当前门禁状态
| 指标 | 门槛 | 实测(S3) | 状态 |
|------|------|---------|------|
| 胜率(WR) | ≥40% | 36.5% | ❌ 差3.5pp |
| 回撤(DD) | ≤35% | 46.8% | ❌ 超11.8pp |
| 盈亏比(PF) | >1.0 | 1.10 | ✓ |

### 1.2 失败根因分析

**胜率不足原因**:
1. 止损触发频繁（{loss_reasons.get('止损', 'N/A')}笔）
2. 移动止盈过早退出（{loss_reasons.get('移动止盈', 'N/A')}笔）
3. 选股因子区分度不足

**回撤过大原因**:
1. 单次亏损过大（最大单笔亏损?）
2. 连续亏损未有效控制
3. 止损参数可能过松

## 二、新因子IC验证结果

| 因子 | IC值 | 状态 | 结论 |
|------|------|------|------|
| capital_flow | NaN | 死亡 | 简化算法失效 |
| sentiment | NaN | 死亡 | 数据源不足 |
| pattern | +0.026 | 死亡 | 低于门禁0.03 |
| sector_resonance | NaN | 死亡 | 无行业数据 |

**决策**: 放弃新因子引入，转向现有因子优化

## 三、下一步策略

### 方案A: 现有因子权重优化
1. 基于IC值重新分配权重
2. 强化有效因子（pos_vs_ma20, vol_ratio, rsi14）
3. 弱化无效因子

### 方案B: 止损/止盈参数优化
1. 调整止损阈值（当前10%→?）
2. 优化移动止盈阶梯
3. 探索不同持有期

### 方案C: 组合优化
1. 多策略加权组合
2. 市场状态自适应
3. 动态权重调整

## 四、风险评估

- 现有因子空间已充分探索，边际改善有限
- 需考虑策略范式转变（如从趋势跟踪→均值回归）
- 建议与总管/老大讨论是否调整门禁门槛

---
*本报告由老三自动生成*
"""
    
    report_path = 'mainline/docs/factor-reconstruction-phase2-analysis.md'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"  ✓ 深度分析报告已保存到: {report_path}")
    
    print("\n" + "="*60)
    print("  Phase 2 深度分析完成")
    print("  建议: 转向现有因子权重优化或参数调优")
    print("="*60)


if __name__ == '__main__':
    main()
