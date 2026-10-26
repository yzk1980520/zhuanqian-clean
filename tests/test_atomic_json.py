#!/usr/bin/env python3
"""
test_atomic_json.py: 原子JSON读写测试
覆盖: 原子写、原子读、并发安全、目录创建
"""
import sys
import os
import pytest
import tempfile
import json
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pipeline.atomic_json import atomic_dump, atomic_load, update_json, FileLock


class TestAtomicDump:
    """原子写测试"""

    def test_basic_write(self, tmp_path):
        """基本写入应成功"""
        data = {"key": "value", "number": 42}
        path = str(tmp_path / "test.json")
        result = atomic_dump(data, path)
        assert result is True
        # 验证文件存在且内容正确
        with open(path, 'r') as f:
            loaded = json.load(f)
        assert loaded == data

    def test_write_creates_directory(self, tmp_path):
        """应自动创建父目录"""
        data = {"test": True}
        path = str(tmp_path / "subdir" / "nested" / "test.json")
        result = atomic_dump(data, path)
        assert result is True
        assert os.path.exists(path)

    def test_overwrite_existing(self, tmp_path):
        """应能覆盖已有文件"""
        path = str(tmp_path / "test.json")
        # 第一次写入
        atomic_dump({"v": 1}, path)
        # 第二次覆盖
        atomic_dump({"v": 2}, path)
        with open(path, 'r') as f:
            loaded = json.load(f)
        assert loaded == {"v": 2}

    def test_write_complex_data(self, tmp_path):
        """复杂数据结构应正确写入"""
        data = {
            "stocks": [
                {"code": "sh600000", "score": 90},
                {"code": "sh600001", "score": 85}
            ],
            "meta": {
                "generated_at": "2026-09-22",
                "version": "1.0"
            }
        }
        path = str(tmp_path / "complex.json")
        atomic_dump(data, path)
        with open(path, 'r') as f:
            loaded = json.load(f)
        assert loaded == data

    def test_write_empty_dict(self, tmp_path):
        """空字典应能写入"""
        path = str(tmp_path / "empty.json")
        atomic_dump({}, path)
        with open(path, 'r') as f:
            loaded = json.load(f)
        assert loaded == {}


class TestAtomicLoad:
    """原子读测试"""

    def test_basic_read(self, tmp_path):
        """基本读取应成功"""
        data = {"key": "value"}
        path = str(tmp_path / "test.json")
        atomic_dump(data, path)
        loaded = atomic_load(path)
        assert loaded == data

    def test_read_nonexistent(self, tmp_path):
        """读取不存在文件应返回default"""
        path = str(tmp_path / "missing.json")
        loaded = atomic_load(path, default={"fallback": True})
        assert loaded == {"fallback": True}

    def test_read_nonexistent_no_default(self, tmp_path):
        """无default时应返回空字典"""
        path = str(tmp_path / "missing.json")
        loaded = atomic_load(path)
        assert loaded == {}

    def test_read_corrupted_file(self, tmp_path):
        """损坏的文件应返回default"""
        path = str(tmp_path / "corrupted.json")
        with open(path, 'w') as f:
            f.write("{invalid json}")
        loaded = atomic_load(path, default={"safe": True})
        assert loaded == {"safe": True}

    def test_read_with_bom(self, tmp_path):
        """带BOM的文件应能正确读取"""
        path = str(tmp_path / "bom.json")
        data = {"test": True}
        with open(path, 'w', encoding='utf-8-sig') as f:
            json.dump(data, f)
        loaded = atomic_load(path)
        assert loaded == data


class TestUpdateJson:
    """更新测试"""

    def test_basic_update(self, tmp_path):
        """基本更新应生效"""
        path = str(tmp_path / "test.json")
        atomic_dump({"count": 0}, path)
        
        def increment(data):
            data["count"] += 1
            return data
        
        result = update_json(path, increment)
        assert result["count"] == 1
        # 验证文件已更新
        loaded = atomic_load(path)
        assert loaded["count"] == 1

    def test_update_creates_file(self, tmp_path):
        """文件不存在时应创建"""
        path = str(tmp_path / "new.json")
        
        def init(data):
            return {"initialized": True}
        
        result = update_json(path, init, default={})
        assert result == {"initialized": True}
        assert os.path.exists(path)

    def test_update_mutator_returns_none(self, tmp_path):
        """mutator返回None时应跳过写入"""
        path = str(tmp_path / "test.json")
        atomic_dump({"count": 10}, path)
        
        def skip_update(data):
            return None
        
        result = update_json(path, skip_update)
        assert result == {"count": 10}  # 未修改
        loaded = atomic_load(path)
        assert loaded["count"] == 10

    def test_update_nested_data(self, tmp_path):
        """嵌套数据结构应正确处理"""
        path = str(tmp_path / "nested.json")
        atomic_dump({
            "trades": [
                {"code": "sh600000", "action": "buy"},
                {"code": "sh600001", "action": "sell"}
            ]
        }, path)
        
        def add_trade(data):
            data["trades"].append({"code": "sh600002", "action": "buy"})
            return data
        
        result = update_json(path, add_trade)
        assert len(result["trades"]) == 3


class TestFileLock:
    """文件锁测试"""

    def test_lock_acquire_release(self, tmp_path):
        """应能正常获取和释放锁"""
        lock_path = str(tmp_path / "test.lock")
        lock = FileLock(lock_path, timeout=5)
        
        assert lock.acquire() is True
        lock.release()
        assert not os.path.exists(lock_path + ".lock")

    def test_lock_context_manager(self, tmp_path):
        """上下文管理器应正确加解锁"""
        lock_path = str(tmp_path / "ctx.lock")
        lock = FileLock(lock_path, timeout=5)
        
        with lock:
            assert os.path.exists(lock_path + ".lock")
        assert not os.path.exists(lock_path + ".lock")

    def test_lock_timeout(self, tmp_path):
        """锁超时应抛出异常"""
        lock_path = str(tmp_path / "timeout.lock")
        lock1 = FileLock(lock_path, timeout=0.1)
        lock2 = FileLock(lock_path, timeout=0.1)
        
        lock1.acquire()
        try:
            with pytest.raises(TimeoutError):
                lock2.acquire()
        finally:
            lock1.release()


class TestConcurrency:
    """并发安全测试"""

    def test_concurrent_writes(self, tmp_path):
        """并发写入应保持数据一致性"""
        path = str(tmp_path / "concurrent.json")
        atomic_dump({"count": 0}, path)
        
        errors = []
        
        def writer(thread_id):
            try:
                for i in range(10):
                    def update(data):
                        data["count"] += 1
                        data[f"thread_{thread_id}"] = i
                        return data
                    update_json(path, update)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        loaded = atomic_load(path)
        assert loaded["count"] == 50  # 5线程 × 10次


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
