"""
评分逻辑重构 - P0阶段：冻结失效因子
"""

import json
import sys
from pathlib import Path

# 项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))


def freeze_invalid_factors():
    """
    冻结IC失效因子（IC<0.03或IR<0.3）
    根据2026-09-07 IC数据：
    - alpha13: IC=-0.0169, IR=-0.24 → 冻结
    - alpha16_fix: IC=-0.0147, IR=-0.26 → 冻结
    - chg5: IC=-0.010, IR=-0.10 → 冻结
    """
    
    # 读取策略配置
    from tdx_strategies import STRATEGIES
    
    # 失效因子列表（2026年IC失效）
    frozen_factors = ["alpha13", "alpha16_fix", "chg5"]
    
    print("=== P0阶段：冻结失效因子 ===")
    print(f"失效因子: {frozen_factors}")
    
    # 冻结所有策略中的失效因子
    for strategy_name, config in STRATEGIES.items():
        print(f"\n策略: {strategy_name}")
        for factor in frozen_factors:
            if factor in config:
                old_weight = config[factor]
                config[factor] = 0
                print(f"  {factor}: {old_weight} → 0 (冻结)")
    
    # 验证修改
    print("\n=== 验证修改后权重 ===")
    for strategy_name, config in STRATEGIES.items():
        if strategy_name == "综合":
            print(f"\n{strategy_name}策略:")
            for factor in ["chg10", "amount_q_reversal", "alpha13", "alpha16_fix", "chg5"]:
                if factor in config:
                    print(f"  {factor}: {config[factor]}")


if __name__ == "__main__":
    freeze_invalid_factors()
