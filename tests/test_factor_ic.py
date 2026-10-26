#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_factor_ic.py — 因子IC监控测试套件
覆盖: 因子函数可用性、IC计算一致性、门禁判定

[t_laosan_c1_test_alignment] 2026-10-24 (裁决日 2026-10-23):
  10/23 大归档后, factor_ic_scan.py / scripts/direct_ic_calc.py 已下线,
  测试侧对齐活跃真源:
    - 因子函数注册表 → scripts/factor_ic_132d_refresh.FACTOR_FUNCTIONS
      (31因子, 逐字提升自 factor_ic_scan FACTORS, 同算术; 其 IC 口径
       单一算术源 = core/scoring/factor_gate_v2.spearman_ic)
    - 4因子日监控实现 → scripts/factor_ic_daily_monitor.py
  每个重定向/跳过均挂归档源路径+裁决日注释。
"""
import sys
import os
import json
import math
from pathlib import Path
from datetime import datetime

import pytest

# 项目路径
PROJECT = Path(__file__).parent.parent
# [t_laosan_c1_test_alignment] 原 sys.path.insert(0, PROJECT/'.scratch') 已移除:
# factor_ic_scan.py 源文件 2026-10-23 归档后不再存在(.scratch 仅剩旧 pycache, 非真源)。


class TestFactorFunctions:
    """测试因子函数是否存在且可调用"""

    def test_factor_scan_availability(self):
        """测试活跃因子注册表中的因子函数 (原 factor_ic_scan.FACTORS 7因子快照)。

        [t_laosan_c1_test_alignment] 归档源: factor_ic_scan.py (2026-10-23 裁决,
        因子函数逐字提升至 scripts/factor_ic_132d_refresh.py FACTOR_FUNCTIONS)。
        活跃注册表已扩至 31 因子, 故改为"7 个快照因子 ⊆ 活跃注册表"超集校验。
        """
        from scripts.factor_ic_132d_refresh import FACTOR_FUNCTIONS

        expected = {
            'low60_dist', 'vol_dryup', 'gap_down_cnt',
            'amount_price_corr', 'red_ratio10', 'overnight_sum20', 'AMIHUD'
        }
        actual = set(FACTOR_FUNCTIONS.keys())

        missing = expected - actual
        assert not missing, f"活跃注册表缺失因子函数: {missing}"

    def test_missing_config_factors(self):
        """测试config.json中配置的因子是否被活跃因子真源覆盖 (原: factor_ic_scan.FACTORS)。

        [t_laosan_c1_test_alignment] 对齐后不变量: config.json 配置的因子
        (UPPER_SHADOW/LOWER_SHADOW/chg5/chg10) 必须全部存在于活跃注册表
        (历史快照断言"恰好缺4因子"已随归档作废)。

        [t_e16c5039 D-15 补数据 2026-10-27 + 总管 00:4x 前提同步]: config factor_weights
        已随 R0 拍板收缩 24→20 键 (删 rsi14/vol_shrink20/vol_price_corr_20/capital_flow,
        均 weight=0 零行为变更; capital_flow 死件标注保留于 D-15 材料 §2-#8)。
        现 20 键缺失集目标 = 0: 缺注册表的 12 件 (11 件旧评分层逐字提升 +
        volatility_breakout 恢复件) 已入 132d 注册表 (同 commit)。
        回归面: 任何新 config 因子漏注册 → 本断言红。
        """
        with open(PROJECT / 'config.json', 'r') as f:
            config = json.load(f)

        configured = set(config.get('factor_weights', {}).keys())

        from scripts.factor_ic_132d_refresh import FACTOR_FUNCTIONS
        available = set(FACTOR_FUNCTIONS.keys())

        missing = configured - available
        assert not missing, f"config.json 配置因子未被活跃因子真源覆盖: {missing}"

    def test_direct_ic_calc_availability(self):
        """测试活跃因子日监控脚本包含预期因子 (原: subprocess 跑 scripts/direct_ic_calc.py)。

        [t_laosan_c1_test_alignment] 归档源: archive/scripts-20261023/direct_ic_calc.py
        (2026-10-23 裁决)。4 因子 (UPPER_SHADOW/LOWER_SHADOW/chg5/chg10) 现实现于
        scripts/factor_ic_daily_monitor.py FACTOR_CALCULATORS。
        原测试为 60s subprocess 实跑, 但活跃 daily_monitor 实跑会写 data/factor_ic/
        (交易数据总管独占区), 故对齐为静态可用性断言 (因子在注册表 + 计算函数可调用)。
        """
        import scripts.factor_ic_daily_monitor as daily

        expected = {'UPPER_SHADOW', 'LOWER_SHADOW', 'chg5', 'chg10'}
        actual = set(daily.FACTOR_CALCULATORS.keys())
        missing = expected - actual
        assert not missing, f"因子日监控注册表缺失因子: {missing}"
        assert callable(daily.calc_upper_shadow), "calc_upper_shadow 应可调用"
        assert callable(daily.calc_chg), "calc_chg(days=5/10) 应可调用"


class TestICCalculation:
    """测试IC计算逻辑"""

    def test_spearman_basic(self):
        """测试Spearman秩相关系数计算 (单一算术源: core/scoring/factor_gate_v2.spearman_ic)。

        [t_laosan_c1_test_alignment] 原 factor_ic_scan.spearman 已随 2026-10-23 归档下线,
        重定向到活跃单一算术源 (n<30 返回 None 语义一致)。
        """
        from core.scoring.factor_gate_v2 import spearman_ic

        # 完美正相关（需要足够样本）
        xs = list(range(50))
        ys = list(range(50))
        ic = spearman_ic(xs, ys)
        assert ic is not None
        assert abs(ic - 1.0) < 0.01, f"完美正相关应为1.0, 实际{ic}"

        # 完美负相关
        ys_neg = list(range(49, -1, -1))
        ic_neg = spearman_ic(xs, ys_neg)
        assert ic_neg is not None
        assert abs(ic_neg - (-1.0)) < 0.01, f"完美负相关应为-1.0, 实际{ic_neg}"

    def test_spearman_insufficient_samples(self):
        """测试样本不足时返回None (n<30 → None, 同 factor_gate_v2.spearman_ic 口径)"""
        from core.scoring.factor_gate_v2 import spearman_ic

        xs = [1, 2, 3]
        ys = [1, 2, 3]
        ic = spearman_ic(xs, ys)
        assert ic is None, "样本不足时应返回None"

    def test_ami_hud_calculation(self):
        """测试AMIHUD因子计算 (活跃真源: scripts/factor_ic_132d_refresh._ami_hud, 同算术)"""
        from scripts.factor_ic_132d_refresh import _ami_hud

        # 模拟数据: 21根K线
        c = [10.0 + i * 0.1 for i in range(21)]  # 收盘价
        a = [1000000.0] * 21  # 成交额

        result = _ami_hud(c, a)
        assert result is not None, "AMIHUD应能计算"
        assert isinstance(result, float), "AMIHUD应返回float"
        assert result >= 0, "AMIHUD应为非负值"


class TestFactorGate:
    """测试门禁判定逻辑"""

    def test_gate_json_exists(self):
        """测试factor_gate.json存在且有效"""
        gate_file = PROJECT / 'data' / 'factor_ic' / 'factor_gate.json'
        assert gate_file.exists(), "factor_gate.json不存在"

        with open(gate_file, 'r') as f:
            gate = json.load(f)

        assert 'gate_passed' in gate
        assert 'effective_factors' in gate
        assert 'effective_list' in gate
        assert 'frozen_list' in gate

    def test_gate_structure(self):
        """测试门禁结构完整性"""
        with open(PROJECT / 'data' / 'factor_ic' / 'factor_gate.json', 'r') as f:
            gate = json.load(f)

        # 有效因子数应等于有效列表长度
        assert gate['effective_factors'] == len(gate['effective_list']), \
            f"有效因子数不匹配: 声明{gate['effective_factors']}, 实际{len(gate['effective_list'])}"

        # 门禁通过条件
        if gate['gate_passed']:
            assert gate['effective_factors'] >= gate.get('threshold', 8), \
                "门禁通过但有效因子数不足"

    def test_ic_threshold_logic(self):
        """测试IC阈值判定逻辑"""
        # 从factor_ic_monitor_all.py提取逻辑
        def decide_exit_code(out_factors, alerts, alert_max=3):
            n_valid = sum(1 for f in out_factors if "rolling20_ic_mean" in out_factors.get(f, {}))
            if alerts:
                return 3
            if n_valid == 0:
                return 4  # 假绿守卫
            return 0

        # 无告警且无有效因子 → exit=4 (假绿守卫)
        out_factors = {'UPPER_SHADOW': {}}  # 无 rolling20_ic_mean 字段
        alerts = []
        code = decide_exit_code(out_factors, alerts)
        assert code == 4, f"无有效因子应返回exit=4, 实际{code}"

        # 有告警 → exit=3
        alerts = ['UPPER_SHADOW']
        code = decide_exit_code(out_factors, alerts)
        assert code == 3, f"有告警应返回exit=3, 实际{code}"

        # 正常情况 → exit=0
        out_factors = {'UPPER_SHADOW': {'rolling20_ic_mean': 0.05}}
        alerts = []
        code = decide_exit_code(out_factors, alerts)
        assert code == 0, f"正常应返回exit=0, 实际{code}"


# [t_039f1e18 2026-10-26 分诊] quick_ic_sample.json = 10-23 归档裁决前的一次性快照产物:
# 从未被 git 跟踪、无活跃写者 (其生产者 scripts/direct_ic_calc.py 已于 2026-10-23 归档至
# archive/scripts-20261023/)。文件缺失 → 跟随数据跳过 (与本文件 TestRealData skip 同模式,
# 挂原因不静默); 4 因子 IC 监控现由 scripts/factor_ic_daily_monitor.py + 132d 权威源承接;
# 快照是否重造 = 台账 D-16 拍板项 (总管)。
_QUICK_SAMPLE = PROJECT / 'data' / 'factor_ic' / 'quick_ic_sample.json'
_QUICK_SAMPLE_SKIP = pytest.mark.skipif(
    not _QUICK_SAMPLE.exists(),
    reason=("quick_ic_sample.json 缺失 (10-23 归档裁决前一次性快照, 无活跃写者, 非 git 跟踪); "
            "4因子IC监控现走 scripts/factor_ic_daily_monitor.py + 132d 权威源; "
            "快照重造拍板见台账 D-16 (t_039f1e18 分诊 2026-10-26)"))


@_QUICK_SAMPLE_SKIP
class TestQuickSample:
    """测试quick_ic_sample.json数据"""

    def test_quick_sample_exists(self):
        """测试quick_ic_sample.json存在"""
        sample_file = PROJECT / 'data' / 'factor_ic' / 'quick_ic_sample.json'
        assert sample_file.exists(), "quick_ic_sample.json不存在"

    def test_quick_sample_structure(self):
        """测试quick_ic_sample.json结构"""
        with open(PROJECT / 'data' / 'factor_ic' / 'quick_ic_sample.json', 'r') as f:
            sample = json.load(f)

        assert 'computed_at' in sample
        assert 'total_samples' in sample
        assert 'results' in sample

        for name, data in sample['results'].items():
            assert 'ic' in data or 'samples' in data

    def test_quick_sample_factors(self):
        """测试quick_ic_sample.json包含预期因子"""
        with open(PROJECT / 'data' / 'factor_ic' / 'quick_ic_sample.json', 'r') as f:
            sample = json.load(f)

        expected = {'UPPER_SHADOW', 'LOWER_SHADOW', 'chg5', 'chg10'}
        actual = set(sample['results'].keys())

        assert expected == actual, f"因子不匹配: 期望{expected}, 实际{actual}"


@_QUICK_SAMPLE_SKIP
class TestICConsistency:
    """测试IC计算一致性"""

    def test_chg5_different_methods(self):
        """测试chg5在不同方法下的一致性"""
        # direct_ic_calc.py 使用Pearson相关
        # factor_ic_monitor_all.py 使用Spearman秩相关
        # 两者应方向一致，数值可能有差异

        with open(PROJECT / 'data' / 'factor_ic' / 'quick_ic_sample.json', 'r') as f:
            quick = json.load(f)

        chg5_ic = quick['results'].get('chg5', {}).get('ic')
        assert chg5_ic is not None, "chg5 IC无法获取"
        assert abs(chg5_ic) >= 0.03, f"chg5 IC={chg5_ic} 低于阈值"

    def test_factor_direction_consistency(self):
        """测试因子方向一致性"""
        with open(PROJECT / 'data' / 'factor_ic' / 'quick_ic_sample.json', 'r') as f:
            quick = json.load(f)

        with open(PROJECT / 'data' / 'factor_ic' / 'factor_gate.json', 'r') as f:
            gate = json.load(f)

        # 检查两个来源中相同因子的方向是否一致
        common_factors = set(quick['results'].keys()) & \
                         {f['name'] for f in gate['effective_list'] + gate['frozen_list']}

        # UPPER_SHADOW在quick中是正(0.0055)，在gate中是负(-0.0424)
        # 这是因为计算方法不同：quick用Pearson，gate用Spearman
        # 所以不强制要求方向一致，只验证数据完整性

        for factor in common_factors:
            quick_ic = quick['results'][factor].get('ic')
            gate_entry = next((f for f in gate['effective_list'] + gate['frozen_list']
                              if f['name'] == factor), None)

            if quick_ic and gate_entry:
                gate_ic = gate_entry['ic']
                # 只验证都有值，允许计算方法差异
                assert isinstance(quick_ic, float), f"{factor} quick IC应为float"
                assert isinstance(gate_ic, float), f"{factor} gate IC应为float"


@pytest.mark.skip(reason=(
    "[t_laosan_c1_test_alignment] 2026-10-23 归档裁决: 源模块 scripts/direct_ic_calc.py 已归档至 "
    "archive/scripts-20261023/direct_ic_calc.py (factor_ic_scan.py 同源下线, .scratch 仅剩旧 pycache)。"
    "get_returns 无活跃等价替代; 且本测试的数据窗口快照断言 (UPPER_SHADOW IC≈0.0055 < 0.03 失效) "
    "已被门禁真源监控取代 (本文件 TestFactorGate/TestICConsistency + scripts/factor_ic_daily_monitor.py "
    "生产监控 + scripts/factor_ic_132d_refresh.py 132d 权威源)。裁决日 2026-10-23。"))
class TestRealData:
    """测试真实数据计算的IC (整类跳过, 理由见上方 decorator)"""

    def test_upper_shadow_ic(self):
        """测试UPPER_SHADOW因子IC"""
        from scripts.direct_ic_calc import calc_upper_shadow, get_returns
        import numpy as np

        # 加载真实数据
        data_dir = PROJECT / 'data' / 'history_daily'
        codes = [f[:-5] for f in os.listdir(data_dir)
                 if f.endswith('.json') and (f.startswith('sh60') or f.startswith('sz00') or f.startswith('sz30'))]

        all_f, all_r = [], []
        for code in codes[:500]:  # 采样
            filepath = data_dir / f'{code}.json'
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                data.sort(key=lambda x: x['date'])
                df = data[-120:]

                if len(df) < 30:
                    continue

                f_vals = calc_upper_shadow(df)
                returns = get_returns(df)

                for f, r in zip(f_vals, returns):
                    if not np.isnan(f) and not np.isnan(r):
                        all_f.append(f)
                        all_r.append(r)
            except Exception:
                print(f"🔴 [tests\\test_factor_ic.py] CR-01: except Exception:", file=sys.stderr)
        if len(all_f) >= 100:
            ic = np.corrcoef(all_f, all_r)[0, 1]
            assert ic is not None, "UPPER_SHADOW IC计算失败"
            # 根据quick_ic_sample.json, UPPER_SHADOW IC≈0.0055 (失效)
            assert abs(ic) < 0.03, f"UPPER_SHADOW IC={ic:.4f} 应低于阈值"
        else:
            pytest.skip("样本不足")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
