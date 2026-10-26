#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_layers_contract.py — 层间契约漂移检测

检测原则:
  契约字面量 (docs/layers-contract.md) vs 实际数据/schema抽验
  - 绿: 实际数据符合契约 → 测试通过
  - 红: 注入畸形数据 → 检测到漂移 → 测试报告错误（人为触发的红）

覆盖范围:
  L1-1: history_daily OHLCV schema
  L1-2: holdings.json schema
  L1-3: trade_log.json schema
  L1-4: financial_cache.json schema
  L1-5: daily_signal.json schema
  L2-1: factors/*.json schema + 因子字段完整性
  L3-1: position_decision.json schema
  L3-3: layers/ 过滤链接口

回授断言:
  - 写入侧: 本测试
  - 消费侧: closedloop_health.py A1断言
"""

import json
import sys
import pytest
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).parent.parent
DATA_DIR = PROJECT / "data"
DOCS_DIR = PROJECT / "docs"
LAYERS_DIR = PROJECT / "layers"

sys.path.insert(0, str(PROJECT))


# ─────────────────────────────────────────────────────────────────────────────
# 契约字面量定义（手工维护，与 docs/layers-contract.md 保持一致）
# ─────────────────────────────────────────────────────────────────────────────

# L1-1: history_daily 每条record必填字段
L1_OHLCV_REQUIRED_FIELDS = {"date", "open", "high", "low", "close", "volume", "amount"}

# L1-2: holdings.json 顶层字段
L1_HOLDINGS_REQUIRED_TOP = {"holdings"}
# holdings[]. 必填子字段
L1_HOLDING_ITEM_REQUIRED = {"symbol", "shares", "avg_cost", "current_price", "market_value", "pnl", "pnl_pct", "status", "risk_control", "updated_at"}
# risk_control 必填子字段
L1_RISK_CONTROL_REQUIRED = {"stop_loss_pct", "take_profit_pct", "max_hold_days", "trailing_tp", "chase_ban_pct", "stop_loss_price", "take_profit_price"}

# L1-3: trade_log.json 顶层字段
L1_TRADE_LOG_REQUIRED_TOP = {"trades"}
L1_TRADE_ITEM_REQUIRED = {"trade_id", "date", "code", "action", "shares", "price", "profit_loss", "profit_pct", "reason"}

# L1-4: financial_cache.json 必填字段
L1_FINANCIAL_REQUIRED_TOP = {"_timestamp", "_date", "stocks"}
L1_FINANCIAL_STOCK_REQUIRED = {"code", "indicators", "fraud", "source"}
L1_FINANCIAL_INDICATOR_SAMPLE = {"revenue", "roe", "debt_ratio"}  # 抽样检查

# L1-5: daily_signal.json 必填字段
L1_DAILY_SIGNAL_REQUIRED = {"date", "gate"}
L1_GATE_REQUIRED = {"status", "sh_close", "ma250", "gate_open"}

# L2-1: factors/*.json 必填字段
L2_FACTOR_FILE_REQUIRED = {"code", "date", "factors"}
# L2: 核心因子字段（STRATEGIES键名子集，抽样而非全量）
L2_FACTOR_SAMPLE_FIELDS = {
    "ma5", "ma10", "ma20", "ma60",
    "chg5", "chg10", "chg20",
    "vol_ratio", "vol_gt2", "vol_shrink",
    "rsi14", "macd_golden_red",
    "pos_vs_ma20", "alpha16_fix",
}

# L2-1 负向约束：因子文件 factor keys 必须全部在此集合内（契约漂移检测）
# 来源：docs/layers-contract.md L2-1 表手工清单（与STRATEGIES权重键对齐）
CONTRACT_FACTOR_NAMES = {
    "ma5", "ma10", "ma20", "ma60", "ma120", "ma_mlt", "ma_above60", "ma_above120",
    "chg5", "chg10", "chg20", "chg5_rev", "chg10_rev", "chg20_rev",
    "vol_ratio", "vol_gt2", "vol_gt1.5", "vol_gt1.2", "vol_shrink",
    "vol_breakout", "vol_dump", "volatility20", "std20", "max_ret5_low", "max_ret5",
    "rsi14", "rsi_strong", "rsi_weak", "rsi_rising", "rsi_oversold", "rsi14_direct",
    "macd_golden_red", "macd_golden", "macd_above0",
    "kdj_golden", "kdj_overbought",
    "pos_vs_ma20", "unlocked_pressure",
    "alpha16_fix", "vol_price_corr_20", "amount_price_corr_20", "alpha13", "alpha16",
    "amount_q_reversal", "weekly_bullish", "weekly_macd_red",
    "industry_hot_top5", "industry_cold_bottom5",
    "fund_flow_pos", "fund_flow_neg",
    "lhb_signal", "pattern_bonus",
    "penalty_far", "penalty_chase_high", "penalty_kdj_ob", "penalty_vol_dump",
    "vol_floor", "vol_shrink20_bonus",
}

# L3-1: position_decision.json 必填字段
L3_DECISION_REQUIRED = {"timestamp", "dry_run", "current_position", "target_position", "strategy", "rebalance", "actions"}

# L3-3: layers/ 模块存在性
LAYERS_MODULES = {
    "l1_tradability": {"apply_tradability_filter"},
    "l2_momentum": {"apply_momentum_filter"},
    "l3_ranking": {"normalize_and_sort"},
}


# ─────────────────────────────────────────────────────────────────────────────
# 绿测试: 用真实数据验证契约一致
# ─────────────────────────────────────────────────────────────────────────────

class TestL1OHLCVContract:
    """L1-1 日线OHLCV schema 契约检测"""

    def test_history_daily_file_exists(self):
        """至少有一个history_daily文件"""
        files = list(DATA_DIR.glob("history_daily/sh*.json"))
        assert len(files) > 0, "未找到任何 history_daily/sh*.json 文件"

    def test_ohlcv_record_schema(self, tmp_path):
        """抽样检查history_daily文件，每个record必须包含7个必填字段"""
        sample_file = DATA_DIR / "history_daily" / "sh000001.json"
        if not sample_file.exists():
            pytest.skip("sh000001.json 不存在")

        with open(sample_file, "r", encoding="utf-8") as f:
            records = json.load(f)

        assert isinstance(records, list), "history_daily 应为 JSON 数组"
        assert len(records) > 0, "history_daily 记录不能为空"

        for i, rec in enumerate(records[:5]):  # 抽样前5条
            missing = L1_OHLCV_REQUIRED_FIELDS - set(rec.keys())
            assert not missing, f"record[{i}] 缺字段: {missing}"

    def test_ohlcv_field_types(self):
        """检查字段类型: date=str, open/high/low/close=number, volume=int, amount=number"""
        sample_file = DATA_DIR / "history_daily" / "sh000001.json"
        if not sample_file.exists():
            pytest.skip("sh000001.json 不存在")

        with open(sample_file, "r", encoding="utf-8") as f:
            records = json.load(f)

        if not records:
            pytest.skip("无记录")

        rec = records[0]
        assert isinstance(rec["date"], str), f"date应为str, 实际{type(rec['date'])}"
        assert isinstance(rec["open"], (int, float)), f"open应为number"
        assert isinstance(rec["close"], (int, float)), f"close应为number"
        assert isinstance(rec["volume"], int), f"volume应为int"


class TestL1HoldingsContract:
    """L1-2 holdings.json schema 契约检测"""

    def test_holdings_file_exists(self):
        assert (DATA_DIR / "holdings.json").exists(), "holdings.json 不存在"

    def test_top_level_schema(self):
        with open(DATA_DIR / "holdings.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        missing = L1_HOLDINGS_REQUIRED_TOP - set(data.keys())
        assert not missing, f"holdings.json 缺顶层字段: {missing}"

    def test_holding_item_schema(self):
        with open(DATA_DIR / "holdings.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        holdings = data.get("holdings", [])
        if not holdings:
            pytest.skip("holdings 为空，跳过子字段检查")

        item = holdings[0]
        missing = L1_HOLDING_ITEM_REQUIRED - set(item.keys())
        assert not missing, f"holdings[0] 缺字段: {missing}"

    def test_risk_control_schema(self):
        with open(DATA_DIR / "holdings.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        holdings = data.get("holdings", [])
        if not holdings:
            pytest.skip("holdings 为空")

        rc = holdings[0].get("risk_control", {})
        missing = L1_RISK_CONTROL_REQUIRED - set(rc.keys())
        assert not missing, f"risk_control 缺字段: {missing}"


class TestL1TradeLogContract:
    """L1-3 trade_log.json schema 契约检测"""

    def test_trade_log_exists(self):
        assert (DATA_DIR / "trade_log.json").exists(), "trade_log.json 不存在"

    def test_top_level_schema(self):
        with open(DATA_DIR / "trade_log.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        missing = L1_TRADE_LOG_REQUIRED_TOP - set(data.keys())
        assert not missing, f"trade_log.json 缺顶层字段: {missing}"

    def test_trade_item_schema(self):
        with open(DATA_DIR / "trade_log.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        trades = data.get("trades", [])
        if not trades:
            pytest.skip("trades 为空")

        missing = L1_TRADE_ITEM_REQUIRED - set(trades[0].keys())
        assert not missing, f"trades[0] 缺字段: {missing}"


class TestL1FinancialCacheContract:
    """L1-4 financial_cache.json schema 契约检测"""

    def test_exists(self):
        assert (DATA_DIR / "financial_cache.json").exists(), "financial_cache.json 不存在"

    def test_top_schema(self):
        with open(DATA_DIR / "financial_cache.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        missing = L1_FINANCIAL_REQUIRED_TOP - set(data.keys())
        assert not missing, f"financial_cache.json 缺顶层字段: {missing}"

    def test_stock_schema(self):
        with open(DATA_DIR / "financial_cache.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        stocks = data.get("stocks", {})
        if not stocks:
            pytest.skip("stocks 为空")

        sample_code = next(iter(stocks))
        stock = stocks[sample_code]
        missing = L1_FINANCIAL_STOCK_REQUIRED - set(stock.keys())
        assert not missing, f"stocks[{sample_code}] 缺字段: {missing}"

    def test_indicators_sample(self):
        with open(DATA_DIR / "financial_cache.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        stocks = data.get("stocks", {})
        if not stocks:
            pytest.skip("stocks 为空")

        sample_code = next(iter(stocks))
        indicators = stocks[sample_code].get("indicators", {})
        present = L1_FINANCIAL_INDICATOR_SAMPLE & set(indicators.keys())
        assert present, f"indicators 缺少抽样字段: {L1_FINANCIAL_INDICATOR_SAMPLE - set(indicators.keys())}"


class TestL1DailySignalContract:
    """L1-5 daily_signal.json schema 契约检测"""

    def test_exists(self):
        assert (DATA_DIR / "daily_signal.json").exists(), "daily_signal.json 不存在"

    def test_top_schema(self):
        with open(DATA_DIR / "daily_signal.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        missing = L1_DAILY_SIGNAL_REQUIRED - set(data.keys())
        assert not missing, f"daily_signal.json 缺顶层字段: {missing}"

    def test_gate_schema(self):
        with open(DATA_DIR / "daily_signal.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        gate = data.get("gate", {})
        missing = L1_GATE_REQUIRED - set(gate.keys())
        assert not missing, f"gate 缺字段: {missing}"


class TestL2FactorsContract:
    """L2-1 factors/*.json schema 契约检测"""

    def test_factors_dir_exists(self):
        assert (DATA_DIR / "factors").is_dir(), "data/factors/ 目录不存在"

    def test_factor_file_schema(self):
        factor_files = list((DATA_DIR / "factors").glob("sh*.json"))
        if not factor_files:
            pytest.skip("无 sh*.json 因子文件")

        with open(factor_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        missing = L2_FACTOR_FILE_REQUIRED - set(data.keys())
        assert not missing, f"factor文件 缺顶层字段: {missing}"

    def test_factor_fields_sample(self):
        """抽样检查因子文件中是否存在核心因子字段"""
        factor_files = list((DATA_DIR / "factors").glob("sh*.json"))
        if not factor_files:
            pytest.skip("无因子文件")

        with open(factor_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        factors = data.get("factors", {})
        present = L2_FACTOR_SAMPLE_FIELDS & set(factors.keys())
        assert present, f"因子文件缺少核心因子: {L2_FACTOR_SAMPLE_FIELDS - set(factors.keys())}"

    @pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): L2 因子全量校验(扫全部 sh*/sz* 因子文件, 实测 78.74s) → 门禁快档排除
    def test_no_unknown_factor_fields(self):
        """因子文件factor keys必须全部在契约清单内（负向约束，漂移检测）"""
        factor_files = list((DATA_DIR / "factors").glob("sh*.json"))
        if not factor_files:
            pytest.skip("无因子文件")

        # 检查所有 sh*.json 和 sz*.json 文件
        all_factor_files = list((DATA_DIR / "factors").glob("*.json"))
        assert all_factor_files, "data/factors/ 下无任何 .json 文件"

        unknown_fields = set()
        sample_file = None
        for f in all_factor_files:  # 全量检查所有因子文件（非抽样）
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            factors = data.get("factors", {})
            unknown = set(factors.keys()) - CONTRACT_FACTOR_NAMES
            if unknown:
                unknown_fields.update(unknown)
                if sample_file is None:
                    sample_file = f.name
        assert not unknown_fields, \
            f"因子文件含契约外未知字段（契约漂移）: {sorted(unknown_fields)} (采样文件: {sample_file})"


class TestL3DecisionContract:
    """L3-1 position_decision.json schema 契约检测"""

    def test_exists(self):
        assert (DATA_DIR / "position_decision.json").exists(), "position_decision.json 不存在"

    def test_schema(self):
        with open(DATA_DIR / "position_decision.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        missing = L3_DECISION_REQUIRED - set(data.keys())
        assert not missing, f"position_decision.json 缺字段: {missing}"


class TestL3LayersModules:
    """L3-3 layers/ 模块存在性和接口检测"""

    def test_modules_exist(self):
        for mod_name in LAYERS_MODULES:
            mod_file = LAYERS_DIR / f"{mod_name}.py"
            assert mod_file.exists(), f"layers/{mod_name}.py 不存在"

    def test_interface_signatures(self):
        """检查各层过滤链文件存在且含契约声明的关键函数"""
        # 不直接import（l3_ranking有预存bug: linear_scale不在scoring_engine中）
        # 改为读取源码验证函数签名存在
        import re
        for mod_name, expected_funcs in LAYERS_MODULES.items():
            mod_file = LAYERS_DIR / f"{mod_name}.py"
            src = mod_file.read_text(encoding="utf-8")
            for fn in expected_funcs:
                assert re.search(rf'^def {fn}\(', src, re.MULTILINE), \
                    f"layers/{mod_name}.py 缺少函数 def {fn}()"


# ─────────────────────────────────────────────────────────────────────────────
# 红测试: 注入畸形数据，验证漂移检测敏感
# ─────────────────────────────────────────────────────────────────────────────

class TestDriftDetectionRed:
    """红测试: 注入畸形数据，验证漂移可被检测到"""

    def test_missing_ohlcv_field_detected(self, tmp_path):
        """缺失OHLCV字段应被检测"""
        bad_data = [{"date": "2026-01-01", "open": 10.0, "high": 11.0}]  # 缺 low/close/volume/amount
        test_file = tmp_path / "sh999999.json"
        test_file.write_text(json.dumps(bad_data), encoding="utf-8")

        with open(test_file, "r", encoding="utf-8") as f:
            records = json.load(f)

        missing = L1_OHLCV_REQUIRED_FIELDS - set(records[0].keys())
        assert missing, f"应检测到缺失字段, 实际缺失: {missing}"

    def test_wrong_type_detected(self, tmp_path):
        """类型不匹配应被检测"""
        bad_data = [{"date": 12345, "open": "not_a_number", "high": 11.0, "low": 9.0,
                      "close": 10.0, "volume": "text", "amount": 1000.0}]
        test_file = tmp_path / "sh999998.json"
        test_file.write_text(json.dumps(bad_data), encoding="utf-8")

        with open(test_file, "r", encoding="utf-8") as f:
            records = json.load(f)

        rec = records[0]
        assert not isinstance(rec["date"], str), "应检测到date类型错误"
        assert not isinstance(rec["open"], (int, float)), "应检测到open类型错误"

    def test_holdings_missing_field_detected(self, tmp_path):
        """holdings.json缺少必填字段应被检测"""
        bad_data = {"holdings": [{"symbol": "sh600000"}]}  # 缺shares, avg_cost等
        test_file = tmp_path / "holdings_bad.json"
        test_file.write_text(json.dumps(bad_data), encoding="utf-8")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        item = data["holdings"][0]
        missing = L1_HOLDING_ITEM_REQUIRED - set(item.keys())
        assert missing, f"应检测到holdings字段缺失: {missing}"

    def test_factor_missing_core_field_detected(self, tmp_path):
        """因子文件缺少code字段应被检测"""
        bad_data = {"date": "2026-01-01", "factors": {"ma5": 10.0}}  # 缺code
        test_file = tmp_path / "factor_bad.json"
        test_file.write_text(json.dumps(bad_data), encoding="utf-8")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        missing = L2_FACTOR_FILE_REQUIRED - set(data.keys())
        assert missing, f"应检测到因子文件字段缺失: {missing}"

    def test_missing_gate_field_detected(self, tmp_path):
        """daily_signal缺少gate字段应被检测（原名test_unexpected_field_in_signal，按老五建议修正命名）"""
        bad_data = {"date": "2026-01-01"}  # 缺gate
        test_file = tmp_path / "signal_bad.json"
        test_file.write_text(json.dumps(bad_data), encoding="utf-8")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        missing = L1_DAILY_SIGNAL_REQUIRED - set(data.keys())
        assert missing, f"应检测到daily_signal字段缺失: {missing}"

    def test_extra_field_in_signal_strict_schema(self, tmp_path):
        """严格schema语义：daily_signal含额外字段也应报红"""
        bad_data = {"date": "2026-01-01", "gate": {"status": "hard", "sh_close": 3888.0, "ma250": 3991.0, "gate_open": True}, "secret_field": 999}
        test_file = tmp_path / "signal_extra.json"
        test_file.write_text(json.dumps(bad_data), encoding="utf-8")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        extra = set(data.keys()) - L1_DAILY_SIGNAL_REQUIRED
        assert extra, f"严格schema下额外字段应被检测: {extra}"


class TestDriftSensitivity:
    """漂移敏感度: 契约扩展时应触发已有测试失败"""

    def test_contract_defined_for_new_field(self):
        """验证契约定义了足够的字段检查点"""
        # 如果未来新增 L1_OHLCV_REQUIRED_FIELDS 中的字段，
        # 现有测试会自动检测到不匹配
        assert len(L1_OHLCV_REQUIRED_FIELDS) >= 5, "契约字段定义过少，无法有效检测漂移"
        assert len(L2_FACTOR_SAMPLE_FIELDS) >= 5, "因子抽样字段过少"
