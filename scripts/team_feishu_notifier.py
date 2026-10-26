#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
团队讨论飞书通知模块

功能：
1. 将三方讨论结果推送到飞书群
2. 发送任务分配通知
3. 发送团队健康报告

依赖：
- lark-cli (飞书CLI工具)
- cron_message_sender.py 中的 send_feishu 函数
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# 导入消息发送模块
try:
    from cron_message_sender import send_feishu
except ImportError:
    send_feishu = None

ROOT = 'D:/open code/zhuanqian/scripts'


# 群ID单一配置源 (2026-09-28 总管根治): 群ID变更只改 feishu_chat_id.txt 一处
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


def send_meeting_notification(topic: str, participants: list, summary: str = "") -> bool:
    """发送三方会议通知"""
    if not send_feishu:
        return False
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    participant_names = ", ".join([p.get("name", p) for p in participants])
    
    message = f"""📋 **三方会议纪要**

**议题**: {topic}
**时间**: {timestamp}
**参与角色**: {participant_names}

---

**会议摘要**:
{summary if summary else '（详见附件）'}

---

💡 请使用以下命令查看详细记录:
```bash
python scripts/team_discussion.py --list
```"""
    
    return send_feishu(message)


def send_task_assignment(task_id: str, title: str, assignee: str, priority: str = "P2") -> bool:
    """发送任务分配通知"""
    if not send_feishu:
        return False
    
    role_names = {
        "opencode": "老三",
        "atomcode": "老五", 
        "niuma": "牛马"
    }
    
    assignee_name = role_names.get(assignee, assignee)
    priority_emoji = {"P0": "🔴", "P1": "🟡", "P2": "⚪"}.get(priority, "⚪")
    
    message = f"""📌 **新任务分配**

**任务ID**: {task_id}
**标题**: {title}
**优先级**: {priority_emoji} {priority}
**分配给**: {assignee_name}

---

📋 使用以下命令查看任务队列:
```bash
python scripts/task_router.py --list
```"""
    
    return send_feishu(message)


def send_health_report(report_data: dict) -> bool:
    """发送团队健康报告"""
    if not send_feishu:
        return False
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 解析报告数据
    active_profiles = report_data.get("summary", {}).get("active_profiles", 0)
    total_profiles = report_data.get("summary", {}).get("total_profiles", 0)
    pending_tasks = report_data.get("task_queue", {}).get("pending", 0)
    
    status_icon = "✅" if active_profiles == total_profiles else "⚠️"
    
    message = f"""📊 **团队健康报告**

**时间**: {timestamp}
**状态**: {status_icon} {active_profiles}/{total_profiles} Profiles 活跃

**任务队列**:
- 待处理: {pending_tasks}
- 进行中: {report_data.get('task_queue', {}).get('in_progress', 0)}
- 评审中: {report_data.get('task_queue', {}).get('review', 0)}
- 已完成: {report_data.get('task_queue', {}).get('done', 0)}

---

💡 使用以下命令查看详细报告:
```bash
python scripts/team_health_check.py
```"""
    
    return send_feishu(message)


def send_role_prompt(role_name: str, prompt: str) -> bool:
    """发送角色提示词（用于调试）"""
    if not send_feishu:
        return False
    
    message = f"""🎭 **{role_name} 提示词**

{prompt}

---

📝 请复制以上内容发送给对应角色模型"""
    
    return send_feishu(message)


def main():
    """主入口（测试用）"""
    import argparse
    
    parser = argparse.ArgumentParser(description="团队讨论飞书通知")
    parser.add_argument("--test", action="store_true", help="发送测试消息")
    parser.add_argument("--meeting", metavar="TOPIC", help="发送会议通知")
    parser.add_argument("--task", nargs=2, metavar=("ID", "TITLE"), help="发送任务分配")
    
    args = parser.parse_args()
    
    if args.test:
        success = send_meeting_notification(
            topic="测试会议",
            participants=[{"name": "老三"}, {"name": "老五"}, {"name": "牛马"}],
            summary="这是测试消息，验证飞书推送功能"
        )
        print(f"{'✅ 测试消息发送成功' if success else '❌ 测试消息发送失败'}")
    
    elif args.meeting:
        pass
    elif args.task:
        task_id, title = args.task
        success = send_task_assignment(task_id, title, "opencode", "P1")
        print(f"{'✅ 任务分配通知已发送' if success else '❌ 发送失败'}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
