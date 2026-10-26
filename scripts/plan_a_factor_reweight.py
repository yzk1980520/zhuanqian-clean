#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
策略空间重标定：因子权重优化方案A
目标：突破门禁壁垒（WR≥40% ∧ DD≤35%）
"""
import json
import copy
from datetime import datetime

CONFIG_PATH = r'D:\open code\zhuanqian\config.json'
FACTOR_WEIGHTS_PATH = r'D:\open code\zhuanqian\factor_weights.json'
BACKUP_PATH = r'D:\open code\zhuanqian\config.json.bak_20261005'

# 加载当前配置
with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
    config = json.load(f)

# 备份
with open(BACKUP_PATH, 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)
print(f"✅ 已备份至 {BACKUP_PATH}")

# IC数据（来自factor_ic_latest.json）
IC_DATA = {
    'UPPER_SHADOW': 0.1697,
    'AMIHUD': 0.1426,
    'CONSECUTIVE_LOSS': 0.1009,
    'LOWER_SHADOW': 0.1056,
    'PRICE_VOL_RANK': -0.2782,  # 负向有效
    'OBV_SLOPE': -0.1089,
    'VOL_RATIO': -0.0853,
    'momentum_20': -0.0767,
    'RSI14': 0.0764,
    'VMR5': -0.0785,
    'VOL_SHRINK20': -0.0533,
    'VCHG': 0.0543,
    'OBV_TREND': 0.0400,
    'ATR_RATIO': -0.0420,
    'CORRELATION_5_20': -0.0412,
    'VR5_20': -0.0337,
    'VOL_FLOOR': -0.0363,
    'vol_ratio': 0.0502,
}

# 当前权重（从高到低）
CURRENT_WEIGHTS = {
    'chg5_rev': 30.0,
    'max_ret5_low': 25.0,
    'ma_mlt': 20.0,
    'macd_golden_red': 15.0,
    'volatility20': 15.0,
    'pos_vs_ma20': -15.0,
    'industry_hot_top5': 15.0,
    'vol_dump': -12.0,
    'chg10_rev': 12.0,
    'unlocked_pressure': -12.0,
    'industry_cold_bottom5': -12.0,
    'penalty_far': -12.0,
    'macd_golden': 10.0,
    'vol_gt2': 10.0,
    'chg20_rev': 10.0,
    'vol_price_corr_20': -10.0,
    'vol_ratio': 10.0,
}

# 方案A：因子权重优化
# 思路：启用高IC因子，降低低IC因子权重
PLAN_A_WEIGHTS = {
    # 高IC有效因子（启用+提升权重）
    'UPPER_SHADOW': 25.0,      # IC=0.17
    'AMIHUD': 20.0,            # IC=0.14
    'CONSECUTIVE_LOSS': 15.0,  # IC=0.10
    'LOWER_SHADOW': 15.0,      # IC=0.11
    
    # 有效因子（保持/适度启用）
    'PRICE_VOL_RANK': -15.0,   # IC=-0.28（负向有效）
    'OBV_SLOPE': -12.0,        # IC=-0.11
    'VOL_RATIO': -10.0,        # IC=-0.09
    'momentum_20': -10.0,      # IC=-0.08
    'RSI14': 10.0,             # IC=0.08
    'VMR5': -8.0,              # IC=-0.08
    
    # 中效因子（部分保留）
    'VCHG': 8.0,               # IC=0.05
    'OBV_TREND': 6.0,          # IC=0.04
    'atr_ratio': -5.0,         # IC=-0.04
    'VOL_SHRINK20': -5.0,      # IC=-0.05
    
    # 低IC失效因子（大幅降低/归零）
    'chg5_rev': 0.0,           # 原30→0（IC失效）
    'max_ret5_low': 0.0,       # 原25→0（IC失效）
    'chg10_rev': 0.0,          # 原12→0（IC失效）
    'chg20_rev': 0.0,          # 原10→0（IC失效）
    
    # 保留的技术因子
    'ma_mlt': 10.0,
    'macd_golden_red': 8.0,
    'volatility20': 8.0,
    'pos_vs_ma20': -8.0,
    'industry_hot_top5': 10.0,
    'industry_cold_bottom5': -8.0,
    
    # 其他保留因子
    'vol_dump': -6.0,
    'unlocked_pressure': -6.0,
    'penalty_far': -6.0,
    'macd_golden': 6.0,
    'vol_gt2': 6.0,
    'vol_ratio': 5.0,
}

# 应用方案A：只写factor_weights.json（不碰config.json）
# 读取现有版本
with open(FACTOR_WEIGHTS_PATH, 'r', encoding='utf-8') as f:
    fw = json.load(f)

# 合并权重（保留现有结构，更新weights字段）
current_version = fw.get('version', '0')
# 解析版本（支持 x.y 或 x.y.z）
parts = current_version.split('.')
try:
    major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    new_version = f'{major}.{minor + 1}'
except (ValueError, IndexError):
    new_version = '2.6'

fw['weights'] = PLAN_A_WEIGHTS
fw['version'] = new_version
fw['updated_at'] = datetime.now().isoformat()
fw['note'] = '方案A因子权重优化应用'

# 原子写入
import core.pipeline.atomic_json as atomic_json  # 2026-10-24 [t_laosan_r5_bare_import]: 原裸 import 只绑定 core, 下方 atomic_json.* 会 NameError, 补 as 别名
atomic_json.atomic_dump(fw, FACTOR_WEIGHTS_PATH, ensure_ascii=False, encoding='utf-8')

# 注意：config.json的factor_weights段保持不变
print(f"✅ 方案A因子权重已写入 {FACTOR_WEIGHTS_PATH} (v{new_version})")
print(f"⚠️  config.json未修改（保持原状）")
print(f"\n=== 权重对比（前10） ===")
print(f"{'因子':<25} {'原权重':>10} {'新权重':>10} {'IC':>10}")
print("-" * 60)
for name in sorted(PLAN_A_WEIGHTS.keys(), key=lambda x: -abs(PLAN_A_WEIGHTS[x]))[:10]:
    old = CURRENT_WEIGHTS.get(name, 0)
    new = PLAN_A_WEIGHTS[name]
    ic = IC_DATA.get(name, 0)
    print(f"{name:<25} {old:>10.1f} {new:>10.1f} {ic:>10.4f}")

print(f"\n总因子数: {len(PLAN_A_WEIGHTS)}")
print(f"非零权重因子: {sum(1 for w in PLAN_A_WEIGHTS.values() if w != 0)}")
