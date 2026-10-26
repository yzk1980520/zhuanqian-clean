#!/usr/bin/env python3
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
atomic_json.py — JSON原子读写工具(防并发覆盖/丢失)
提供:
- FileLock: 跨进程文件锁(Windows msvcrt)
- atomic_dump: 原子写(临时文件+os.replace)
- update_json: 读-改-写全程加锁(真正防并发丢失)
所有trade_log/holdings等关键数据文件的写操作都应使用本工具
"""
import json, os, tempfile, threading
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import msvcrt  # Windows文件锁
except ImportError:
    msvcrt = None

# 进程内锁
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


class FileLock:
    """跨进程文件锁(基于锁文件+msvcrt)"""

    def __init__(self, path, timeout=15):
        self.lock_path = path + ".lock"
        self.timeout = timeout
        self._fh = None

    def acquire(self):
        import time
        deadline = time.time() + self.timeout
        while True:
            try:
                self._fh = open(self.lock_path, "w")
                if msvcrt:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except (OSError, PermissionError):
                if self._fh:
                    try:
                        self._fh.close()
                    except Exception:
                        pass
                    self._fh = None
                if time.time() > deadline:
                    raise TimeoutError(f"获取文件锁超时: {self.lock_path}")
                time.sleep(0.1)

    def release(self):
        try:
            if self._fh and msvcrt:
                try:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            if self._fh:
                self._fh.close()
                self._fh = None
            try:
                os.unlink(self.lock_path)
            except Exception:
                pass
        except Exception:
            pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


def _get_thread_lock(path):
    with _LOCKS_GUARD:
        if path not in _LOCKS:
            _LOCKS[path] = threading.Lock()
        return _LOCKS[path]


def atomic_dump(data, path, encoding="utf-8", indent=2, ensure_ascii=False,
                default=None, **kwargs):
    """原子写入JSON: 临时文件+fsync+os.replace+目录fsync(真正防断电丢失)
    R5 (2026-08-31): 增加 fsync 保证 tempfile 内容落盘, 并对目录 fsync 保证
    rename 元数据落盘; 任何一步失败清理 tmp 并抛出。
    跨进程读-改-写请改用 update_json(内含 FileLock)。
    """
    path = os.path.abspath(path)
    lock = _get_thread_lock(path)
    with lock:
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        tmp_dir_fd = None
        try:
            with os.fdopen(fd, "w", encoding=encoding) as f:
                json.dump(data, f, ensure_ascii=ensure_ascii,
                          indent=indent, default=default, **kwargs)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    # 某些文件系统/平台不支持 fsync, 降级但不阻断
                    pass
            # 先替换(原子), 再 fsync 目录以落盘 rename 元数据
            os.replace(tmp, path)
            try:
                # Windows: os.open 支持 O_DIRECTORY 不通用, 直接尝试
                tmp_dir_fd = os.open(d, os.O_RDONLY)
                os.fsync(tmp_dir_fd)
            except OSError:
                pass
        finally:
            if tmp_dir_fd is not None:
                try:
                    os.close(tmp_dir_fd)
                except Exception:
                    pass
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
    return True


# R5 兼容别名: 部分旧脚本用 atomic_json(path, data) 或 dump(path, data) 风格
atomic_json = atomic_dump
dump = atomic_dump


def atomic_load(path, default=None, encoding="utf-8-sig"):
    """读取JSON (utf-8-sig 兼容BOM, 2026-08-16: channel.json曾带BOM导致读失败被R4拦截)"""
    try:
        with open(path, "r", encoding=encoding) as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def update_json(path, mutator, default=None):
    """读-改-写(跨进程文件锁+原子写): mutator(data)返回新data
    用法: update_json('trade_log.json', lambda d: (d['buys'].append(x), d)[1])
    R3 防护: mutator 返回 None 视为"放弃修改"(跳过), 不写文件, 返回原 data。
    否则 atomic_dump(None) 会把 JSON 文件写成 null 损坏数据。
    R4 防护 (2026-08-16 台账丢失教训): 文件存在但读取失败(损坏/编码)
    → 抛 RuntimeError, 禁止静默用 default 覆盖写丢历史数据。
    不依赖 atomic_load 的 default 信号(读失败且default=None时其返回{}无法区分),
    显式: 文件不存在→default初始化; 存在但json.load失败→抛错。
    """
    path = os.path.abspath(path)
    with FileLock(path):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except Exception as e:
                raise RuntimeError(
                    f"update_json 读取失败({path}): {e} — 拒绝用 default 覆盖, 请人工检查")
        else:
            data = default if default is not None else {}
        new_data = mutator(data)
        if new_data is None:
            return data  # 放弃修改, 不写
        atomic_dump(new_data, path)
        return new_data


if __name__ == "__main__":
    # 自测
    import tempfile as tf
    t = os.path.join(tf.gettempdir(), "atomic_test.json")
    atomic_dump({"a": [1, 2, 3]}, t)
    print("✅ 原子写OK:", atomic_load(t))
    os.unlink(t)
