"""post_mortem_diagnose.py 单测 (t_64c8bbf0, 2026-10-26) — 17-case 门禁中的 10 case。

覆盖:
- 因子 IC 诊断 (no_data / reversed / weak / list 格式)
- 门禁诊断结论 (strict_valid < 8 → fail-close 结论)
- 交易归因 (dict / list 两种格式)
- run_post_mortem 文件产出 / main 无参 manual trigger / 损坏 JSON 记 warning

隔离原则: PROJ monkeypatch 到 tmp_path, 生产 data/ 零写入; 诊断函数直调纯 dict, 无文件依赖。
"""
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "post_mortem_diagnose.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("post_mortem_diagnose_under_test", SCRIPT)
    assert spec is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def proj(mod, tmp_path, monkeypatch):
    """PROJ → tmp_path: run_post_mortem / main 的文件产出全部落 tmp, 不碰生产 data/。"""
    monkeypatch.setattr(mod, "PROJ", tmp_path)
    return tmp_path


def test_factor_ic_no_data(mod):
    """ic_data=None → {"status": "no_data"}。"""
    assert mod._factor_ic_diagnosis(None) == {"status": "no_data"}


def test_factor_ic_dict_reversed(mod):
    """IC=-0.02 (< -0.01) → 进入 reversed 列表。"""
    d = mod._factor_ic_diagnosis({"f_reversed": {"ic_mean": -0.02}, "f_ok": {"ic_mean": 0.05}})
    assert d["status"] == "ok"
    assert "f_reversed" in d["reversed"]
    assert "f_ok" not in d["reversed"]


def test_factor_ic_dict_weak(mod):
    """IC=0.005 (|IC| < 0.01) → 进入 weak 列表。"""
    d = mod._factor_ic_diagnosis({"f_weak": {"ic_mean": 0.005}, "f_ok": {"ic_mean": 0.05}})
    assert d["status"] == "ok"
    assert "f_weak" in d["weak"]
    assert "f_ok" not in d["weak"]


def test_factor_ic_list_format(mod):
    """list 输入 → 正确解析为因子列表。"""
    d = mod._factor_ic_diagnosis([
        {"name": "f1", "ic_mean": 0.3},
        {"name": "f2", "ic_mean": -0.05},
    ])
    assert d["status"] == "ok"
    assert d["total_factors"] == 2
    assert d["reversed"] == ["f2"]
    assert d["top3_ic"]["f1"] == 0.3


def test_gate_strict_valid_low(mod, proj):
    """strict_valid_count=5 < 8 → auto_conclusions 存在 fail-close 结论。"""
    res = mod.run_post_mortem({"status": "FAIL"}, context={"gate": {"strict_valid_count": 5}})
    assert any("strict_valid" in c for c in res["auto_conclusions"]), res["auto_conclusions"]
    assert any("5 < 8" in c or "< 8" in c for c in res["auto_conclusions"])


def test_trade_diagnosis_dict_format(mod):
    """{"trades": [...]} → 正确摘要 (含 date/code/direction/return_pct 兜底键)。"""
    d = mod._trade_diagnosis({"trades": [
        {"ts": "t1", "symbol": "SH600000", "side": "buy", "pnl": 1.2},
        {"date": "t2", "code": "SZ000001", "direction": "sell", "return_pct": -0.3},
    ]})
    assert d["status"] == "ok"
    assert d["recent_trades"][0] == {"ts": "t1", "symbol": "SH600000", "side": "buy", "pnl": 1.2}
    assert d["recent_trades"][1] == {"ts": "t2", "symbol": "SZ000001", "side": "sell", "pnl": -0.3}


def test_trade_diagnosis_list_format(mod):
    """[...] 直接列表 → 正确摘要。"""
    d = mod._trade_diagnosis([{"ts": "t1", "symbol": "X", "side": "buy", "pnl": 0.1}])
    assert d["status"] == "ok"
    assert len(d["recent_trades"]) == 1
    assert d["recent_trades"][0]["symbol"] == "X"


def test_run_post_mortem_writes_file(mod, proj):
    """run_post_mortem() → <PROJ>/data/post_mortem_*.json 存在且可解析。"""
    res = mod.run_post_mortem({"status": "FAIL", "commit": "abc123"})
    files = list((proj / "data").glob("post_mortem_*.json"))
    assert len(files) == 1, files
    loaded = json.loads(files[0].read_text(encoding="utf-8"))
    assert loaded["backtest_status"] == "FAIL"
    assert loaded["backtest_commit"] == "abc123"
    assert loaded is not None and res["diagnosis"]["factor_ic"]["status"] in ("no_data", "ok", "unparsed")


def test_main_no_result_arg(mod, proj, monkeypatch):
    """main() 无 --result → manual trigger 正常, 产出诊断文件。"""
    monkeypatch.setattr("sys.argv", ["post_mortem_diagnose.py"])
    mod.main()
    files = list((proj / "data").glob("post_mortem_*.json"))
    assert len(files) == 1, files
    loaded = json.loads(files[0].read_text(encoding="utf-8"))
    assert loaded["backtest_status"] == "FAIL"


def test_load_corrupt_file_logs_warning(mod, tmp_path, monkeypatch):
    """损坏 JSON → 返回 default 且 logger.warning 被调用 (宪法 VII: 不静默吞异常)。"""
    p = tmp_path / "corrupt.json"
    p.write_text("{broken json", encoding="utf-8")
    mock_logger = MagicMock()
    monkeypatch.setattr(mod, "logger", mock_logger)
    result = mod._load(p, default={"fallback": 1})
    assert result == {"fallback": 1}
    mock_logger.warning.assert_called_once()


def test_run_post_mortem_filename_unique(mod, proj):
    """两次快速调用 run_post_mortem → 产生 2 个不同文件名（纳秒尾防碰撞）。"""
    mod.run_post_mortem({"status": "FAIL"})
    import time as _time
    _time.sleep(0.01)  # 10ms 保证纳秒尾差异
    mod.run_post_mortem({"status": "FAIL"})
    files = list((proj / "data").glob("post_mortem_*.json"))
    assert len(files) == 2, f"expected 2 files, got {len(files)}: {files}"


def test_run_post_mortem_with_factor_ic_context(mod, proj):
    """context.factor_ic 直传 → 不读 factor_ic.json，直接用 context 数据。"""
    ctx = {"factor_ic": {"f_reversed": {"ic_mean": -0.03}, "f_ok": {"ic_mean": 0.05}}}
    res = mod.run_post_mortem({"status": "FAIL"}, context=ctx)
    ic_diag = res["diagnosis"]["factor_ic"]
    assert ic_diag["status"] == "ok"
    assert "f_reversed" in ic_diag["reversed"]
    assert "f_ok" not in ic_diag["reversed"]
