"""
多Agent向量协同引擎
时间：2026-10-06
编制：老五（数据回测专家）

核心功能：
1. Agent注册与权重管理
2. 输出向量化融合
3. 动态权重调整（基于历史表现）
4. 冲突仲裁机制
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any


class MultiAgentVectorCollaboration:
    """多Agent向量协同引擎"""
    
    def __init__(self):
        """初始化Agent协同引擎"""
        self.agents = {}  # Agent历史记录
        self.weights = {}  # 动态权重
    
    def register_agent(self, agent_id: str, initial_weight: float = 1.0, role: str = ""):
        """
        注册Agent
        
        Args:
            agent_id: Agent唯一标识
            initial_weight: 初始权重
            role: Agent角色描述
        """
        self.agents[agent_id] = {
            'role': role,
            'history': [],  # 历史输出记录
            'accuracy': 0.0,  # 历史准确率
            'weight': initial_weight,
            'registered_at': datetime.now().isoformat()
        }
        self.weights[agent_id] = initial_weight
    
    def update_agent_performance(self, agent_id: str, is_correct: bool, confidence: float = 1.0):
        """
        更新Agent表现（基于实际结果验证）
        
        Args:
            agent_id: Agent标识
            is_correct: 本次输出是否正确
            confidence: 输出置信度
        """
        if agent_id not in self.agents:
            raise ValueError(f"Agent {agent_id} 未注册")
        
        # 记录历史（带置信度加权）
        self.agents[agent_id]['history'].append({
            'correct': is_correct,
            'confidence': confidence,
            'timestamp': datetime.now().isoformat()
        })
        
        # 计算近期准确率（最近10次，带置信度加权）
        recent = self.agents[agent_id]['history'][-10:]
        if recent:
            weighted_correct = sum(
                1 for h in recent if h['correct']
            )
            weighted_total = sum(h['confidence'] for h in recent)
            self.agents[agent_id]['accuracy'] = (
                weighted_correct / weighted_total 
                if weighted_total > 0 else 0.0
            )
        
        # 更新权重（准确率越高，权重越高）
        self.weights[agent_id] = self.agents[agent_id]['accuracy']
    
    def fuse_outputs(self, agent_outputs: Dict[str, List[float]]) -> List[float]:
        """
        融合多Agent输出（向量加权平均）
        
        Args:
            agent_outputs: {agent_id: output_vector}
                          output_vector = [gate_status, confidence, risk_level, ...]
        
        Returns:
            融合后的输出向量
        """
        if not agent_outputs:
            return []
        
        # 获取向量维度
        first_vector = list(agent_outputs.values())[0]
        dim = len(first_vector)
        
        fused = np.zeros(dim)
        total_weight = 0
        
        for agent_id, output in agent_outputs.items():
            weight = self.weights.get(agent_id, 0.1)
            output_array = np.array(output)
            fused += weight * output_array
            total_weight += weight
        
        return (fused / total_weight).tolist() if total_weight > 0 else fused.tolist()
    
    def resolve_conflict(self, agent_outputs: Dict[str, List[float]]) -> Tuple[str, List[float]]:
        """
        冲突仲裁（基于向量距离）
        
        Args:
            agent_outputs: {agent_id: output_vector}
        
        Returns:
            (winning_agent_id, winning_output)
        """
        if len(agent_outputs) == 1:
            agent_id = list(agent_outputs.keys())[0]
            return agent_id, agent_outputs[agent_id]
        
        outputs = list(agent_outputs.values())
        agent_ids = list(agent_outputs.keys())
        
        # 计算各输出向量的距离
        distances = []
        for i, out_i in enumerate(outputs):
            dist = sum([
                np.linalg.norm(np.array(out_i) - np.array(out_j))
                for j, out_j in enumerate(outputs) if i != j
            ])
            distances.append((i, dist))
        
        # 选距离最小（最中心）的输出
        center_idx = min(distances, key=lambda x: x[1])[0]
        center_agent = agent_ids[center_idx]
        
        return center_agent, agent_outputs[center_agent]
    
    def calculate_consensus(self, agent_outputs: Dict[str, List[float]]) -> Dict:
        """
        计算Agent共识度
        
        Returns:
            {
              'consensus_score': float,  # 共识度（0-1）
              'divergence': float,  # 分歧度
              'winner': str,  # 获胜Agent
              'fused_output': List[float]  # 融合输出
            }
        """
        if not agent_outputs:
            return {'consensus_score': 0, 'divergence': 0, 'winner': None, 'fused_output': []}
        
        outputs = list(agent_outputs.values())
        
        # 计算共识度（基于向量相似度）
        if len(outputs) < 2:
            return {
                'consensus_score': 1.0,
                'divergence': 0.0,
                'winner': list(agent_outputs.keys())[0],
                'fused_output': outputs[0]
            }
        
        # 计算两两相似度
        similarities = []
        for i in range(len(outputs)):
            for j in range(i+1, len(outputs)):
                sim = np.dot(np.array(outputs[i]), np.array(outputs[j])) / (
                    np.linalg.norm(np.array(outputs[i])) * np.linalg.norm(np.array(outputs[j]))
                )
                similarities.append(sim)
        
        consensus_score = np.mean(similarities)
        divergence = 1 - consensus_score
        
        # 仲裁
        winner_id, winner_output = self.resolve_conflict(agent_outputs)
        
        # 融合
        fused_output = self.fuse_outputs(agent_outputs)
        
        return {
            'consensus_score': round(float(consensus_score), 4),
            'divergence': round(float(divergence), 4),
            'winner': winner_id,
            'fused_output': [round(x, 4) for x in fused_output]
        }
    
    def generate_report(self) -> Dict:
        """生成Agent协同报告"""
        agent_summary = []
        for agent_id, agent_data in self.agents.items():
            agent_summary.append({
                'agent_id': agent_id,
                'role': agent_data['role'],
                'accuracy': round(agent_data['accuracy'], 4),
                'weight': round(agent_data['weight'], 4),
                'history_count': len(agent_data['history'])
            })
        
        return {
            'timestamp': datetime.now().isoformat(),
            'agent_count': len(self.agents),
            'agents': agent_summary,
            'weights': {k: round(v, 4) for k, v in self.weights.items()}
        }


def main():
    """主函数：演示Agent协同"""
    print('='*70)
    print('  多Agent向量协同引擎 v1.0')
    print('='*70)
    print()
    
    # 创建协同引擎
    engine = MultiAgentVectorCollaboration()
    
    # 注册Agent（模拟团队角色）
    agents = [
        ('laowu', '老五', '数据评审专家'),
        ('laosan', '老三', '技术实现专家'),
        ('zongguan', '总管', '调度统筹专家'),
        ('niuma', '牛马', '市场观察专家'),
        ('atomcode', 'atomcode', '安全审查专家'),
        ('opencode', 'opencode', '系统测试专家')
    ]
    
    print("注册Agent:")
    for agent_id, cn_name, role in agents:
        engine.register_agent(agent_id, role=cn_name + '(' + role + ')')
        print(f"  ✅ {cn_name} ({agent_id}) - {role}")
    print()
    
    # 模拟历史表现
    print("模拟历史表现:")
    simulation_data = {
        'laowu': [(True, 0.9), (True, 0.85), (False, 0.8), (True, 0.95)],
        'laosan': [(True, 0.95), (True, 0.9), (True, 0.85), (True, 0.9)],
        'zongguan': [(True, 0.85), (False, 0.7), (True, 0.8), (True, 0.9)],
        'niuma': [(True, 0.8), (True, 0.75), (True, 0.85), (False, 0.7)],
        'atomcode': [(True, 0.9), (True, 0.95), (True, 0.85), (True, 0.9)],
        'opencode': [(True, 0.85), (True, 0.8), (False, 0.75), (True, 0.8)]
    }
    
    for agent_id, history in simulation_data.items():
        for is_correct, confidence in history:
            engine.update_agent_performance(agent_id, is_correct, confidence)
        print(f"  {agent_id}: 准确率={engine.agents[agent_id]['accuracy']:.2%}, 权重={engine.weights[agent_id]:.4f}")
    print()
    
    # 模拟Agent输出
    print("模拟Agent输出向量:")
    agent_outputs = {
        'laowu': [1.0, 0.9, 0.8],  # [闸门状态, 置信度, 风险等级]
        'laosan': [1.0, 0.95, 0.7],
        'zongguan': [0.0, 0.8, 0.9],  # 与老五冲突
        'niuma': [1.0, 0.85, 0.75],
        'atomcode': [1.0, 0.9, 0.7],
        'opencode': [1.0, 0.85, 0.75]
    }
    
    for agent_id, output in agent_outputs.items():
        print(f"  {agent_id}: {output}")
    print()
    
    # 计算共识
    print("共识分析:")
    consensus = engine.calculate_consensus(agent_outputs)
    print(f"  共识度: {consensus['consensus_score']:.2%}")
    print(f"  分歧度: {consensus['divergence']:.2%}")
    print(f"  获胜Agent: {consensus['winner']}")
    print(f"  融合输出: {consensus['fused_output']}")
    print()
    
    # 生成报告
    report = engine.generate_report()
    print("Agent权重分布:")
    for agent_id, weight in report['weights'].items():
        print(f"  {agent_id}: {weight:.4f}")
    print()
    
    # 保存报告
    output_file = Path(r'D:\open code\zhuanqian\data\agent_collaboration_report.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"报告已保存: {output_file}")
    print()
    print('='*70)


if __name__ == '__main__':
    main()
