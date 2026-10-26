#!/usr/bin/env python3
"""
tests/test_health_monitor.py — 健康监控模块测试
覆盖G1: 缺少health_monitor模块测试
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip("health_monitor", reason="health_monitor is an external module not in this repo (环境依赖债 D-4)")

from health_monitor.models import AlertSeverity, CheckStatus, HealthCheckResult, HealthReport
from health_monitor.monitor import HealthMonitor
from health_monitor.checkers.gateway import check_gateway_health
from health_monitor.checkers.data import check_data_freshness, check_tdx_data
from health_monitor.checkers.service import check_service_ports
from health_monitor.checkers.cron import check_cron_status


class TestHealthCheckResult:
    """测试HealthCheckResult数据模型"""
    
    def test_create_pass_result(self):
        result = HealthCheckResult(
            checker="test",
            status=CheckStatus.PASS,
            message="All good"
        )
        assert result.status == CheckStatus.PASS
        assert result.is_critical() == False
    
    def test_create_fail_result(self):
        result = HealthCheckResult(
            checker="test",
            status=CheckStatus.FAIL,
            severity=AlertSeverity.P0
        )
        assert result.is_critical() == True
    
    def test_to_dict(self):
        result = HealthCheckResult(
            checker="test",
            status=CheckStatus.PASS,
            message="OK",
            details={"key": "value"}
        )
        d = result.to_dict()
        assert d["checker"] == "test"
        assert d["status"] == "pass"
        assert d["details"] == {"key": "value"}


class TestHealthReport:
    """测试HealthReport数据模型"""
    
    def test_add_result(self):
        report = HealthReport()
        result = HealthCheckResult(checker="test", status=CheckStatus.PASS)
        report.add_result(result)
        assert len(report.results) == 1
        assert report.summary["total"] == 1
    
    def test_is_healthy(self):
        report = HealthReport()
        report.add_result(HealthCheckResult(checker="test", status=CheckStatus.PASS))
        assert report.is_healthy() == True
    
    def test_is_unhealthy_with_critical_fail(self):
        report = HealthReport()
        report.add_result(HealthCheckResult(
            checker="test",
            status=CheckStatus.FAIL,
            severity=AlertSeverity.P0
        ))
        assert report.is_healthy() == False
    
    def test_to_dict(self):
        report = HealthReport()
        report.add_result(HealthCheckResult(checker="test", status=CheckStatus.PASS))
        d = report.to_dict()
        assert "timestamp" in d
        assert "summary" in d
        assert "results" in d
        assert "is_healthy" in d


class TestHealthMonitor:
    """测试HealthMonitor核心引擎"""
    
    def test_register_checker(self):
        monitor = HealthMonitor()
        
        def dummy_checker():
            return HealthCheckResult(checker="dummy", status=CheckStatus.PASS)
        
        monitor.register_checker("dummy", dummy_checker)
        assert "dummy" in monitor.checkers
    
    def test_run_check_unknown(self):
        monitor = HealthMonitor()
        result = monitor.run_check("unknown")
        assert result.status == CheckStatus.SKIPPED
    
    def test_run_check_success(self):
        monitor = HealthMonitor()
        
        def good_checker():
            return HealthCheckResult(checker="good", status=CheckStatus.PASS)
        
        monitor.register_checker("good", good_checker)
        result = monitor.run_check("good")
        assert result.status == CheckStatus.PASS
    
    def test_run_check_failure(self):
        monitor = HealthMonitor()
        
        def bad_checker():
            return HealthCheckResult(checker="bad", status=CheckStatus.FAIL)
        
        monitor.register_checker("bad", bad_checker)
        result = monitor.run_check("bad")
        assert result.status == CheckStatus.FAIL
    
    def test_run_check_exception(self):
        monitor = HealthMonitor()
        
        def exploding_checker():
            raise ValueError("Boom!")
        
        monitor.register_checker("exploding", exploding_checker)
        result = monitor.run_check("exploding")
        assert result.status == CheckStatus.FAIL
        assert result.severity == AlertSeverity.P0
    
    def test_run_all(self, tmp_path):
        monitor = HealthMonitor(report_dir=tmp_path / "reports")
        
        def checker1():
            return HealthCheckResult(checker="c1", status=CheckStatus.PASS)
        
        def checker2():
            return HealthCheckResult(checker="c2", status=CheckStatus.FAIL, severity=AlertSeverity.P1)
        
        monitor.register_checker("c1", checker1)
        monitor.register_checker("c2", checker2)
        
        report = monitor.run_all()
        assert len(report.results) == 2
        assert report.summary["pass"] == 1
        assert report.summary["fail"] == 1
    
    def test_get_latest_report_empty(self, tmp_path):
        monitor = HealthMonitor(report_dir=tmp_path / "reports")
        assert monitor.get_latest_report() is None
    
    def test_get_latest_report_after_save(self, tmp_path):
        monitor = HealthMonitor(report_dir=tmp_path / "reports")
        
        def checker():
            return HealthCheckResult(checker="c1", status=CheckStatus.PASS)
        
        monitor.register_checker("c1", checker)
        monitor.run_all()
        
        report = monitor.get_latest_report()
        assert report is not None
        assert report.is_healthy()


class TestGatewayChecker:
    """测试Gateway检查器"""
    
    @patch('urllib.request.urlopen')
    def test_gateway_healthy(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"status": "ok", "version": "1.0"}).encode()
        mock_urlopen.return_value = mock_response
        
        result = check_gateway_health()
        assert result.status == CheckStatus.PASS
        assert "Gateway健康" in result.message
    
    @patch('urllib.request.urlopen')
    def test_gateway_unhealthy(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"status": "error"}).encode()
        mock_urlopen.return_value = mock_response
        
        result = check_gateway_health()
        assert result.status == CheckStatus.FAIL
    
    @patch('urllib.request.urlopen', side_effect=Exception("Connection refused"))
    def test_gateway_connection_failed(self, mock_urlopen):
        result = check_gateway_health()
        assert result.status == CheckStatus.FAIL
        assert result.severity == AlertSeverity.P0


class TestDataChecker:
    """测试数据检查器"""
    
    def test_data_freshness_missing_file(self, tmp_path):
        # 切换到临时目录，模拟缺失文件
        original_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            result = check_data_freshness()
            assert result.status == CheckStatus.FAIL
            assert "缺失" in result.message
        finally:
            os.chdir(original_cwd)
    
    def test_tdx_data_missing_dir(self, tmp_path):
        original_cwd = Path.cwd()
        try:
            import os
            os.chdir(tmp_path)
            result = check_tdx_data()
            assert result.status == CheckStatus.FAIL
            assert "TDX数据目录不存在" in result.message
        finally:
            os.chdir(original_cwd)


class TestServiceChecker:
    """测试服务端口检查器"""
    
    def test_check_service_ports(self):
        # 由于端口检查依赖实际服务，这里只验证基本逻辑
        result = check_service_ports()
        assert result.checker == "service_ports"
        assert result.status in [CheckStatus.PASS, CheckStatus.FAIL]


class TestCronChecker:
    """测试定时任务检查器"""
    
    def test_check_cron_status(self):
        # Windows系统才有schtasks
        import platform
        if platform.system() == "Windows":
            result = check_cron_status()
            assert result.checker == "cron_status"
        else:
            pytest.skip("Only runs on Windows")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
