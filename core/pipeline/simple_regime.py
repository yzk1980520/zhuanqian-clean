"""
简化版市场状态机 (2026-09-04 方案C)
替代原market_state_engine.py的复杂HMM逻辑
使用环境门状态作为regime代理
"""
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from pathlib import Path

# P1修复(20261023): 原 Path(__file__).parent 在S4迁移后指向core/pipeline/,
# data/daily_signal.json 实际在仓库根 → 复用L7已锚定的PROJECT_ROOT。
PROJECT = PROJECT_ROOT


def get_simple_regime():
    """
    简化市场状态判断
    返回: {regime, confidence, gate_status, score}
    
    regime: "bull" | "bear" | "震荡"
    confidence: 0-1 确信度
    gate_status: "open" | "close"
    score: 0-100 综合评分
    """
    # 读取门禁状态
    gate_path = os.path.join(PROJECT, "data", "daily_signal.json")
    gate_status = "close"
    gate_score = 50
    
    try:
        if os.path.exists(gate_path):
            with open(gate_path, 'r', encoding='utf-8') as f:
                ds = json.load(f)
            gate_open = ds.get("gate_open", False) or ds.get("gate") in ("开", "open")
            gate_status = "open" if gate_open else "close"
            gate_score = ds.get("rank_ic", 50) * 100  # 归一化
    except (FileNotFoundError, IOError, KeyError, PermissionError, json.JSONDecodeError) as e:
        pass
    
    # 用门禁状态作为regime代理
    # 门开 = 牛市/震荡偏多，门关 = 熊市/观望
    if gate_status == "open":
        if gate_score > 60:
            regime = "bull"
            confidence = 0.7
        else:
            regime = "震荡"
            confidence = 0.5
    else:
        regime = "bear"
        confidence = 0.8  # 门关时确信度高（避险模式）
    
    return {
        "regime": regime,
        "confidence": confidence,
        "gate_status": gate_status,
        "gate_score": gate_score,
        "updated": "2026-09-04",
        "method": "simple_gate_proxy"
    }


def get_strategy_weights(regime):
    """根据regime返回因子权重调整"""
    # 牛市：动量因子权重↑，质量因子权重↓
    # 熊市：质量因子权重↑，动量因子权重↓
    # 震荡：均衡
    weights = {
        "bull": {"momentum": 1.2, "quality": 0.8, "value": 1.0},
        "bear": {"momentum": 0.7, "quality": 1.3, "value": 1.2},
        "震荡": {"momentum": 1.0, "quality": 1.0, "value": 1.0}
    }
    return weights.get(regime, weights["震荡"])


def should_reduce_position(regime, current_position_ratio):
    """判断是否应该降仓"""
    if regime == "bear":
        return current_position_ratio > 0.3
    elif regime == "bull":
        return False
    else:  # 震荡
        return current_position_ratio > 0.7


if __name__ == "__main__":
    import pprint
    state = get_simple_regime()
    pprint.pprint(state)
    print("\nStrategy weights:", get_strategy_weights(state["regime"]))
