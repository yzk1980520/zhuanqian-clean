#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aoci_rebuild_index.py — 修复AOCI索引格式

修复多行条目问题，确保每条记录单行化
"""
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
INDEX_FILE = PROJECT_ROOT / "aoci.code.txt"

def is_entry_start(line):
    """判断是否是新条目开始"""
    return bool(re.match(r'^[^\s\[]+[a-zA-Z_][a-zA-Z0-9_]*\.py\[', line))

def extract_tag(line):
    """从行中提取标签"""
    match = re.search(r'\[([A-Z]+)(\d+T)\]', line)
    return match.group(0) if match else "[UNK]"

def normalize_line(line):
    """规范化单行条目"""
    line = line.strip()
    if not line or line.startswith('#') or line.startswith('====='):
        return None
    
    # 确保以 .py[ 开头（如果可能）
    if '.py[' not in line and not line.startswith('_') and not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*\.py\[', line):
        # 可能是描述行，跳过
        return None
    
    # 清理尾部
    line = re.sub(r'\s+$', '', line)
    
    # 确保FRAS格式完整
    if not re.search(r'\| F:', line):
        # 缺少FRAS字段，跳过或标记
        pass
    
    return line

def main():
    
    # 读取原始索引
    raw_content = INDEX_FILE.read_text(encoding='utf-8')
    lines = raw_content.split('\n')
    
    # 解析条目
    entries = []
    current_entry = None
    current_path = None
    
    for line in lines:
        # 检测新条目开始
        if is_entry_start(line):
            if current_entry:
                entries.append(current_entry)
            current_entry = line
            current_path = re.match(r'^([^\[]+)', line).group(1) if re.match(r'^([^\[]+)', line) else None
        elif current_entry and line.strip():
            # 续行
            if line.startswith('#') or line.startswith('='):
                continue  # 跳过注释和分隔线
            # 追加到当前条目
            current_entry += ' ' + line.strip()
    
    if current_entry:
        entries.append(current_entry)
    
    # 清理并去重
    cleaned = []
    seen = set()
    for entry in entries:
        entry = normalize_line(entry)
        if entry and entry not in seen:
            seen.add(entry)
            cleaned.append(entry)
    
    # 写回
    header = [
        '#AOCI-CODE-VOLUME: 1',
        '#Auto-rebuilt by aoci_rebuild_index.py',
        f'#Timestamp: {Path(__file__).parent.parent.name}',
        '',
    ]
    
    new_content = header + cleaned
    INDEX_FILE.write_text('\n'.join(new_content) + '\n', encoding='utf-8')
    
    print(f"\n✅ 修复完成")
    print(f"   原始行数: {len(lines)}")
    print(f"   条目数: {len(entries)}")
    print(f"   清理后: {len(cleaned)}")
    print(f"   输出文件: {INDEX_FILE}")

if __name__ == '__main__':
    main()
