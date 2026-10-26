# -*- coding: utf-8 -*-
"""
test_dashboard_data_api.py — S7看板美化: /api/dashboard_data 端点测试

宪法合规:
- FR-002: 健康API端点已集成
- 宪法看板UI规范: holdings字段兼容(code/symbol)
- 宪法VII: 异常不吞 (except Exception:)
"""
import json
import os
import sys
import pytest
from pathlib import Path

# 注入项目根目录
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboards"))


class TestAggregateDashboardData:
    """测试 _aggregate_dashboard_data() 聚合函数"""

    def test_returns_dict_with_required_keys(self):
        from board_server import _aggregate_dashboard_data
        data = _aggregate_dashboard_data()
        assert isinstance(data, dict)
        required = {"generated_at", "holdings", "health", "feishu", "laosi", "cron"}
        assert required.issubset(data.keys()), f"缺少键: {required - data.keys()}"

    def test_generated_at_is_recent(self):
        from board_server import _aggregate_dashboard_data
        import time
        data = _aggregate_dashboard_data()
        # generated_at 格式 YYYY-MM-DD HH:MM:SS
        ts = data["generated_at"]
        assert len(ts) == 19, f"时间戳格式错误: {ts}"
        # 解析验证
        parsed = time.strptime(ts, "%Y-%m-%d %H:%M:%S")
        now = time.localtime()
        age_hours = (now.tm_year * 366 + now.tm_yday - parsed.tm_year * 366 - parsed.tm_yday) * 24
        assert age_hours < 1, f"时间戳过期: {ts}"

    def test_holdings_fields_compatible(self):
        """宪法看板UI规范: holdings字段兼容 code/symbol"""
        from board_server import _aggregate_dashboard_data
        data = _aggregate_dashboard_data()
        h = data["holdings"]
        assert "total_assets" in h
        assert "position_ratio" in h
        assert "count" in h
        assert isinstance(h["items"], list)
        # 每个持仓项应有code或symbol
        for item in h["items"]:
            code = item.get("code") or item.get("symbol")
            assert code != "N/A" or len(h["items"]) == 0, "持仓项缺少code/symbol字段"

    def test_health_status_exists(self):
        from board_server import _aggregate_dashboard_data
        data = _aggregate_dashboard_data()
        health = data["health"]
        assert "status" in health
        assert health["status"] in ("healthy", "unhealthy", "unknown")

    def test_feishu_pending_count(self):
        from board_server import _aggregate_dashboard_data
        data = _aggregate_dashboard_data()
        feishu = data["feishu"]
        assert "pending_count" in feishu
        assert isinstance(feishu["pending_count"], int)
        assert feishu["pending_count"] >= 0

    def test_cron_counts_valid(self):
        from board_server import _aggregate_dashboard_data
        data = _aggregate_dashboard_data()
        cron = data["cron"]
        assert "active" in cron
        assert "total" in cron
        assert cron["active"] <= cron["total"]


class TestSafeHoldingsCode:
    """测试 _safe_holdings_code() 字段兼容"""

    def test_symbol_only(self):
        from board_server import _safe_holdings_code
        p = {"symbol": "sh603727"}
        assert _safe_holdings_code(p) == "sh603727"

    def test_code_only(self):
        from board_server import _safe_holdings_code
        p = {"code": "sh600097"}
        assert _safe_holdings_code(p) == "sh600097"

    def test_both_prefer_code(self):
        from board_server import _safe_holdings_code
        p = {"code": "sh600097", "symbol": "sh603727"}
        # code优先
        assert _safe_holdings_code(p) == "sh600097"

    def test_neither_returns_na(self):
        from board_server import _safe_holdings_code
        p = {}
        assert _safe_holdings_code(p) == "N/A"


class TestAPIEndpoint:
    """测试 /api/dashboard_data HTTP端点"""

    @pytest.fixture
    def server(self):
        """启动临时server用于测试"""
        from board_server import Handler, PORT
        from http.server import ThreadingHTTPServer
        import threading

        server = ThreadingHTTPServer(("127.0.0.1", PORT + 100), Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{PORT + 100}"
        server.shutdown()

    def test_endpoint_returns_json(self, server):
        import urllib.request
        url = f"{server}/api/dashboard_data"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.headers["Content-Type"] == "application/json; charset=utf-8"
            body = json.loads(resp.read().decode("utf-8"))
            assert "holdings" in body
            assert "health" in body

    def test_endpoint_error_handling(self, server, monkeypatch):
        """测试异常路径: 当聚合函数抛出异常时返回error"""
        import urllib.request
        from board_server import _aggregate_dashboard_data

        def raise_exc():
            raise RuntimeError("测试异常")

        monkeypatch.setattr("board_server._aggregate_dashboard_data", raise_exc)

        url = f"{server}/api/dashboard_data"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            assert "error" in body
            assert "测试异常" in body["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


class TestLaowuReviewStatus:
    """D4: 测试 _get_laowu_review_status() + laowu_review API键"""

    def test_returns_dict_with_keys(self):
        from board_server import _get_laowu_review_status
        result = _get_laowu_review_status()
        assert isinstance(result, dict)
        assert "status" in result
        assert "message" in result

    def test_status_is_valid_enum(self):
        from board_server import _get_laowu_review_status
        result = _get_laowu_review_status()
        assert result["status"] in ("approved", "pending", "unknown", "error"), \
            f"invalid status: {result['status']}"

    def test_api_includes_laowu_review_key(self):
        from board_server import _aggregate_dashboard_data
        data = _aggregate_dashboard_data()
        assert "laowu_review" in data, "API响应缺少laowu_review键"
        assert isinstance(data["laowu_review"], dict)
        assert "status" in data["laowu_review"]

    def test_laowu_msg_variants(self):
        """老五审批三种状态: ✅/⚠️/—未知"""
        from board_server import _get_laowu_review_status
        msg = _get_laowu_review_status()["message"]
        # 消息应为有效中文状态
        assert len(msg) > 1, f"消息过短: {msg}"


class TestHealthCardRendering:
    """D4: 测试 build_html() 中健康卡包含老四/老五/飞书行"""

    def test_health_card_has_laosi_row(self):
        from board_server import build_html
        html = build_html()
        assert "老四巡检" in html, "健康卡缺少老四巡检行"

    def test_health_card_has_laowu_row(self):
        from board_server import build_html
        html = build_html()
        assert "老五审批" in html, "健康卡缺少老五审批行"

    def test_health_card_has_feishu_row(self):
        from board_server import build_html
        html = build_html()
        assert "飞书待投递" in html, "健康卡缺少飞书待投递行"

    def test_health_card_has_data_field_attrs(self):
        """D2/D3: 健康卡行应有 data-field 属性供JS更新"""
        from board_server import build_html
        html = build_html()
        assert 'data-field="laosi-status"' in html or "data-field='laosi-status'" in html, \
            "缺少laosi-status data-field"
        assert 'data-field="laowu-status"' in html or "data-field='laowu-status'" in html, \
            "缺少laowu-status data-field"
        assert 'data-field="feishu-pending"' in html or "data-field='feishu-pending'" in html, \
            "缺少feishu-pending data-field"

    def test_js_has_fetch_status_indicator(self):
        """D4: 页脚应有 #fetch-status 指示器"""
        from board_server import build_html
        html = build_html()
        assert 'id="fetch-status"' in html, "缺少fetch-status指示器"

    def test_js_error_handler_exists(self):
        """D4: JS应有catch块处理fetch失败"""
        from board_server import build_html
        html = build_html()
        assert ".catch" in html, "JS缺少error handler"
