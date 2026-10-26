# -*- coding: utf-8 -*-
"""P2 fuse 触发器回归 (老三 2026-09-27, 台账C件1, 交@laowu验收)。

老五验收口径: fuse 三态断言, 缺一不算交——
  ① 默认 v2_fuse=False 零行为(不碰 _CFG_CACHE / 不写模块属性 / return False)
  ② 命中(滚动10笔胜率<25% 或 峰值回撤>35%) → 翻转 enabled=False + 模块级留痕 + return True
  ③ 不命中(胜率≥25% 且 回撤≤35%) → enabled 不变, fuse_state['tripped']=False, return False
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.scoring.tdx_factor_v2 as tdx_factor_v2
from backtest.backtest_rotation import _v2_fuse_check


def _reset_module():
    tdx_factor_v2._fuse_triggered = False
    tdx_factor_v2._fuse_trigger_date = None
    tdx_factor_v2._fuse_trigger_reason = None


def _eq_peak(peak=10000.0, cur=9000.0, n=3):
    """构造峰值回撤 (peak-cur)/peak*100。cur 越小回撤越大。"""
    return [{'date': f'd{i}', 'equity': peak if i < n - 1 else cur} for i in range(n)]


def _trades(wins):
    """最近10笔: wins 笔 pnl>0, 余 pnl<0 → 胜率 = wins/10。"""
    return [{'pnl': 100.0} for _ in range(wins)] + [{'pnl': -50.0} for _ in range(10 - wins)]


def _run(config, trades, eq, cfg_dict):
    """跑一次 _v2_fuse_check(load_config 被 mock 返回 cfg_dict), 返回 (ret, fuse_state, cfg)。
    fuse_state 初值与引擎 L519 真实契约一致: {'tripped':False,'reason':None,'tripped_on':None}
    (函数尾行 return fuse_state['tripped'], 缺键会 KeyError)。"""
    _reset_module()
    fs = {'tripped': False, 'reason': None, 'tripped_on': None}
    with patch.object(tdx_factor_v2, "load_config", return_value=cfg_dict):
        ret = _v2_fuse_check(config, trades, eq, fs)
    return ret, fs, cfg_dict


class TestFuseThreeState:
    def test_default_off_zero_behavior(self):
        """① v2_fuse=False → 首行 return False, 不碰 cfg, 不写模块属性。"""
        ret, fs, cfg = _run(SimpleNamespace(v2_fuse=False), _trades(0), _eq_peak(), {'enabled': True})
        assert ret is False, "默认off必须零行为"
        assert cfg['enabled'] is True, "off态不得翻 _CFG_CACHE.enabled"
        assert tdx_factor_v2._fuse_triggered is False, "off态不得写模块级 fuse 属性"
        assert fs.get('tripped') in (None, False)

    def test_hit_winrate(self):
        """② 胜率20%(2/10)<25% → 命中: 翻 enabled=False + 模块留痕 + return True。"""
        ret, fs, cfg = _run(SimpleNamespace(v2_fuse=True), _trades(2), _eq_peak(), {'enabled': True})
        assert ret is True, "胜率<25%必须命中"
        assert cfg['enabled'] is False, "命中必须翻 enabled=False 回基线"
        assert fs.get('tripped') is True
        assert tdx_factor_v2._fuse_triggered is True
        assert "winrate" in str(tdx_factor_v2._fuse_trigger_reason)

    def test_hit_drawdown(self):
        """② 胜率达标(5/10=50%)但峰值回撤>35% → 回撤触发。"""
        eq = _eq_peak(peak=10000.0, cur=6000.0, n=3)  # dd=40% >35%
        ret, fs, cfg = _run(SimpleNamespace(v2_fuse=True), _trades(5), eq, {'enabled': True})
        assert ret is True, "峰值回撤>35%必须命中"
        assert cfg['enabled'] is False
        assert "peak_drawdown" in str(tdx_factor_v2._fuse_trigger_reason)

    def test_no_hit(self):
        """③ 胜率30%≥25% 且 回撤10%≤35% → 不命中: enabled 不变, 不触发。"""
        eq = _eq_peak(peak=10000.0, cur=9000.0, n=3)  # dd=10%
        ret, fs, cfg = _run(SimpleNamespace(v2_fuse=True), _trades(3), eq, {'enabled': True})
        assert ret is False, "胜率≥25%且回撤≤35%不命中"
        assert cfg['enabled'] is True, "不命中不得翻 enabled"
        assert tdx_factor_v2._fuse_triggered is False
        assert fs.get('tripped') in (None, False)

    def test_already_tripped_idempotent(self):
        """幂等: cfg 已回基线(enabled=False)时, 不重复置位, 返回 fuse_state['tripped']。"""
        ret, fs, cfg = _run(SimpleNamespace(v2_fuse=True), _trades(2), _eq_peak(), {'enabled': False})
        assert ret is False, "已回基线态返回 fuse_state['tripped'](首次为 False), 不重复翻"
        assert fs.get('tripped') in (None, False)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
