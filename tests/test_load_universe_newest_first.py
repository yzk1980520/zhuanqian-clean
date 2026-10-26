# -*- coding: utf-8 -*-
"""test_load_universe_newest_first.py — Kimi-41 Q4债2 TDD: load_universe 检测 newest-first 必须 loud fail

拍板口径: 检测到 newest-first(倒序) 应 loud fail + 打印诊断 + 拒绝继续, 要求上游修数据。
"静默翻转 = 让 TDX 数据问题永远不暴露, 修症状不修根因" → 禁止 valid.reverse() 静默处理。

RED: 当前实现无检测 → newest-first 被当正常数据返回(静默), 测试 fail。
GREEN: 实现单调性检测后 → newest-first raise RuntimeError(带诊断), 正序正常返回。
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE / "scripts"))
import run_pca_ic_analysis as m  # 模块级 import 已验证 0.2s 无副作用


def _bars(n, newest_first):
    """构造 n 根 bar, close>0(过 valid 判定), date 按序或倒序。"""
    base = date(2026, 4, 1)
    out = []
    for i in range(n):
        d = base - timedelta(days=i) if newest_first else base + timedelta(days=i)
        out.append({"date": d.isoformat(), "open": 10.0, "high": 11.0,
                    "low": 9.0, "close": 10.0, "volume": 1000, "amount": 10000})
    return out


def _write(tmp_path, code, bars):
    (tmp_path / f"{code}.json").write_text(__import__("json").dumps(bars), encoding="utf-8")


class TestLoadUniverseNewestFirst:
    def test_newest_first_loud_fail(self, tmp_path, monkeypatch):
        """newest-first 数据 → 必须 raise RuntimeError(带诊断), 不得静默接受/翻转。"""
        monkeypatch.setattr(m, "DATA_DIR", tmp_path)
        _write(tmp_path, "sh000001", _bars(80, newest_first=True))
        with pytest.raises(RuntimeError, match="newest-first"):
            m.load_universe(["sh000001"])

    def test_newest_first_lists_offender_in_diagnosis(self, tmp_path, monkeypatch, capsys):
        """诊断必须点名 offender code(可追溯, 供上游定位) — 异常 message + stderr 都要有。"""
        monkeypatch.setattr(m, "DATA_DIR", tmp_path)
        _write(tmp_path, "sh000002", _bars(75, newest_first=True))
        exc = None
        try:
            m.load_universe(["sh000002"])
        except RuntimeError as e:
            exc = e
        assert exc is not None, "newest-first 必须 raise"
        assert "sh000002" in str(exc), "异常 message 必须点名倒序股票"
        err = capsys.readouterr().err
        assert "sh000002" in err, "stderr 诊断必须点名倒序股票"

    def test_ascending_ok_returns_records(self, tmp_path, monkeypatch):
        """正序(oldest-first)数据 → 正常返回, 不误伤。"""
        monkeypatch.setattr(m, "DATA_DIR", tmp_path)
        _write(tmp_path, "sh000003", _bars(80, newest_first=False))
        rec = m.load_universe(["sh000003"])
        assert "sh000003" in rec, "正序数据必须被正常载入"
        assert len(rec["sh000003"]) > 0

    def test_mixed_only_bad_triggers(self, tmp_path, monkeypatch):
        """混入 1 只倒序 → 整批 loud fail(防个别坏股污染截面)。"""
        monkeypatch.setattr(m, "DATA_DIR", tmp_path)
        _write(tmp_path, "sh000004", _bars(80, newest_first=False))  # 好
        _write(tmp_path, "sh000005", _bars(75, newest_first=True))   # 坏
        with pytest.raises(RuntimeError, match="newest-first"):
            m.load_universe(["sh000004", "sh000005"])

    def test_short_file_skipped_not_flagged(self, tmp_path, monkeypatch):
        """<70 根的倒序文件走现有 skip 分支, 不误报(不干扰 min-bars 门)。"""
        monkeypatch.setattr(m, "DATA_DIR", tmp_path)
        _write(tmp_path, "sh000006", _bars(50, newest_first=True))   # <70
        rec = m.load_universe(["sh000006"])
        assert "sh000006" not in rec, "<70 根应被跳过, 不触发 newest-first raise"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
