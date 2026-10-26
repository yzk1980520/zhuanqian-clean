#!/usr/bin/env python3
"""
Jev决策引擎 - TypeSafe API集成测试
"""

import requests
import json
import time
from typing import Dict, List, Optional


class JevTestEngine:
    """Jev决策引擎测试类"""
    
    def __init__(self):
        self.api_url = "https://api.typesafe.ai/v1/systemone"
        self.available = False
        self.test_results = {}
    
    def check_api(self):
        """检查API可用性"""
        try:
            resp = requests.get(self.api_url, timeout=5)
            self.available = resp.status_code == 405  # 405表示API可达但需要POST
            return self.available
        except Exception as e:
            self.available = False
            return False
    
    def test_choice(self, context: str, options: List[str], instructions: str = "") -> dict:
        """测试Choice原语"""
        payload = {
            "task": "choice",
            "context": context,
            "options": options,
            "instructions": instructions
        }
        
        start = time.time()
        try:
            resp = requests.post(
                self.api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            latency = (time.time() - start) * 1000
            
            if resp.status_code == 200:
                return {
                    "success": True,
                    "latency_ms": latency,
                    "result": resp.json()
                }
            else:
                return {
                    "success": False,
                    "latency_ms": latency,
                    "error": f"HTTP {resp.status_code}: {resp.text}"
                }
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {
                "success": False,
                "latency_ms": latency,
                "error": str(e)
            }
    
    def test_noul(self, context: str, question: str) -> dict:
        """测试Noul原语"""
        return self.test_choice(
            context=context,
            options=["是", "否"],
            instructions=f"请判断：{question}"
        )
    
    def test_score(self, context: str, rubric: List[str]) -> dict:
        """测试Score原语"""
        return self.test_choice(
            context=context,
            options=rubric,
            instructions="请根据以下标准评分"
        )


def run_tests():
    """运行所有测试"""
    engine = JevTestEngine()
    
    
    # 检查API
    if engine.check_api():
        pass
    else:
        return
    
    # 测试Choice
    choice_test = engine.test_choice(
        context="用户问：帮我分析这只股票的技术面",
        options=["选股", "回测", "风控", "持仓", "其他"],
        instructions="判断用户意图"
    )
    
    if choice_test["success"]:
        result = choice_test["result"]
        print(f"✅ Choice测试成功 ({choice_test['latency_ms']:.0f}ms)")
        print(f"   选择: {result.get('choice', 'N/A')}")
        print(f"   置信度: {result.get('confidence', 'N/A')}")
        print(f"   概率分布: {result.get('probabilities', {})}")
        engine.test_results['choice'] = choice_test
    else:
        print(f"❌ Choice测试失败: {choice_test.get('error')}")
        engine.test_results['choice'] = choice_test
    
    # 测试Noul
    noul_test = engine.test_noul(
        context="持仓: 吉华集团(sh603980), 成本: 8.60元, 现价: 8.05元, 浮亏: -6.4%, 止损线: 7.86元",
        question="当前浮亏-6.4%，接近止损线7.86元，是否应该止损？"
    )
    
    if noul_test["success"]:
        result = noul_test["result"]
        print(f"✅ Noul测试成功 ({noul_test['latency_ms']:.0f}ms)")
        print(f"   决策: {result.get('choice', 'N/A')}")
        print(f"   置信度: {result.get('confidence', 'N/A')}")
        engine.test_results['noul'] = noul_test
    else:
        print(f"❌ Noul测试失败: {noul_test.get('error')}")
        engine.test_results['noul'] = noul_test
    
    # 测试Score
    score_test = engine.test_score(
        context="""
        股票: XXXX
        breakout_strength: 0.75
        chg5_rev: 0.68
        sector_correlation: 0.82
        momentum_reversal: 0.45
        fund_flow_intensity: 0.91
        vol_ratio: 0.38
        市场环境: 震荡市
        """,
        rubric=["强卖出", "卖出", "观望", "买入", "强买入"]
    )
    
    if score_test["success"]:
        result = score_test["result"]
        print(f"✅ Score测试成功 ({score_test['latency_ms']:.0f}ms)")
        print(f"   评分: {result.get('choice', 'N/A')}")
        print(f"   置信度: {result.get('confidence', 'N/A')}")
        engine.test_results['score'] = score_test
    else:
        print(f"❌ Score测试失败: {score_test.get('error')}")
        engine.test_results['score'] = score_test
    
    # 总结
    
    success_count = sum(1 for v in engine.test_results.values() if v.get("success"))
    total_count = len(engine.test_results)
    
    print(f"成功: {success_count}/{total_count}")
    
    if success_count == total_count:
        pass
    elif success_count > 0:
        pass
    else:
        pass
    
    return engine.test_results


if __name__ == "__main__":
    run_tests()
