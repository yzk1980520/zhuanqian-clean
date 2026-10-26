# P-C2 对照组测试: data_quality_checker P2 交易日历过滤修复 + GAP-005 读侧豁免
# 老五切片 P2 (ae6ccad5 日历过滤, 8971faec GAP-005 台账), 老三 10/24 05:4x 补对照组
# 口径: 合成仓 + monkeypatch ROOT 隔离真实台账, 断言假红/真缺口/豁免/fail-close 四态
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import data_quality_checker  # noqa: E402

# 交易日历(含周末/国庆休市): 以 sh000001 基准在库日期为准
TD = ["2026-09-29", "2026-09-30", "2026-10-09", "2026-10-12", "2026-10-13",
      "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20",
      "2026-10-21", "2026-10-22", "2026-10-23"]


def _recs(dss):
    return json.dumps([{"date": d, "close": 1.0} for d in dss])


def _mk(tmp, files, ledger=None, ledger_status="open-exempt"):
    """合成仓: tmp/data/history_daily 数据面 + tmp/data 台账面 (ROOT 指向 tmp)"""
    (tmp / "data" / "history_daily").mkdir(parents=True)
    for n, dss in files.items():
        (tmp / "data" / "history_daily" / n).write_text(_recs(dss), encoding="utf-8")
    if ledger is not None:
        (tmp / "data" / "known_gaps.json").write_text(json.dumps(
            {"gaps": [{"gap_id": "GAP-005", "status": ledger_status, **ledger}]}),
            encoding="utf-8")
        (tmp / "data" / "delisted_classification_full.json").write_text(
            json.dumps(ledger.get("cls", {})), encoding="utf-8")
        (tmp / "data" / "stale_alive_21.json").write_text(
            json.dumps(ledger.get("alive", [])), encoding="utf-8")
    return tmp


def test_t1_holiday_weekend_not_flagged(tmp_path, monkeypatch):
    # 股票完整覆盖基准 30 交易日, 自然日里的周末/国庆(10-01/02)不在基准 → 0 issues
    monkeypatch.setattr(data_quality_checker, "ROOT", str(tmp_path))
    t = _mk(tmp_path, {"sh000001.json": TD, "sh603727.json": TD})
    assert data_quality_checker.check_date_completeness(str(t / "data" / "history_daily")) == []


def test_t2_source_gap_flagged(tmp_path, monkeypatch):
    # 真实源缺口(2 交易日)→ 精确报该 2 日
    monkeypatch.setattr(data_quality_checker, "ROOT", str(tmp_path))
    t = _mk(tmp_path, {"sh000001.json": TD,
                       "sz000999.json": [d for d in TD if d not in ("2026-10-12", "2026-10-16")]})
    issues = data_quality_checker.check_date_completeness(str(t / "data" / "history_daily"))
    assert [i["code"] for i in issues] == ["sz000999"]
    assert set(issues[0]["missing_dates"]) == {"2026-10-12", "2026-10-16"}


def test_t3_bond_metadata_excluded(tmp_path, monkeypatch):
    # 债券(sh1100xx)/指数段/元数据文件不入股票面 → 0 issues
    monkeypatch.setattr(data_quality_checker, "ROOT", str(tmp_path))
    t = _mk(tmp_path, {"sh000001.json": TD, "sh110075.json": TD[:4],
                       "a4_factor_research.json": [], "sh600000.json": TD})
    assert data_quality_checker.check_date_completeness(str(t / "data" / "history_daily")) == []


def test_t4_no_reference_failclose(tmp_path, monkeypatch):
    # 基准(sh000001)不可得 → fail-close 0 issues + 留痕(不静默绿, 不误报自然日)
    monkeypatch.setattr(data_quality_checker, "ROOT", str(tmp_path))
    t = _mk(tmp_path, {"sh600000.json": TD})
    assert data_quality_checker.check_date_completeness(str(t / "data" / "history_daily")) == []


def test_t5_gap005_exempt_stale_not_flagged(tmp_path, monkeypatch):
    # GAP-005 台账在位: 豁免码 sh600068 停更末日=终态 → 0 issues; 非豁免码缺口仍报
    monkeypatch.setattr(data_quality_checker, "ROOT", str(tmp_path))
    t = _mk(tmp_path,
            {"sh000001.json": TD,
             "sh600068.json": TD[:5],              # 豁免件停更 → 不报
             "sz000100.json": [d for d in TD if d != "2026-10-23"]},  # 非豁免缺口 → 报
            ledger={"cls": {"with_data": ["sh600068"], "st_skipped": []}, "alive": []})
    issues = data_quality_checker.check_date_completeness(str(t / "data" / "history_daily"))
    assert [i["code"] for i in issues] == ["sz000100"], issues
    assert "sh600068" not in [i["code"] for i in issues]


def test_t6_gap005_ledger_missing_failclose(tmp_path, monkeypatch):
    # 台账缺失/非 open-exempt → fail-close 不豁免, 缺口照报 (不误绿)
    monkeypatch.setattr(data_quality_checker, "ROOT", str(tmp_path))
    t = _mk(tmp_path, {"sh000001.json": TD, "sh600068.json": TD[:5]},
            ledger={"cls": {}, "alive": []}, ledger_status="closed")
    issues = data_quality_checker.check_date_completeness(str(t / "data" / "history_daily"))
    assert [i["code"] for i in issues] == ["sh600068"], "台账 closed 不得豁免"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
