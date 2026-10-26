# -*- coding: utf-8 -*-
"""test_data_supply_scripts.py — 数据供给脚本功能回归测试 (P1 M-1 + P2 M-7, 2026-10-24 老五R0裁定)

覆盖对象:
  - scripts/auto_tdx_refresh.py (TDX核心股日线每日刷新, cron 3498d272 目标脚本)
  - scripts/lhb_backfill.py     (龙虎榜历史回填, cron c7e3f9a2b104 目标脚本)

粒度 (任务单验收):
  1. 模块可导入 (importlib 直接加载, 断言关键符号存在)
  2. CLI --help / --dry-run 不崩 (子进程实跑, rc=0; 对生产 data/ 只读, 前后文件集快照比对不新增写)
  3. auto_tdx_refresh: 新鲜度判定单测 (fresh/stale/边界/缺失/空/损坏, 显式 stocks 注入)
     + 刷新路径 mock TDX 解析 (get_tdx_data 注入, 断言落盘 JSON schema: 键/类型/升序)
     + --dry-run 不写文件 + 不调 TDX 读取 + --force 全败 rc=1 / 部分成功 rc=0
  4. lhb_backfill: dry-run 缺口检测 (固定日期+tmp AKSHARE_DIR, 缺工作日枚举/--limit 截断/不拉取不写)
     + 拉取路径全 mock (akshare stub + 假 DataFrame, 断言 payload schema/.hmac/报告/无数据与异常路径)
  5. M-7 数据化 CORE_STOCKS 逻辑单测: 持仓码 union 固定核心 / 轮出跟随 / 等价原7硬编码 /
     缺失与损坏 fallback 原7只 + WARN (禁静默吞, caplog 断言)

纪律: 全 mock 不联网 (TDX 二进制/akshare 均注入); 不碰生产 data/ 写口
(子进程烟测仅追加各自日志文件 = 脚本固有行为; holdings.json 只读)。
"""
import importlib.util
import json
import logging
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AUTO_SCRIPT = ROOT / "scripts" / "auto_tdx_refresh.py"
LHB_SCRIPT = ROOT / "scripts" / "lhb_backfill.py"

# 原7只硬编码 (206da970 版 L80, 含 sh603727=现行持仓) — 等价性基准
LEGACY_CORE7 = ["sh600519", "sh600000", "sz000858", "sh601318", "sz000001", "sh600036", "sh603727"]


# ============================================================================
# 模块加载 (importlib 直载 scripts/ 真源, 独立模块名防污染)
# ============================================================================

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def atr():
    """auto_tdx_refresh 模块 (venv 环境: numpy/core.pipeline 可用, 无网络调用)"""
    return _load("auto_tdx_refresh_under_test", AUTO_SCRIPT)


@pytest.fixture(scope="module")
def lhb():
    """lhb_backfill 模块 (akshare 仅 import 不联网; 拉取全部走 stub)"""
    return _load("lhb_backfill_under_test", LHB_SCRIPT)


def _write_holdings(path: Path, holdings):
    path.write_text(json.dumps({"holdings": holdings}, ensure_ascii=False), encoding="utf-8")


def _records(n_days=5, latest=None):
    """合成 TDX 记录 (core.pipeline 真源口径: date 对象 + 数值字段)"""
    end = latest or date.today()
    out = []
    for i in range(n_days, 0, -1):
        d = end - timedelta(days=i - 1)
        out.append({
            "date": d, "open": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i,
            "close": 10.5 + i, "amount": 1_000_000 * i, "volume": 100_000 * i,
        })
    return out


# ============================================================================
# 1. 模块可导入 + 关键符号
# ============================================================================

class TestModuleImportable:
    def test_auto_tdx_refresh_symbols(self, atr):
        for attr in ("main", "check_data_freshness", "refresh_stock_data", "resolve_core_stocks",
                     "_read_holding_codes", "_serialize_records",
                     "CORE_STOCKS_FIXED", "CORE_STOCKS_FALLBACK", "HOLDINGS_FILE",
                     "DATA_DIR", "FRESHNESS_MAX_LAG_DAYS"):
            assert hasattr(atr, attr), f"auto_tdx_refresh 缺符号 {attr}"

    def test_lhb_backfill_symbols(self, lhb):
        for attr in ("main", "try_pull", "existing_lhb_days", "atomic_write",
                     "_write_hmac", "log", "START_DATE", "AKSHARE_DIR", "LOG_FILE"):
            assert hasattr(lhb, attr), f"lhb_backfill 缺符号 {attr}"

    def test_legacy_fallback_equivalence(self, atr):
        """M-7: fallback 列表必须逐字等于 206da970 版原7只硬编码 (含 sh603727, 顺序不变)"""
        assert atr.CORE_STOCKS_FALLBACK == LEGACY_CORE7
        assert atr.CORE_STOCKS_FIXED == LEGACY_CORE7[:6]


# ============================================================================
# 2. CLI --help / --dry-run 不崩 (子进程实跑, 对生产 data/ 只读)
# ============================================================================

def _run_cli(script: Path, *args, timeout=180):
    return subprocess.run(
        [sys.executable, str(script), *[str(a) for a in args]],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", timeout=timeout,
    )


def _snapshot_files(dirpath: Path, pattern: str = None):
    out = set()
    if not dirpath.exists():
        return out
    for p in dirpath.iterdir():
        if p.is_file() and (pattern is None or re.fullmatch(pattern, p.name)):
            out.add(p.name)
    return out


class TestCliSmoke:
    def test_help_auto(self):
        r = _run_cli(AUTO_SCRIPT, "--help")
        assert r.returncode == 0, f"--help rc={r.returncode}: {r.stderr[-300:]}"
        assert "--dry-run" in r.stdout and "--force" in r.stdout

    def test_help_lhb(self):
        r = _run_cli(LHB_SCRIPT, "--help")
        assert r.returncode == 0, f"--help rc={r.returncode}: {r.stderr[-300:]}"
        assert "--dry-run" in r.stdout and "--limit" in r.stdout and "--start" in r.stdout

    def test_dry_run_auto_no_write(self):
        """实跑 --dry-run: rc=0 + data/history_daily 文件集前后不变 (只查新鲜度不写)"""
        ddir = ROOT / "data" / "history_daily"
        before = _snapshot_files(ddir, r".*\.json")
        r = _run_cli(AUTO_SCRIPT, "--dry-run")
        combined = r.stdout + r.stderr
        assert r.returncode == 0, f"--dry-run rc={r.returncode}: {combined[-400:]}"
        assert "不写文件" in combined  # 烟测日志口径
        assert _snapshot_files(ddir, r".*\.json") == before, "dry-run 不得写 history_daily"

    def test_dry_run_lhb_no_write(self):
        """实跑 --dry-run: rc=0 + data/akshare get_lhb_detail 文件集前后不变 (缺口枚举不拉取)"""
        adir = ROOT / "data" / "akshare"
        before = _snapshot_files(adir, r"get_lhb_detail_\d{8}\.json")
        r = _run_cli(LHB_SCRIPT, "--dry-run")
        combined = r.stdout + r.stderr
        assert r.returncode == 0, f"--dry-run rc={r.returncode}: {combined[-400:]}"
        assert "缺失交易日" in combined and "不拉取不写文件" in combined
        assert _snapshot_files(adir, r"get_lhb_detail_\d{8}\.json") == before, "dry-run 不得写 lhb 文件"


# ============================================================================
# 3. auto_tdx_refresh: 新鲜度判定 + mock TDX 刷新 + main() 路径
# ============================================================================

class TestFreshness:
    def _seed(self, atr, tmp_path, code, days_ago):
        recs = _records(n_days=3, latest=date.today() - timedelta(days=days_ago))
        (tmp_path / f"{code}.json").write_text(
            json.dumps([{"date": r["date"].strftime("%Y-%m-%d"), "open": r["open"],
                         "high": r["high"], "low": r["low"], "close": r["close"],
                         "amount": r["amount"], "volume": r["volume"]} for r in recs]),
            encoding="utf-8")

    def test_fresh_and_stale_split(self, atr, tmp_path, monkeypatch):
        monkeypatch.setattr(atr, "DATA_DIR", tmp_path)
        self._seed(atr, tmp_path, "sh600519", days_ago=0)   # 新鲜 (lag=0 ≤ 3)
        self._seed(atr, tmp_path, "sz000858", days_ago=10)  # 滞后 (10 > 3)
        issues = atr.check_data_freshness(stocks=["sh600519", "sz000858"])
        assert len(issues) == 1
        assert "sz000858" in issues[0] and "滞后" in issues[0]
        assert not any("sh600519" in i for i in issues)

    def test_lag_boundary_3_vs_4(self, atr, tmp_path, monkeypatch):
        """滞后3天=新鲜 (仅 >3 判需刷新), 4天=滞后 — 边界不漂移"""
        monkeypatch.setattr(atr, "DATA_DIR", tmp_path)
        self._seed(atr, tmp_path, "sh600000", days_ago=3)
        assert atr.check_data_freshness(stocks=["sh600000"]) == []
        self._seed(atr, tmp_path, "sh600000", days_ago=4)
        issues = atr.check_data_freshness(stocks=["sh600000"])
        assert len(issues) == 1 and "滞后" in issues[0]

    def test_missing_empty_corrupt(self, atr, tmp_path, monkeypatch):
        monkeypatch.setattr(atr, "DATA_DIR", tmp_path)
        (tmp_path / "sz000001.json").write_text("[]", encoding="utf-8")           # 空数据
        (tmp_path / "sh601318.json").write_text("{broken", encoding="utf-8")      # 损坏
        issues = atr.check_data_freshness(stocks=["sz000001", "sh601318", "sh600036"])
        assert len(issues) == 3
        joined = " | ".join(issues)
        assert "空数据" in joined and "解析错误" in joined and "文件缺失" in joined

    def test_new_holding_followed(self, atr, tmp_path, monkeypatch):
        """M-7 数据缺口修复验证: 持仓轮入新码 → 新鲜度检查覆盖该码 (文件缺失可检出)"""
        monkeypatch.setattr(atr, "DATA_DIR", tmp_path)
        _write_holdings(tmp_path / "holdings.json", [{"symbol": "sz000002"}])
        monkeypatch.setattr(atr, "HOLDINGS_FILE", tmp_path / "holdings.json")
        stocks = atr.resolve_core_stocks()
        assert "sz000002" in stocks and "sh603727" not in stocks
        issues = atr.check_data_freshness(stocks)
        assert any("sz000002" in i and "文件缺失" in i for i in issues)


class TestRefreshWithMockedTdx:
    def test_refresh_writes_schema(self, atr, tmp_path, monkeypatch):
        """mock TDX 解析注入 → 刷新落盘 schema: 键齐全/date字符串/数值类型/升序"""
        monkeypatch.setattr(atr, "DATA_DIR", tmp_path)
        monkeypatch.setattr(atr, "get_tdx_data", lambda code, days=150: _records(n_days=5))
        assert atr.refresh_stock_data("sh600519") is True
        data = json.loads((tmp_path / "sh600519.json").read_text(encoding="utf-8"))
        assert len(data) == 5
        dates = [r["date"] for r in data]
        assert dates == sorted(dates), "必须升序 (旧惯例 2026-10-15 归一化)"
        for r in data:
            assert set(r.keys()) == {"date", "open", "high", "low", "close", "amount", "volume"}
            assert isinstance(r["date"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"])
            assert isinstance(r["amount"], int) and isinstance(r["volume"], int)
            assert isinstance(r["open"], float) and isinstance(r["close"], float)

    def test_refresh_tdx_missing_warns_false(self, atr, tmp_path, monkeypatch, caplog):
        """TDX 文件缺失 (get_tdx_data 返回 None) → 不写文件, 返回 False, WARN 非静默"""
        monkeypatch.setattr(atr, "DATA_DIR", tmp_path)
        monkeypatch.setattr(atr, "get_tdx_data", lambda code, days=150: None)
        with caplog.at_level(logging.WARNING, logger="auto_tdx_refresh"):
            assert atr.refresh_stock_data("sh600519") is False
        assert not (tmp_path / "sh600519.json").exists()
        assert any("缺失或无有效记录" in m for m in caplog.messages), "TDX缺失必须WARN响铃"

    def test_refresh_read_error_false(self, atr, tmp_path, monkeypatch):
        """TDX 读取抛 OSError → 捕获为显式异常 (禁裸except), 返回 False"""
        monkeypatch.setattr(atr, "DATA_DIR", tmp_path)

        def boom(code, days=150):
            raise OSError("模拟TDX读取失败")

        monkeypatch.setattr(atr, "get_tdx_data", boom)
        assert atr.refresh_stock_data("sh600519") is False
        assert not (tmp_path / "sh600519.json").exists()


class TestMainPaths:
    def _setup(self, atr, monkeypatch, tmp_path, holdings, tdx_fake):
        ddir = tmp_path / "data"
        ddir.mkdir()
        monkeypatch.setattr(atr, "DATA_DIR", ddir)
        hpath = tmp_path / "holdings.json"
        _write_holdings(hpath, holdings)
        monkeypatch.setattr(atr, "HOLDINGS_FILE", hpath)
        monkeypatch.setattr(atr, "get_tdx_data", tdx_fake)
        return ddir

    def test_dry_run_no_tdx_no_write(self, atr, monkeypatch, tmp_path):
        """--dry-run: 不调 TDX 读取 + 不写任何 json (schema 侧证)"""
        calls = []

        def sentinel(code, days=150):
            calls.append(code)
            raise AssertionError("--dry-run 不得触碰 TDX 读取")

        ddir = self._setup(atr, monkeypatch, tmp_path, [], sentinel)
        rc = atr.main(["--dry-run"])
        assert rc == 0 and calls == []
        assert list(ddir.glob("*.json")) == [], "dry-run 不得写文件"

    def test_force_partial_success_rc0(self, atr, monkeypatch, tmp_path):
        """--force 部分成功 (3固定+持仓sh600030刷新, 3只TDX无数据) → rc=0, 成功者落盘, 失败者无文件"""
        called = []

        def fake(code, days=150):
            called.append(code)
            return _records(n_days=3) if code in ("sh600519", "sh600000", "sz000858", "sh600030") else None

        ddir = self._setup(atr, monkeypatch, tmp_path,
                           [{"symbol": "sh600030"}], fake)  # 持仓轮入 sh600030 → 有效列表7只
        rc = atr.main(["--force"])
        assert rc == 0
        assert sorted(called) == sorted(atr.CORE_STOCKS_FIXED + ["sh600030"])
        for ok in ("sh600519", "sh600000", "sz000858", "sh600030"):
            assert (ddir / f"{ok}.json").exists(), f"{ok} 刷新成功者必须落盘"
        for bad in ("sh601318", "sz000001", "sh600036"):
            assert not (ddir / f"{bad}.json").exists(), f"{bad} TDX无数据不得写文件"

    def test_force_all_fail_rc1(self, atr, monkeypatch, tmp_path, caplog):
        """--force 全败 (TDX 全无数据) → 复检仍滞后 + success=0 → rc=1 (loud, 非静默)"""
        ddir = self._setup(atr, monkeypatch, tmp_path, [], lambda code, days=150: None)
        with caplog.at_level(logging.WARNING, logger="auto_tdx_refresh"):
            rc = atr.main(["--force"])
        assert rc == 1
        assert any("刷新未生效" in m for m in caplog.messages)
        assert list(ddir.glob("*.json")) == []

    def test_fresh_no_force_no_refresh(self, atr, monkeypatch, tmp_path):
        """数据新鲜 + 非 force → 不刷新直接 rc=0 (TDX 零调用)"""
        ddir = self._setup(atr, monkeypatch, tmp_path, [], lambda code, days=150: _records(3))
        # 预置全量新鲜文件 (today 结尾)
        for c in atr.CORE_STOCKS_FIXED:
            (ddir / f"{c}.json").write_text(json.dumps([{"date": date.today().isoformat(),
                                                         "open": 1.0, "high": 1.0, "low": 1.0,
                                                         "close": 1.0, "amount": 1, "volume": 1}]),
                                            encoding="utf-8")
        calls = []
        monkeypatch.setattr(atr, "get_tdx_data",
                            lambda code, days=150: calls.append(code) or _records(3))
        assert atr.main([]) == 0
        assert calls == [], "数据新鲜且非--force 不得触发刷新"


# ============================================================================
# 4. M-7: 数据化 CORE_STOCKS 逻辑单测
# ============================================================================

class TestM7CoreStocksResolution:
    def test_union_holding_new_code(self, atr, tmp_path, monkeypatch):
        """持仓码 union 固定核心: 新持仓追加在6只固定之后 (确定性顺序), 去重"""
        h = tmp_path / "holdings.json"
        _write_holdings(h, [{"symbol": "sh600030"}, {"code": "sz000002"},
                            {"symbol": "sh600519"}, {"symbol": None}])
        monkeypatch.setattr(atr, "HOLDINGS_FILE", h)
        assert atr.resolve_core_stocks() == atr.CORE_STOCKS_FIXED + ["sh600030", "sz000002"]
        # sh600519 与固定列表重复 → 去重; symbol=None → 跳过

    def test_equivalent_to_legacy_hardcode_when_holding_sh603727(self, atr, tmp_path, monkeypatch):
        """验收③ 代码侧: 现持仓含 sh603727 → 有效列表与原7只硬编码完全等价 (成员+顺序)"""
        h = tmp_path / "holdings.json"
        _write_holdings(h, [{"symbol": "sh603727", "code": "sh603727"}])
        monkeypatch.setattr(atr, "HOLDINGS_FILE", h)
        assert atr.resolve_core_stocks() == LEGACY_CORE7

    def test_rotation_follows(self, atr, tmp_path, monkeypatch):
        """持仓轮出: sh603727 不在持仓 → 有效列表不再含它, 新持仓入列 (数据缺口修复)"""
        h = tmp_path / "holdings.json"
        _write_holdings(h, [{"symbol": "sh600030"}])
        monkeypatch.setattr(atr, "HOLDINGS_FILE", h)
        out = atr.resolve_core_stocks()
        assert "sh603727" not in out and "sh600030" in out and len(out) == 7

    def test_empty_holdings_only_fixed_core(self, atr, tmp_path, monkeypatch):
        """空持仓 (清仓期) → 仅固定6只, 不 fallback 不 WARN"""
        h = tmp_path / "holdings.json"
        _write_holdings(h, [])
        monkeypatch.setattr(atr, "HOLDINGS_FILE", h)
        assert atr.resolve_core_stocks() == atr.CORE_STOCKS_FIXED

    def test_missing_file_fallback_warn_not_silent(self, atr, tmp_path, monkeypatch, caplog):
        """holdings.json 缺失 → fallback 原7只硬编码 + WARN 响铃 (禁静默吞)"""
        monkeypatch.setattr(atr, "HOLDINGS_FILE", tmp_path / "no_such.json")
        with caplog.at_level(logging.WARNING, logger="auto_tdx_refresh"):
            out = atr.resolve_core_stocks()
        assert out == LEGACY_CORE7
        assert any("fallback" in m for m in caplog.messages), "fallback 必须 WARN, 不得静默"

    def test_corrupt_json_fallback_warn_not_silent(self, atr, tmp_path, monkeypatch, caplog):
        """holdings.json 损坏 (非JSON) → 同缺失: fallback 原7只 + WARN"""
        h = tmp_path / "holdings.json"
        h.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(atr, "HOLDINGS_FILE", h)
        with caplog.at_level(logging.WARNING, logger="auto_tdx_refresh"):
            out = atr.resolve_core_stocks()
        assert out == LEGACY_CORE7
        assert any("fallback" in m for m in caplog.messages)

    def test_weird_structure_no_crash(self, atr, tmp_path, monkeypatch, caplog):
        """结构异常: holdings非列表=损坏 → fallback原7只+WARN (禁静默收窄为6只); 非dict条目跳过, 裸字符串码容忍"""
        h = tmp_path / "holdings.json"
        h.write_text(json.dumps({"holdings": "oops"}), encoding="utf-8")
        monkeypatch.setattr(atr, "HOLDINGS_FILE", h)
        with caplog.at_level(logging.WARNING, logger="auto_tdx_refresh"):
            assert atr.resolve_core_stocks() == atr.CORE_STOCKS_FALLBACK
        assert any("fallback" in m for m in caplog.messages)
        h.write_text(json.dumps({"holdings": ["sh600030", 42, None]}), encoding="utf-8")
        out = atr.resolve_core_stocks()
        assert out == atr.CORE_STOCKS_FIXED + ["sh600030"]  # 非str条目跳过


# ============================================================================
# 5. lhb_backfill: 缺口检测 + 拉取路径 (全 mock 不联网)
# ============================================================================

class _FixedDate(date):
    """固定 today=2026-10-24 (周六): 缺口枚举区间 10-19(一)..10-23(五) 5个交易日, 测试确定性"""
    @classmethod
    def today(cls):
        return cls(2026, 10, 24)


class FakeDF:
    """假 DataFrame: to_json(orient, force_ascii) → 纯 Python 行列表 JSON (mock akshare 返回)"""

    def __init__(self, rows):
        self._rows = rows

    def __len__(self):
        return len(self._rows)

    def to_json(self, orient=None, force_ascii=None):
        return json.dumps(self._rows, ensure_ascii=not (force_ascii in (False, None)))


class StubAK:
    """akshare stub: stock_lhb_detail_em(start_date, end_date) 按日返回预设"""

    def __init__(self, by_day):
        self.by_day = by_day
        self.calls = []

    def stock_lhb_detail_em(self, start_date, end_date):
        self.calls.append((start_date, end_date))
        return self.by_day.get(start_date)


class TestLhbGapDetection:
    def _env(self, lhb, monkeypatch, tmp_path, existing=()):
        adir = tmp_path / "akshare"
        adir.mkdir()
        for ys in existing:
            (adir / f"get_lhb_detail_{ys}.json").write_text('{"data": []}', encoding="utf-8")
        logf = tmp_path / "lhb.log"
        monkeypatch.setattr(lhb, "AKSHARE_DIR", str(adir))
        monkeypatch.setattr(lhb, "LOG_FILE", str(logf))
        monkeypatch.setattr(lhb, "START_DATE", _FixedDate(2026, 10, 19))
        monkeypatch.setattr(lhb, "date", _FixedDate)
        return adir, logf

    def test_dry_run_enumerates_missing_weekdays(self, lhb, monkeypatch, tmp_path):
        """缺口检测: 已有 10-19/20/22 → 缺 [20261021, 20261023] (10-24为周六不计); rc=0 不拉取不写"""
        adir, logf = self._env(lhb, monkeypatch, tmp_path,
                               existing=("20261019", "20261020", "20261022"))
        calls = []
        monkeypatch.setattr(lhb, "try_pull",
                            lambda day: calls.append(day) or None)
        rc = lhb.main(["--dry-run", "--start", "20261019"])
        assert rc == 0 and calls == [], "dry-run 不得调用拉取"
        assert [p.name for p in adir.glob("get_lhb_detail_*.json")] == \
               [f"get_lhb_detail_{ys}.json" for ys in ("20261019", "20261020", "20261022")]
        text = logf.read_text(encoding="utf-8")
        assert "'20261021'" in text and "'20261023'" in text
        assert "缺失交易日: 2 个" in text and "不拉取不写文件" in text

    def test_dry_run_limit_truncates(self, lhb, monkeypatch, tmp_path):
        adir, logf = self._env(lhb, monkeypatch, tmp_path,
                               existing=("20261019", "20261020", "20261022"))
        monkeypatch.setattr(lhb, "try_pull", lambda day: (_ for _ in ()).throw(AssertionError()))
        rc = lhb.main(["--dry-run", "--start", "20261019", "--limit", "1"])
        assert rc == 0
        assert "缺失交易日: 1 个" in logf.read_text(encoding="utf-8")

    def test_dry_run_all_present_zero_missing(self, lhb, monkeypatch, tmp_path):
        """反例: 缺口=0 (5个交易日全在) → rc=0 且 0 个"""
        adir, logf = self._env(lhb, monkeypatch, tmp_path,
                               existing=("20261019", "20261020", "20261021", "20261022", "20261023"))
        rc = lhb.main(["--dry-run", "--start", "20261019"])
        assert rc == 0
        assert "缺失交易日: 0 个" in logf.read_text(encoding="utf-8")

    def test_existing_lhb_days_pattern(self, lhb, monkeypatch, tmp_path):
        """existing_lhb_days: 仅 get_lhb_detail_YYYYMMDD.json (8位数字) 计数, 干扰项不认"""
        adir, _ = self._env(lhb, monkeypatch, tmp_path)
        for name in ("get_lhb_detail_20260501.json", "get_lhb_detail_20260502.json",  # 真文件
                     "get_lhb_detail_2026501.json",          # 7位 → 不认
                     "get_lhb_detail_20260502.json.hmac",     # .hmac 侧文件 → 不认
                     "backup_20261015.json", "lhb_backfill.log"):
            (adir / name).write_text("{}", encoding="utf-8")
        assert lhb.existing_lhb_days() == {"20260501", "20260502"}

    def test_bad_start_format_rc2_loud(self, lhb, monkeypatch, tmp_path, capsys):
        adir, _ = self._env(lhb, monkeypatch, tmp_path)
        rc = lhb.main(["--dry-run", "--start", "2026-10-19"])
        assert rc == 2
        assert "格式应为 YYYYMMDD" in capsys.readouterr().err


class TestLhbPullAllMocked:
    def _env(self, lhb, monkeypatch, tmp_path, by_day, existing=(), sleep_noop=True):
        adir, logf = self._env_pull_base(lhb, monkeypatch, tmp_path, existing)
        stub = StubAK(by_day)
        monkeypatch.setattr(lhb, "ak", stub)
        if sleep_noop:
            monkeypatch.setattr(lhb.time, "sleep", lambda s: None)
        proj = tmp_path / "proj"
        proj.mkdir()
        monkeypatch.setattr(lhb, "PROJECT", str(proj))
        return adir, logf, stub, proj

    @staticmethod
    def _env_pull_base(lhb, monkeypatch, tmp_path, existing=()):
        adir = tmp_path / "akshare"
        adir.mkdir()
        for ys in existing:
            (adir / f"get_lhb_detail_{ys}.json").write_text('{"data": []}', encoding="utf-8")
        monkeypatch.setattr(lhb, "AKSHARE_DIR", str(adir))
        monkeypatch.setattr(lhb, "LOG_FILE", str(tmp_path / "lhb.log"))
        monkeypatch.setattr(lhb, "START_DATE", _FixedDate(2026, 10, 19))
        monkeypatch.setattr(lhb, "date", _FixedDate)
        return adir, tmp_path / "lhb.log"

    def test_pull_success_writes_payload_hmac_report(self, lhb, monkeypatch, tmp_path):
        """成功路径: payload schema {"data":[rows]} + .hmac + 报告; 已有19/20 → 缺[21,22,23], --limit 2 截断生效"""
        rows = [{"code": "sh600519", "name": "贵州茅台", "close": 10.5}]
        adir, logf, stub, proj = self._env(lhb, monkeypatch, tmp_path,
                                            {"20261021": FakeDF(rows), "20261022": FakeDF(rows)},
                                            existing=("20261019", "20261020"))
        rc = lhb.main(["--start", "20261019", "--limit", "2"])
        assert rc == 0
        assert [c[0] for c in stub.calls] == ["20261021", "20261022"]
        p = json.loads((adir / "get_lhb_detail_20261021.json").read_text(encoding="utf-8"))
        assert p == {"data": rows}
        hmac_sig = (adir / "get_lhb_detail_20261021.json.hmac").read_text(encoding="utf-8")
        assert re.fullmatch(r"[0-9a-f]{64}", hmac_sig)
        rep = json.loads((proj / ".scratch" / "lhb_backfill_report.json").read_text(encoding="utf-8"))
        assert rep["ok_days"] == ["20261021", "20261022"] and rep["err_count"] == 0
        assert rep["ok_count"] == 2 and rep["task"] == "lhb_backfill"

    def test_pull_no_data_rc0_no_write(self, lhb, monkeypatch, tmp_path):
        """无数据 (节假日/接口空) → rc=0 (归档版口径: 部分失败非脚本bug), 不写 json, 记 err_days;
        已有19/20/23 → 缺[21,22]: 21无数据(不写), 22成功(写)"""
        adir, logf, stub, proj = self._env(lhb, monkeypatch, tmp_path,
                                            {"20261021": None, "20261022": FakeDF([{"x": 1}])},
                                            existing=("20261019", "20261020", "20261023"))
        rc = lhb.main(["--start", "20261019"])
        assert rc == 0
        assert not (adir / "get_lhb_detail_20261021.json").exists()
        assert (adir / "get_lhb_detail_20261022.json").exists()
        rep = json.loads((proj / ".scratch" / "lhb_backfill_report.json").read_text(encoding="utf-8"))
        assert rep["err_days"] == ["20261021"] and rep["ok_days"] == ["20261022"]
        assert "无数据" in logf.read_text(encoding="utf-8")

    def test_pull_exception_rc0_no_write(self, lhb, monkeypatch, tmp_path):
        """接口异常 (拉取抛错) → try_pull 捕获响铃返回 None → rc=0 不写文件 (异常路径同无数据)"""
        class BoomAK:
            def stock_lhb_detail_em(self, start_date, end_date):
                raise ConnectionError("模拟东财接口不可达")
        monkeypatch.setattr(lhb.time, "sleep", lambda s: None)
        adir, logf = self._env_pull_base(lhb, monkeypatch, tmp_path)
        monkeypatch.setattr(lhb, "ak", BoomAK())
        proj = tmp_path / "proj"
        proj.mkdir()
        monkeypatch.setattr(lhb, "PROJECT", str(proj))
        rc = lhb.main(["--start", "20261023"])  # 仅 10-23 一个工作日
        assert rc == 0
        assert list(adir.glob("get_lhb_detail_*.json")) == []
        assert "拉取异常" in logf.read_text(encoding="utf-8")
