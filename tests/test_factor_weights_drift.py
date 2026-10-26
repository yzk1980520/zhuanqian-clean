# -*- coding: utf-8 -*-
"""
因子权重漂移守卫单测（2026-10-07 老三建）

覆盖3项：
1. get_known_factor_keys 返回真实 key 数 > 0（路径修复验证）
2. RSI14 等合法因子不在未知key列表中（不误报）
3. 守卫对真实 config.json 能检测漂移（已知有3个未知key）

守卫脚本：.agent/regression/factor_weights_drift_check.py
"""
import json
import os
import pytest

# 注入守卫路径
sys_path = os.path.join(os.path.dirname(__file__), '..', '.agent', 'regression')
if sys_path not in __import__('sys').path:
    __import__('sys').path.insert(0, sys_path)

from factor_weights_drift_check import get_known_factor_keys, check_config_drift


class TestFactorWeightsDrift:
    """因子权重漂移守卫测试"""

    def test_known_keys_non_empty(self):
        """测试1: get_known_factor_keys 返回真实 key 数 > 0（路径修复验证）"""
        keys = get_known_factor_keys()
        assert len(keys) > 0, f"已知因子 key 数必须 > 0，实际: {len(keys)}"
        assert 'RSI14' in keys, "已知因子应包含 RSI14"
        assert 'momentum_20' in keys, "已知因子应包含 momentum_20"

    def test_valid_factor_not_flagged(self):
        """测试2: RSI14 等合法因子不在未知key列表中"""
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        config_path = os.path.join(repo_root, 'config.json')

        if not os.path.exists(config_path):
            pytest.skip('config.json 不存在')

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        fw = config.get('factor_weights', {})
        if not fw:
            pytest.skip('config.json 无 factor_weights')

        # RSI14 是合法因子，不应出现在'未知key'警告中
        warnings, _ = check_config_drift(config_path, verbose=False)
        unknown_warnings = [w for w in warnings if '未知 key' in w]

        for w in unknown_warnings:
            assert 'RSI14' not in w, f"RSI14 是合法因子，不应被误报为未知: {w}"

    def test_drift_guard_detects_unknown_key(self, tmp_path):
        """测试3(B 构造性重写, K53 §二 拍 B): 守卫能检测未知 key 漂移 — 正向"该报时能报"。

        原 test 硬编码 3 具体 key(price_reversal_5d/value_proxy/amount_price_corr_20),
        前提"config 含3个未知key" 随 09-20 前视剔除 + git 4114679b 死段清理已失效
        (config 未知 key=0) → 正向守卫能力被拆掉, test 恒红。

        B 重写(3 条绑定):
          1. 构造性: tmp config 塞一个白名单外探针 key → check_config_drift(tmp) → 断言该 key 被报出
             (不依赖 config 现态, 因子增删不影响)
          2. 不碰实盘: 全程 tmp 路径, 绝不读/写 config.json
          3. 不洗绿/不 skip: 断言真触发守卫(探针 key 必须在未知 key 警告里)
        """
        import json as _json
        # 白名单 = get_known_factor_keys() (收自 factor_weights.json + registry.json, 固定, 不随 config 变)
        known = get_known_factor_keys()
        assert len(known) > 0, f"白名单为空, 守卫前置失效: {known}"
        # 造一个白名单外探针 key (保证与白名单无交集)
        probe = "ZZ_PROBE_UNKNOWN_FACTOR_ZZ"
        while probe in known:
            probe += "_"
        # tmp config (绝不碰实盘 config.json)
        tmp_cfg = tmp_path / "config_probe.json"
        tmp_cfg.write_text(_json.dumps({"factor_weights": {probe: 0.5}}), encoding="utf-8")
        # 跑守卫: 检查1(未知 key) 必报出 probe → 正向漂移检测
        warnings, _ = check_config_drift(str(tmp_cfg), verbose=False)
        unknown_warnings = [w for w in warnings if "未知 key" in w]
        combined = " ".join(unknown_warnings)
        assert probe in combined, f"守卫未报出探针未知 key: {unknown_warnings} (正向漂移守卫失效)"
