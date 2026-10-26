#!/usr/bin/env python3
# 收编入 check_all.py health dispatch(check_all.py:78)执行; 脚本仍存活(非废弃), 请经 check_all health 调用
# -*- coding: utf-8 -*-
"""
chain_health_check.py - 链健康检查脚本

检查项:
1. 环境门状态 (daily_signal.json)
2. 数据质量 (data_quality_daily.json)
3. 持仓跟踪 (holdings.json + sim_positions.json)
4. 技能库健康 (skills/zhuanqian/)
5. Cron任务状态
6. 语义记忆检索 (memory_manager.py)

作者: 总管（Hermes）
时间: 2026-09-14
版本: v1.1.0
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# 添加scripts目录到路径
scripts_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(scripts_dir))

# 项目根目录
PROJECT_ROOT = scripts_dir.parent

# 导入记忆管理器
from memory_manager import get_memory_manager


def check_gate_status() -> dict:
    """检查环境门状态"""
    signal_path = PROJECT_ROOT / 'data' / 'daily_signal.json'
    
    if not signal_path.exists():
        return {
            'status': 'FAIL',
            'error': 'daily_signal.json不存在',
            'last_update': None
        }
    
    with open(signal_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    gate_status = data.get('gate_status', 'UNKNOWN')
    sh_price = data.get('sh_price', 0)
    ma250 = data.get('ma250', 0)
    
    # 记录到语义记忆
    try:
        mgr = get_memory_manager()
        mgr.add_experience(
            content=f'环境门状态: {gate_status}，上证{sh_price:.0f} vs MA250 {ma250:.0f}',
            category='decision',
            context='系统健康检查',
            outcome='环境门状态已记录到语义记忆'
        )
    except Exception:
        print(f"🔴 [scripts\chain_health_check.py] CR-01: except Exception:", file=sys.stderr)
    return {
        'status': 'OK' if gate_status in ['OPEN', 'FAIL'] else 'UNKNOWN',
        'gate_status': gate_status,
        'sh_price': sh_price,
        'ma250': ma250,
        'last_update': data.get('last_update')
    }


def check_data_quality() -> dict:
    """检查数据质量"""
    quality_path = PROJECT_ROOT / 'data' / 'data_quality_daily.json'
    
    if not quality_path.exists():
        return {
            'status': 'FAIL',
            'error': 'data_quality_daily.json不存在'
        }
    
    with open(quality_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    completeness = data.get('completeness', {}).get('score', 0)
    accuracy = data.get('accuracy', {}).get('score', 0)
    freshness = data.get('freshness', {}).get('score', 0)
    
    overall = min(completeness, accuracy, freshness)
    
    return {
        'status': 'OK' if overall >= 70 else 'WARN',
        'completeness': completeness,
        'accuracy': accuracy,
        'freshness': freshness,
        'overall': overall
    }


def check_holdings() -> dict:
    """检查持仓跟踪"""
    # 优先检查holdings.json
    holdings_path = PROJECT_ROOT / 'data' / 'holdings.json'
    
    if holdings_path.exists():
        with open(holdings_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        positions = data.get('positions', [])
        
        # 记录到语义记忆
        try:
            mgr = get_memory_manager()
            if positions:
                position_str = ', '.join([p.get('code', 'unknown') for p in positions])
                mgr.add_experience(
                    content=f'当前持仓: {position_str}',
                    category='experience',
                    context='持仓跟踪检查',
                    outcome='持仓信息已记录'
                )
        except Exception:
            print(f"🔴 [scripts\chain_health_check.py] CR-01: except Exception:", file=sys.stderr)
        return {
            'status': 'OK' if len(positions) > 0 else 'EMPTY',
            'count': len(positions),
            'positions': positions
        }
    
    # 降级检查sim_positions.json
    sim_path = PROJECT_ROOT / 'data' / 'sim_positions.json'
    if sim_path.exists():
        with open(sim_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {
            'status': 'OK' if data.get('positions') else 'EMPTY',
            'count': len(data.get('positions', [])),
            'positions': data.get('positions', [])
        }
    
    return {
        'status': 'FAIL',
        'error': 'holdings.json和sim_positions.json均不存在'
    }


def check_skills_health() -> dict:
    """检查技能库健康度"""
    skills_dir = PROJECT_ROOT / 'skills' / 'zhuanqian'
    
    if not skills_dir.exists():
        return {
            'status': 'FAIL',
            'error': 'skills/zhuanqian/不存在'
        }
    
    # 统计技能
    total = 0
    complete = 0
    has_trigger = 0
    has_reference = 0
    
    for skill_dir in skills_dir.iterdir():
        if skill_dir.is_dir():
            total += 1
            skill_md = skill_dir / 'SKILL.md'
            
            if skill_md.exists():
                content = skill_md.read_text(encoding='utf-8')
                
                # 检查必要字段
                if 'role_identity' in content or '## Critical Pitfalls' in content:
                    complete += 1
                if 'trigger' in content.lower():
                    has_trigger += 1
                
                # 检查reference
                ref_dir = skill_dir / 'references'
                if ref_dir.exists() and len(list(ref_dir.glob('*.md'))) > 0:
                    has_reference += 1
    
    health_rate = (complete / total * 100) if total > 0 else 0
    
    return {
        'status': 'OK' if health_rate >= 80 else 'WARN',
        'total': total,
        'complete': complete,
        'has_trigger': has_trigger,
        'has_reference': has_reference,
        'health_rate': round(health_rate, 1)
    }


def check_cron_status() -> dict:
    """检查cron任务状态"""
    try:
        result = subprocess.run(
            ['hermes', 'cron', 'list'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            active_count = sum(1 for line in lines if '| active |' in line.lower())
            
            return {
                'status': 'OK' if active_count >= 20 else 'WARN',
                'active_jobs': active_count
            }
        else:
            return {
                'status': 'FAIL',
                'error': f'hermes cron list失败: {result.stderr}'
            }
    except Exception as e:
        return {
            'status': 'FAIL',
            'error': str(e)
        }


def check_memory_retrieval() -> dict:
    """检查语义记忆检索功能"""
    try:
        mgr = get_memory_manager()
        
        # 测试检索
        test_query = "因子IC翻转"
        results = mgr.search_similar(test_query, top_k=3)
        
        return {
            'status': 'OK' if len(results) > 0 else 'EMPTY',
            'test_query': test_query,
            'results_count': len(results),
            'avg_similarity': sum(r['similarity'] for r in results) / len(results) if results else 0
        }
    except Exception as e:
        return {
            'status': 'FAIL',
            'error': str(e)
        }


def main():
    """主函数"""
    
    checks = [
        ('环境门状态', check_gate_status),
        ('数据质量', check_data_quality),
        ('持仓跟踪', check_holdings),
        ('技能库健康', check_skills_health),
        ('Cron任务', check_cron_status),
        ('语义记忆', check_memory_retrieval)
    ]
    
    results = {}
    fail_count = 0
    
    for name, check_fn in checks:
        print(f"\n检查{name}...", end=' ')
        try:
            result = check_fn()
            results[name] = result
            
            status = result.get('status', 'UNKNOWN')
            if status == 'OK':
                pass
            elif status == 'FAIL':
                fail_count += 1
            else:
                pass
        except Exception as e:
            results[name] = {'status': 'FAIL', 'error': str(e)}
            fail_count += 1
    
    # 汇总
    
    print(f"\n检查项总数: {len(checks)}")
    print(f"通过: {len(checks) - fail_count}")
    print(f"失败: {fail_count}")
    
    if fail_count == 0:
        return 0
    elif fail_count <= 2:
        return 1
    else:
        return 2


if __name__ == '__main__':
    sys.exit(main())
