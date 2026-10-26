#!/usr/bin/env python3
"""
公共工具模块 - AtomCode集成
提供跨平台路径查找、日志记录等通用功能
"""

import os
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

# 配置日志
logger = logging.getLogger(__name__)

# 默认超时配置
DEFAULT_TIMEOUT = 180  # 秒
COMPLEX_ANALYSIS_TIMEOUT = 300  # 秒
STANDARD_TIMEOUT = 60  # 秒


def find_atomcode() -> Optional[str]:
    """
    跨平台查找AtomCode可执行文件
    
    Returns:
        AtomCode路径，如果未找到返回None
    """
    # 1. PATH中查找
    path_found = shutil.which("atomcode")
    if path_found:
        logger.debug(f"在PATH中找到AtomCode: {path_found}")
        return path_found
    
    # 2. Windows常见安装位置
    if os.name == 'nt':
        candidates = [
            Path.home() / "AppData" / "Roaming" / "npm" / "atomcode.cmd",
            Path.home() / ".atomcode" / "bin" / "atomcode.exe",
            Path("C:/Users") / Path.home().name / "AppData" / "Roaming" / "npm" / "atomcode.cmd",
        ]
    else:
        pass
        # 3. Linux/Mac常见安装位置
        candidates = [
            Path("/usr/local/bin/atomcode"),
            Path("/opt/atomcode/bin/atomcode"),
            Path.home() / ".local" / "bin" / "atomcode",
            Path.home() / ".atomcode" / "bin" / "atomcode",
        ]
    
    for candidate in candidates:
        if candidate.exists():
            logger.debug(f"找到AtomCode: {candidate}")
            return str(candidate)
    
    logger.warning("未找到AtomCode，请确保已安装: npm install -g @atomcode/cli")
    return None


def validate_api_key(key: str) -> bool:
    """
    验证API Key格式
    
    Args:
        key: API Key字符串
    
    Returns:
        是否有效
    """
    # 华泰API Key格式: ht_开头的44字符字符串
    if not key.startswith("ht_"):
        logger.warning(f"API Key格式错误: 应以ht_开头，当前: {key[:8]}...")
        return False
    if len(key) != 44:
        logger.warning(f"API Key长度错误: 应为44字符，当前: {len(key)}字符")
        return False
    return True


def ensure_directory(path: Path) -> None:
    """确保目录存在"""
    path.mkdir(parents=True, exist_ok=True)


def safe_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    安全写入文件（原子写）
    
    Args:
        path: 目标路径
        content: 内容
        encoding: 编码
    """
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temp_path.write_text(content, encoding=encoding)
        temp_path.replace(path)
        logger.debug(f"文件已写入: {path}")
    except Exception as e:
        logger.error(f"文件写入失败: {path}, 错误: {e}")
        raise


def parse_jsonl_line(line: str) -> Optional[Dict[str, Any]]:
    """
    安全解析JSONL行
    
    Args:
        line: JSONL行
    
    Returns:
        解析后的字典，失败返回None
    """
    import json
    line = line.strip()
    if not line.startswith('{'):
        return None
    
    try:
        return json.loads(line)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON解析失败: {e}, 内容: {line[:100]}")
        return None
