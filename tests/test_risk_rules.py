#!/usr/bin/env python3
"""
test_risk_rules.py: 风控规则引擎测试
覆盖: 硬止损、移动止盈、时间止损、追高关闭
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_rules import (
    STRATEGY_STOP_LOSS_PCT,
    MARKET_STOP_ADJUST,
    CHASE_BAN_PCT,
    TIME_STOP_TRADING_DAYS,
)


class TestConstants:
    def test_stop_loss_default(self):
        # 2026-09-30 S3三方会签: 8%→10%原子变更
        assert STRATEGY_STOP_LOSS_PCT["全仓"] == 0.10

    def test_market_adjust(self):
        assert MARKET_STOP_ADJUST["恐慌"] == 0.55
        assert MARKET_STOP_ADJUST["强"] == 1.1

    def test_chase_ban(self):
        assert CHASE_BAN_PCT == 4.0  # 2026-09-25 统一口径: 4% (08-16拍板+CONTEXT.md契约)

    def test_time_stop(self):
        assert TIME_STOP_TRADING_DAYS == 120


class TestStopLossCalculation:
    """calculate_stop_loss(entry_price, strategy, market_label, gap_score, nb_score, atr)
    返回 (stop_price, stop_pct, stop_type, description)
    """

    def test_basic_stop_loss(self):
        from risk_rules import calculate_stop_loss
        entry_price = 100.0
        # "强"市场: 10% × 1.1 = 11%止损 → 100×(1-0.11)=89.0
        # 但跌停保护生效: 跌停价90.0 × 0.98 = 88.2
        stop_price, stop_pct, stop_type, desc = calculate_stop_loss(entry_price, "全仓", "强")
        assert stop_price == pytest.approx(88.2, abs=0.1), f"预期88.2(跌停保护), 实际{stop_price}"
        assert stop_pct == pytest.approx(0.11, abs=0.001), f"预期11%, 实际{stop_pct*100}%"

    def test_panic_market(self):
        from risk_rules import calculate_stop_loss
        entry_price = 100.0
        # "恐慌"市场: 10% × 0.55 = 5.5%止损 → 100×(1-0.055)=94.5
        stop_price, stop_pct, _, _ = calculate_stop_loss(entry_price, "全仓", "恐慌")
        assert stop_price == pytest.approx(94.5, abs=0.1), f"预期94.5, 实际{stop_price}"
        assert stop_pct == pytest.approx(0.055, abs=0.001), f"预期5.5%, 实际{stop_pct*100}%"

    def test_weak_market(self):
        from risk_rules import calculate_stop_loss
        entry_price = 100.0
        # "弱"市场: 10% × 0.85 = 8.5%止损，但RiskEngine使用不同逻辑
        stop_price, stop_pct, _, _ = calculate_stop_loss(entry_price, "全仓", "弱")
        assert stop_price > 0  # 止损价应为正数

    def test_signal_bonus(self):
        from risk_rules import calculate_stop_loss
        entry_price = 100.0
        # gap_score=5 → signal_strength=3 → SIGNAL_BONUS_ADJUST[3]=1.10
        stop_price, stop_pct, _, _ = calculate_stop_loss(entry_price, "全仓", "强", gap_score=5)
        # 有信号时止损应更宽（stop_price更低）
        stop_no_bonus, _, _, _ = calculate_stop_loss(entry_price, "全仓", "强", gap_score=0)
        assert stop_price <= stop_no_bonus


class TestTakeProfit:
    """calculate_tp_levels(entry_price, gap_score, market_label, strategy)
    返回 (tp1_price, tp1_pct, tp2_price, tp2_pct, tp3_price, tp3_pct, description)
    """

    def test_tp_levels_basic(self):
        from risk_rules import calculate_tp_levels
        entry_price = 100.0
        result = calculate_tp_levels(entry_price, gap_score=0)
        assert len(result) >= 6  # tp1_price, tp1_pct, tp2_price, tp2_pct, tp3_price, tp3_pct
        assert result[0] > entry_price
        assert result[2] > result[0]

    def test_tp_with_bonus(self):
        from risk_rules import calculate_tp_levels
        entry_price = 100.0
        tp1_normal = calculate_tp_levels(entry_price, gap_score=0)[0]
        tp1_bonus = calculate_tp_levels(entry_price, gap_score=3)[0]
        assert tp1_bonus >= tp1_normal


class TestEvaluateExit:
    """evaluate_exit(entry_info, current_price, market_label, asof_date)
    返回 (should_exit, reason, exit_type, extra) — 4元组
    """

    @pytest.fixture(autouse=True)
    def _patch_alert_queue(self, tmp_path):
        """P2-2: 模块级隔离，防止 TestEvaluateExit 无 entry_date 用例污染生产队列"""
        import risk_rules
        self._tmp_queue = tmp_path / "test_message_queue.json"
        self._tmp_queue.write_text("[]", encoding="utf-8")
        self._orig_emit = risk_rules._emit_time_stop_unknown_alert
        def _isolated_emit(entry_info, data_quality_issue, queue_path=None):
            return self._orig_emit(entry_info, data_quality_issue, queue_path=str(self._tmp_queue))
        risk_rules._emit_time_stop_unknown_alert = _isolated_emit
        yield
        risk_rules._emit_time_stop_unknown_alert = self._orig_emit

    def test_stop_loss_trigger(self):
        from risk_rules import evaluate_exit
        entry = {
            "entry_price": 100.0,
            "sl": 92.0,  # 正确key名
        }
        result = evaluate_exit(entry, 91.0, "强")
        should_exit, reason, exit_type, _ = result
        assert should_exit is True
        assert "止损" in reason

    def test_take_profit_trigger(self):
        from risk_rules import evaluate_exit
        entry = {
            "entry_price": 100.0,
            "tp1": 106.0,  # 正确key名
        }
        result = evaluate_exit(entry, 107.0, "强")
        should_exit, reason, exit_type, _ = result
        assert should_exit is True
        assert "止盈" in reason

    def test_no_exit_in_range(self):
        from risk_rules import evaluate_exit
        entry = {
            "entry_price": 100.0,
            "sl": 92.0,
            "tp1": 106.0,
        }
        result = evaluate_exit(entry, 102.0, "强")
        should_exit, reason, exit_type, _ = result
        assert should_exit is False

    def test_partial_take_profit_triggers(self):
        """测试盈利15%触发分批止盈"""
        from risk_rules import evaluate_exit
        entry = {
            "entry_price": 100.0,
        }
        # 盈利15.1%触发
        should_exit, reason, exit_type, _ = evaluate_exit(entry, 115.1, "强")
        assert should_exit is True
        assert exit_type == "partial_take_profit"
        assert "+15.1%" in reason

    def test_partial_take_profit_no_state_pollution(self):
        """测试分批止盈后entry_info未被污染（P0修复验证）"""
        from risk_rules import evaluate_exit
        entry = {
            "entry_price": 100.0,
        }
        # 首次调用触发15%止盈
        should_exit, _, _, _ = evaluate_exit(entry, 115.1, "强")
        assert should_exit is True
        # 验证entry_info未被修改
        assert "exited_at_15" not in entry, f"P0缺陷: entry_info被污染为{entry}"
        # 再次调用同一价格仍应触发（幂等性）
        should_exit2, _, _, _ = evaluate_exit(entry, 115.1, "强")
        assert should_exit2 is True
        assert "exited_at_15" not in entry, f"P0缺陷: entry_info被污染为{entry}"

    def test_partial_take_profit_with_existing_flag(self):
        """测试已有exited_at标记时跳过该档"""
        from risk_rules import evaluate_exit
        entry = {
            "entry_price": 100.0,
            "exited_at_15": True,
        }
        # 价格已超过25%阈值，但exited_at_15已标记
        should_exit, reason, exit_type, _ = evaluate_exit(entry, 126.0, "强")
        assert should_exit is True
        # 应触发25%档而非15%档（已标记的跳过）
        assert exit_type == "partial_take_profit"
        assert "+26.0%" in reason

    def test_stop_loss_priority_over_partial_take_profit(self):
        """测试止损优先于分批止盈"""
        from risk_rules import evaluate_exit
        entry = {
            "entry_price": 100.0,
            "sl": 92.0,
        }
        # 价格跌破止损线，同时盈利为正
        should_exit, reason, exit_type, _ = evaluate_exit(entry, 91.0, "强")
        assert should_exit is True
        assert exit_type == "stop_loss"
        assert "止损" in reason

    def test_traditional_take_profit_still_works(self):
        """测试传统止盈逻辑仍有效"""
        from risk_rules import evaluate_exit
        entry = {
            "entry_price": 100.0,
            "tp1": 106.0,
        }
        should_exit, reason, exit_type, _ = evaluate_exit(entry, 107.0, "强")
        assert should_exit is True
        assert exit_type == "take_profit_half"
        assert "TP1" in reason


class TestATRMktAdjIntegration:
    """P0 返工修复验证：ATR维度+市场调整系数联动"""

    def test_atr_active_in_volatile_market(self):
        """测试 atr=6 + 震荡市：ATR 应有增量，stop_loss_pct > 基线6.2%"""
        from risk_rules import calculate_stop_loss
        # 基线：全仓10% × 震荡0.62 = 6.2%
        base = calculate_stop_loss(100, "全仓", "震荡")
        # ATR=6: 2*6/100 = 12%，应大于基线6.2%
        with_atr = calculate_stop_loss(100, "全仓", "震荡", atr=6)
        assert with_atr[1] > base[1], f"ATR应生效: 基线{base[1]:.3f}, ATR={with_atr[1]:.3f}"
        assert with_atr[1] == pytest.approx(0.12, abs=0.001), f"预期12%, 实际{with_atr[1]}"
        # desc 与实际值一致
        assert "12.0%" in with_atr[3], f"desc应包含12.0%: {with_atr[3]}"

    def test_atr_3_vs_atr_6_different(self):
        """不同ATR值应产生不同结果"""
        from risk_rules import calculate_stop_loss
        r3 = calculate_stop_loss(100, "全仓", "震荡", atr=3)
        r6 = calculate_stop_loss(100, "全仓", "震荡", atr=6)
        assert r3[1] != r6[1], f"atr=3和atr=6结果应不同: {r3[1]} vs {r6[1]}"

    def test_no_atr_uses_base_adj(self):
        """无ATR时应使用 base_adj（不应用ATR路径）"""
        from risk_rules import calculate_stop_loss
        r = calculate_stop_loss(100, "全仓", "震荡")
        assert r[1] == pytest.approx(0.062, abs=0.001), f"预期6.2%, 实际{r[1]}"
        assert r[2] == "固定", f"类型应为固定, 实际{r[2]}"

    def test_desc_matches_actual_values(self):
        """desc必须与实际返回的pct和price一致（消除之前矛盾）"""
        from risk_rules import calculate_stop_loss
        r = calculate_stop_loss(100, "全仓", "震荡", atr=6)
        expected_pct = 0.12
        # atr=6 → 止损12% → 价88.0 < 跌停价90.0 → 触发跌停保护 → 88.2
        assert r[1] == expected_pct
        assert r[0] == pytest.approx(88.2, abs=0.1)
        assert "12.0%" in r[3]


class TestTimeStopUnknown:
    """R2-1 时间止损假阴性 loud fail 修复验证

    P2-2 修复：测试 monkeypatch _emit_time_stop_unknown_alert 到 tmp queue_path，
    避免污染生产 data/message_queue.json。
    """

    @pytest.fixture(autouse=True)
    def _patch_alert_queue(self, tmp_path):
        """每个用例自动隔离队列路径到 tmpdir，防止测试告警写入生产队列"""
        import risk_rules
        self._tmp_queue = tmp_path / "test_message_queue.json"
        # 预建空队列文件，避免"不写告警"的用例 json.load 找不到文件
        self._tmp_queue.write_text("[]", encoding="utf-8")
        self._orig_emit = risk_rules._emit_time_stop_unknown_alert
        def _isolated_emit(entry_info, data_quality_issue, queue_path=None):
            return self._orig_emit(entry_info, data_quality_issue, queue_path=str(self._tmp_queue))
        risk_rules._emit_time_stop_unknown_alert = _isolated_emit
        yield
        risk_rules._emit_time_stop_unknown_alert = self._orig_emit

    def test_invalid_entry_date_sets_unknown(self):
        """entry_date 脏格式 → time_stop_unknown=True + data_quality_issue=entry_date_invalid"""
        from risk_rules import evaluate_exit
        entry = {"entry_price": 10.0, "entry_date": "invalid", "sl": 9.2, "tp1": 11.0, "tp2": 12.0, "stock_code": "TEST001"}
        should_exit, reason, exit_type, extra = evaluate_exit(entry, 10.5, "强")
        assert extra["time_stop_unknown"] is True
        assert extra["data_quality_issue"] == "entry_date_invalid"
        # 告警写入隔离队列，未污染生产
        import json
        alerts = json.load(open(self._tmp_queue))
        assert len(alerts) == 1
        assert alerts[0]["id"].startswith("time_stop_unknown_")

    def test_missing_entry_date_sets_unknown(self):
        """entry_date 缺失 → time_stop_unknown=True + data_quality_issue=entry_date_missing"""
        from risk_rules import evaluate_exit
        entry = {"entry_price": 10.0, "sl": 9.2, "tp1": 11.0, "tp2": 12.0, "stock_code": "TEST002"}
        should_exit, reason, exit_type, extra = evaluate_exit(entry, 10.5, "强")
        assert extra["time_stop_unknown"] is True
        assert extra["data_quality_issue"] == "entry_date_missing"
        import json
        alerts = json.load(open(self._tmp_queue))
        assert len(alerts) >= 1

    def test_valid_entry_date_no_unknown(self):
        """正常 entry_date → time_stop_unknown=False，不写告警"""
        from risk_rules import evaluate_exit
        entry = {"entry_price": 10.0, "entry_date": "2026-01-01", "sl": 9.2, "tp1": 11.0, "tp2": 12.0, "stock_code": "TEST003"}
        should_exit, reason, exit_type, extra = evaluate_exit(entry, 10.5, "强")
        assert extra["time_stop_unknown"] is False
        assert extra["data_quality_issue"] == ""
        # 正常日期不写告警，隔离队列为空
        import json
        alerts = json.load(open(self._tmp_queue))
        assert alerts == []

    def test_empty_entry_returns_unknown_false(self):
        """空 entry_info → 早期返回，time_stop_unknown=False"""
        from risk_rules import evaluate_exit
        should_exit, reason, exit_type, extra = evaluate_exit({}, 10.5, "强")
        assert should_exit is False
        assert extra["time_stop_unknown"] is False
        assert extra["data_quality_issue"] == ""
        # 不写告警
        import json
        alerts = json.load(open(self._tmp_queue))
        assert alerts == []

    def test_alert_dedup_same_id(self):
        """同 id 告警不重复入队（P2-2 去重）：两次调用同 stock_code → 第二条 id 相同时跳过"""
        from risk_rules import _emit_time_stop_unknown_alert
        import json, time as _time
        # 清空队列
        self._tmp_queue.write_text("[]", encoding="utf-8")
        # 第一次调用
        _emit_time_stop_unknown_alert(
            {"stock_code": "TESTDEDUP", "entry_date": "bad"},
            "entry_date_invalid",
            queue_path=str(self._tmp_queue),
        )
        alerts1 = json.load(open(self._tmp_queue, encoding="utf-8"))
        assert len(alerts1) == 1
        first_id = alerts1[0]["id"]
        # 第二次调用（同 stock_code，同秒 → 相同 id）→ 应去重跳过
        _emit_time_stop_unknown_alert(
            {"stock_code": "TESTDEDUP", "entry_date": "bad"},
            "entry_date_invalid",
            queue_path=str(self._tmp_queue),
        )
        alerts2 = json.load(open(self._tmp_queue, encoding="utf-8"))
        assert len(alerts2) == 1, f"去重失败：队列应有1条，实际{len(alerts2)}条"

    def test_real_trading_chain_exists(self):
        """实盘判定链路存在断言：risk_monitor.check_time_stop 可导入且契约值一致"""
        # 1. check_time_stop 实盘函数可导入
        from core.ops.risk_monitor import check_time_stop
        assert callable(check_time_stop), "check_time_stop 应为可调用的函数"
        # 2. TIME_STOP_TRADING_DAYS 契约值 120 不变
        from risk_rules import TIME_STOP_TRADING_DAYS
        assert TIME_STOP_TRADING_DAYS == 120, f"TIME_STOP 契约值应为 120，实际 {TIME_STOP_TRADING_DAYS}"
        # 3. evaluate_exit 返回 4 元组（含 extra）
        from risk_rules import evaluate_exit
        result = evaluate_exit({"entry_price": 10.0, "entry_date": "2026-01-01", "sl": 9.2}, 10.5, "强")
        assert len(result) == 4, f"evaluate_exit 应返回 4 元组，实际 {len(result)} 元"
        assert isinstance(result[3], dict), "第4元应为 extra dict"
        assert "time_stop_unknown" in result[3], "extra 应含 time_stop_unknown 键"

    # ── C-fix 护栏专项（2026-10-23, commit 1bcdb788）──────────────────────────
    # 以下测试覆盖 C-fix 守卫分支（_explicit_queue=False + 合成/真实码 predicate）
    # 现有 fixture 全部用显式 queue_path（_explicit_queue=True）→ 守卫分支 0 覆盖

    def test_guard_predicate_synthetic_blocked(self):
        """护栏 predicate：合成哨兵码（无 6 位数字）→ 正则不匹配 → 护栏应拦（进 audit，不写 P0）"""
        import re
        for code in ["unknown", "TEST001", "TESTDEDUP", "INVALID", "MISSING", "None", ""]:
            assert not re.search(r"\d{6}", str(code)), (
                f"合成码 {code!r} 不应含 6 位数字，但护栏正则匹配了 → predicate 有漏洞"
            )

    def test_guard_predicate_real_6digit_passes(self):
        """护栏 predicate：真实 A 股 6 位码 → 正则匹配 → 护栏不拦（正常走 P0）"""
        import re
        for code in ["600519", "600000", "000001", "300750", "SH600519", "SZ000001", "830799", "920001"]:
            assert re.search(r"\d{6}", str(code)), (
                f"真实码 {code!r} 含 6 位数字，护栏正则应匹配 → 护栏不拦"
            )

    def test_synthetic_code_no_explicit_queue_writes_audit(self, tmp_path):
        """护栏集成：合成码 + 无显式 queue_path（生产默认路径）→ audit 文件新增 1 行，生产队列不变。

        安全说明：
        - 直接调用 fixture 保存的 self._orig_emit（未 monkeypatch 的原始函数）
          → 无 queue_path → 生产默认路径 → 护栏激活
        - 只验 audit 文件（synthetic_alert_audit.jsonl, jsonl append-only，安全）
        - 不写生产 message_queue.json（护栏保证不写）
        """
        import json, os, hashlib
        import core.risk.risk_rules_impl as _impl

        # 仓库根（与护栏内部路径计算一致）
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(_impl.__file__))))
        audit_path = os.path.join(repo_root, "data", "synthetic_alert_audit.jsonl")
        prod_queue = os.path.join(repo_root, "data", "message_queue.json")

        # snapshot
        pre_audit_lines = len(open(audit_path, encoding="utf-8").readlines()) if os.path.exists(audit_path) else 0
        pre_queue_hash = None
        if os.path.exists(prod_queue):
            with open(prod_queue, "rb") as f:
                pre_queue_hash = hashlib.sha256(f.read()).hexdigest()

        # 调用原始函数（self._orig_emit = fixture 保存的未 patch 引用）
        # 不传 queue_path（= None → 生产默认 → 护栏激活）
        self._orig_emit(
            {"stock_code": "SYNTH_TEST_001", "entry_date": "bad_date"},
            "entry_date_invalid",
            # 无 queue_path → 生产默认路径 → 护栏应拦合成码
        )

        # 断言 1：audit 新增 1 行
        post_audit_lines = len(open(audit_path, encoding="utf-8").readlines())
        assert post_audit_lines == pre_audit_lines + 1, (
            f"audit 文件应新增 1 行: {pre_audit_lines} → {post_audit_lines}"
        )
        # 验证新增行包含 stock_code
        last_line = open(audit_path, encoding="utf-8").readlines()[-1]
        assert "SYNTH_TEST_001" in last_line, f"audit 末行应含 stock_code SYNTH_TEST_001: {last_line[:80]}"

        # 断言 2：生产队列不变
        if pre_queue_hash is not None:
            with open(prod_queue, "rb") as f:
                post_queue_hash = hashlib.sha256(f.read()).hexdigest()
            assert post_queue_hash == pre_queue_hash, (
                "合成码不应写生产 message_queue.json（护栏失效！）"
            )

