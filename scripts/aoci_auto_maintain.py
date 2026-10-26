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
aoci_auto_maintain.py — AOCI索引自动维护脚本
触发方式: Git pre-commit hook + 每日cron

职责:
1. 检测新增Python文件，自动提取FRAS元数据
2. 检查索引条目完整性（缺失字段告警）
3. 生成漂移报告并推送飞书
4. 记录操作日志到.aoci/maintain_log.jsonl
"""
import os
import sys
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 项目根目录（脚本在scripts/子目录，需要向上一级）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
INDEX_FILE = PROJECT_ROOT / "aoci.code.txt"
LOG_FILE = PROJECT_ROOT / ".aoci" / "maintain_log.jsonl"
DRIFT_FILE = PROJECT_ROOT / ".aoci" / "drift_report.json"

# AOCI二进制路径（可通过环境变量覆盖）
AOCI_EXE_PATH = os.environ.get('AOCI_EXE', r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\bin\aoci.exe")

# 飞书CLI路径（可通过环境变量覆盖）
LARK_CLI_PATH = os.environ.get('LARK_CLI', r"D:\npm-global\lark-cli.cmd")

# FRAS字段正则
FRAS_PATTERN = re.compile(
    r'^([^\[]+)\[([A-Z]+[0-9T]+)\]:\s*'  # 文件名+标签
    r'F:\s*([^|]+)\|\s*'                   # F:职责
    r'R:\s*([^|]+)\|\s*'                   # R:依赖
    r'A:\s*([^|]+)\|\s*'                   # A:API
    r'S:\s*(.+)$'                          # S:说明
)

# 优先级标签映射
TAG_PRIORITY = {
    'BD': 'P0',  # 核心业务
    'BG': 'P1',  # 工具层
    'AD': 'P2',  # 管理逻辑
    'CD': 'P3',  # 健康监控
    'PQ': 'P4',  # 测试
    'CO': 'P5',  # 报告
    'AO': 'P6',  # 文档
}


class AOCIMaintainer:
    """AOCI索引自动维护器"""

    def __init__(self):
        self.index_entries = self._load_index()
        self.log_file = LOG_FILE
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> Dict[str, dict]:
        """加载现有索引"""
        entries = {}
        if INDEX_FILE.exists():
            with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # 匹配格式: filename[TAG]: F:... | R:... | A:... | S:...
                    match = FRAS_PATTERN.match(line)
                    if match:
                        filename, tag, func, requires, api, spec = match.groups()
                        # 提取纯文件名（不含路径）
                        clean_name = os.path.basename(filename.strip())
                        entries[clean_name] = {
                            'tag': tag.strip(),
                            'func': func.strip(),
                            'requires': requires.strip(),
                            'api': api.strip(),
                            'spec': spec.strip(),
                            'line': line,
                            'path': filename.strip()  # 保留完整路径
                        }
        return entries

    def _save_index(self):
        """保存索引"""
        with open(INDEX_FILE, 'w', encoding='utf-8') as f:
            f.write('#AOCI-CODE-VOLUME: 1\n')
            for entry in self.index_entries.values():
                f.write(entry['line'] + '\n')

    def _log(self, action: str, details: dict):
        """记录操作日志"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'details': details
        }
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

    def detect_new_files(self, git_diff: str) -> List[str]:
        """检测新增Python文件"""
        new_files = []
        for line in git_diff.split('\n'):
            if line.startswith('A') or line.startswith('M'):
                parts = line.split(' ', 2)
                if len(parts) >= 2:
                    filepath = parts[-1].strip()
                    if filepath.endswith('.py') and not filepath.startswith('.venv'):
                        new_files.append(filepath)
        return new_files

    def extract_fras_metadata(self, filepath: str) -> Optional[dict]:
        """从Python文件提取FRAS元数据"""
        full_path = PROJECT_ROOT / filepath
        if not full_path.exists():
            return None

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read(2000)  # 只读前2000字符

            # 提取模块文档字符串
            doc_match = re.search(r'"""(.+?)"""', content, re.DOTALL)
            func_desc = doc_match.group(1).strip() if doc_match else ""

            # 提取主要类
            classes = re.findall(r'class\s+(\w+)', content)

            # 提取主要函数
            functions = re.findall(r'def\s+(\w+)\s*\(', content)

            # 提取导入依赖
            imports = re.findall(r'from\s+(\S+)\s+import', content)
            imports += re.findall(r'import\s+(\S+)', content)

            # 生成标签
            tag = self._generate_tag(filepath, classes, functions)

            # 生成摘要
            summary = self._generate_summary(filepath, func_desc, classes, functions)

            # 确定优先级
            priority = self._determine_priority(filepath, classes)

            return {
                'filename': os.path.basename(filepath),
                'tag': tag,
                'priority': priority,
                'func': func_desc[:100] if func_desc else '待补充',
                'requires': ', '.join(set(imports[:5])) if imports else '-',
                'api': ', '.join(functions[:3]) if functions else '-',
                'spec': summary[:80] if summary else '待补充'
            }
        except Exception as e:
            self._log('extract_error', {'file': filepath, 'error': str(e)})
            return None

    def _generate_tag(self, filepath: str, classes: List[str], functions: List[str]) -> str:
        """生成FRAS标签"""
        base = os.path.basename(filepath).replace('.py', '')

        # 根据文件类型确定标签前缀
        if 'test_' in base:
            prefix = 'PQ'
        elif base in ['integrated_picker', 'backtest_rotation', 'tdx_core']:
            prefix = 'BD'
        elif base in ['risk_rules', 'atomic_json', 'config_loader']:
            prefix = 'BG'
        elif base in ['orchestrator', 'evolution_v2', 'factor_gate']:
            prefix = 'AD'
        elif 'health' in base.lower():
            prefix = 'CD'
        else:
            prefix = 'AO'

        # 根据重要性确定等级
        if classes or len(functions) > 3:
            level = '7T'  # 核心
        elif functions:
            level = '6T'  # 重要
        else:
            level = '5T'  # 辅助

        return f"{prefix}{level}"

    def _generate_summary(self, filepath: str, doc: str, classes: List[str], functions: List[str]) -> str:
        """生成功能摘要"""
        if doc:
            # 从文档字符串提取关键信息
            lines = doc.split('\n')
            for line in lines:
                if '职责:' in line or '功能:' in line or '用途:' in line:
                    return line.split(':', 1)[-1].strip()[:60]
            return doc[:60]

        # 从类和函数推断
        if classes:
            return f"{classes[0]}相关功能"
        if functions:
            return f"{functions[0]}相关功能"
        return "待分析"

    def _determine_priority(self, filepath: str, classes: List[str]) -> str:
        """确定优先级"""
        base = os.path.basename(filepath).replace('.py', '')

        # P0核心文件
        if base in ['integrated_picker', 'backtest_rotation', 'risk_rules', 'tdx_core']:
            return 'P0'

        # P1重要文件
        if base in ['config_loader', 'tdx_indicators', 'tdx_strategies', 'data_pipeline',
                    'factor_gate', 'orchestrator', 'evolution_v2', 'health_monitor']:
            return 'P1'

        # P2测试文件
        if 'test_' in base:
            return 'P2'

        # P3其他
        return 'P3'

    def check_completeness(self) -> dict:
        """检查索引完整性"""
        issues = []

        for filename, entry in self.index_entries.items():
            # 检查必需字段
            if not entry.get('func') or entry['func'] == '待补充':
                issues.append({
                    'file': filename,
                    'issue': '功能描述缺失或占位符',
                    'severity': 'medium'
                })
            if not entry.get('api') or entry['api'] == '-':
                issues.append({
                    'file': filename,
                    'issue': 'API定义缺失',
                    'severity': 'low'
                })
            if not entry.get('requires'):
                issues.append({
                    'file': filename,
                    'issue': '依赖关系未定义',
                    'severity': 'low'
                })
            if not entry.get('spec'):
                issues.append({
                    'file': filename,
                    'issue': '规格说明缺失',
                    'severity': 'low'
                })

        return {
            'total_entries': len(self.index_entries),
            'issues_count': len(issues),
            'issues': issues[:10]  # 最多返回10个
        }

    def generate_drift_report(self, previous_hash: str, current_hash: str) -> dict:
        """生成漂移报告"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'previous_hash': previous_hash,
            'current_hash': current_hash,
            'changes': {
                'entries_added': 0,
                'entries_removed': 0,
                'entries_modified': 0
            },
            'drift_detected': False
        }

        # 对比基线
        baseline_file = PROJECT_ROOT / '.aoci' / 'baseline.json'
        if baseline_file.exists():
            with open(baseline_file, 'r', encoding='utf-8') as f:
                baseline = json.load(f)

            previous_count = baseline.get('entry_count', 0)
            current_count = len(self.index_entries)

            report['changes']['entries_added'] = current_count - previous_count
            report['drift_detected'] = abs(current_count - previous_count) > 5

        return report

    def push_notification(self, message: str, severity: str = 'info'):
        """推送飞书通知"""
        try:
            import subprocess
            # 使用环境变量配置的路径
            lark_cli = LARK_CLI_PATH
            chat_id = FEISHU_CHAT_ID

            # 构建消息
            severity_emoji = {'critical': '🔴', 'warning': '🟡', 'info': '🟢'}.get(severity, 'ℹ️')
            full_message = f"{severity_emoji} [AOCI自动维护]\n{message}"

            result = subprocess.run(
                [lark_cli, 'im', '+messages-send', '--text', '-',
                 '--chat-id', chat_id, '--as', 'user'],
                input=full_message,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=30
            )

            if result.returncode == 0:
                self._log('notification_sent', {'severity': severity, 'message': message[:50]})
                return True
            else:
                self._log('notification_failed', {'error': result.stderr[:200]})
                return False
        except Exception as e:
            self._log('notification_error', {'error': str(e)})
            return False

    def run_full_maintenance(self, git_diff: str = "") -> dict:
        """执行完整维护流程"""
        result = {
            'timestamp': datetime.now().isoformat(),
            'actions': [],
            'status': 'success'
        }

        # 1. 检测新增文件
        if git_diff:
            new_files = self.detect_new_files(git_diff)
            result['actions'].append({
                'action': 'detect_new_files',
                'count': len(new_files),
                'files': new_files
            })

            # 2. 提取元数据
            for filepath in new_files:
                metadata = self.extract_fras_metadata(filepath)
                if metadata:
                    filename = os.path.basename(filepath)
                    if filename not in self.index_entries:
                        # 生成完整FRAS条目
                        entry_line = (
                            f"{filename}[{metadata['tag']}]: "
                            f"F:{metadata['func']} | "
                            f"R:{metadata['requires']} | "
                            f"A:{metadata['api']} | "
                            f"S:{metadata['spec']}"
                        )
                        self.index_entries[filename] = {
                            'tag': metadata['tag'],
                            'func': metadata['func'],
                            'requires': metadata['requires'],
                            'api': metadata['api'],
                            'spec': metadata['spec'],
                            'line': entry_line,
                            'priority': metadata['priority']
                        }
                        result['actions'].append({
                            'action': 'added_entry',
                            'file': filename,
                            'tag': metadata['tag'],
                            'priority': metadata['priority']
                        })

            # 3. 保存索引
            self._save_index()
            result['actions'].append({
                'action': 'index_saved',
                'total_entries': len(self.index_entries)
            })

        # 4. 检查完整性
        completeness = self.check_completeness()
        result['completeness'] = completeness

        # 5. 生成漂移报告
        drift_report = self.generate_drift_report("unknown", "current")
        result['drift'] = drift_report

        # 6. 记录日志
        self._log('maintenance_run', result)

        return result


def main():
    """主入口"""
    maintainer = AOCIMaintainer()

    # 获取git diff（如果有）
    git_diff = ""
    if len(sys.argv) > 1 and sys.argv[1] == '--pre-commit':
        try:
            result = subprocess.run(
                ['git', 'diff', '--cached', '--name-status'],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT
            )
            git_diff = result.stdout
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            print(f"⚠️ [scripts\aoci_auto_maintain.py] 兼容处理: except (subprocess.CalledProcessError, FileNotFoundError, OSError):", file=sys.stderr)
    # 执行维护
    result = maintainer.run_full_maintenance(git_diff)

    # 输出结果

    # 如果有问题，推送告警
    if result['completeness']['issues_count'] > 5:
        maintainer.push_notification(
            f"索引完整性检查发现问题: {result['completeness']['issues_count']}项",
            'warning'
        )

    if result['drift'].get('drift_detected'):
        maintainer.push_notification(
            "检测到索引漂移，请审查变更",
            'critical'
        )


if __name__ == '__main__':
    main()
