# -*- coding: utf-8 -*-
"""MarketStateAdapter - 市场状态适配器接口

深度模块设计：
- 解耦RiskEngine与MarketStateEngine实现
- 便于测试时注入MockMarketState
- 符合依赖倒置原则
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class MarketStateAdapter(Protocol):
    """市场状态适配器接口（Seam: RiskEngine与市场状态的边界）
    
    调用方只需知道MarketStateAdapter接口，无需了解具体实现。
    测试时可注入MockMarketState，无需启动真实MarketStateEngine。
    """
    
    def get_regime(self) -> str:
        """获取市场状态
        
        Returns:
            市场状态字符串，如"强"/"偏暖"/"震荡"/"偏弱"/"恐慌"/"极强"
        """
        ...
    
    def get_confidence(self) -> float:
        """获取市场状态置信度
        
        Returns:
            置信度（0.0-1.0）
        """
        ...
    
    def get_strategy_weights(self) -> dict:
        """获取策略权重配置（可选接口）
        
        Returns:
            策略权重字典，如{"momentum": 0.3, "quality": 0.2, ...}
        """
        ...


class MarketStateAdapterImpl:
    """MarketStateAdapter默认实现（适配现有MarketStateEngine）"""
    
    def __init__(self, market_state_engine):
        """
        Args:
            market_state_engine: 现有的MarketStateEngine实例
        """
        self._engine = market_state_engine
    
    def get_regime(self) -> str:
        """适配MarketStateEngine的regime字段"""
        return self._engine.regime
    
    def get_confidence(self) -> float:
        """适配MarketStateEngine的confidence字段"""
        return self._engine.confidence
    
    def get_strategy_weights(self) -> dict:
        """适配MarketStateEngine的strategy_weights字段"""
        return getattr(self._engine, 'strategy_weights', {})


class MockMarketState:
    """MockMarketState（用于单元测试）
    
    示例用法:
        mock = MockMarketState(regime="强", confidence=0.85)
        engine = RiskEngine(config=RiskConfig(), market_state=mock)
    """
    
    def __init__(self, regime: str = "强", confidence: float = 0.85, strategy_weights: dict = None):
        self._regime = regime
        self._confidence = confidence
        self._strategy_weights = strategy_weights or {
            "momentum": 0.3,
            "quality": 0.2,
            "value": 0.2,
            "growth": 0.3,
        }
    
    def get_regime(self) -> str:
        return self._regime
    
    def get_confidence(self) -> float:
        return self._confidence
    
    def get_strategy_weights(self) -> dict:
        return self._strategy_weights.copy()
    
    def with_regime(self, regime: str) -> 'MockMarketState':
        """链式调用：设置市场状态"""
        self._regime = regime
        return self
    
    def with_confidence(self, confidence: float) -> 'MockMarketState':
        """链式调用：设置置信度"""
        self._confidence = confidence
        return self
