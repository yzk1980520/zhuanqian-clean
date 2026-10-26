# -*- coding: utf-8 -*-
"""test_factor_registry_todict.py — P0隐患TDD: FactorMetadata.to_dict/save 对 ic_mean=None 必须安全

Kimi-41 Q1 B-prime 把旧定义 IC 隔离为 ic_mean=None(顶层置空+ic_history留痕)。
若 to_dict 对 None 调 round(), 生成器/任何 save 路径直接崩 → 属"定义源模块"脆弱点。
RED: 先证明当前实现崩; GREEN: 修复后 to_dict 保 None, 且 round 值语义不变。
"""
import sys
from pathlib import Path
BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))
import pytest

from core.scoring.factor_registry import FactorMetadata


class TestToDictNoneSafe:
    def test_todict_with_isolated_ic_none(self):
        # 隔离后合法状态: ic_mean=None (旧定义IC已移入ic_history)
        m = FactorMetadata(
            factor_id="TEST", name="t", category="x", description="d",
            ic_mean=None, icir=None,
        )
        d = m.to_dict()
        assert d["ic_mean"] is None, "to_dict 必须保留 None(隔离语义), 不得吞成 0.0"
        assert d["icir"] is None

    def test_todict_numeric_unchanged(self):
        # 数值路径语义不变(不回归)
        m = FactorMetadata(factor_id="T2", name="t", category="x", description="d",
                           ic_mean=0.050177, icir=0.2509)
        d = m.to_dict()
        assert d["ic_mean"] == pytest.approx(0.050177, abs=1e-6)
        assert d["icir"] == pytest.approx(0.2509, abs=1e-4)

    def test_roundtrip_none_preserved(self):
        m = FactorMetadata(factor_id="T3", name="t", category="x", description="d",
                          ic_mean=None, icir=None)
        m.gate_status = "pending"
        d = m.to_dict()
        back = FactorMetadata.from_dict(d)
        assert back.ic_mean is None, "from_dict 往返必须保留 None"
        assert back.gate_status == "pending"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
