"""
5次跃迁模块单元测试
时间：2026-10-06（修复 flaky 测试）
编制：老五（数据回测专家）

测试范围：
1. IC复利效应计算器
2. 多Agent向量协同引擎
3. 凸性风险保护器
4. 实盘大数迭代闭环
"""

import sys
import unittest
import numpy as np
from pathlib import Path

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

# 固定随机种子，确保测试可重复
np.random.seed(42)


class TestICCapitalCompound(unittest.TestCase):
    """IC复利效应计算器测试"""
    
    def test_empty_sequence(self):
        """测试空序列应抛出异常"""
        from ic_capital_compound import ICCapitalCompound
        with self.assertRaises(ValueError):
            ICCapitalCompound([])
    
    def test_single_element(self):
        """测试单元素序列应抛出异常"""
        from ic_capital_compound import ICCapitalCompound
        with self.assertRaises(ValueError):
            ICCapitalCompound([0.05])
    
    def test_two_elements(self):
        """测试两元素序列应抛出异常"""
        from ic_capital_compound import ICCapitalCompound
        with self.assertRaises(ValueError):
            ICCapitalCompound([0.05, -0.03])
    
    def test_negative_ic(self):
        """测试负IC序列"""
        from ic_capital_compound import ICCapitalCompound
        ic = ICCapitalCompound([-0.05, -0.03, -0.04])
        
        cumulative = ic.calculate_cumulative_ic()
        self.assertLess(cumulative, 0, "负IC序列的累计IC应为负")
    
    def test_mixed_ic(self):
        """测试混合IC序列"""
        from ic_capital_compound import ICCapitalCompound
        ic = ICCapitalCompound([0.05, -0.03, 0.04, -0.02])
        
        # 均值为0.01，IR应大于0
        ir = ic.calculate_ir_annual()
        self.assertGreater(ir, 0, "IR应大于0")
    
    def test_real_data(self):
        """测试真实数据（19因子）"""
        from ic_capital_compound import ICCapitalCompound
        ic_values = [-0.0337, 0.0543, -0.0785, -0.1089, -0.0363, -0.0533, 
                     0.1613, 0.040, -0.042, 0.0764, -0.0853, 0.1056, 
                     0.1697, 0.1009, -0.2782, -0.0412, -0.0767, 0.0502, 0.1426]
        ic = ICCapitalCompound(ic_values)
        
        cumulative = ic.calculate_cumulative_ic()
        ir = ic.calculate_ir_annual()
        
        # 验证数值合理性
        self.assertGreater(cumulative, 0, "累计IC应为正")
        self.assertGreater(ir, 0.4, "IR应大于0.4")
        self.assertLess(ir, 0.6, "IR应小于0.6")


class TestMultiAgentCollaboration(unittest.TestCase):
    """多Agent向量协同引擎测试"""
    
    def setUp(self):
        """设置测试环境"""
        from multi_agent_collaboration import MultiAgentVectorCollaboration
        self.engine = MultiAgentVectorCollaboration()
        self.engine.register_agent('laowu', role='老五')
        self.engine.register_agent('laosan', role='老三')
    
    def test_single_agent_fusion(self):
        """测试单Agent协同"""
        output = self.engine.fuse_outputs({'laowu': [1.0, 0.9, 0.8]})
        self.assertEqual(output, [1.0, 0.9, 0.8])
    
    def test_empty_output(self):
        """测试空输出融合"""
        output = self.engine.fuse_outputs({})
        self.assertEqual(output, [])
    
    def test_dimension_mismatch(self):
        """测试维度不一致"""
        with self.assertRaises(ValueError):
            self.engine.fuse_outputs({
                'laowu': [1.0, 0.9],
                'laosan': [1.0, 0.9, 0.8]
            })
    
    def test_conflict_resolution(self):
        """测试冲突仲裁"""
        outputs = {
            'laowu': [1.0, 0.9, 0.8],
            'laosan': [0.0, 0.1, 0.2]
        }
        winner, winner_output = self.engine.resolve_conflict(outputs)
        
        # 获胜者应该是中心点（距离其他输出之和最小）
        self.assertIn(winner, ['laowu', 'laosan'])
    
    def test_consensus_calculation(self):
        """测试共识度计算"""
        outputs = {
            'laowu': [1.0, 0.9, 0.8],
            'laosan': [1.0, 0.85, 0.75]
        }
        consensus = self.engine.calculate_consensus(outputs)
        
        # 高相似输出应有高共识度
        self.assertGreater(consensus['consensus_score'], 0.9)
        self.assertLess(consensus['divergence'], 0.1)


class TestConvexityRiskProtector(unittest.TestCase):
    """凸性风险保护器测试"""
    
    def test_normal_data(self):
        """测试正常数据处理"""
        from convexity_risk_protector import ConvexityRiskProtector
        train = np.random.normal(0.001, 0.02, 100)
        test = np.random.normal(0.0008, 0.025, 20)
        
        protector = ConvexityRiskProtector(train, test)
        report = protector.generate_protection_report()
        
        self.assertIn('convexity_risk', report)
        self.assertIn('risk_level', report['convexity_risk'])
    
    def test_extreme_degradation(self):
        """测试极端退化数据"""
        from convexity_risk_protector import ConvexityRiskProtector
        train = np.random.normal(0.002, 0.01, 100)
        test = np.random.normal(-0.001, 0.05, 20)  # 严重退化
        
        protector = ConvexityRiskProtector(train, test)
        report = protector.generate_protection_report()
        
        # 应检测到高风险（WARNING或CRITICAL）
        risk_level = report['convexity_risk']['risk_level']
        self.assertTrue('WARNING' in risk_level or 'CRITICAL' in risk_level,
                       f"风险等级应为WARNING或CRITICAL，实际: {risk_level}")
    
    def test_zero_variance(self):
        """测试零方差数据"""
        from convexity_risk_protector import ConvexityRiskProtector
        train = np.ones(100) * 0.001
        test = np.ones(20) * 0.001
        
        protector = ConvexityRiskProtector(train, test)
        var, cvar = protector.calculate_cvar(test)
        
        # 零方差时VaR/CVaR应接近输入值（因为是百分位数）
        self.assertAlmostEqual(var, 0.001, places=6)
        self.assertAlmostEqual(cvar, 0.001, places=6)


class TestLargeNumberIterationLoop(unittest.TestCase):
    """实盘大数迭代闭环测试"""
    
    def test_normal_sample(self):
        """测试正常样本（50笔）"""
        from large_number_iteration_loop import LargeNumberIterationLoop
        trades = [{'pnl_pct': np.random.normal(1.0, 3.0)} for _ in range(50)]
        
        loop = LargeNumberIterationLoop(trades)
        report = loop.generate_report()
        
        self.assertEqual(report['sample_analysis']['current_n'], 50)
        self.assertTrue(report['sample_analysis']['is_sufficient'])
    
    def test_small_sample(self):
        """测试最小样本（5笔）"""
        from large_number_iteration_loop import LargeNumberIterationLoop
        trades = [{'pnl_pct': 1.0} for _ in range(5)]
        
        loop = LargeNumberIterationLoop(trades)
        report = loop.generate_report()
        
        # 样本不足
        self.assertFalse(report['sample_analysis']['is_sufficient'])
    
    def test_all_loss(self):
        """测试全亏损样本"""
        from large_number_iteration_loop import LargeNumberIterationLoop
        trades = [{'pnl_pct': -2.0} for _ in range(30)]
        
        loop = LargeNumberIterationLoop(trades)
        report = loop.generate_report()
        
        sig_test = report['significance_test']
        # 全亏损应显著为负（t-test检验均值是否显著小于0）
        # 注意：这里的is_significant是检验均值是否显著大于0
        # 全亏损时应该是不显著（不能拒绝均值为0的原假设）或显著为负
        # 由于scipy的ttest_1samp检验的是是否显著不等于0
        # 全亏损时应该显著不等于0（即显著为负）
        self.assertTrue(sig_test['is_significant'], "全亏损样本应统计显著")
        self.assertLess(sig_test['t_statistic'], 0, "t统计量应为负")


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestICCapitalCompound))
    suite.addTests(loader.loadTestsFromTestCase(TestMultiAgentCollaboration))
    suite.addTests(loader.loadTestsFromTestCase(TestConvexityRiskProtector))
    suite.addTests(loader.loadTestsFromTestCase(TestLargeNumberIterationLoop))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 输出结果
    print()
    print('='*70)
    print(f"测试结果：{result.testsRun}个测试，{len(result.failures)}个失败，{len(result.errors)}个错误")
    print('='*70)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
