#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冷却期满评估脚本 - 9/28自动执行
"""

import json
import subprocess
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data'
LOG_DIR = PROJECT_ROOT / 'logs'
COOLDOWN_FILE = DATA_DIR / 'cooldown.json'


def load_cooldown():
    if COOLDOWN_FILE.exists():
        with open(COOLDOWN_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def run_full_scan():
    """运行完整选股扫描"""
    cmd = ['python3', 'integrated_picker.py', '--scan']
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT)
        )
        return {
            'success': result.returncode == 0,
            'output': result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout,
            'error': result.stderr
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def check_signal_strength(scan_result: dict) -> dict:
    """检查信号强度"""
    if not scan_result['success']:
        return {'strength': 'error', 'message': '扫描失败'}
    
    output = scan_result['output']
    
    # 解析市场评分
    market_score = None
    for line in output.split('\n'):
        if '综合评分:' in line or '市场量化' in line:
            try:
                parts = line.split(':')
                if len(parts) > 1:
                    market_score = float(parts[-1].strip().split('/')[0].strip())
                    break
            except AttributeError:
                print(f"🔴 [scripts\cooldown_eval.py] CR-01: except AttributeError:", file=sys.stderr)
    # 解析TOP1候选
    top_candidate = None
    for line in output.split('\n'):
        if '#1' in line and 'sh' in line:
            parts = line.split()
            if len(parts) >= 3:
                top_candidate = {
                    'code': parts[1],
                    'name': parts[2],
                    'score': None
                }
                # 查找评分
                for next_line in output.split('\n')[output.split('\n').index(line)+1:output.split('\n').index(line)+3]:
                    if '综合' in next_line or '分' in next_line:
                        try:
                            top_candidate['score'] = float(next_line.split(':')[1].strip())
                            break
                        except AttributeError:
                            print(f"🔴 [scripts\cooldown_eval.py] CR-01: except AttributeError:", file=sys.stderr)
            break
    
    # 判断信号强度
    if market_score and market_score >= 60:
        strength = 'strong'
    elif market_score and market_score >= 50:
        strength = 'medium'
    else:
        strength = 'weak'
    
    return {
        'strength': strength,
        'market_score': market_score,
        'top_candidate': top_candidate,
        'recommendation': 'buy' if strength == 'strong' and top_candidate and top_candidate.get('score', 0) >= 70 else 'watch'
    }


def main():
    
    # 加载冷却期
    cooldown = load_cooldown()
    print(f"\n冷却状态: {cooldown.get('cooldown_status', 'unknown')}")
    print(f"冷却结束: {cooldown.get('cooldown_end', '未知')}")
    
    # 运行完整扫描
    scan_result = run_full_scan()
    
    if scan_result['success']:
        pass
        # 检查信号强度
        signal = check_signal_strength(scan_result)
        print(f"\n📈 信号强度: {signal['strength']}")
        print(f"   市场评分: {signal['market_score']}")
        print(f"   TOP候选: {signal['top_candidate']}")
        print(f"   建议: {signal['recommendation']}")
        
        # 保存评估结果
        eval_file = LOG_DIR / f"cooldown_eval_{datetime.now().strftime('%Y%m%d')}.json"
        with open(eval_file, 'w', encoding='utf-8') as f:
            json.dump({
                'eval_time': datetime.now().isoformat(),
                'scan_success': True,
                'signal': signal,
                'full_output': scan_result['output']
            }, f, ensure_ascii=False, indent=2)
        
        print(f"\n📝 评估结果已保存: {eval_file}")
    else:
        print(f"❌ 扫描失败: {scan_result.get('error', '未知错误')}")
    
    return 0 if scan_result['success'] else 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
