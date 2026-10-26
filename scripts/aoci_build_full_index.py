#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aoci_build_full_index.py — 全量AOCI索引构建脚本

职责:
1. 扫描所有Python文件
2. 自动提取FRAS元数据并生成标签
3. 重建aoci.code.txt完整索引
4. 输出索引统计报告

用法: python scripts/aoci_build_full_index.py [--dry-run] [--verbose]
"""
import os
import sys
import re
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
INDEX_FILE = PROJECT_ROOT / "aoci.code.txt"
META_FILE = PROJECT_ROOT / "aoci.meta.txt"
REPORT_FILE = PROJECT_ROOT / ".aoci" / f"full_index_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

# 排除目录
EXCLUDE_DIRS = {
    '.venv', '__pycache__', '.git', '.hermes', 'data', 'logs',
    'scripts/.venv', 'mainline/docs', '.scratch', '.agent'
}

# 核心模块优先级映射
PRIORITY_MAP = {
    'integrated_picker': 'P0',
    'backtest_rotation': 'P0',
    'risk_rules': 'P0',
    'tdx_core': 'P0',
    'positioner': 'P0',
    'config_loader': 'P1',
    'tdx_indicators': 'P1',
    'tdx_strategies': 'P1',
    'data_pipeline': 'P1',
    'factor_gate': 'P1',
    'orchestrator': 'P1',
    'evolution_v2': 'P1',
    'health_monitor': 'P1',
    'auto_review': 'P1',
    'jevonian_scorer': 'P1',
}

# 文件类型映射
FILE_TYPE_MAP = {
    'test_': 'PQ',  # 测试
    'mock_': 'PQ',  # 模拟
    '_test.py': 'PQ',
    'report_': 'CO',  # 报告
    'dashboard_': 'CO',
    'manual_': 'AO',  # 文档
    '_util.py': 'BG',  # 工具
    '_helper.py': 'BG',
    'config_': 'BG',
    'constants': 'BG',
}

# 领域逻辑前缀
DOMAIN_PREFIXES = [
    'backtest_', 'factor_', 'score_', 'pick_', 'trade_',
    'position_', 'risk_', 'market_', 'news_', 'web_',
    'aoci_', 'admin_', 'monitor_',
]


def is_core_file(filepath: str) -> bool:
    """判断是否为核心文件"""
    base = os.path.basename(filepath).replace('.py', '')
    return base in PRIORITY_MAP or any(p in base for p in DOMAIN_PREFIXES)


def extract_metadata(filepath: str) -> Optional[Dict]:
    """从Python文件提取FRAS元数据"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read(3000)
    except Exception:
        print(f"🔴 [scripts\aoci_build_full_index.py] CR-01(return): except Exception:", file=sys.stderr)
        return None
    # 提取文档字符串
    doc_match = re.search(r'"""(.+?)"""', content, re.DOTALL)
    doc = doc_match.group(1).strip() if doc_match else ""

    # 提取类
    classes = re.findall(r'class\s+(\w+)', content)

    # 提取函数
    functions = re.findall(r'def\s+(\w+)\s*\(', content)

    # 提取导入
    imports = re.findall(r'from\s+(\S+)\s+import', content)
    imports += re.findall(r'import\s+(\S+)', content)
    imports = list(set(imports[:5]))  # 去重取前5

    # 生成标签
    tag = generate_tag(filepath, classes, functions)

    # 生成职责描述
    func_desc = extract_function_description(content, doc)

    # 生成API摘要
    api_list = functions[:3] if functions else []

    # 生成规格说明
    spec = generate_spec(doc, classes, functions)

    return {
        'tag': tag,
        'func': func_desc[:80] if func_desc else '待补充',
        'requires': ', '.join(imports) if imports else '-',
        'api': ', '.join(api_list) if api_list else '-',
        'spec': spec[:60] if spec else '待补充',
        'classes': classes,
        'functions': functions,
        'imports': imports,
    }


def generate_tag(filepath: str, classes: List[str], functions: List[str]) -> str:
    """生成FRAS标签"""
    base = os.path.basename(filepath).replace('.py', '')

    # 确定前缀
    prefix = 'AO'  # 默认文档
    for pattern, pfx in FILE_TYPE_MAP.items():
        if pattern in base:
            prefix = pfx
            break

    # 领域前缀覆盖
    if is_core_file(filepath):
        prefix = 'BD'  # 核心业务

    # 确定等级
    total_defs = len(classes) + len(functions)
    if total_defs >= 5:
        level = '7T'  # 核心
    elif total_defs >= 3:
        level = '6T'  # 重要
    elif total_defs >= 1:
        level = '5T'  # 辅助
    else:
        level = '4T'  # 轻微

    return f"{prefix}{level}"


def extract_function_description(content: str, doc: str) -> str:
    """从文档字符串或代码推断职责描述"""
    if doc:
        # 寻找职责相关行
        for line in doc.split('\n'):
            line = line.strip()
            if any(kw in line for kw in ['职责:', '功能:', '用途:', '说明:', '简介:']):
                return line.split(':', 1)[-1].strip()[:80]
        # 返回第一行非空内容
        for line in doc.split('\n'):
            line = line.strip()
            if line and len(line) > 5:
                return line[:80]
    return "待补充"


def generate_spec(doc: str, classes: List[str], functions: List[str]) -> str:
    """生成功能规格说明"""
    if doc:
        for line in doc.split('\n'):
            line = line.strip()
            if any(kw in line for kw in ['参数:', '返回:', '注意:', '警告:']):
                return line[:60]
        return doc[:60]

    if classes:
        return f"{classes[0]}类实现"
    if functions:
        return f"{functions[0]}函数实现"
    return "待分析"


def scan_python_files(root: Path) -> List[str]:
    """扫描所有Python文件"""
    files = []
    for py_file in root.rglob('*.py'):
        # 检查是否在排除目录中
        rel_path = py_file.relative_to(root)
        parts = rel_path.parts
        if any(part in EXCLUDE_DIRS for part in parts):
            continue
        files.append(str(rel_path))
    return sorted(files)


def build_index(files: List[str], verbose: bool = False) -> Tuple[Dict[str, Dict], int]:
    """构建索引"""
    entries = {}
    stats = {
        'total': len(files),
        'indexed': 0,
        'failed': 0,
        'by_priority': {'P0': 0, 'P1': 0, 'P2': 0, 'P3': 0, 'P4': 0, 'P5': 0, 'P6': 0},
        'by_type': {},
    }

    for filepath in files:
        full_path = root / filepath
        if not full_path.exists():
            continue

        metadata = extract_metadata(str(full_path))
        if not metadata:
            stats['failed'] += 1
            if verbose:
                print(f"  ❌ 失败: {filepath}")
            continue

        filename = os.path.basename(filepath)
        tag = metadata['tag']

        # 统计
        stats['indexed'] += 1
        priority = determine_priority(filepath)
        stats['by_priority'][priority] = stats['by_priority'].get(priority, 0) + 1

        # 按类型统计
        prefix = tag[:2]
        stats['by_type'][prefix] = stats['by_type'].get(prefix, 0) + 1

        # 生成索引行
        entry_line = (
            f"{filepath}[{tag}]: "
            f"F:{metadata['func']} | "
            f"R:{metadata['requires']} | "
            f"A:{metadata['api']} | "
            f"S:{metadata['spec']}"
        )

        entries[filepath] = {
            'tag': tag,
            'func': metadata['func'],
            'requires': metadata['requires'],
            'api': metadata['api'],
            'spec': metadata['spec'],
            'line': entry_line,
            'priority': priority,
            'classes': metadata['classes'],
            'functions': metadata['functions'],
        }

        if verbose:
            status = "✅" if priority in ['P0', 'P1'] else "⚪"
            print(f"  {status} {filepath} [{tag}] P{priority}")

    return entries, stats


def determine_priority(filepath: str) -> str:
    """确定文件优先级"""
    base = os.path.basename(filepath).replace('.py', '')
    if base in PRIORITY_MAP:
        return PRIORITY_MAP[base]
    if is_core_file(filepath):
        return 'P1'
    if 'test_' in base or '_test.py' in base:
        return 'P4'
    return 'P3'


def save_index(entries: Dict[str, Dict]):
    """保存索引到aoci.code.txt"""
    header = [
        '#AOCI-CODE-VOLUME: 1',
        '#Auto-generated by aoci_build_full_index.py',
        f'#Timestamp: {datetime.now().isoformat()}',
        '',
    ]

    lines = header.copy()
    # 按优先级排序
    priority_order = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3, 'P4': 4, 'P5': 5, 'P6': 6}
    sorted_entries = sorted(
        entries.items(),
        key=lambda x: priority_order.get(x[1]['priority'], 9)
    )

    for filepath, entry in sorted_entries:
        lines.append(entry['line'])

    INDEX_FILE.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"\n✅ 索引已保存到: {INDEX_FILE}")
    print(f"   总条目: {len(entries)}")


def save_report(stats: Dict, entries: Dict[str, Dict]):
    """保存详细报告"""
    report = {
        'timestamp': datetime.now().isoformat(),
        'stats': stats,
        'entries_summary': {
            k: {
                'tag': v['tag'],
                'priority': v['priority'],
                'func': v['func'][:50],
            }
            for k, v in entries.items()
        },
    }

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n📊 详细报告已保存到: {REPORT_FILE}")
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description='全量AOCI索引构建')
    parser.add_argument('--dry-run', action='store_true', help='仅扫描不保存')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    args = parser.parse_args()

    global root
    root = PROJECT_ROOT

    print(f"\n项目根目录: {root}")
    print(f"索引文件: {INDEX_FILE}")

    # 扫描文件
    files = scan_python_files(root)
    print(f"   找到 {len(files)} 个Python文件")

    if not files:
        return

    # 构建索引
    entries, stats = build_index(files, verbose=args.verbose)

    # 输出统计
    print(f"   总文件数: {stats['total']}")
    print(f"   成功索引: {stats['indexed']}")
    print(f"   索引失败: {stats['failed']}")
    print(f"\n   优先级分布:")
    for p in ['P0', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6']:
        count = stats['by_priority'].get(p, 0)
        if count > 0:
            bar = '█' * (count // 5) if count >= 5 else '█' * count
            print(f"      {p}: {count:3d} {bar}")

    print(f"\n   类型分布:")
    for t in sorted(stats['by_type'].keys()):
        count = stats['by_type'][t]
        print(f"      {t}: {count:3d}")

    if args.dry_run:
        return

    # 保存索引
    save_index(entries)

    # 保存报告
    report = save_report(stats, entries)



if __name__ == '__main__':
    main()
