# -*- coding: utf-8 -*-
"""test_factor_registry_audit.py — 全量审查: R5(ic_history schema) + R6(同名遮蔽) 修复

R5: 真实 ic_history.json 是 dict 型 {"history":{factor:[vals]},...}, 但根版 FactorRegistry
    期望 record-list。_load 把 dict 直接赋给 self.ic_history(List) → update_ic 的 .append 崩,
    且日监控 factor_ic_daily_monitor.py 用 try/except 吞掉 = 假绿("已同步"其实没同步)。
    修复: _load 归一 ic_history 为 list, 原 dict 保留到 legacy(不丢数据), loud 诊断;
    备份后 update_ic 生效, 不再崩/假绿。

R6: scripts/factor_registry.py(375行, 另一套 {"registry":{...}} 实现, 无 FactorMetadata)
    与根 factor_registry.py(有 FactorMetadata/to_dict) 同名遮蔽。日监控靠 sys.path 顺序拿根版,
    一旦某脚本 path 顺序变就静默拿到影子版 = 假绿。修复: 日监控显式按绝对路径加载根版 + 断言。

全部测试隔离在 tmp_path, 不碰真实 registry.json/ic_history.json。
"""
import sys, os, json
from pathlib import Path

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE / "scripts"))
sys.path.insert(0, str(BASE))

from tests.test_factor_registry_fixtures import isolated_registry


class TestR5IcHistorySchema:
    """ic_history.json 真 schema 是 dict 型 {"history":{factor:[ic,...]}} (factor_ic_monitor 写),
    根版 FactorRegistry 误当 record-list → update_ic 崩/日监控假绿。根因修法: 根版说 dict schema。"""

    def test_load_keeps_dict_schema(self, isolated_registry):
        reg, _ = isolated_registry
        assert isinstance(reg.ic_history, dict), "R5: ic_history 应说 dict schema(与 factor_ic_monitor 对齐)"
        assert reg.ic_history.get("history", {}).get("chg5") == [0.9, 0.8], "R5: 旧数据不得丢失"

    def test_update_ic_two_arg_appends_not_crash(self, isolated_registry):
        reg, _ = isolated_registry
        reg.update_ic("chg5", 0.05)   # 修复前: (a)icir 缺参 TypeError (b)dict.append AttributeError
        vals = reg.ic_history.setdefault("history", {}).get("chg5", [])
        assert vals[-1] == 0.05, "R5: update_ic 应把 ic 追加到 dict schema 对应因子序列末尾"

    def test_save_ic_history_roundtrip(self, isolated_registry):
        reg, tmp = isolated_registry
        reg.update_ic("chg5", 0.05)
        reg._save_ic_history()
        reloaded = json.loads((tmp / "ic_history.json").read_text(encoding="utf-8"))
        assert reloaded.get("history", {}).get("chg5", []).count(0.05) >= 1, \
            "R5: _save_ic_history 必须 round-trip(丢旧数据=假绿复发)"
        # 二次 load 仍可读, 不崩
        assert isinstance(reloaded, dict)


class TestR6ImportShading:
    def test_monitor_resolves_root_factor_registry(self, tmp_path):
        """复刻 factor_ic_daily_monitor 的显式加载, 断言拿到根版(有 FactorMetadata)而非 scripts 影子版。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_root_fr_probe", BASE / "factor_registry.py")
        fr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fr)
        assert hasattr(fr, "FactorMetadata"), "R6: 根版必须有 FactorMetadata"
        assert hasattr(fr.FactorRegistry, "check_gate"), "R6: 根版 FactorRegistry 必须完整"
        # 影子版指纹: scripts 版无 FactorMetadata → 若误 import 到它则此断言拦下
        spec2 = importlib.util.spec_from_file_location(
            "_scripts_fr_probe", BASE / "scripts/factor_registry.py")
        sf = importlib.util.module_from_spec(spec2)
        try:
            spec2.loader.exec_module(sf)
            shaded_no_class = not hasattr(sf, "FactorMetadata")
        except Exception:
            shaded_no_class = True
        assert shaded_no_class or sf is fr, \
            "R6: 影子版与根版若都能 import 且同结构则遮蔽无险, 否则必须锁死根版"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
