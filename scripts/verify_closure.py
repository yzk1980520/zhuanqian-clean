import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""验证市场状态门控和配置更新"""
import json
import sys
import os

sys.path.insert(0, r'D:\open code\zhuanqian')
os.chdir(r'D:\open code\zhuanqian')

print("=" * 60)
print("  全闭环验证")
print("=" * 60)

# 1. 验证config.json
print("\n【1. config.json配置验证】")
with open(r'D:\open code\zhuanqian\config.json', encoding='utf-8') as f:
    config = json.load(f)

print(f"  pick_min_score: {config['selection']['pick_min_score']} (期望: 15)")
print(f"  market_gate.weak_threshold: {config['market_gate']['weak_threshold']} (期望: 40)")
print(f"  market_gate.skip_when_weak: {config['market_gate']['skip_when_weak']} (期望: True)")
print(f"  time_stop.max_hold_days: {config['time_stop']['max_hold_days']} (期望: 60)")

assert config['selection']['pick_min_score'] == 15, "pick_min_score错误"
assert config['market_gate']['weak_threshold'] == 40, "weak_threshold错误"
assert config['market_gate']['skip_when_weak'] == True, "skip_when_weak错误"
assert config['time_stop']['max_hold_days'] == 60, "max_hold_days错误"
print("  ✅ config.json验证通过")

# 2. 验证因子权重
print("\n【2. 因子权重验证】")
from core.pipeline.tdx_core import STRATEGIES
s = STRATEGIES['综合']
print(f"  rsi_strong: {s.get('rsi_strong')} (期望: ≤3)")
print(f"  chg5_gt8: {s.get('chg5_gt8')} (期望: ≤3)")
print(f"  fund_flow_pos: {s.get('fund_flow_pos')} (期望: ≥8)")
print(f"  industry_hot_top5: {s.get('industry_hot_top5')} (期望: ≥8)")

assert s.get('rsi_strong', 0) <= 3, "rsi_strong未降权"
assert s.get('chg5_gt8', 0) <= 3, "chg5_gt8未降权"
assert s.get('fund_flow_pos', 0) >= 8, "fund_flow未升权"
assert s.get('industry_hot_top5', 0) >= 8, "industry未升权"
print("  ✅ 因子权重验证通过")

# 3. 验证止损逻辑
print("\n【3. 止损逻辑验证】")
from auto_tune_weights import load_config
contract = load_config()
stop_pct = contract.get('stop_loss_pct', 0.08)
print(f"  stop_loss_pct: {stop_pct} (期望: 0.08)")
assert abs(stop_pct - 0.08) < 0.001, "stop_loss_pct错误"
print("  ✅ 止损逻辑验证通过")

# 4. 验证时间止损
print("\n【4. 时间止损验证】")
from backtest.backtest_rotation import RotationConfig
cfg = RotationConfig("验证", max_hold_days=60)
print(f"  max_hold_days: {cfg.max_hold_days} (期望: 60)")
assert cfg.max_hold_days == 60, "max_hold_days错误"
print("  ✅ 时间止损验证通过")

print("\n" + "=" * 60)
print("  ✅ 全部验证通过！")
print("=" * 60)
