#!/usr/bin/env python3
"""
多Agent心跳检查器 · 测试套件
覆盖：状态快照、差异计算、通知生成、日志写入、缓存读写
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# 导入被测模块
import multi_agent_heartbeat as hab


CST = timezone(timedelta(hours=8))


def test_log_writes_to_file(tmp_path):
    """测试log函数写入日志文件"""
    log_file = tmp_path / "test.log"
    with patch.object(hab, "LOG_FILE", log_file):
        hab.log("test message")
    
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "test message" in content
    assert datetime.fromisoformat(content.split("[")[1].split("]")[0])  # 时间戳有效


def test_load_state_empty_cache(tmp_path):
    """测试加载空缓存返回空dict"""
    cache_file = tmp_path / "state.json"
    with patch.object(hab, "STATE_CACHE_FILE", cache_file):
        assert cache_file.exists() is False
        result = hab.load_state()
        assert result == {}


def test_load_state_existing_cache(tmp_path):
    """测试加载已有缓存"""
    cache_file = tmp_path / "state.json"
    cache_data = {"workbuddy": {"timestamp": "2026-10-19T03:51:00+08:00"}}
    cache_file.write_text(json.dumps(cache_data), encoding="utf-8")
    
    with patch.object(hab, "STATE_CACHE_FILE", cache_file):
        result = hab.load_state()
        assert result == cache_data


def test_save_state_creates_file(tmp_path):
    """测试保存状态创建文件"""
    cache_file = tmp_path / "state.json"
    test_state = {"workbuddy": {"total": 5}}
    
    with patch.object(hab, "STATE_CACHE_FILE", cache_file):
        hab.save_state(test_state)
    
    assert cache_file.exists()
    loaded = json.loads(cache_file.read_text(encoding="utf-8"))
    assert loaded == test_state


def test_save_state_atomic_write(tmp_path):
    """测试原子写入（先写.tmp再rename）"""
    cache_file = tmp_path / "state.json"
    test_state = {"workbuddy": {"total": 5}}
    
    with patch.object(hab, "STATE_CACHE_FILE", cache_file):
        hab.save_state(test_state)
    
    # 不应有临时文件残留
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_diff_state_no_changes():
    """测试无变化时diff返回空列表"""
    old = {
        "by_status": {"todo": 2, "running": 1},
        "recent_tasks": [{"id": "t_001", "title": "任务A"}],
    }
    new = {
        "by_status": {"todo": 2, "running": 1},
        "recent_tasks": [{"id": "t_001", "title": "任务A"}],
    }
    
    changes = hab.diff_state(old, new)
    assert changes == []


def test_diff_state_status_change():
    """测试状态数量变化检测"""
    old = {"by_status": {"todo": 2, "running": 1}}
    new = {"by_status": {"todo": 3, "running": 1}}
    
    changes = hab.diff_state(old, new)
    assert len(changes) == 1
    assert changes[0]["type"] == "status_change"
    assert changes[0]["status"] == "todo"
    assert changes[0]["old"] == 2
    assert changes[0]["new"] == 3


def test_diff_state_new_task():
    """测试新任务检测"""
    old = {"recent_tasks": [{"id": "t_001", "title": "任务A"}]}
    new = {"recent_tasks": [{"id": "t_001", "title": "任务A"}, {"id": "t_002", "title": "任务B"}]}
    
    changes = hab.diff_state(old, new)
    assert len(changes) == 1
    assert changes[0]["type"] == "new_task"
    assert changes[0]["task_id"] == "t_002"


def test_diff_state_task_removed():
    """测试任务移除不触发变化（只关注新增和状态变化）"""
    old = {"recent_tasks": [{"id": "t_001"}, {"id": "t_002"}]}
    new = {"recent_tasks": [{"id": "t_001"}]}
    
    changes = hab.diff_state(old, new)
    # 移除不触发变化
    assert changes == []


def test_format_comment_no_changes():
    """测试无变化时comment内容"""
    comment = hab.format_comment("老六", [])
    assert "无变化" in comment


def test_format_comment_with_changes():
    """测试有变化时comment内容"""
    changes = [
        {"type": "status_change", "status": "running", "old": 1, "new": 2},
        {"type": "new_task", "task_id": "t_002", "title": "新任务", "status": "todo"},
    ]
    comment = hab.format_comment("老六", changes)
    
    assert "running" in comment
    assert "新任务" in comment
    assert "todo" in comment


def test_snapshot_agent_status_with_mock():
    """测试状态快照（mock kanban list）"""
    mock_tasks = [
        {"id": "t_001", "status": "todo", "title": "任务A", "priority": 5, "assignee": "workbuddy"},
        {"id": "t_002", "status": "running", "title": "任务B", "priority": 3, "assignee": "workbuddy"},
    ]
    
    with patch("multi_agent_heartbeat.run_kanban_list", return_value=mock_tasks):
        result = hab.snapshot_agent_status("workbuddy")
    
    assert result["assignee"] == "workbuddy"
    assert result["total"] == 2
    assert result["by_status"]["todo"] == 1
    assert result["by_status"]["running"] == 1
    assert "timestamp" in result


def test_snapshot_agent_status_empty():
    """测试空任务列表"""
    with patch("multi_agent_heartbeat.run_kanban_list", return_value=[]):
        result = hab.snapshot_agent_status("workbuddy")
    
    assert result["total"] == 0
    assert result["by_status"] == {}


def test_main_run_without_changes(tmp_path):
    """测试主函数运行（无变化场景）"""
    log_file = tmp_path / "test.log"
    cache_file = tmp_path / "state.json"
    
    mock_state = {
        "workbuddy": {
            "by_status": {"todo": 2, "running": 1},
            "recent_tasks": [{"id": "t_001"}, {"id": "t_002"}],
        }
    }
    cache_file.write_text(json.dumps(mock_state), encoding="utf-8")
    
    with patch("multi_agent_heartbeat.LOG_FILE", log_file):
        with patch("multi_agent_heartbeat.STATE_CACHE_FILE", cache_file):
            with patch("multi_agent_heartbeat.snapshot_agent_status", return_value=mock_state["workbuddy"]):
                hab.main()
    
    # 日志应写入
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "无状态变化" in content or "心跳检查完成" in content


def test_agent_map_coverage():
    """测试Agent映射覆盖"""
    assert "workbuddy" in hab.AGENT_MAP
    assert "laosan" in hab.AGENT_MAP
    assert "atomcode" in hab.AGENT_MAP
    assert hab.AGENT_MAP["workbuddy"] == "老六"
    assert hab.AGENT_MAP["laosan"] == "老三"
    assert hab.AGENT_MAP["atomcode"] == "老五"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
