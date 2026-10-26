#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py dispatch

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
aoci_daily_check.py — AOCI每日巡检脚本
触发方式: Windows Task Scheduler / cron

职责:
1. 运行aoci check检测漂移
2. 扫描新增Python文件
3. 检查索引完整性
4. 生成日报并推送飞书
"""
import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# 项目根目录（脚本在scripts/子目录，需要向上一级）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
AOCI_EXE = Path(r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\bin\aoci.exe")
INDEX_FILE = PROJECT_ROOT / "aoci.code.txt"
DRIFT_LOG = PROJECT_ROOT / ".aoci" / "drift_daily.json"
REPORT_DIR = PROJECT_ROOT / "mainline" / "docs" / "aoci-daily"


def run_aoci_check() -> dict:
    """运行aoci check命令"""
    try:
        import subprocess
        aoci_exe = AOCI_EXE_PATH
        result = subprocess.run(
            [aoci_exe, '--repo', '.', 'check'],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=60
        )
        return {
            'exit_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr
        }
    except Exception as e:
        return {
            'exit_code': -1,
            'stdout': '',
            'stderr': str(e)
        }


def scan_new_files() -> list:
    """扫描未索引的Python文件"""
    indexed_files = set()
    if INDEX_FILE.exists():
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('#') or not line.strip():
                    continue
                # 提取文件名（第一个[之前的部分）
                match = line.split('[')[0].strip()
                if match and match.endswith('.py'):
                    indexed_files.add(match)

    # 扫描项目Python文件
    scanned = []
    for py_file in PROJECT_ROOT.glob('*.py'):
        if py_file.name not in indexed_files and not py_file.name.startswith('.'):
            scanned.append(str(py_file))

    for py_dir in ['tdx_score', 'health_monitor', 'agents', 'scripts']:
        dir_path = PROJECT_ROOT / py_dir
        if dir_path.exists():
            for py_file in dir_path.glob('*.py'):
                if py_file.name not in indexed_files and not py_file.name.startswith('.'):
                    scanned.append(str(py_file))

    return scanned


def check_index_completeness() -> dict:
    """检查索引完整性"""
    if not INDEX_FILE.exists():
        return {'status': 'error', 'message': '索引文件不存在'}

    entries = 0
    complete = 0
    issues = []

    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            entries += 1

            # 检查是否包含所有FRAS字段
            if all(field in line for field in ['F:', 'R:', 'A:', 'S:']):
                complete += 1
            else:
                issues.append({
                    'line': line[:80],
                    'missing_fields': [f for f in ['F:', 'R:', 'A:', 'S:'] if f not in line]
                })

    return {
        'status': 'ok' if len(issues) < 5 else 'warning',
        'total_entries': entries,
        'complete_entries': complete,
        'completeness_rate': f"{complete/entries*100:.1f}%" if entries > 0 else "0%",
        'issues_count': len(issues)
    }


def generate_daily_report(drift_result: dict, new_files: list, completeness: dict) -> dict:
    """生成日报"""
    report = {
        'timestamp': datetime.now().isoformat(),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'aoci_check': drift_result,
        'new_files_count': len(new_files),
        'new_files': new_files[:10],  # 最多显示10个
        'index_completeness': completeness,
        'action_required': len(new_files) > 0 or completeness['issues_count'] > 5
    }

    # 保存报告
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORT_DIR / f"aoci_daily_{datetime.now().strftime('%Y%m%d')}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report


def send_feishu_notification(report: dict):
    """推送飞书通知"""
    try:
        import subprocess
        # 使用环境变量配置的路径
        lark_cli = os.environ.get('LARK_CLI', r"D:\npm-global\lark-cli.cmd")
        chat_id = FEISHU_CHAT_ID

        # 构建消息
        message = f"📊 [AOCI每日巡检] {report['date']}\n\n"

        # 索引完整性
        completeness = report['index_completeness']
        message += f"索引完整性: {completeness['completeness_rate']} ({completeness['total_entries']}条)\n"

        # 新增文件
        if report['new_files_count'] > 0:
            message += f"新增文件: {report['new_files_count']}个需索引\n"
        else:
            message += "新增文件: 0个\n"

        # 问题数量
        if completeness['issues_count'] > 0:
            message += f"完整性问题: {completeness['issues_count']}项\n"
        else:
            message += "完整性问题: 无\n"

        # 操作建议
        if report['action_required']:
            message += "\n⚠️ 建议: 运行 `python scripts/aoci_auto_maintain.py` 更新索引"
        else:
            message += "\n✅ 状态: 正常"

        # 发送
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
    print(f"[{datetime.now()}] Starting AOCI daily check...")

    # 1. 运行aoci check
    drift_result = run_aoci_check()
    print(f"   Exit code: {drift_result['exit_code']}")
    if drift_result['stdout']:
        print(f"   Output: {drift_result['stdout'][:200]}")

    # 2. 扫描新增文件
    new_files = scan_new_files()
    print(f"   Found {len(new_files)} unindexed files")

    # 3. 检查索引完整性
    completeness = check_index_completeness()
    print(f"   Rate: {completeness['completeness_rate']}")

    # 4. 生成日报
    report = generate_daily_report(drift_result, new_files, completeness)

    # 5. 推送通知（如果有问题）
    if report['action_required']:
        send_feishu_notification(report)

    # 6. 输出结果

    # 返回退出码（用于cron）
    sys.exit(0 if not report['action_required'] else 1)


if __name__ == '__main__':
    main()
