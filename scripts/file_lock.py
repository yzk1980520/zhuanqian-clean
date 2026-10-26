#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件锁工具
解决Windows下的文件竞争问题
"""
import os
import time
import tempfile
from pathlib import Path
from contextlib import contextmanager
from typing import Generator


class FileLock:
    """跨平台文件锁"""
    
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.pid = os.getpid()
    
    def acquire(self, timeout: float = 30.0) -> bool:
        """
        获取文件锁
        
        Args:
            timeout: 超时时间（秒）
        
        Returns:
            是否成功获取锁
        """
        start_time = time.time()
        
        while True:
            try:
                # 尝试创建锁文件
                if self.lock_path.exists():
                    # 检查是否是死锁
                    lock_age = time.time() - self.lock_path.stat().st_mtime
                    if lock_age > timeout:
                        print(f"⚠️ 检测到死锁（{lock_age:.1f}秒），强制清除")
                        self.lock_path.unlink()
                    else:
                        # 还在等待
                        if time.time() - start_time > timeout:
                            return False
                        time.sleep(0.1)
                        continue
                
                # 创建锁文件
                with open(self.lock_path, 'w') as f:
                    f.write(str(self.pid))
                
                return True
                
            except Exception as e:
                print(f"❌ 获取文件锁失败: {e}")
                return False
    
    def release(self):
        """释放文件锁"""
        try:
            if self.lock_path.exists():
                # 检查是否是自己的锁
                with open(self.lock_path, 'r') as f:
                    lock_pid = f.read().strip()
                
                if lock_pid == str(self.pid):
                    self.lock_path.unlink()
        except Exception as e:
            print(f"❌ 释放文件锁失败: {e}")


@contextmanager
def locked_file(file_path: Path, timeout: float = 30.0) -> Generator[None, None, None]:
    """
    带文件锁的文件操作上下文管理器
    
    Args:
        file_path: 目标文件路径
        timeout: 锁超时时间
    
    Yields:
        文件路径
    """
    lock_path = file_path.with_suffix('.lock')
    lock = FileLock(lock_path)
    
    if not lock.acquire(timeout):
        raise TimeoutError(f"无法获取文件锁: {file_path}")
    
    try:
        yield file_path
    finally:
        lock.release()


def read_locked(file_path: Path, timeout: float = 30.0) -> str:
    """读取带锁的文件"""
    with locked_file(file_path, timeout) as fpath:
        with open(fpath, 'r', encoding='utf-8') as f:
            return f.read()


def write_locked(file_path: Path, content: str, timeout: float = 30.0):
    """写入带锁的文件"""
    with locked_file(file_path, timeout) as fpath:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
