"""真突破检测集成模块

将tdx_breakout_detector集成到integrated_picker.py的选股流程中

使用位置:
1. 流动性过滤层之后（Layer1）
2. 综合评分层之前
3. 龙虎榜评分层之前（可选）

集成方式:
- 可选开关：ENABLE_BREAKOUT_FILTER = True/False
- 阈值可调：BREAKOUT_VOL_THRESHOLD, BREAKOUT_MA_THRESHOLD
- 回退兼容：不满足真突破条件的股票仍保留在候选池（降低权重）
"""
import sys
from pathlib import Path

# 添加项目路径 (2026-10-14 P0同类修复 + 基地化S3 2026-10-22: 迁 core/scoring/ 后单层parent误指 core/scoring → 取 parent.parent=仓库根)
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

from core.scoring.tdx_breakout_detector import calc_breakout_score, is_true_breakout


# 配置开关（用户可调整）
ENABLE_BREAKOUT_FILTER = True  # 是否启用真突破检测
BREAKOUT_VOL_THRESHOLD = 1.5   # 成交量放大阈值
BREAKOUT_MA_THRESHOLD = 1.03   # 均线多头阈值
BREAKOUT_MIN_SCORE = 55        # 最低综合评分门槛


def apply_breakout_filter(records, current_price, min_score=BREAKOUT_MIN_SCORE):
    """应用真突破过滤
    
    Args:
        records: 历史行情记录列表
        current_price: 当前价格
        min_score: 最低评分门槛
    
    Returns:
        {'breakout': bool, 'score': int, 'details': dict, 'pass': bool}
    """
    if not records or len(records) < 21:
        return {
            'breakout': False,
            'score': 0,
            'details': {'vol_ratio': 1.0, 'ma5_ma20': 1.0, 'chg20': 0},
            'pass': False,
            'reason': '数据不足'
        }
    
    try:
        # 提取收盘价和成交量
        closes = [r['close'] for r in records[-25:]]
        volumes = [r['volume'] for r in records[-25:]]
        
        # 计算真突破评分
        result = calc_breakout_score(
            closes=closes,
            volumes=volumes,
            current_price=current_price,
            vol_threshold=BREAKOUT_VOL_THRESHOLD,
            ma_threshold=BREAKOUT_MA_THRESHOLD
        )
        
        # 判定是否通过
        passed = result['breakout'] and result['score'] >= min_score
        
        return {
            'breakout': result['breakout'],
            'score': result['score'],
            'details': result['details'],
            'pass': passed,
            'reason': '' if passed else f"评分{result['score']}<{min_score}"
        }
    except Exception as e:
        return {
            'breakout': False,
            'score': 0,
            'details': {},
            'pass': False,
            'reason': f'计算失败: {str(e)}'
        }


def integrate_breakout_to_picker(picker_func):
    """装饰器：将真突破检测集成到选股流程
    
    用法:
        @integrate_breakout_to_picker
        def run_integrated_picker(...):
            ...
    """
    def wrapper(*args, **kwargs):
        # 调用原始函数
        results = picker_func(*args, **kwargs)
        
        # 对结果应用真突破过滤
        if ENABLE_BREAKOUT_FILTER and results:
            filtered_results = []
            for item in results:
                # 提取必要数据
                code = item[0]  # 股票代码
                price = item[1]  # 当前价格
                records = item[2]  # 历史记录（假设有）
                
                # 应用过滤
                breakout_result = apply_breakout_filter(records, price)
                
                # 根据结果调整权重
                if breakout_result['pass']:
                    # 真突破票，加分
                    item[9]['score'] = item[9].get('score', 0) + 5
                    item[9]['breakout_bonus'] = True
                else:
                    # 非真突破，扣分（可选）
                    # item[9]['score'] = max(0, item[9].get('score', 0) - 3)
                    pass
                
                filtered_results.append(item)
            
            return filtered_results
        
        return results
    
    return wrapper


# 测试代码
if __name__ == "__main__":
    print("=== 真突破检测集成测试 ===\n")
    
    # 模拟测试数据
    test_records = [
        {'close': 10.0 + i * 0.05, 'volume': 100000 + i * 5000, 'date': f"2026-09-{i:02d}"}
        for i in range(25)
    ]
    
    # 最后一天放量突破
    test_records[24]['volume'] = 350000
    test_records[24]['close'] = 12.0
    
    result = apply_breakout_filter(test_records, test_records[-1]['close'])
    
    print(f"测试结果:")
    print(f"  是否真突破: {result['breakout']}")
    print(f"  综合评分: {result['score']}")
    print(f"  是否通过: {result['pass']}")
    print(f"  详情: {result['details']}")
    print(f"  原因: {result['reason']}")
    
    if result['pass']:
        print("\n✅ 真突破检测集成测试通过")
    else:
        print("\n⚠️ 测试结果异常，需要调整阈值")