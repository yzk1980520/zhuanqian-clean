# -*- coding: utf-8 -*-
"""LHB 龙虎榜因子复活 (2026-10-14) — 单一读点 + point-in-time + 零覆盖证明

背景: 09-04 原块四缺陷(路径/模式/schema/日期过滤), IC=0.0991 最强因子长期静默恒0。
复活=生产 compute_indicators(code=) 与回测 fast_compute_all(code=) 共用
read_lhb_signal 单一读点。本测试全部断言挂一手证据 (SOUL#5)。
"""
import json
import os
import re
from datetime import date, datetime, timezone, timedelta

import core.scoring.tdx_indicators as tdx_indicators
from core.scoring.tdx_indicators import read_lhb_signal, compute_indicators
from backtest.backtest_fast_inds import fast_compute_all

TZ8 = timezone(timedelta(hours=8))


def _ms(y, m, d):
    return int(datetime(y, m, d, 0, 0, tzinfo=TZ8).timestamp() * 1000)


def _mk_akshare_dir(tmp_path, pull_ymd, rows):
    d = tmp_path / "akshare"
    d.mkdir()
    (d / f"get_lhb_detail_{pull_ymd}.json").write_text(
        json.dumps({"data": rows}, ensure_ascii=False), encoding="utf-8")
    return str(d)


def _recs30():
    recs, p, d0 = [], 10.0, date(2026, 1, 1)
    from datetime import timedelta as _td
    for i in range(30):
        p *= 1.01
        recs.append({"date": d0 + _td(days=i), "open": p * 0.999,
                    "high": p * 1.02, "low": p * 0.99, "close": p,
                    "volume": 1000 + i, "amount": p * (1000 + i)})
    return recs


def test_lhb_semantics_code_keyed_units_same_day(tmp_path):
    """±1 语义 / code键控 / 百分数单位 / 当日过滤 — 合成数据直证"""
    rows = [
        {"代码": "600000", "上榜日": _ms(2026, 1, 5), "净买额占总成交比": 12.5},
        {"代码": "600004", "上榜日": _ms(2026, 1, 5), "净买额占总成交比": -8.0},
        {"代码": "600002", "上榜日": _ms(2026, 1, 5), "净买额占总成交比": 2.0},
        {"代码": "000001", "上榜日": _ms(2026, 1, 4), "净买额占总成交比": 50.0},
    ]
    d = _mk_akshare_dir(tmp_path, "20260105", rows)
    assert read_lhb_signal("600000", date(2026, 1, 5), data_dir=d) == 1.0
    assert read_lhb_signal("600004", date(2026, 1, 5), data_dir=d) == -1.0
    assert read_lhb_signal("600002", date(2026, 1, 5), data_dir=d) == 0.0
    # 01-04 的行在 01-05 扫描日不算 (当日口径)
    assert read_lhb_signal("000001", date(2026, 1, 5), data_dir=d) == 0.0
    # 未上榜 → 0
    assert read_lhb_signal("999999", date(2026, 1, 5), data_dir=d) == 0.0
    # code=None → 0 (兼容语义)
    assert read_lhb_signal(None, date(2026, 1, 5), data_dir=d) == 0.0
    # 日期串 "YYYY-MM-DD" 归一化
    assert read_lhb_signal("600000", "2026-01-05", data_dir=d) == 1.0


def test_lhb_no_lookahead(tmp_path):
    """01-05 扫描日不得看到 01-06 拉取的文件 (point-in-time 硬约束)"""
    rows = [{"代码": "600000", "上榜日": _ms(2026, 1, 6), "净买额占总成交比": 20.0}]
    d = _mk_akshare_dir(tmp_path, "20260106", rows)
    assert read_lhb_signal("600000", date(2026, 1, 5), data_dir=d) == 0.0


def test_lhb_real_data_zero_pointintime_coverage():
    """真实数据(4个文件) point-in-time 有效覆盖=0 → 门禁结论的数据侧证据

    文件: 0925(拉)/1003/1004/1005(拉), 上榜日行 ∈ {09-18,09-21..24,09-28,29,30}
    有效扫描日 S 需满足: 存在 pull_date <= S 的文件含 上榜日==S 的行。
    所有上榜日的行都只出现在更晚的拉取文件里 → 无任何有效 S。
    且标准回测窗口末端 2026-09-18 < 首个拉取日 2026-09-25。
    """
    # 2026-10-24 T051 C4 对齐 (S6 迁移诊断): 原 dirname(tdx_indicators.__file__) 锚点随 S6
    # 模块迁 core/scoring/ 后指向 core/scoring/data/akshare (不存在)。本测试语义 =
    # 2026-10-15 冻结快照 (4 文件: 0925/1003/1004/1005), 真址 data/akshare/backup_20261015/
    # (活跃 data/akshare/ 已持续新增 5-6 月拉取件, 文件集不再等于断言集)。
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = os.path.join(_repo_root, "data", "akshare", "backup_20261015")
    files = {}
    for fn in os.listdir(base):
        m = re.match(r"get_lhb_detail_(\d{8})\.json$", fn)
        if m:
            files[m.group(1)] = os.path.join(base, fn)
    pulls = sorted(files)
    row_dates, valid_days = set(), set()
    for pull, path in files.items():
        parsed = tdx_indicators._lhb_parse_file(path)
        for rd, codes in parsed.items():
            row_dates.add(rd)
            # rd 的行在 pull 文件里 → 有效扫描日只能是 rd 且需 pull <= rd
            if pull <= rd and any(abs(c) > 0.05 for c in codes.values()):
                valid_days.add(rd)
    assert pulls == ["20260925", "20261003", "20261004", "20261005"], f"文件集变化: {pulls}"
    # 字面量固定(独立源=2026-10-14 手工检视 JSON 所得, 非代码复算): 行上榜日共 8 天
    assert row_dates == {"20260918", "20260921", "20260922", "20260923", "20260924",
                         "20260928", "20260929", "20260930"}, f"LHB行上榜日集漂移: {row_dates}"
    assert valid_days == set(), f"意外存在 point-in-time 有效日: {valid_days}"
    # 标准回测窗口末端早于首个拉取日 → 窗口内 LHB 覆盖必为 0
    assert date(2026, 9, 18) < date(2026, 9, 25)
    # 窗口外(10月)同样 0: 10月扫描日的行需 pull<=扫描日 且 上榜日==扫描日
    for s in ("20261008", "20261009", "20261014"):
        files_le = [p for p in pulls if p <= s]
        ok = False
        for pull in files_le:
            parsed = tdx_indicators._lhb_parse_file(files[pull])
            if s in parsed and any(abs(c) > 0.05 for c in parsed[s].values()):
                ok = True
        assert not ok, f"{s} 意外有有效LHB"


def test_fast_compute_all_lhb_wiring():
    """回测快路径接线: code= → 键存在; code=None → 键缺省 (tdx_score 取0, 零行为变化)"""
    recs = _recs30()
    last_ds = str(recs[-1]["date"])
    r = fast_compute_all(recs, keep_dates={last_ds}, code="600000")
    assert r and "lhb_signal" in r[-1][1], "code= 时 lhb_signal 键缺失"
    r0 = fast_compute_all(recs, keep_dates={last_ds})
    assert "lhb_signal" not in r0[-1][1], "code=None 不应注入键 (既有调用方零行为变化)"
    # 真实数据下当前值必须为 0.0 (零覆盖证明的另一面)
    assert r[-1][1]["lhb_signal"] == 0.0


def test_lhb_cache_invalidates_on_file_overwrite(tmp_path):
    """同路径文件被拉取器覆盖(数据更新)后必须重新解析 — 缓存按 mtime 失效, 非路径常驻

    第一性: 拉取器写固定文件名 get_lhb_detail_<pull>.json; 若进程跨拉取周期存活,
    按路径常驻缓存会读到陈旧数据 (09-25 事故同型: 陈旧=静默错误)。
    断言方式: 不清缓存直接改写文件(仅 mtime 变化), 二读必须拿到新解析值。
    """
    import time
    d = _mk_akshare_dir(tmp_path, "20260105",
                        [{"代码": "600000", "上榜日": _ms(2026, 1, 5), "净买额占总成交比": 2.0}])
    assert read_lhb_signal("600000", date(2026, 1, 5), data_dir=d) == 0.0  # 2% 未破阈 (冷解析)
    time.sleep(2.5)  # Windows st_mtime 粒度粗, 留足间隔
    (tmp_path / "akshare" / "get_lhb_detail_20260105.json").write_text(
        json.dumps({"data": [{"代码": "600000", "上榜日": _ms(2026, 1, 5), "净买额占总成交比": 12.5}]},
                   ensure_ascii=False), encoding="utf-8")
    # 未清缓存: 路径常驻实现会返回旧解析(0.0) → 本断言即 RED 判据; mtime 失效实现返回 1.0
    assert read_lhb_signal("600000", date(2026, 1, 5), data_dir=d) == 1.0


def test_compute_indicators_code_param():
    """生产路径: code= → 输出含 lhb_signal; 不传 code → 含键且为0 (键始终存在, 与评分契约一致)"""
    recs = _recs30()
    inds = compute_indicators(recs, code="600000")
    assert inds and inds.get("lhb_signal") == 0.0
    inds0 = compute_indicators(recs)
    assert inds0 and "lhb_signal" in inds0 and inds0["lhb_signal"] == 0.0
