#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
治理层审计日志记录器

功能：
  1. Git提交审计：pre-commit hook调用
  2. 配置变更快照：生成哈希追踪
  3. 权限事件记录：记录关键操作
"""
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(r'D:/open code/zhuanqian')
GOV_AUDIT_LOG = ROOT / 'data' / 'governance_audit.jsonl'
PERM_AUDIT_LOG = ROOT / 'data' / 'permission_audit.jsonl'

# 需要追踪的配置变更文件
CONFIG_FILES = [
    'config.json',
    'data/factor_weights.json',
    'data/gate_status.json',
    'data/risk_rules.json',
    'data/holding_params.json',
    'data/strategy_config.json',
    'data/alert_cooldown.json',
]


def get_git_info():
    """获取Git提交信息"""
    info = {}
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            capture_output=True, text=True, cwd=ROOT
        )
        info['hash'] = result.stdout.strip() if result.returncode == 0 else ''
        
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%an'],
            capture_output=True, text=True, cwd=ROOT
        )
        info['author'] = result.stdout.strip() if result.returncode == 0 else ''
        
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%s'],
            capture_output=True, text=True, cwd=ROOT
        )
        info['message'] = result.stdout.strip() if result.returncode == 0 else ''
    except Exception:
        info = {'hash': '', 'author': '', 'message': ''}
    
    return info


def snapshot_config_hash():
    """生成配置哈希快照"""
    snapshot = {
        'type': 'config_snapshot',
        'timestamp': datetime.now().isoformat(),
        'configs': {}
    }
    
    for cfg_path in CONFIG_FILES:
        fp = ROOT / cfg_path
        if fp.exists():
            content = fp.read_text(encoding='utf-8')
            snapshot['configs'][cfg_path] = {
                'hash': hashlib.sha256(content.encode()).hexdigest()[:16],
                'size': fp.stat().st_size,
                'mtime': datetime.fromtimestamp(fp.stat().st_mtime).isoformat()
            }
        else:
            snapshot['configs'][cfg_path] = {'exists': False}
    
    return snapshot


def log_governance_event(event_type, actor, details=None):
    """记录治理事件"""
    entry = {
        'timestamp': datetime.now().isoformat(),
        'event': event_type,
        'actor': actor,
        'details': details or {},
        'git_info': get_git_info()
    }
    
    with open(GOV_AUDIT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    return entry


def log_permission_event(event_type, actor, details=None, approved_by=None):
    """记录权限相关事件"""
    entry = {
        'timestamp': datetime.now().isoformat(),
        'event': event_type,
        'actor': actor,
        'approved_by': approved_by,
        'details': details or {}
    }
    
    with open(PERM_AUDIT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    # P0事件立即通知（运行时导入避免循环依赖）
    if event_type in ['rollback', 'threshold_modify', 'factor_add']:
        try:
            from scripts.alert_engine import send_alert as _notify
            _notify('P1', f"权限操作: {event_type} by {actor}", 'governance')
        except Exception:
            print(f"🔴 [scripts\governance_logger.py] CR-01: except Exception:", file=sys.stderr)
    return entry


def pre_commit_hook():
    """Git pre-commit钩子调用入口"""
    # 记录提交审计
    commit_info = get_git_info()
    
    entry = {
        'type': 'commit',
        'timestamp': datetime.now().isoformat(),
        'git_hash': commit_info.get('hash', ''),
        'author': commit_info.get('author', ''),
        'message': commit_info.get('message', ''),
    }
    
    with open(GOV_AUDIT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    # 检查是否修改了配置敏感文件
    result = subprocess.run(
        ['git', 'diff', '--cached', '--name-only'],
        capture_output=True, text=True, cwd=ROOT
    )
    
    modified_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
    sensitive_changes = [f for f in modified_files if any(c in f for c in ['config', 'gate_status', 'factor_weights'])]
    
    if sensitive_changes:
        log_governance_event('config_sensitive_change', commit_info.get('author', ''), {
            'files': sensitive_changes,
            'commit_hash': commit_info.get('hash', '')
        })
        print(f"[audit] 检测到敏感配置变更: {sensitive_changes}")
    
    print(f"[audit] 提交审计已记录: {commit_info.get('hash', '')[:8]}")
    return 0


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--snapshot':
        snap = snapshot_config_hash()
    else:
        pre_commit_hook()
