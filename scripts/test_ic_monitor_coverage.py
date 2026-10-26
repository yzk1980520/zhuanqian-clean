#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
IC监控覆盖率测试（TDD第一版）
目标：验证IC监控覆盖生产因子，而非仅V2测试集
"""
import sys, os, json
from pathlib import Path
# 2026-10-15 总管 CI兼容: 原硬编码 'D:/open code/zhuanqian' 绝对路径在CI ubuntu 上
# FileNotFoundError, 改为相对仓库根解析(本地/CI 通用)
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / '.scratch'))
import pytest

def test_ic_monitor_covers_production_factors():
    """测试1: IC监控应覆盖生产因子，而非V2测试集"""
    # 加载生产因子权重
    weights = json.load(open(REPO_ROOT / 'factor_weights.json'))
    prod_factors = [k for k, v in weights['weights'].items() if v != 0]
    
    # 加载IC监控报告
    latest_ic = None
    audit_dir = REPO_ROOT / 'data' / 'audit'
    if not audit_dir.is_dir():
        pytest.skip("data/audit 不存在(CI环境无本地审计产物, 该测试依赖实盘数据)")
    for f in sorted(os.listdir(audit_dir)):
        if f.startswith('factor_ic_rolling_20d_'):
            latest_ic = json.load(open(os.path.join(audit_dir, f)))
    
    if latest_ic is None:
        return False, "无IC监控报告"
    
    ic_factors = set(latest_ic['factors'].keys())
    prod_set = set(prod_factors)
    
    # 测试1a: 应有交集（监控至少覆盖部分生产因子）
    overlap = ic_factors & prod_set
    if not overlap:
        return False, f"IC监控覆盖{len(ic_factors)}个因子，与生产因子{len(prod_set)}个完全不重叠"
    
    # 测试1b: 覆盖率应>50%
    coverage = len(overlap) / len(prod_set)
    if coverage < 0.5:
        return False, f"IC监控覆盖率仅{coverage:.1%}，低于50%阈值"
    
    return True, f"覆盖率{coverage:.1%}，重叠{len(overlap)}个因子"

def test_gap_down_cnt_not_in_production():
    """测试2: gap_down_cnt不应在生产因子中"""
    weights = json.load(open(REPO_ROOT / 'factor_weights.json'))
    prod_factors = [k for k, v in weights['weights'].items() if v != 0]
    
    if 'gap_down_cnt' in prod_factors:
        return False, "gap_down_cnt在生产因子中，不应告警"
    return True, "gap_down_cnt确实在生产因子外，告警无效"

def test_numpi_importable():
    """测试3: numpy应可正常导入"""
    try:
        import numpy
        return True, f"numpy {numpy.__version__} OK"
    except ImportError as e:
        return False, f"numpy导入失败: {e}"

if __name__ == '__main__':
    tests = [
        test_ic_monitor_covers_production_factors,
        test_gap_down_cnt_not_in_production,
        test_numpi_importable,
    ]
    
    results = []
    for test in tests:
        try:
            passed, msg = test()
            results.append({'test': test.__name__, 'passed': passed, 'msg': msg})
            status = '✅' if passed else '❌'
            print(f"{status} {test.__name__}: {msg}")
        except Exception as e:
            results.append({'test': test.__name__, 'passed': False, 'msg': str(e)})
            print(f"❌ {test.__name__}: 异常 - {e}")
    
    # 汇总
    passed = sum(1 for r in results if r['passed'])
    total = len(results)
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed < total:
        sys.exit(1)
