# -*- coding: utf-8 -*-
"""test_factor_ic_universe_purity.py — t_bbc3444e universe 纯度过滤层 TDD

RED 前基线: _is_etf() 前缀粗判(sh51/56/58/sz15/16)漏放 444 只非 A 股品种
(基金/LOF 249 + 债券/可转债 184 + B股/其他 11)进 2000 只截面, 行业映射覆盖率
73.7% < 80% 红线 (Task A data/audit/aa_resid_mom_retest_20261026.md §二)。
GREEN 判据:
  1. _is_ashare_stock 白名单(60/68/00/30)精确判别 A 股 vs 基金/债/B股/指数;
  2. _load_universe 默认模式: 漏放的非 A 股剔除但占窗口 slot(旧 2000 槽等价),
     旧 _is_etf 排除段剔除且不占 slot(与旧引擎逐文件等价);
  3. --include-etf 取证模式: 除指数外全收(旧行为, 不占 slot);
  4. hook 未映射组键: A 股缺映射标 UNMAPPED_ASHARE, 非 A 股标 UNMAPPED,
     映射缺失时原样返回(不造数)。
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "f132_purity", BASE / "scripts" / "factor_ic_132d_refresh.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def m():
    return _load_module()


def _bars(n=70):
    out = []
    for i in range(n):
        out.append({"date": f"2026-{i // 28 + 1:02d}-{i % 28 + 1:02d}",
                    "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0,
                    "volume": 1000, "amount": 10000})
    return out


def _write(tmp_path, code, bars):
    (tmp_path / f"{code}.json").write_text(json.dumps(bars), encoding="utf-8")


class TestIsAshareStock:
    @pytest.mark.parametrize("code", [
        "sh600000", "sh601000", "sh603000", "sh605000",
        "sh688001", "sh689001",
        "sz000001", "sz001001", "sz002001", "sz003001",
        "sz300001", "sz301001", "sz302001",
    ])
    def test_ashare_true(self, m, code):
        assert m._is_ashare_stock(code), f"{code} 应判为 A 股"

    @pytest.mark.parametrize("code", [
        # 基金/LOF/ETF/跨境
        "sh501001", "sh508001", "sh511010", "sh513050", "sh520001",
        "sh530001", "sh551001", "sh560001", "sh588000",
        "sz159001", "sz160001",
        # 债券/可转债
        "sh110050", "sh113050", "sh118001", "sh132001", "sh127001",
        # B股 / 其他段
        "sh204001", "sh900901", "sz200001", "sz201001",
        # 指数 / 通达信板块指数
        "sh000001", "sz399001", "sh880001", "sh881001", "sh999999",
    ])
    def test_non_ashare_false(self, m, code):
        assert not m._is_ashare_stock(code), f"{code} 不得判为 A 股"


class TestLoadUniversePurity:
    def test_leaked_excluded_but_slot_kept(self, m, tmp_path, monkeypatch):
        """旧 3 槽窗口 = [sh113050(债,leaked), sh600000, sh600001]
        (sh511010 属旧 _is_etf 排除段, 旧引擎中不占 slot)。
        新口径: sh113050 剔除但占 slot → universe = {sh600000, sh600001}, 逐码等价。"""
        _write(tmp_path, "sh113050", _bars())   # leaked 债券(非 sh51/56/58/sz15/16)
        _write(tmp_path, "sh511010", _bars())   # 旧 _is_etf 排除段
        _write(tmp_path, "sh600000", _bars())
        _write(tmp_path, "sh600001", _bars())
        monkeypatch.setattr(m, "HISTORY_DIR", tmp_path)
        monkeypatch.setattr(m, "_INCLUDE_ETF", False)
        u = m._load_universe(3)
        assert set(u) == {"sh600000", "sh600001"}, "leaked 非 A 股必须剔除, 且关窗点与旧 3 槽等价"
        assert "sh113050" not in u and "sh511010" not in u

    def test_all_ashare_window_unchanged(self, m, tmp_path, monkeypatch):
        """窗口内全是 A 股时, 行为与旧引擎完全一致(收满 max_stocks 才停)。"""
        for c in ("sh600000", "sh600001", "sh600002", "sh600003"):
            _write(tmp_path, c, _bars())
        monkeypatch.setattr(m, "HISTORY_DIR", tmp_path)
        monkeypatch.setattr(m, "_INCLUDE_ETF", False)
        u = m._load_universe(2)
        assert set(u) == {"sh600000", "sh600001"}

    def test_include_etf_mode_old_behavior(self, m, tmp_path, monkeypatch):
        """--include-etf 取证模式: 除指数外全收(含基金/债券), 不占 slot。"""
        for c in ("sh113050", "sh511010", "sh600000", "sh600001"):
            _write(tmp_path, c, _bars())
        monkeypatch.setattr(m, "HISTORY_DIR", tmp_path)
        monkeypatch.setattr(m, "_INCLUDE_ETF", True)
        u = m._load_universe(4)
        assert set(u) == {"sh113050", "sh511010", "sh600000", "sh600001"}, \
            "include-etf 模式必须恢复旧行为(全收除指数)"

    def test_short_file_skipped_no_slot(self, m, tmp_path, monkeypatch):
        """过不了根数门的 leaked 文件: 剔除且不计 slot(与旧引擎一致)。"""
        _write(tmp_path, "sh113050", _bars(n=30))  # < 66 根
        _write(tmp_path, "sh600000", _bars())
        _write(tmp_path, "sh600001", _bars())
        monkeypatch.setattr(m, "HISTORY_DIR", tmp_path)
        monkeypatch.setattr(m, "_INCLUDE_ETF", False)
        u = m._load_universe(2)
        assert set(u) == {"sh600000", "sh600001"}


class TestUnmappedGroupKey:
    def test_unmapped_ashare_vs_unmapped(self, m, monkeypatch):
        """A 股缺映射 → UNMAPPED_ASHARE 组; 非 A 股缺映射 → UNMAPPED 组; 组内去均值。"""
        monkeypatch.setattr(m, "_T1_INDUSTRY_MAP_CACHE",
                            {"sh600000": "801010"})
        res = m._t1_industry_demean([1.0, 3.0, 5.0, 7.0],
                                     ["sh600000", "sh600001", "sh600002", "sh511010"])
        assert res == pytest.approx([0.0, -1.0, 1.0, 0.0]), \
            "801010 组 [1] 残差 0; UNMAPPED_ASHARE 组 [3,5] 均值 4; UNMAPPED 组 [7] 残差 0"

    def test_missing_map_returns_identity(self, m, monkeypatch):
        """映射为空 → 原样返回(退化为原始动量, 不造数)。"""
        monkeypatch.setattr(m, "_T1_INDUSTRY_MAP_CACHE", {})
        vals = [1.0, 2.0, 3.0]
        assert m._t1_industry_demean(vals, ["sh600000", "sh600001", "sh600002"]) == vals


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider"])
