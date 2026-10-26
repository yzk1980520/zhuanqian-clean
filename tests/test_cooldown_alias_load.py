# -*- coding: utf-8 -*-
"""test_cooldown_alias_load.py — P0#1 冷却期在 spec 别名加载下 KeyError (RED→GREEN)

根因 (2026-10-09 实跑 A链/cron 双复现): orchestrator.py:210 用
spec_from_file_location("integrated_picker_prod") 别名加载 integrated_picker.py
且不注册 sys.modules; integrated_picker.py:158 `sys.modules[__name__]`
→ KeyError 'integrated_picker_prod' → 被 except 吞成 "检查失败: ..."
→ P0 交易纪律 "冷却5天" 实盘从未真正生效 (SOUL#9 同源静默)。

修复: picker:158 鲁棒化 — sys.modules[__name__] 仅命中才用, 否则回退模块顶层 PROJECT。

seam (已对齐): integrated_picker.check_cooldown_for_pick() 在 spec 别名加载上下文下,
  必须 (a) 不抛/不吞 KeyError (b) 正确读 data/holdings.json (c) 按 COOLDOWN_DAYS=5 判定。
  独立字面 worked-example: entry=今日-3 → (False, 3, "冷却期中..."); entry=今日-8 → (True, 8, "冷却期满...")。
"""
import sys, os, json
from pathlib import Path
from datetime import date, timedelta

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))


def _load_as_alias():
    """复刻 orchestrator.py:208-213 的别名加载 (未注册 sys.modules), 再 import core.pipeline.integrated_picker
    取到同一模块对象 — 关键: 模块名 __name__ 会是 'integrated_picker' 还是被 spec 别名污染?
    spec_from_file_location 用 location name 'integrated_picker_prod', 但本测试 import 的是
    integrated_picker (正常), 其 __name__='integrated_picker' 已在 sys.modules。
    为精确复现 KeyError, 用 spec 独立加载一个'别名模块实例'并直接调它的函数。"""
    import importlib.util as ilu
    # 2026-10-24 T051 C4 对齐 (S4 基地化 2026-10-22): 根级 integrated_picker.py 已降为 S4 shim
    # (仅 `from core.pipeline.integrated_picker import *`), 别名加载 shim 时函数绑定的 globals
    # 属于真源模块, fixture 的 monkeypatch(PROJECT) 不生效 → 4 项全 FAIL。
    # 改加载真源 core/pipeline/integrated_picker.py (P0#1 sys.modules.get 回退修复所在处)。
    prod_path = BASE / "core" / "pipeline" / "integrated_picker.py"
    # 复刻 orchestrator: 同一份源码, 但用一个 fresh spec 别名 (orchestrator 未注册 sys.modules)
    # 直接加载别名模块并调其函数 — 此时 __name__='integrated_picker_prod' 不在 sys.modules
    spec = ilu.spec_from_file_location("integrated_picker_prod_test", str(prod_path))
    mod = ilu.module_from_spec(spec)
    # 不注册 sys.modules (orchestrator 同款: exec_module 后未 setdefault)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def alias_module(tmp_path, monkeypatch):
    """别名加载 + 指向 tmp_path 的 PROJECT (monkeypatch 其属性), 隔离 holdings.json"""
    mod = _load_as_alias()
    monkeypatch.setattr(mod, "PROJECT", str(tmp_path))
    return mod


def _write_holdings(tmp_path, entry_offset_days):
    (tmp_path / "data").mkdir()
    entry = (date.today() + timedelta(days=entry_offset_days)).strftime("%Y-%m-%d")
    holdings = {"holdings": [{"code": "sh603099", "name": "长白山", "entry_date": entry}]}
    (tmp_path / "data" / "holdings.json").write_text(
        json.dumps(holdings, ensure_ascii=False), encoding="utf-8")


def test_cooldown_alias_load_recent_entry(tmp_path, alias_module, monkeypatch):
    """RED 核心: 别名加载下 entry=今日-3天 → 冷却期中 (False, 3, ...), 不再 KeyError"""
    _write_holdings(tmp_path, -3)
    allow, days, msg = alias_module.check_cooldown_for_pick()
    assert allow is False, f"3天前入场应处冷却期, 实际 allow={allow}, msg={msg}"
    assert days == 3
    assert "冷却期中" in msg, f"msg 应含'冷却期中', 实际: {msg!r} (KeyError 会给出'检查失败')"


def test_cooldown_alias_load_mature_entry(tmp_path, alias_module, monkeypatch):
    """独立字面 worked-example: entry=今日-8天 ≥ COOLDOWN_DAYS(5) → 冷却期满 (True, 8, ...)"""
    _write_holdings(tmp_path, -8)
    allow, days, msg = alias_module.check_cooldown_for_pick()
    assert allow is True, f"8天前入场应冷却期满, 实际 allow={allow}, msg={msg}"
    assert days == 8
    assert "冷却期满" in msg


def test_cooldown_alias_load_no_holdings(tmp_path, alias_module, monkeypatch):
    """无 holdings.json → (True, 0, '无持仓文件'), 不 KeyError"""
    (tmp_path / "data").mkdir()
    allow, days, msg = alias_module.check_cooldown_for_pick()
    assert allow is True
    assert days == 0
    assert "无持仓文件" in msg


def test_cooldown_alias_load_empty(tmp_path, alias_module, monkeypatch):
    """空仓 (holdings=[]) → (True, 0, '空仓'), 不 KeyError"""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "holdings.json").write_text(
        json.dumps({"holdings": []}), encoding="utf-8")
    allow, days, msg = alias_module.check_cooldown_for_pick()
    assert allow is True
    assert days == 0
    assert "空仓" in msg


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
