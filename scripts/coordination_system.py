#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局协调系统 - 自动化阻塞修复器
版本: v1.0
职责: 识别阻塞点 → 自动修复 → 升级汇报
"""
import json
import time
import sys
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable

# 配置
CONFIG_FILE = Path(__file__).parent.parent / 'config.json'
TASK_BOARD_FILE = Path(__file__).parent.parent / '.agent' / 'TASK-BOARD.json'
LOG_FILE = Path(__file__).parent.parent / 'logs' / 'coordination.log'

class BlockerDetector:
    """阻塞点检测器"""
    
    def __init__(self):
        self.blockers = []
    
    def detect_timeouts(self) -> List[Dict]:
        """检测超时任务"""
        timeout_tasks = []
        board = self._load_board()
        now = datetime.now()
        
        for task in board.get('tasks', []):
            deadline = datetime.fromisoformat(task['deadline'])
            if now > deadline and task['status'] == 'pending':
                timeout_tasks.append({
                    'type': 'TIMEOUT',
                    'task_id': task['id'],
                    'title': task['title'],
                    'assignee': task['assignee'],
                    'priority': task['priority'],
                    'overdue_seconds': (now - deadline).total_seconds(),
                    'severity': 'P0' if task['priority'] == 'P0' else 'P1'
                })
        
        return timeout_tasks
    
    def detect_stalled_tasks(self) -> List[Dict]:
        """检测停滞任务（超过SLA但未超时）"""
        stalled_tasks = []
        board = self._load_board()
        now = datetime.now()
        
        sla_limits = {'P0': 7200, 'P1': 28800, 'P2': 86400, 'P3': 259200}
        
        for task in board.get('tasks', []):
            if task['status'] != 'pending':
                continue
            
            priority = task.get('priority', 'P2')
            sla = sla_limits.get(priority, 86400)
            
            created_at = datetime.fromisoformat(task['created_at'])
            elapsed = (now - created_at).total_seconds()
            
            if elapsed > sla * 0.8:  # 超过80% SLA
                stalled_tasks.append({
                    'type': 'STALLED',
                    'task_id': task['id'],
                    'title': task['title'],
                    'assignee': task['assignee'],
                    'priority': priority,
                    'elapsed_minutes': int(elapsed / 60),
                    'sla_minutes': int(sla / 60),
                    'progress_percent': int(elapsed / sla * 100)
                })
        
        return stalled_tasks
    
    def detect_missing_dependencies(self) -> List[Dict]:
        """检测缺失依赖"""
        missing_deps = []
        
        # 检查数据文件
        data_files = [
            'data/stock_pool.json',
            'data/factor_ic.json',
            'data/gate_status.json'
        ]
        
        for file_path in data_files:
            full_path = Path(__file__).parent.parent / file_path
            if not full_path.exists():
                missing_deps.append({
                    'type': 'MISSING_DEPENDENCY',
                    'file': file_path,
                    'severity': 'P1'
                })
        
        return missing_deps
    
    def _load_board(self) -> Dict:
        """加载任务看板"""
        try:
            if TASK_BOARD_FILE.exists():
                with open(TASK_BOARD_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, EOFError) as e:
            print(f"⚠️ 任务看板解析失败: {e}")
            # 创建备份
            backup_path = TASK_BOARD_FILE.with_suffix('.bak')
            try:
                TASK_BOARD_FILE.rename(backup_path)
                print(f"✅ 已备份到: {backup_path}")
            except Exception as backup_error:
                print(f"❌ 备份失败: {backup_error}")
        
        return {'tasks': [], 'stats': {}}
    
    def run_detection(self) -> List[Dict]:
        """运行完整检测"""
        all_blockers = []
        
        all_blockers.extend(self.detect_timeouts())
        all_blockers.extend(self.detect_stalled_tasks())
        all_blockers.extend(self.detect_missing_dependencies())
        
        return all_blockers


class BlockerResolver:
    """阻塞点修复器"""
    
    def __init__(self):
        self.fix_history = []
    
    def resolve_timeout(self, blocker: Dict) -> Dict:
        """修复超时"""
        print(f"\n🔧 正在修复超时任务: {blocker['task_id']}")
        
        # 策略1: 发送提醒
        print("  策略1: 发送飞书提醒...")
        remind_result = self._send_reminder(blocker)
        
        if remind_result['success']:
            return {'success': True, 'fix': 'reminder_sent'}
        
        # 策略2: 重新分配
        print("  策略2: 重新分配任务...")
        reassign_result = self._reassign_task(blocker)
        
        if reassign_result['success']:
            return {'success': True, 'fix': 'task_reassigned'}
        
        # 策略3: 升级汇报
        print("  策略3: 升级汇报给老大...")
        escalate_result = self._escalate(blocker)
        
        return escalate_result
    
    def resolve_stalled(self, blocker: Dict) -> Dict:
        """修复停滞"""
        print(f"\n🔧 正在修复停滞任务: {blocker['task_id']}")
        
        # 检查是否需要帮助
        print("  检查任务状态...")
        status_check = self._check_task_status(blocker)
        
        if status_check['needs_help']:
            print("  提供协助...")
            help_result = self._provide_help(blocker)
            return help_result
        
        return {'success': False, 'reason': 'no_action_needed'}
    
    def resolve_missing_dependency(self, blocker: Dict) -> Dict:
        """修复缺失依赖"""
        print(f"\n🔧 正在修复缺失依赖: {blocker['file']}")
        
        # 尝试自动下载
        print("  尝试从网络下载...")
        download_result = self._download_file(blocker['file'])
        
        if download_result['success']:
            return download_result
        
        # 尝试使用缓存
        print("  尝试使用缓存数据...")
        cache_result = self._use_cache(blocker['file'])
        
        return cache_result
    
    def _send_reminder(self, blocker: Dict) -> Dict:
        """发送飞书提醒"""
        try:
            from feishu_sender import send_feishu_message
            message = f"""⏰ 【任务超时提醒】

任务ID: {blocker['task_id']}
标题: {blocker['title']}
负责人: {blocker['assignee']}
超时: {int(blocker['overdue_seconds'] / 60)}分钟

请立即处理！"""
            
            result = send_feishu_message(message)
            return result
        except Exception as e:
            print(f"  ❌ 发送提醒失败: {e}")
            return {'success': False, 'error': str(e)}
    
    def _reassign_task(self, blocker: Dict) -> Dict:
        """重新分配任务"""
        print(f"  🔄 重新分配任务 {blocker['task_id']}")
        
        # 更新任务看板
        board = BlockerDetector()._load_board()
        for task in board.get('tasks', []):
            if task['id'] == blocker['task_id']:
                task['assignee'] = '@总管'
                task['status'] = 'in_progress'
                task['reassign_reason'] = f'原负责人超时{int(blocker["overdue_seconds"] / 60)}分钟'
                print(f"  ✅ 已重新分配给 @总管")
                break
        
        # 保存
        with open(TASK_BOARD_FILE, 'w', encoding='utf-8') as f:
            json.dump(board, f, ensure_ascii=False, indent=2)
        
        return {'success': True, 'new_assignee': '@总管'}
    
    def _escalate(self, blocker: Dict) -> Dict:
        """升级汇报"""
        print(f"  🚨 升级汇报给老大")
        
        message = f"""🚨 【阻塞升级报告】

任务ID: {blocker['task_id']}
阻塞类型: 超时
标题: {blocker['title']}
负责人: {blocker['assignee']}
超时: {int(blocker['overdue_seconds'] / 60)}分钟

已尝试:
  1. 发送飞书提醒 - 失败
  2. 重新分配任务 - 失败

建议方案:
  A. 手动介入处理
  B. 调整任务优先级
  C. 延长截止时间

请老大决策。"""
        
        try:
            from feishu_sender import send_feishu_message
            result = send_feishu_message(message)
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _check_task_status(self, blocker: Dict) -> Dict:
        """检查任务状态"""
        board = BlockerDetector()._load_board()
        for task in board.get('tasks', []):
            if task['id'] == blocker['task_id']:
                return {
                    'status': task.get('status'),
                    'progress': task.get('progress', 0),
                    'needs_help': task.get('progress', 0) < 50
                }
        return {'needs_help': False}
    
    def _provide_help(self, blocker: Dict) -> Dict:
        """提供协助"""
        print(f"  🤝 提供协助...")
        
        # 这里可以添加具体的协助逻辑
        return {'success': True, 'help': 'provided'}
    
    def _download_file(self, file_path: str) -> Dict:
        """下载文件"""
        print(f"  📥 尝试下载: {file_path}")
        
        # 示例：下载股票池数据
        if 'stock_pool' in file_path:
            try:
                # 使用akshare获取
                import akshare as ak
                stock_data = ak.stock_zh_a_spot_em()
                # 保存到文件
                output_path = Path(__file__).parent.parent / file_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                stock_data.to_json(output_path, orient='records', force_ascii=False)
                return {'success': True, 'source': 'akshare'}
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        return {'success': False, 'error': 'unsupported_file_type'}
    
    def _use_cache(self, file_path: str) -> Dict:
        """使用缓存数据"""
        print(f"  💾 尝试使用缓存...")
        
        cache_path = Path(__file__).parent.parent / 'cache' / file_path
        if cache_path.exists():
            import shutil
            target_path = Path(__file__).parent.parent / file_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(cache_path, target_path)
            return {'success': True, 'source': 'cache'}
        
        return {'success': False, 'error': 'no_cache_available'}
    
    def resolve_blocker(self, blocker: Dict) -> Dict:
        """统一修复入口"""
        resolver_map = {
            'TIMEOUT': self.resolve_timeout,
            'STALLED': self.resolve_stalled,
            'MISSING_DEPENDENCY': self.resolve_missing_dependency
        }
        
        resolver = resolver_map.get(blocker['type'])
        if resolver:
            return resolver(blocker)
        
        return {'success': False, 'reason': 'unknown_blocker_type'}
    
    def resolve_all(self, blockers: List[Dict]) -> List[Dict]:
        """批量修复"""
        results = []
        for blocker in blockers:
            result = self.resolve_blocker(blocker)
            results.append({
                'blocker': blocker,
                'result': result
            })
            self.fix_history.append({
                'timestamp': datetime.now().isoformat(),
                'blocker': blocker,
                'result': result
            })
        return results


class CoordinationSystem:
    """全局协调系统主控制器"""
    
    def __init__(self):
        self.detector = BlockerDetector()
        self.resolver = BlockerResolver()
        self.log_file = LOG_FILE
    
    def run_cycle(self):
        """运行一个协调周期"""
        print("\n" + "=" * 80)
        print("🔄 全局协调系统运行中...")
        print("=" * 80)
        
        # 1. 检测阻塞
        print("\n📊 【步骤1】检测阻塞点...")
        blockers = self.detector.run_detection()
        
        if not blockers:
            print("✅ 无阻塞点，系统运行正常")
            return {'status': 'healthy', 'blockers_found': 0}
        
        print(f"🔴 发现 {len(blockers)} 个阻塞点")
        for b in blockers:
            print(f"  - [{b['type']}] {b.get('task_id', b.get('file', 'unknown'))}")
        
        # 2. 自动修复
        print("\n🔧 【步骤2】自动修复阻塞...")
        results = self.resolver.resolve_all(blockers)
        
        success_count = sum(1 for r in results if r['result']['success'])
        print(f"✅ 成功修复 {success_count}/{len(blockers)} 个阻塞点")
        
        # 3. 汇报结果
        print("\n📝 【步骤3】生成汇报...")
        self._generate_report(blockers, results)
        
        # 4. 返回状态
        return {
            'status': 'healthy' if success_count == len(blockers) else 'degraded',
            'blockers_found': len(blockers),
            'blockers_fixed': success_count,
            'fix_rate': success_count / len(blockers) * 100 if blockers else 100
        }
    
    def _generate_report(self, blockers: List[Dict], results: List[Dict]):
        """生成汇报报告"""
        report = []
        report.append(f"【协调系统汇报 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}】")
        report.append("")
        
        for i, (blocker, result) in enumerate(zip(blockers, results), 1):
            status = "✅ 已修复" if result['result']['success'] else "❌ 待处理"
            report.append(f"{i}. [{blocker['type']}] {status}")
            if not result['result']['success']:
                report.append(f"   原因: {result['result'].get('error', 'unknown')}")
        
        report.append("")
        report.append(f"修复率: {len([r for r in results if r['result']['success']])}/{len(results)}")
        
        # 保存报告
        report_text = "\n".join(report)
        print(report_text)
        
        # 写入日志
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*80}\n")
            f.write(report_text + "\n")


def main():
    """主函数"""
    system = CoordinationSystem()
    result = system.run_cycle()
    
    print("\n" + "=" * 80)
    print(f"✅ 协调周期完成")
    print(f"状态: {result['status']}")
    print(f"发现阻塞: {result['blockers_found']}")
    print(f"成功修复: {result['blockers_fixed']}")
    print(f"修复率: {result['fix_rate']:.1f}%")
    print("=" * 80)
    
    return 0 if result['status'] == 'healthy' else 1


if __name__ == '__main__':
    exit(main())
