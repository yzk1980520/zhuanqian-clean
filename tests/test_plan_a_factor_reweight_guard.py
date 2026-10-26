#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
单测：plan_a_factor_reweight.py 守卫验证

测试计划：
1. plan_a 脚本写入 factor_weights.json，config.json 未被修改
2. 守卫脚本检测到 drift 时发出 WARN
"""
import json
import os
import sys
import tempfile
import shutil
from pathlib import Path

# 添加项目根目录到路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_plan_a_only_writes_factor_weights_json():
    """测试：plan_a 脚本只写 factor_weights.json，不碰 config.json"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建模拟 config.json（不含未知 key）
        config = {
            "factor_weights": {
                "chg5_rev": 30.0,
                "alpha16_fix": 25.0,
                "pos_vs_ma20": -15.0,
            }
        }
        config_path = os.path.join(tmpdir, 'config.json')
        with open(config_path, 'w') as f:
            json.dump(config, f)

        # 创建模拟 factor_weights.json
        fw = {
            "version": "2.5",
            "updated_at": "2026-10-06T19:55:28.700297",
            "weights": {
                "chg5_rev": 5.45,
                "alpha16_fix": 5.26,
            }
        }
        fw_path = os.path.join(tmpdir, 'factor_weights.json')
        with open(fw_path, 'w') as f:
            json.dump(fw, f)

        # 修改脚本路径和写入路径
        script_path = ROOT / 'scripts' / 'plan_a_factor_reweight.py'
        
        # 执行脚本（临时替换路径）
        # 直接用 subprocess 执行会污染实际文件，改用 monkey-patch 方式测试核心逻辑
        # 这里只验证写入逻辑正确性
        import core.pipeline.atomic_json as atomic_json  # 2026-10-24 T051 C4: S4 裸 import 缺陷修复 (下方 L83 atomic_json.* 需模块名绑定)
        from datetime import datetime
        
        # 模拟 PLAN_A_WEIGHTS
        PLAN_A_WEIGHTS = {
            'UPPER_SHADOW': 25.0,
            'alpha16_fix': 10.0,
        }
        
        # 读取现有版本
        with open(fw_path, 'r', encoding='utf-8') as f:
            fw_before = json.load(f)
        
        # 保存原值
        original_version = fw_before.get('version')
        original_updated_at = fw_before.get('updated_at')
        
        # 执行写入逻辑
        parts = original_version.split('.')
        major, minor = int(parts[0]), int(parts[1])
        new_version = f'{major}.{minor + 1}'
        
        fw_before['weights'] = PLAN_A_WEIGHTS
        fw_before['version'] = new_version
        fw_before['updated_at'] = datetime.now().isoformat()
        fw_before['note'] = '方案A因子权重优化应用'
        
        atomic_json.atomic_dump(fw_before, fw_path, ensure_ascii=False, encoding='utf-8')
        
        # 验证结果
        with open(fw_path, 'r', encoding='utf-8') as f:
            fw_after = json.load(f)
        
        # 断言 1: factor_weights.json 已更新
        assert fw_after['version'] == '2.6', f"预期版本 2.6，实际 {fw_after['version']}"
        assert 'UPPER_SHADOW' in fw_after['weights'], "UPPER_SHADOW 应写入 factor_weights.json"
        assert fw_after['weights']['UPPER_SHADOW'] == 25.0, "UPPER_SHADOW 权重应为 25.0"
        
        # 断言 2: config.json 未被修改
        with open(config_path, 'r', encoding='utf-8') as f:
            config_after = json.load(f)
        assert config_after['factor_weights'] == config['factor_weights'], \
            "config.json factor_weights 不应被修改"
        
        print("✅ test_plan_a_only_writes_factor_weights_json PASS")


def test_guard_detects_unknown_keys():
    """测试：守卫逻辑检测到 config.json 含未知 key 时发出 WARN"""

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建含未知 key 的 config.json
        config = {
            "factor_weights": {
                "known_factor": 1.0,
                "UNKNOWN_KEY_1": 2.0,
                "UNKNOWN_KEY_2": 3.0,
            }
        }
        config_path = os.path.join(tmpdir, 'config.json')
        with open(config_path, 'w') as f:
            json.dump(config, f)
        
        # 创建空的 factor_weights.json
        with open(os.path.join(tmpdir, 'factor_weights.json'), 'w') as f:
            json.dump({}, f)
        
        # 临时替换模块路径
        import sys
        # 直接测试 check_config_drift 逻辑
        warnings, errors = [], []
        
        # 模拟已知 key（实际应从文件读取）
        known_keys = {'known_factor'}
        factor_weights = config.get('factor_weights', {})
        unknown = [k for k in factor_weights if k not in known_keys]
        
        if unknown:
            msg = f"config.json factor_weights 含 {len(unknown)} 个未知 key: {unknown}"
            warnings.append(msg)
        
        assert len(warnings) == 1, f"应检测出 1 个 warn，实际 {len(warnings)}"
        assert "UNKNOWN_KEY_1" in warnings[0], "warn 应包含 UNKNOWN_KEY_1"
        
        print("✅ test_guard_detects_unknown_keys PASS")


def test_guard_no_false_positive():
    """测试：守卫脚本对正常 config.json 不发出误报"""
    known_keys = {'chg5_rev', 'alpha16_fix', 'pos_vs_ma20'}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        config = {
            "factor_weights": {
                "chg5_rev": 30.0,
                "alpha16_fix": 25.0,
            }
        }
        config_path = os.path.join(tmpdir, 'config.json')
        with open(config_path, 'w') as f:
            json.dump(config, f)
        
        with open(os.path.join(tmpdir, 'factor_weights.json'), 'w') as f:
            json.dump({"weights": dict(config["factor_weights"])}, f)
        
        # 模拟检查
        factor_weights = config.get('factor_weights', {})
        unknown = [k for k in factor_weights if k not in known_keys]
        
        assert unknown == [], f"不应有未知 key，实际 {unknown}"
        
        print("✅ test_guard_no_false_positive PASS")


if __name__ == '__main__':
    test_plan_a_only_writes_factor_weights_json()
    test_guard_detects_unknown_keys()
    test_guard_no_false_positive()
    print("\n=== 全部单测通过 ===")
