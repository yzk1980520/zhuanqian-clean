#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_aoci_maintenance.py — AOCI自动维护系统测试
测试范围：脚本逻辑、索引维护、漂移检测
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

# 导入被测模块
import aoci_auto_maintain
import aoci_daily_check
import aoci_weekly_score


class TestAOCIMaintainer:
    """AOCI自动维护器测试"""

    def setup_method(self, method):
        """每个测试前的设置"""
        import tempfile
        self.temp_dir = tempfile.mkdtemp()
        self.index_file = Path(self.temp_dir) / "aoci.code.txt"
        self.log_file = Path(self.temp_dir) / "maintain_log.jsonl"

    def teardown_method(self, method):
        """每个测试后的清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_index(self):
        """测试索引加载"""
        # 创建测试索引文件
        self.index_file.write_text("""#AOCI-CODE-VOLUME: 1
integrated_picker.py[BD7T]: F:多因子选股主入口 | R:tdx_core,scoring_engine | A:pick_top1() | S:每日选股核心逻辑
backtest_rotation.py[BG6T]: F:回测引擎 | R:tdx_core,risk_rules | A:run_backtest() | S:132日全量扫描
""")

        # 修改模块的INDEX_FILE路径
        with patch.object(aoci_auto_maintain, 'INDEX_FILE', self.index_file):
            maintainer = aoci_auto_maintain.AOCIMaintainer()
            assert len(maintainer.index_entries) == 2
            assert 'integrated_picker.py' in maintainer.index_entries
            assert 'backtest_rotation.py' in maintainer.index_entries

    def test_extract_fras_metadata(self):
        """测试FRAS元数据提取"""
        # 创建测试Python文件
        test_file = Path(self.temp_dir) / "test_module.py"
        test_file.write_text('''"""
test_module.py — 测试模块
职责: 提供测试功能
用途: 单元测试用例
"""
import os
import sys

class TestClass:
    """测试类"""
    def test_method(self):
        """测试方法"""
        pass

def main():
    """主函数"""
    pass
''')

        with patch.object(aoci_auto_maintain, 'PROJECT_ROOT', Path(self.temp_dir)):
            maintainer = aoci_auto_maintain.AOCIMaintainer()
            metadata = maintainer.extract_fras_metadata("test_module.py")

            assert metadata is not None
            assert metadata['filename'] == 'test_module.py'
            assert 'test_method' in metadata['api']
            assert 'main' in metadata['api']

    def test_generate_tag(self):
        """测试标签生成"""
        with patch.object(aoci_auto_maintain, 'PROJECT_ROOT', Path(self.temp_dir)):
            maintainer = aoci_auto_maintain.AOCIMaintainer()

            # 测试核心文件标签
            assert maintainer._generate_tag('integrated_picker.py', ['Picker'], ['pick']) == 'BD7T'
            assert maintainer._generate_tag('test_xyz.py', [], []) == 'PQ5T'
            assert maintainer._generate_tag('health_monitor.py', [], []) == 'CD5T'

    def test_check_completeness(self):
        """测试完整性检查"""
        # 创建索引文件
        index_content = """#AOCI-CODE-VOLUME: 1
file1.py[TAG1]: F:有效功能 | R:dep1 | A:api1 | S:spec1
file2.py[TAG2]: F:待补充 | R:dep2 | A:api2 | S:spec2
"""
        index_file = Path(self.temp_dir) / "aoci.code.txt"
        index_file.write_text(index_content)

        with patch.object(aoci_auto_maintain, 'INDEX_FILE', index_file):
            maintainer = aoci_auto_maintain.AOCIMaintainer()
            result = maintainer.check_completeness()

            assert result['total_entries'] == 2
            assert result['issues_count'] >= 1  # file2的func字段是"待补充"

    def test_generate_drift_report(self):
        """测试漂移报告生成"""
        # 创建基线文件
        baseline_file = Path(self.temp_dir) / ".aoci" / "baseline.json"
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        baseline_file.write_text(json.dumps({'entry_count': 100}))

        with patch.object(aoci_auto_maintain, 'PROJECT_ROOT', Path(self.temp_dir)):
            maintainer = aoci_auto_maintain.AOCIMaintainer()
            maintainer.index_entries = {'a.py': {}, 'b.py': {}}  # 2个条目

            report = maintainer.generate_drift_report("old", "new")

            assert report['drift_detected'] is True  # 变化超过5
            assert report['changes']['entries_added'] == -98


class TestDailyCheck:
    """每日巡检测试"""

    def test_run_aoci_check(self):
        """测试aoci check执行"""
        result = aoci_daily_check.run_aoci_check()

        assert 'exit_code' in result
        assert 'stdout' in result
        assert 'stderr' in result

    def test_scan_new_files(self):
        """测试新增文件扫描"""
        # 创建测试索引文件
        index_content = "integrated_picker.py[BD7T]: F:test | R:test | A:test | S:test\n"
        (Path(__file__).parent.parent / "aoci.code.txt").write_text(index_content)

        new_files = aoci_daily_check.scan_new_files()

        # 应该排除已索引的文件
        assert 'integrated_picker.py' not in str(new_files)

    def test_check_index_completeness(self):
        """测试索引完整性检查"""
        # 创建完整索引
        index_content = """#AOCI-CODE-VOLUME: 1
file1.py[TAG1]: F:func1 | R:dep1 | A:api1 | S:spec1
file2.py[TAG2]: F:func2 | R:dep2 | A:api2 | S:spec2
"""
        index_file = Path(__file__).parent.parent / "aoci.code.txt"
        original_content = index_file.read_text() if index_file.exists() else None
        index_file.write_text(index_content)

        try:
            result = aoci_daily_check.check_index_completeness()
            assert result['status'] == 'ok'
            assert result['total_entries'] == 2
            assert result['completeness_rate'] == '100.0%'
        finally:
            if original_content:
                index_file.write_text(original_content)
            else:
                index_file.unlink(missing_ok=True)


class TestWeeklyScore:
    """每周评分测试"""

    def test_load_index(self):
        """测试索引加载"""
        # 创建测试索引
        index_content = """#AOCI-CODE-VOLUME: 1
test1.py[TAG1]: F:func1 | R:dep1 | A:api1 | S:spec1
test2.py[TAG2]: F:func2 | R:dep2 | A:api2 | S:spec2
incomplete.py[TAG3]: F:func3 | R: | A:api3 | S:spec3
"""
        index_file = Path(__file__).parent.parent / "aoci.code.txt"
        original_content = index_file.read_text() if index_file.exists() else None
        index_file.write_text(index_content)

        try:
            entries = aoci_weekly_score.load_index()
            assert len(entries) == 3
            assert entries['test1.py']['complete'] is True
            assert entries['incomplete.py']['complete'] is False  # requires字段为空
        finally:
            if original_content:
                index_file.write_text(original_content)
            else:
                index_file.unlink(missing_ok=True)

    def test_count_python_files(self):
        """测试Python文件统计"""
        counts = aoci_weekly_score.count_python_files()

        assert counts['total'] > 0
        assert 'root' in counts
        assert 'scripts' in counts
        assert 'tests' in counts

    def test_calculate_coverage(self):
        """测试覆盖率计算"""
        entries = {
            'file1.py': {'complete': True},
            'file2.py': {'complete': True},
            'file3.py': {'complete': False}
        }
        counts = {'total': 10, 'root': 5, 'tests': 2, 'scripts': 1, 'tdx_score': 1, 'health_monitor': 0, 'agents': 0}

        coverage = aoci_weekly_score.calculate_coverage(entries, counts)

        assert coverage['coverage_rate'] == '30.0%'
        assert coverage['completeness_rate'] == '66.7%'
        assert coverage['test_coverage'] == '0.0%'  # 没有test_开头的条目

    def test_generate_report(self):
        """测试报告生成"""
        entries = {'test.py': {'complete': True}}
        counts = {'total': 100, 'root': 50, 'tests': 10, 'scripts': 5, 'tdx_score': 5, 'health_monitor': 5, 'agents': 2}
        coverage = {
            'coverage_rate': '1.0%',
            'completeness_rate': '100.0%',
            'test_coverage': '10.0%'
        }

        report = aoci_weekly_score.generate_report(entries, counts, coverage)

        assert 'timestamp' in report
        assert 'summary' in report
        assert len(report['recommendations']) > 0
        assert report['recommendations'][0]['priority'] == 'high'  # 覆盖率<50%


def run_tests():
    """运行所有测试"""
    import unittest

    # 发现并运行测试
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_tests())
