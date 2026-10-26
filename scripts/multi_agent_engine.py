"""
多Agent向量协同引擎 - 跃迁③实现
功能：
1. 定义5个独立策略Agent（动量/价值/质量/反转/波动率）
2. 实现共识引擎（投票+加权融合）
3. 向量协同决策（方向+置信度+支持度）
"""
import json
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

class SignalDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

@dataclass
class AgentSignal:
    """Agent信号数据类"""
    agent_name: str
    direction: SignalDirection
    magnitude: float  # 0-1，信号强度
    confidence: float  # 0-1，置信度
    reasoning: str  # 决策依据

class MomentumAgent:
    """动量策略Agent"""
    
    def __init__(self):
        self.name = "Momentum"
        self.weight = 0.25
    
    def predict(self, stock_data: Dict) -> AgentSignal:
        """基于动量因子预测"""
        chg5 = stock_data.get('chg5', 0)
        chg10 = stock_data.get('chg10', 0)
        momentum_20 = stock_data.get('momentum_20', 0)
        
        # 动量信号计算
        score = (chg5 * 0.4 + chg10 * 0.3 + momentum_20 * 0.3) / 100
        
        if score > 0.05:
            direction = SignalDirection.BULLISH
        elif score < -0.05:
            direction = SignalDirection.BEARISH
        else:
            direction = SignalDirection.NEUTRAL
        
        return AgentSignal(
            agent_name=self.name,
            direction=direction,
            magnitude=min(abs(score) * 10, 1.0),
            confidence=min(abs(score) * 5, 1.0),
            reasoning=f"5日涨跌{chg5:.2f}%, 动量{momentum_20:.2f}"
        )

class ValueAgent:
    """价值策略Agent"""
    
    def __init__(self):
        self.name = "Value"
        self.weight = 0.20
    
    def predict(self, stock_data: Dict) -> AgentSignal:
        """基于价值因子预测"""
        pb = stock_data.get('pb', 5)  # 市盈率
        ps = stock_data.get('ps', 2)  # 市销率
        dividend_yield = stock_data.get('dividend_yield', 0)
        
        # 价值评分（越低越好）
        value_score = (pb / 20 + ps / 3 + max(0, 1 - dividend_yield * 10)) / 3
        
        if value_score < 0.4:
            direction = SignalDirection.BULLISH
        elif value_score > 0.7:
            direction = SignalDirection.BEARISH
        else:
            direction = SignalDirection.NEUTRAL
        
        return AgentSignal(
            agent_name=self.name,
            direction=direction,
            magnitude=min(abs(value_score - 0.5) * 2, 1.0),
            confidence=min(value_score * 2, 1.0),
            reasoning=f"估值指标PB={pb:.2f}, PS={ps:.2f}"
        )

class QualityAgent:
    """质量策略Agent"""
    
    def __init__(self):
        self.name = "Quality"
        self.weight = 0.20
    
    def predict(self, stock_data: Dict) -> AgentSignal:
        """基于质量因子预测"""
        roe = stock_data.get('roe', 0.1)
        revenue_growth = stock_data.get('revenue_growth', 0.1)
        profit_growth = stock_data.get('profit_growth', 0.05)
        
        # 质量评分（越高越好）
        quality_score = (roe * 10 + revenue_growth * 5 + profit_growth * 5) / 3
        
        if quality_score > 0.6:
            direction = SignalDirection.BULLISH
        elif quality_score < 0.3:
            direction = SignalDirection.BEARISH
        else:
            direction = SignalDirection.NEUTRAL
        
        return AgentSignal(
            agent_name=self.name,
            direction=direction,
            magnitude=min(quality_score, 1.0),
            confidence=min(quality_score * 1.5, 1.0),
            reasoning=f"ROE={roe*100:.1f}%, 营收增长{revenue_growth*100:.1f}%"
        )

class ReversalAgent:
    """均值回归Agent"""
    
    def __init__(self):
        self.name = "Reversal"
        self.weight = 0.20
    
    def predict(self, stock_data: Dict) -> AgentSignal:
        """基于反转因子预测"""
        rsi14 = stock_data.get('rsi14', 50)
        chg5 = stock_data.get('chg5', 0)
        lower_shadow = stock_data.get('lower_shadow', 0)
        
        # 反转信号（超跌反弹）
        if rsi14 < 30 and chg5 < -0.1:
            direction = SignalDirection.BULLISH
        elif rsi14 > 70 and chg5 > 0.1:
            direction = SignalDirection.BEARISH
        else:
            direction = SignalDirection.NEUTRAL
        
        magnitude = min(abs(rsi14 - 50) / 50, 1.0)
        
        return AgentSignal(
            agent_name=self.name,
            direction=direction,
            magnitude=magnitude,
            confidence=min(abs(rsi14 - 50) / 30, 1.0),
            reasoning=f"RSI={rsi14:.1f}, 5日涨跌{chg5*100:.1f}%"
        )

class VolatilityAgent:
    """波动率策略Agent"""
    
    def __init__(self):
        self.name = "Volatility"
        self.weight = 0.15
    
    def predict(self, stock_data: Dict) -> AgentSignal:
        """基于波动率因子预测"""
        vol_ratio = stock_data.get('vol_ratio', 1.0)
        atr_ratio = stock_data.get('atr_ratio', 1.0)
        std20 = stock_data.get('std20', 0.03)
        
        # 波动率信号（低波动利好）
        volatility_score = (vol_ratio + atr_ratio) / 2
        
        if volatility_score < 0.7 and std20 < 0.04:
            direction = SignalDirection.BULLISH
        elif volatility_score > 1.3 or std20 > 0.06:
            direction = SignalDirection.BEARISH
        else:
            direction = SignalDirection.NEUTRAL
        
        return AgentSignal(
            agent_name=self.name,
            direction=direction,
            magnitude=min(volatility_score * 0.5, 1.0),
            confidence=min((1 - std20 * 10) * 0.5, 1.0),
            reasoning=f"量比={vol_ratio:.2f}, ATR比={atr_ratio:.2f}"
        )

class MultiAgentEngine:
    """多Agent向量协同引擎"""

    def __init__(self, consensus_threshold=0.6):
        self.agents = [
            MomentumAgent(),
            ValueAgent(),
            QualityAgent(),
            ReversalAgent(),
            VolatilityAgent()
        ]
        self.consensus_threshold = consensus_threshold
        self.vote_history = []
        # B12修复: 权重归一化
        self._normalize_weights()

    def _normalize_weights(self):
        """B12: 确保Agent权重和为1"""
        total_weight = sum(agent.weight for agent in self.agents)
        if abs(total_weight - 1.0) > 0.01:
            for agent in self.agents:
                agent.weight = agent.weight / total_weight
            print(f"  ✅ Agent权重已归一化: {sum(a.weight for a in self.agents):.4f}")
        else:
            print(f"  ✅ Agent权重已归一化: {sum(a.weight for a in self.agents):.4f}")
    
    def filter_valid_signals(self, signals):
        """过滤有效Agent信号（置信度>0.1）"""
        valid = [s for s in signals if s.confidence >= 0.1]
        
        if len(valid) < 3:
            return None, f"有效Agent不足: {len(valid)}/5"
        
        return valid, f"有效Agent: {len(valid)}/5"
    
    def get_consensus_signal(self, stock_data: Dict) -> Dict:
        """获取共识信号"""
        # 收集所有Agent信号
        signals = {}
        for agent in self.agents:
            signal = agent.predict(stock_data)
            signals[agent.name] = signal
        
        # 过滤有效信号（置信度>0.1）
        valid_signals, filter_msg = self.filter_valid_signals(list(signals.values()))
        if valid_signals is None:
            return {
                'action': 'HOLD',
                'conviction': 'LOW',
                'support': 0,
                'total_agents': len(signals),
                'valid_agents': len(valid_signals) if valid_signals else 0,
                'weighted_score': 0,
                'signals': {name: s.direction.value for name, s in signals.items()},
                'reasoning': f"⚠️ {filter_msg}",
                'warning': filter_msg
            }
        
        # 投票统计
        bullish = sum(1 for s in signals.values() if s.direction == SignalDirection.BULLISH)
        bearish = sum(1 for s in signals.values() if s.direction == SignalDirection.BEARISH)
        neutral = sum(1 for s in signals.values() if s.direction == SignalDirection.NEUTRAL)
        total = len(signals)

        # B10: 分歧度统计
        divergence_score = self.calculate_divergence(bullish, bearish, neutral, total)

        # 加权得分
        weighted_score = sum(
            s.magnitude * s.confidence * agent.weight
            for agent, s in zip(self.agents, signals.values())
            if s.direction == SignalDirection.BULLISH
        ) - sum(
            s.magnitude * s.confidence * agent.weight
            for agent, s in zip(self.agents, signals.values())
            if s.direction == SignalDirection.BEARISH
        )
        
        # 共识判断
        if bullish / total >= self.consensus_threshold:
            action = 'BUY'
            conviction = 'HIGH' if bullish >= 4 else 'MEDIUM'
            support = bullish
        elif bearish / total >= self.consensus_threshold:
            action = 'SELL'
            conviction = 'HIGH' if bearish >= 4 else 'MEDIUM'
            support = bearish
        elif divergence_score > 0.5:
            # B10: 高分歧度，输出统计
            action = 'HOLD'
            conviction = 'LOW'
            support = max(bullish, bearish)
        else:
            action = 'HOLD'
            conviction = 'MEDIUM'
            support = max(bullish, bearish)

        # 记录历史
        self.vote_history.append({
            'timestamp': datetime.now().isoformat(),
            'signals': {name: s.direction.value for name, s in signals.items()},
            'vote_count': {'bull': bullish, 'bear': bearish, 'neutral': neutral},
            'action': action
        })

        return {
            'action': action,
            'conviction': conviction,
            'support': support,
            'total_agents': total,
            'weighted_score': round(weighted_score, 4),
            'signals': {name: s.direction.value for name, s in signals.items()},
            'bullish': bullish,
            'bearish': bearish,
            'neutral': neutral,
            'divergence_score': round(divergence_score, 4),  # B10: 分歧度
            'reasoning': self._generate_reasoning(signals),
            'warning': '' if divergence_score <= 0.5 else f"⚠️ 高分歧度: {divergence_score:.2f}"
        }

    def calculate_divergence(self, bullish, bearish, neutral, total):
        """B10: 计算分歧度（0-1，1为完全分歧）"""
        if total < 3:
            return 0.0

        # 分歧度 = min(看涨数, 看跌数) / 总数
        # 完全一致: 0; 完全分歧: 0.5
        min_side = min(bullish, bearish)
        divergence = min_side / total if total > 0 else 0

        return round(divergence, 4)
    
    def _generate_reasoning(self, signals: Dict) -> str:
        """生成决策理由"""
        parts = []
        for name, signal in signals.items():
            if signal.direction != SignalDirection.NEUTRAL:
                parts.append(f"{name}: {signal.direction.value} ({signal.confidence:.0%})")
        
        return "; ".join(parts) if parts else "各Agent意见不一"
    
    def get_diversification_bonus(self, portfolio_signals: List[Dict]) -> float:
        """计算分散化增益"""
        if not portfolio_signals:
            return 0.0
        
        # 计算信号相关性
        directions = [1 if s['action'] == 'BUY' else (-1 if s['action'] == 'SELL' else 0) 
                      for s in portfolio_signals]
        
        if len(directions) < 2:
            return 0.0
        
        arr = np.array(directions)
        correlation = np.corrcoef(arr[0], arr[1:]).mean() if len(arr) > 2 else 0
        
        # 分散化增益（低相关性高增益）
        diversification_bonus = max(0, 1 - abs(correlation))
        
        return round(diversification_bonus, 4)


def main():
    """主函数"""
    print("=" * 80)
    print("🤖 多Agent向量协同引擎 - 跃迁③实现")
    print("=" * 80)
    
    # 初始化引擎
    engine = MultiAgentEngine(consensus_threshold=0.6)
    
    # 测试几只股票
    test_stocks = [
        {'code': 'sz301281', 'chg5': -45.79, 'chg10': -30.5, 'momentum_20': -20.3, 
         'pb': 25, 'ps': 3, 'dividend_yield': 0.02, 'roe': 0.15, 'revenue_growth': 0.2,
         'profit_growth': 0.18, 'rsi14': 25, 'lower_shadow': 0.05, 'vol_ratio': 0.8,
         'atr_ratio': 0.7, 'std20': 0.035},
        {'code': 'sz000858', 'chg5': -14.51, 'chg10': -8.2, 'momentum_20': -5.3,
         'pb': 18, 'ps': 2, 'dividend_yield': 0.03, 'roe': 0.2, 'revenue_growth': 0.15,
         'profit_growth': 0.12, 'rsi14': 35, 'lower_shadow': 0.03, 'vol_ratio': 1.2,
         'atr_ratio': 1.1, 'std20': 0.04},
    ]
    
    print("\n【多Agent协同选股测试】\n")
    
    for stock in test_stocks:
        result = engine.get_consensus_signal(stock)
        
        print(f"股票: {stock['code']}")
        print(f"  共识动作: {result['action']}")
        print(f"  置信度: {result['conviction']}")
        print(f"  支持数: {result['support']}/{result['total_agents']}")
        print(f"  加权得分: {result['weighted_score']:.4f}")
        print(f"  各Agent意见: {result['signals']}")
        print(f"  决策理由: {result['reasoning']}")
        print()
    
    # 计算分散化增益
    portfolio_signals = [
        engine.get_consensus_signal(test_stocks[0]),
        engine.get_consensus_signal(test_stocks[1])
    ]
    bonus = engine.get_diversification_bonus(portfolio_signals)
    print(f"分散化增益: {bonus:.4f}")
    
    print("\n✅ 多Agent协同引擎测试完成")
    print("\n关键特性:")
    print("  ✓ 5个独立Agent（动量/价值/质量/反转/波动率）")
    print("  ✓ 投票共识机制（60%阈值）")
    print("  ✓ 加权向量融合")
    print("  ✓ 分散化增益计算")


if __name__ == '__main__':
    main()
