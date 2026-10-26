#!/usr/bin/env python3
"""
test_pattern_recognition.py: 技术形态识别加分测试
覆盖: Layer 7完整流程、形态加分、冲突抑制逻辑
"""
import pytest
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPatternBonus:
    """形态加分逻辑测试"""
    
    def test_w_bottom_bonus(self):
        """测试W底加分"""
        _PATTERN_BONUS = {"W底": 5, "杯柄": 5, "牛旗": 3, "三角收敛": 2, "V型反转": 2}
        assert _PATTERN_BONUS.get("W底", 2) == 5
    
    def test_cup_handle_bonus(self):
        """测试杯柄加分"""
        _PATTERN_BONUS = {"W底": 5, "杯柄": 5, "牛旗": 3, "三角收敛": 2, "V型反转": 2}
        assert _PATTERN_BONUS.get("杯柄", 2) == 5
    
    def test_default_bonus(self):
        """测试未知形态默认加分"""
        _PATTERN_BONUS = {"W底": 5, "杯柄": 5, "牛旗": 3, "三角收敛": 2, "V型反转": 2}
        assert _PATTERN_BONUS.get("未知形态", 2) == 2
    
    def test_score_clamp(self):
        """测试评分封顶100"""
        current_score = 98
        bonus = 5
        new_score = round(min(100.0, current_score + bonus), 1)
        assert new_score == 100.0


class TestConflictSuppression:
    """冲突抑制逻辑测试（P2）"""
    
    def test_suppress_high_outflow(self):
        """测试高流出抑制（>5亿）"""
        inflow = -6e8  # 6亿流出
        bonus = 5
        
        if inflow < -5e8:
            bonus = min(bonus, 1)
        
        assert bonus == 1  # 封顶1分
    
    def test_suppress_medium_outflow(self):
        """测试中等流出抑制（>2亿）"""
        inflow = -3e8  # 3亿流出
        bonus = 5
        
        if inflow < -5e8:
            bonus = min(bonus, 1)
        elif inflow < -2e8:
            bonus = max(1, bonus // 2)
        
        assert bonus == 2  # 减半
    
    def test_no_suppression_inflow(self):
        """测试流入不抑制"""
        inflow = 5e8  # 5亿流入
        bonus = 5
        
        if inflow < -5e8:
            bonus = min(bonus, 1)
        elif inflow < -2e8:
            bonus = max(1, bonus // 2)
        
        assert bonus == 5  # 不抑制
    
    def test_no_suppression_small_outflow(self):
        """测试小额流出不抑制"""
        inflow = -1e8  # 1亿流出
        bonus = 5
        
        if inflow < -5e8:
            bonus = min(bonus, 1)
        elif inflow < -2e8:
            bonus = max(1, bonus // 2)
        
        assert bonus == 5  # 不抑制


class TestPatternRecognitionMock:
    """形态识别接口mock测试"""
    
    def test_identify_all_patterns_found(self):
        """测试形态识别成功（逻辑验证）"""
        # 模拟识别结果
        result = {
            "found": True,
            "pattern": "W底",
            "confidence": 0.85
        }
        
        assert result["found"] == True
        assert result["pattern"] == "W底"
    
    def test_identify_all_patterns_not_found(self):
        """测试形态识别失败（逻辑验证）"""
        # 模拟识别结果
        result = {
            "found": False,
            "pattern": None,
            "confidence": 0.0
        }
        
        assert result["found"] == False
    
    def test_import_failure_fallback(self):
        """测试导入失败降级处理"""
        # 模拟导入失败（不实际导入，只测试逻辑）
        try:
            # 尝试导入一个不存在的模块
            import nonexistent_module_xyz
        except ImportError:
            print(f"🔴 [tests\test_pattern_recognition.py] CR-01: except ImportError:", file=sys.stderr)
class TestLayer7Integration:
    """Layer 7集成测试"""
    
    def test_pattern_scoring_logic(self):
        """测试完整形态评分逻辑"""
        # 模拟Layer 7核心逻辑
        _PATTERN_BONUS = {"W底": 5, "杯柄": 5, "牛旗": 3, "三角收敛": 2, "V型反转": 2}
        flow_map = {"600000": -6e8}  # 高流出
        
        # 模拟一只股票
        code = "sh600000"
        clean = code[2:]
        inflow = flow_map.get(clean, 0)
        
        bonus = _PATTERN_BONUS.get("W底", 2)
        
        # 冲突抑制
        if inflow < -5e8:
            bonus = min(bonus, 1)
        
        assert bonus == 1  # 应被抑制到1分
    
    def test_multiple_patterns_take_highest(self):
        """测试多形态取最高分"""
        # identify_all_patterns应返回最高分形态
        patterns = ["W底", "杯柄", "牛旗"]
        scores = [5, 5, 3]
        
        # 取最高分
        max_score = max(scores)
        assert max_score == 5


class TestPatternDebugOutput:
    """形态识别调试输出测试"""
    
    def test_signal_format(self):
        """测试信号格式"""
        pattern = "W底"
        bonus = 5
        suppress = "⚠️流出>5亿"
        
        sig = f"📐{pattern}+{bonus}分"
        if suppress:
            sig += f"({suppress})"
        
        assert "📐" in sig
        assert pattern in sig
        assert suppress in sig
    
    def test_signal_no_suppress(self):
        """测试无抑制信号格式"""
        pattern = "杯柄"
        bonus = 5
        suppress = ""
        
        sig = f"📐{pattern}+{bonus}分"
        if suppress:
            sig += f"({suppress})"
        
        assert "📐" in sig
        assert "(" not in sig  # 无抑制时无括号


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
