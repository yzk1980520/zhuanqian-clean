#!/usr/bin/env python3

def _load_feishu_chat_id():
    """群ID单一配置源(2026-09-28 总管根治): 只改 仓库根/feishu_chat_id.txt 一处, 全脚本跟随。"""
    import os as _os
    d = _os.path.dirname(_os.path.abspath(__file__))
    if _os.path.basename(d) == "scripts":
        d = _os.path.dirname(d)
    try:
        with open(_os.path.join(d, "feishu_chat_id.txt"), encoding="utf-8") as _f:
            v = _f.read().strip()
            return v or "oc_100a06a1c71d5f8b1e58f1e420cadd1a"
    except Exception:
        return "oc_100a06a1c71d5f8b1e58f1e420cadd1a"
FEISHU_CHAT_ID = _load_feishu_chat_id()
# -*- coding: utf-8 -*-
"""
aoci_weekly_score.py — AOCI索引质量评分脚本
触发方式: Windows Task Scheduler（每周日21:00）

职责:
1. 计算索引覆盖率
2. 评估FRAS字段完整性
3. 生成质量评分报告
4. 推送飞书周报
"""
import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
INDEX_FILE = PROJECT_ROOT / "aoci.code.txt"
REPORT_DIR = PROJECT_ROOT / "mainline" / "docs" / "aoci-weekly"


def load_index() -> dict:
    """加载索引条目"""
    entries = {}
    if not INDEX_FILE.exists():
        return entries

    FRAS_PATTERN = re.compile(
        r'^([^\[]+)\[([A-Z]+[0-9T]+)\]:\s*'
        r'F:\s*([^|]+)\|\s*'
        r'R:\s*([^|]+)\|\s*'
        r'A:\s*([^|]+)\|\s*'
        r'S:\s*(.+)$'
    )

    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = FRAS_PATTERN.match(line)
            if match:
                filename, tag, func, requires, api, spec = match.groups()
                entries[os.path.basename(filename.strip())] = {
                    'tag': tag.strip(),
                    'func': func.strip(),
                    'requires': requires.strip(),
                    'api': api.strip(),
                    'spec': spec.strip(),
                    'complete': all([func.strip(), requires.strip(), api.strip(), spec.strip()])
                }
    return entries


def count_python_files() -> dict:
    """统计Python文件数量"""
    counts = {
        'root': 0,
        'scripts': 0,
        'tests': 0,
        'tdx_score': 0,
        'health_monitor': 0,
        'agents': 0,
        'total': 0
    }

    # 根目录
    for f in PROJECT_ROOT.glob('*.py'):
        if not f.name.startswith('.'):
            counts['root'] += 1
            counts['total'] += 1

    # scripts目录
    scripts_dir = PROJECT_ROOT / 'scripts'
    if scripts_dir.exists():
        for f in scripts_dir.glob('*.py'):
            if not f.name.startswith('.'):
                counts['scripts'] += 1
                counts['total'] += 1

    # tests目录
    tests_dir = PROJECT_ROOT / 'tests'
    if tests_dir.exists():
        for f in tests_dir.glob('test_*.py'):
            counts['tests'] += 1
            counts['total'] += 1

    # tdx_score目录
    tdx_dir = PROJECT_ROOT / 'tdx_score'
    if tdx_dir.exists():
        for f in tdx_dir.glob('*.py'):
            if not f.name.startswith('.'):
                counts['tdx_score'] += 1
                counts['total'] += 1
        for f in (tdx_dir / 'factors').glob('*.py'):
            counts['tdx_score'] += 1
            counts['total'] += 1

    # health_monitor目录
    hm_dir = PROJECT_ROOT / 'health_monitor'
    if hm_dir.exists():
        for f in hm_dir.glob('*.py'):
            if not f.name.startswith('.'):
                counts['health_monitor'] += 1
                counts['total'] += 1
        for subdir in ['checkers', 'reporters', 'self_healing']:
            subdir_path = hm_dir / subdir
            if subdir_path.exists():
                for f in subdir_path.glob('*.py'):
                    counts['health_monitor'] += 1
                    counts['total'] += 1

    # agents目录
    agents_dir = PROJECT_ROOT / 'agents'
    if agents_dir.exists():
        for f in agents_dir.glob('*.py'):
            if not f.name.startswith('.'):
                counts['agents'] += 1
                counts['total'] += 1

    return counts


def calculate_coverage(entries: dict, file_counts: dict) -> dict:
    """计算覆盖率"""
    total_files = file_counts['total']
    indexed_files = len(entries)

    # 核心文件覆盖
    core_files = ['integrated_picker.py', 'backtest/backtest_rotation.py', 'risk_rules.py', 'tdx_core.py']
    core_indexed = sum(1 for f in core_files if f in entries)

    # 测试文件覆盖
    test_files = [f for f in entries.keys() if f.startswith('test_')]
    test_total = file_counts['tests']

    # 健康监控覆盖
    hm_entries = {k: v for k, v in entries.items() if 'health_monitor' in k or k.startswith('health_')}
    hm_total = file_counts['health_monitor']

    # 完整性统计
    complete_entries = sum(1 for v in entries.values() if v.get('complete', False))

    return {
        'total_files': total_files,
        'indexed_files': indexed_files,
        'coverage_rate': f"{indexed_files/total_files*100:.1f}%" if total_files > 0 else "0%",
        'core_coverage': f"{core_indexed/len(core_files)*100:.1f}%" if core_files else "0%",
        'test_coverage': f"{len(test_files)/test_total*100:.1f}%" if test_total > 0 else "0%",
        'hm_coverage': f"{len(hm_entries)/hm_total*100:.1f}%" if hm_total > 0 else "0%",
        'completeness_rate': f"{complete_entries/indexed_files*100:.1f}%" if indexed_files > 0 else "0%",
        'core_indexed': f"{core_indexed}/{len(core_files)}",
        'test_indexed': f"{len(test_files)}/{test_total}",
        'hm_indexed': f"{len(hm_entries)}/{hm_total}"
    }


def generate_report(entries: dict, file_counts: dict, coverage: dict) -> dict:
    """生成质量评分报告"""
    report = {
        'timestamp': datetime.now().isoformat(),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'week': f"第{datetime.now().isocalendar()[1]}周",
        'summary': {
            'total_entries': len(entries),
            'total_files': file_counts['total'],
            'coverage_rate': coverage['coverage_rate'],
            'completeness_rate': coverage['completeness_rate']
        },
        'coverage_details': coverage,
        'file_counts': file_counts,
        'recommendations': []
    }

    # 生成建议
    if float(coverage['coverage_rate'].replace('%', '')) < 50:
        report['recommendations'].append({
            'priority': 'high',
            'message': '索引覆盖率低于50%，建议优先补充核心文件'
        })

    if float(coverage['test_coverage'].replace('%', '')) < 50:
        report['recommendations'].append({
            'priority': 'medium',
            'message': '测试文件覆盖不足，建议补充tests/目录下的测试文件'
        })

    if float(coverage['completeness_rate'].replace('%', '')) < 90:
        report['recommendations'].append({
            'priority': 'high',
            'message': '索引完整性低于90%，建议检查缺失字段'
        })

    if not report['recommendations']:
        report['recommendations'].append({
            'priority': 'info',
            'message': '索引质量良好，继续保持'
        })

    return report


def save_report(report: dict):
    """保存报告"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORT_DIR / f"aoci_weekly_{datetime.now().strftime('%Y%m%d')}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report_file


def send_feishu_weekly(report: dict):
    """推送飞书周报"""
    try:
        import subprocess
        lark_cli = r"D:\npm-global\lark-cli.cmd"
        chat_id = FEISHU_CHAT_ID

        message = f"📊 [AOCI周报] {report['date']} {report['week']}\n\n"
        message += f"索引覆盖: {report['summary']['coverage_rate']} ({report['summary']['total_entries']}/{report['summary']['total_files']})\n"
        message += f"完整性: {report['summary']['completeness_rate']}\n\n"

        message += "【覆盖率详情】\n"
        message += f"- 核心文件: {report['coverage_details']['core_coverage']} ({report['coverage_details']['core_indexed']})\n"
        message += f"- 测试文件: {report['coverage_details']['test_coverage']} ({report['coverage_details']['test_indexed']})\n"
        message += f"- 监控模块: {report['coverage_details']['hm_coverage']} ({report['coverage_details']['hm_indexed']})\n\n"

        message += "【建议】\n"
        for rec in report['recommendations']:
            emoji = {'high': '🔴', 'medium': '🟡', 'low': '🔵', 'info': '🟢'}.get(rec['priority'], 'ℹ️')
            message += f"{emoji} {rec['message']}\n"

        result = subprocess.run(
            [lark_cli, 'im', '+messages-send', '--text', '-',
             '--chat-id', chat_id, '--as', 'user'],
            input=message,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=30
        )

        return result.returncode == 0
    except Exception as e:
        print(f"飞书推送失败: {e}", file=sys.stderr)
        return False


def main():
    """主入口"""
    print(f"[{datetime.now()}] Starting AOCI weekly score...")

    # 1. 加载索引
    entries = load_index()
    print(f"   Loaded {len(entries)} entries")

    # 2. 统计文件
    file_counts = count_python_files()
    print(f"   Total: {file_counts['total']} files")

    # 3. 计算覆盖率
    coverage = calculate_coverage(entries, file_counts)

    # 4. 生成报告
    report = generate_report(entries, file_counts, coverage)

    # 5. 保存报告
    report_file = save_report(report)
    print(f"   Saved to: {report_file}")

    # 6. 推送飞书
    send_feishu_weekly(report)

    # 7. 输出结果

    return 0


if __name__ == '__main__':
    sys.exit(main())
