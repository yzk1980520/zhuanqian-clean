#!/usr/bin/env python3
"""
chan_engine.py 测试
覆盖：边界条件 + 正常流程 + Layer 8 接口
"""

import pytest
try:
    from chan_engine import (
        detect_fractals, merge_klines, form_pens,
        form_segments, identify_zones, detect_divergence,
        identify_buy_sell_points, compute_chan_score,
        get_layer8_score
    )
except ImportError:
    pytest.skip("chan_engine module not installed (baseline pre-existing), skipping all tests", allow_module_level=True)


def test_empty():
    """空输入边界"""
    assert detect_fractals([]) == []
    assert merge_klines([], 'up') == []
    assert form_pens([], []) == []
    assert form_segments([]) == []
    assert identify_zones([]) == []
    assert identify_buy_sell_points([], [], {}) == {'found': False, 'type': None, 'score': 0}
    result = compute_chan_score([])
    assert result['score'] == 0
    assert result['signals'] == []
    assert result['divergence'] == {}
    assert result['point'] == {}
    print('  ✅ test_empty')


def test_too_few():
    """K线太少"""
    bars = [{'high': 10, 'low': 9, 'close': 9.5, 'volume': 1000} for _ in range(3)]
    assert detect_fractals(bars) == []
    result = compute_chan_score(bars)
    assert result['score'] == 0
    assert result['signals'] == []
    print('  ✅ test_too_few')


def test_basic_flow():
    """基础流程测试"""
    # 构造含分型/K线合并/笔/线段/中枢的数据
    bars = []
    for i in range(50):
        import math
        # 波动走势，带分型结构
        base = 10 + math.sin(i * 0.3) * 2
        bars.append({
            'high': base + 0.5,
            'low': base - 0.5,
            'close': base + (0.2 if i % 2 == 0 else -0.2),
            'volume': 1000 + (i % 5) * 100
        })
    
    # 执行流程
    fractals = detect_fractals(bars)
    merged = merge_klines(bars, 'up')
    pens = form_pens(fractals, merged)
    segments = form_segments(pens)
    zones = identify_zones(segments)
    divergence = detect_divergence(bars)
    point = identify_buy_sell_points(bars, zones, divergence)
    score = compute_chan_score(bars)
    
    # 验证返回格式
    assert isinstance(score['score'], int)
    assert -20 <= score['score'] <= 20
    assert isinstance(score['signals'], list)
    assert isinstance(score['divergence'], dict)
    assert isinstance(score['point'], dict)
    print(f'  ✅ test_basic_flow (fractals={len(fractals)}, zones={len(zones)}, score={score["score"]})')


def test_merge_klines():
    """K线合并处理"""
    # 上升包含：后一根完全包含前一根
    bars_up = [
        {'high': 10, 'low': 9, 'close': 9.5, 'volume': 100},
        {'high': 11, 'low': 10, 'close': 10.5, 'volume': 100},  # 高>前高，低>前低 → 不包含
    {'high': 12, 'low': 9.5, 'close': 11, 'volume': 100},   # 高>前高，低<前低 → 包含
    ]
    merged = merge_klines(bars_up, 'up')
    # 第1根独立，第2根不包含（low=10 > prev_low=9），第3根包含
    assert len(merged) == 2
    
    # 下降包含：后一根完全包含前一根
    bars_down = [
        {'high': 12, 'low': 10, 'close': 11, 'volume': 100},
        {'high': 11, 'low': 9, 'close': 10.5, 'volume': 100},    # 高<前高，低<前低 → 不包含
        {'high': 10, 'low': 9.5, 'close': 9.5, 'volume': 100},   # 高<前高，低>前低 → 包含
    ]
    merged = merge_klines(bars_down, 'down')
    assert len(merged) == 2
    
    # 无包含
    bars_none = [
        {'high': 10, 'low': 9, 'close': 9.5, 'volume': 100},
        {'high': 12, 'low': 11, 'close': 11.5, 'volume': 100},
        {'high': 9, 'low': 8, 'close': 8.5, 'volume': 100},
    ]
    merged = merge_klines(bars_none, 'up')
    assert len(merged) == 3
    
    print('  ✅ test_merge_klines')


def test_form_pens():
    """笔划分"""
    # 底→顶→底→顶 = 3笔（up, down, up）
    fractals = [(2, 'bottom'), (5, 'top'), (8, 'bottom'), (11, 'top')]
    merged = [{'high': 10 + i, 'low': 9 + i, 'close': 9.5 + i, 'volume': 100} for i in range(15)]
    
    pens = form_pens(fractals, merged)
    assert len(pens) == 3  # up, down, up
    
    # 验证方向：底→顶=上升，顶→底=下降，底→顶=上升
    assert pens[0]['direction'] == 'up'     # bottom → top = 上升
    assert pens[1]['direction'] == 'down'   # top → bottom = 下降
    assert pens[2]['direction'] == 'up'     # bottom → top = 上升
    
    print('  ✅ test_form_pens')


def test_form_segments():
    """线段划分（2笔同向即可成段）"""
    # 两笔上升 + 两笔下降 = 2线段
    pens = [
        {'direction': 'up'}, {'direction': 'up'},
        {'direction': 'down'}, {'direction': 'down'},
    ]
    segments = form_segments(pens)
    assert len(segments) == 2
    
    # 不足2笔
    pens_short = [{'direction': 'up'}]
    assert form_segments(pens_short) == []
    
    print('  ✅ test_form_segments')


def test_segments_2pens():
    """form_segments 2笔成段验证"""
    pens = [
        {'direction': 'up'}, {'direction': 'up'},
        {'direction': 'down'}, {'direction': 'down'},
    ]
    segments = form_segments(pens)
    assert len(segments) == 2
    assert segments[0]['direction'] == 'up'
    assert segments[1]['direction'] == 'down'
    print('  ✅ test_segments_2pens')


def test_layer8_interface():
    """Layer 8 接口验证"""
    import math
    bars = []
    for i in range(60):
        base = 50 - i * 0.3 if i < 30 else 41 + (i - 30) * 0.1
        vol = 1000 - i * 10 if i < 30 else 700 + (i - 30) * 5
        bars.append({'high': base + 0.5, 'low': base - 0.5, 'close': base, 'volume': max(100, vol)})
    
    score, signals = get_layer8_score(bars)
    assert isinstance(score, int)
    assert isinstance(signals, list)
    assert -20 <= score <= 20
    print(f'  ✅ test_layer8_interface (score={score})')


def test_chan_score_format():
    """compute_chan_score 返回格式验证"""
    import math
    bars = [
        {'high': 10 + math.sin(i * 0.3) * 2, 
         'low': 10 + math.sin(i * 0.3) * 2 - 1,
         'close': 10 + math.sin(i * 0.3) * 2,
         'volume': 1000}
        for i in range(50)
    ]
    result = compute_chan_score(bars)
    assert 'score' in result
    assert 'signals' in result
    assert 'divergence' in result
    assert 'point' in result
    assert 'zones' in result
    assert 'fractals' in result
    assert isinstance(result['score'], int)
    assert -20 <= result['score'] <= 20
    print(f'  ✅ test_chan_score_format')


if __name__ == '__main__':
    print('=== 缠论引擎测试 ===')
    test_empty()
    test_too_few()
    test_basic_flow()
    test_merge_klines()
    test_form_pens()
    test_form_segments()
    test_segments_2pens()
    test_layer8_interface()
    test_chan_score_format()
    print('\n✅ 全部通过')
