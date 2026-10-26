#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_walk_forward_backtest.py - Walk-Forward回测引擎S3集成版测试
测试public interface: simulate_strategy返回值结构, run结果结构
"""
import sys
import os
import contextlib
import types
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


@contextlib.contextmanager
def _isolated_gate():
    """把 walk_forward_gate 的全部真实落盘点重定向到 tmp，保证门禁单测不碰真实产物/台账。

    覆盖 4 个真实写/读点（回归跑 `pytest tests/test_walk_forward_backtest.py` 会污染
    真实文件的根因 —— 历史缺陷是这些测试只 patch OUT_DIR）：
      - wf_gate.OUT_DIR                源结果目录（读）
      - wf_gate.GATE_FILE              data/walk_forward_gate.json（原子写, gate.py L427）
      - wf_gate.SOURCE_LEDGER          state/walk_forward_source_ledger.jsonl（追加, L212）
      - record_gate_fingerprint.LEDGER state/gate_fingerprints.jsonl（追加；
        由 evaluate() 内 record_fingerprint(ledger=None -> 模块 LEDGER) 触发）
    台账"只增不删"：本 helper 只把写点重定向到 tmp，绝不删改任何真实历史行。
    注意 record_fingerprint 在 evaluate() 内是顶层 `from record_gate_fingerprint import
    record_fingerprint` 触发（走 sys.modules 顶层同名对象），故必须 patch 顶层模块的 LEDGER。
    """
    import scripts.walk_forward_gate as wf_gate
    import record_gate_fingerprint as rgf
    base = Path(tempfile.mkdtemp())
    out_dir = base / "output" / "diagnostic"
    out_dir.mkdir(parents=True, exist_ok=True)
    gate_file = base / "data" / "walk_forward_gate.json"
    source_ledger = base / "state" / "walk_forward_source_ledger.jsonl"
    source_ledger.parent.mkdir(parents=True, exist_ok=True)
    fp_ledger = base / "state" / "gate_fingerprints.jsonl"
    orig = {
        "out_dir": wf_gate.OUT_DIR,
        "gate_file": wf_gate.GATE_FILE,
        "source_ledger": wf_gate.SOURCE_LEDGER,
        "fp_ledger": rgf.LEDGER,
    }
    try:
        wf_gate.OUT_DIR = out_dir
        wf_gate.GATE_FILE = gate_file
        wf_gate.SOURCE_LEDGER = source_ledger
        rgf.LEDGER = fp_ledger
        yield types.SimpleNamespace(
            base=base, out_dir=out_dir, gate_file=gate_file,
            source_ledger=source_ledger, fp_ledger=fp_ledger,
        )
    finally:
        wf_gate.OUT_DIR = orig["out_dir"]
        wf_gate.GATE_FILE = orig["gate_file"]
        wf_gate.SOURCE_LEDGER = orig["source_ledger"]
        rgf.LEDGER = orig["fp_ledger"]


class TestWalkForwardBacktest(unittest.TestCase):
    """测试walk_forward_backtest.py的S3集成版"""
    
    def setUp(self):
        from scripts.walk_forward_backtest import WalkForwardBacktest
        self.engine = WalkForwardBacktest(
            train_size=252,
            test_size=63,
            step_size=63
        )
    
    def test_simulate_strategy_returns_dict(self):
        import pandas as pd
        n_train = 300
        n_test = 100
        train_prices = [10.0 + i * 0.1 for i in range(n_train)]
        test_prices = [train_prices[-1] + i * 0.05 for i in range(n_test)]
        train_df = pd.DataFrame({'close': train_prices})
        test_df = pd.DataFrame({'close': test_prices})
        result = self.engine.simulate_strategy(train_df, test_df)
        self.assertIsInstance(result, dict)
        self.assertIn('oos_sharpe', result)
        self.assertIn('is_sharpe', result)
        self.assertIn('status', result)
    
    def test_simulate_strategy_success_case(self):
        import pandas as pd
        n_train = 300
        n_test = 100
        train_prices = [10.0 + i * 0.01 for i in range(n_train)]
        test_prices = [train_prices[-1] + i * 0.005 for i in range(n_test)]
        train_df = pd.DataFrame({'close': train_prices})
        test_df = pd.DataFrame({'close': test_prices})
        result = self.engine.simulate_strategy(train_df, test_df)
        self.assertEqual(result['status'], 'success')
        self.assertIsInstance(result['oos_sharpe'], float)
        self.assertIsInstance(result['is_sharpe'], float)
    
    def test_simulate_strategy_insufficient_data(self):
        import pandas as pd
        train_df = pd.DataFrame({'close': [10.0, 10.5, 11.0]})
        test_df = pd.DataFrame({'close': [11.5, 12.0]})
        result = self.engine.simulate_strategy(train_df, test_df)
        self.assertEqual(result['status'], 'insufficient_data')
    
    def test_simulate_strategy_returns_valid_sharpe_range(self):
        import pandas as pd
        n_train = 300
        n_test = 100
        train_prices = [10.0 + i * 0.01 for i in range(n_train)]
        test_prices = [train_prices[-1] + i * 0.005 for i in range(n_test)]
        train_df = pd.DataFrame({'close': train_prices})
        test_df = pd.DataFrame({'close': test_prices})
        result = self.engine.simulate_strategy(train_df, test_df)
        self.assertGreaterEqual(result['oos_sharpe'], 0.0)
        self.assertLessEqual(result['oos_sharpe'], 2.0)
        self.assertGreaterEqual(result['is_sharpe'], 0.0)
        self.assertLessEqual(result['is_sharpe'], 2.0)
    
    def test_run_returns_summary_dict(self):
        import pandas as pd
        mock_records = []
        for i in range(400):
            mock_records.append({'date': f'2024-{i//30+1:02d}-{i%30+1:02d}', 'close': 10.0 + i * 0.01})
        mock_df = pd.DataFrame(mock_records)
        with patch.object(self.engine, 'load_stock_data') as mock_load, patch.object(self.engine, 'walk_forward_split') as mock_split:
            mock_load.return_value = mock_df
            mock_split.return_value = [(mock_df.iloc[:300], mock_df.iloc[300:])]
            result = self.engine.run(['sh600000'])
            self.assertIsInstance(result, dict)
            self.assertIn('mean_oos_sharpe', result)
            self.assertIn('mean_is_sharpe', result)
            self.assertIn('sharpe_drop', result)
            self.assertIn('decay_pctl', result)
    
    def test_run_with_empty_list(self):
        result = self.engine.run([])
        self.assertEqual(result['status'], 'no_data')
        self.assertIn('message', result)
    
    def test_calculate_sharpe_edge_cases(self):
        import pandas as pd
        empty_series = pd.Series([])
        self.assertEqual(self.engine.calculate_sharpe(empty_series), 0.0)
        single_series = pd.Series([0.1])
        self.assertEqual(self.engine.calculate_sharpe(single_series), 0.0)
        const_series = pd.Series([0.1, 0.1, 0.1, 0.1])
        self.assertEqual(self.engine.calculate_sharpe(const_series), 0.0)


class TestWalkForwardGate(unittest.TestCase):
    """测试walk_forward_gate.py门禁逻辑

    所有门禁用例都通过 _isolated_gate() 把 OUT_DIR/GATE_FILE/SOURCE_LEDGER 与
    record_gate_fingerprint.LEDGER 一并重定向到 tmp。历史缺陷是这些测试只 patch
    OUT_DIR，导致回归跑会覆写真实 data/walk_forward_gate.json 并向真实台账追加假行。
    """

    def setUp(self):
        from scripts.walk_forward_gate import evaluate
        self.evaluate = evaluate

    def _write_result(self, out_dir, filename, is_sharpe, oos_sharpe,
                      timestamp='2026-10-21T03:00:00'):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        result_file = out_dir / filename
        result_data = {'mean_is_sharpe': is_sharpe, 'mean_oos_sharpe': oos_sharpe,
                       'timestamp': timestamp, 'successful_windows': 100}
        with open(result_file, 'w') as f:
            json.dump(result_data, f)
        return result_file

    def test_gate_pass_when_decay_low(self):
        with _isolated_gate() as ns:
            self._write_result(ns.out_dir, 'walk-forward-test-test.json', 0.5, 0.4)
            exit_code, payload = self.evaluate(threshold=0.5, metric='ratio')
            self.assertEqual(exit_code, 0)
            self.assertFalse(payload['blocked'])
            self.assertLess(payload['decay'], 0.5)
            # 门禁 JSON 确实写到了 tmp 而非真实路径
            self.assertTrue(ns.gate_file.exists())

    def test_gate_block_when_decay_high(self):
        with _isolated_gate() as ns:
            self._write_result(ns.out_dir, 'walk-forward-test-test.json', 0.5, 0.1)
            exit_code, payload = self.evaluate(threshold=0.5, metric='ratio')
            self.assertEqual(exit_code, 3)
            self.assertTrue(payload['blocked'])
            self.assertGreater(payload['decay'], 0.5)

    def test_gate_fail_when_no_result_file(self):
        import scripts.walk_forward_gate as wf_gate
        with _isolated_gate() as ns:
            wf_gate.OUT_DIR = Path('/nonexistent/path')
            exit_code, payload = self.evaluate(threshold=0.5)
            self.assertEqual(exit_code, 2)
            self.assertIsNone(payload)


class TestWalkForwardIntegration(unittest.TestCase):
    """端到端集成测试（全部真实落盘点经 _isolated_gate() 重定向到 tmp）"""

    def test_full_workflow(self):
        import scripts.walk_forward_gate as wf_gate
        with _isolated_gate() as ns:
            result_data = {'mean_is_sharpe': 0.5266, 'mean_oos_sharpe': 0.3911,
                           'sharpe_drop': 0.1355, 'decay_pctl': 0.2573,
                           'timestamp': '2026-10-21T04:00:00',
                           'successful_windows': 11238, 'stock_processed': 500}
            result_file = ns.out_dir / 'walk-forward-test-20261021_040000.json'
            with open(result_file, 'w') as f:
                json.dump(result_data, f)
            exit_code, payload = wf_gate.evaluate(threshold=0.5, metric='ratio')
            self.assertEqual(exit_code, 0)
            self.assertFalse(payload['blocked'])
            self.assertAlmostEqual(payload['is_sharpe'], 0.5266, places=4)
            self.assertAlmostEqual(payload['oos_sharpe'], 0.3911, places=4)
            self.assertAlmostEqual(payload['decay'], 0.2573, places=4)


class TestGateIsolationGuard(unittest.TestCase):
    """回归守卫（本单 t_1349c14e）：门禁用例跑完，真实 gate JSON / 两份指纹台账必须 0 变更。

    自证逻辑：用与 TestWalkForwardGate / TestWalkForwardIntegration 相同的 _isolated_gate()
    helper 执行一次完整门禁用例，随后断言——
      1) 真实 data/walk_forward_gate.json 字节 + mtime 未变；
      2) 真实 state/walk_forward_source_ledger.jsonl 无新增行；
      3) 真实 state/gate_fingerprints.jsonl 无新增行。
    若有人在 _isolated_gate() 里移除任一 patch（GATE_FILE/SOURCE_LEDGER/LEDGER），
    本守卫会当场报红。台账历史污染行"只增不删"，本测试不删改任何真实历史行。
    """

    @staticmethod
    def _snapshot(path):
        if not path.exists():
            return None
        text = path.read_text(encoding='utf-8')
        return {
            'bytes': path.read_bytes(),
            'mtime': path.stat().st_mtime,
            'lines': len(text.splitlines()),
        }

    def _assert_unchanged(self, before, after, label, path):
        if before is None:
            self.assertIsNone(after,
                              f"{label} 本不存在，但门禁用例却在 {path} 创建/写出了它")
            return
        self.assertEqual(before['bytes'], after['bytes'],
                         f"门禁用例改了真实 {label} 内容（{path}）")
        self.assertEqual(before['mtime'], after['mtime'],
                         f"门禁用例改了真实 {label} 的 mtime（{path}）")
        self.assertEqual(before['lines'], after['lines'],
                         f"门禁用例向真实 {label} 追加/删减了行（{path}）")

    def test_real_gate_json_and_ledgers_untouched_by_gate_case(self):
        import scripts.walk_forward_gate as wf_gate
        real_gate = PROJECT_ROOT / 'data' / 'walk_forward_gate.json'
        real_src_ledger = PROJECT_ROOT / 'state' / 'walk_forward_source_ledger.jsonl'
        real_fp_ledger = PROJECT_ROOT / 'state' / 'gate_fingerprints.jsonl'

        before_gate = self._snapshot(real_gate)
        before_src = self._snapshot(real_src_ledger)
        before_fp = self._snapshot(real_fp_ledger)

        # 执行一次完整门禁用例（OUT_DIR/GATE_FILE/SOURCE_LEDGER/LEDGER 全重定向到 tmp）
        with _isolated_gate() as ns:
            result_data = {'mean_is_sharpe': 0.5266, 'mean_oos_sharpe': 0.3911,
                           'sharpe_drop': 0.1355, 'decay_pctl': 0.2573,
                           'timestamp': '2026-10-21T04:00:00',
                           'successful_windows': 11238, 'stock_processed': 500}
            result_file = ns.out_dir / 'walk-forward-test-20261021_040000.json'
            with open(result_file, 'w') as f:
                json.dump(result_data, f)
            exit_code, payload = wf_gate.evaluate(threshold=0.5, metric='ratio')
            self.assertEqual(exit_code, 0)
            self.assertFalse(payload['blocked'])
            # gate JSON 确实写到了 tmp 而非真实路径
            self.assertTrue(ns.gate_file.exists())

        after_gate = self._snapshot(real_gate)
        after_src = self._snapshot(real_src_ledger)
        after_fp = self._snapshot(real_fp_ledger)

        self._assert_unchanged(before_gate, after_gate, "gate JSON", real_gate)
        self._assert_unchanged(before_src, after_src, "source ledger", real_src_ledger)
        self._assert_unchanged(before_fp, after_fp, "gate_fingerprints ledger", real_fp_ledger)


if __name__ == '__main__':
    unittest.main(verbosity=2)
