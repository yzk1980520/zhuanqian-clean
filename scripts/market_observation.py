# -*- coding: utf-8 -*-
"""
市场观察期监控脚本 - 9/24~9/28
每日检查市场状态变化，生成观察报告
"""

import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data'
DOCS_DIR = PROJECT_ROOT / 'docs'


def check_market_status():
    """检查当前市场状态"""
    signal_file = DATA_DIR / 'daily_signal.json'
    if signal_file.exists():
        with open(signal_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def run_picker_scan():
    """运行选股扫描"""
    cmd = ['python3', 'integrated_picker.py', '--scan']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(PROJECT_ROOT))
        return result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
    except Exception as e:
        return f"扫描失败: {e}"


def generate_daily_report(date_str, market_score, top_candidates):
    """生成日度观察报告"""
    report = {
        'date': date_str,
        'market_score': market_score,
        'status': '观察期',
        'top_candidates': top_candidates,
        'recommendation': '继续观望，等待信号强化'
    }
    
    report_file = DOCS_DIR / f'observation_{date_str}.json'
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    return report


def main():
    print(f"\n{'='*60}")
    print(f"市场观察期监控 - {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*60}\n")
    
    # 检查市场状态
    signal = check_market_status()
    if signal:
        score = signal.get('market_score', 'N/A')
        gate = signal.get('gate', {})
        print(f"📊 市场评分: {score}/100")
        print(f"🚪 环境门: {gate.get('status', 'N/A')}")
        print(f"💼 仓位建议: {gate.get('position_ratio', 'N/A')}")
    else:
        pass
    # 运行扫描获取TOP候选
    scan_result = run_picker_scan()
    
    # 保存报告
    today = datetime.now().strftime('%Y%m%d')
    report = generate_daily_report(today, score, [])
    
    print(f"\n✅ 观察报告已保存: docs/observation_{today}.json")
    print(f"\n📅 下次评估: 9月28日(冷却期满)")
    print(f"{'='*60}\n")
    
    return 0


if __name__ == '__main__':
    main()
