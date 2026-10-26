#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务路由分发器 v2.0

功能：
1. 接收任务描述
2. 根据任务类型路由到对应角色
3. 生成任务单并保存到队列
4. 触发对应角色的Hermes实例

用法：
  python scripts/task_router.py "修复选股bug" --type code
  python scripts/task_router.py "风控参数审查" --type review
  python scripts/task_router.py --list
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

PROJECT_ROOT = Path(__file__).parent.parent
ROLES_FILE = PROJECT_ROOT / ".hermes" / "roles" / "definitions.json"
TASK_QUEUE_FILE = PROJECT_ROOT / ".hermes" / "task_queue.json"
MEETING_DIR = PROJECT_ROOT / "docs" / "meetings"


class TaskRouter:
    """任务路由器"""
    
    # 任务类型映射
    TASK_TYPES = {
        "code": "opencode",  # 代码相关 → 老三
        "backtest": "opencode",  # 回测 → 老三
        "data": "opencode",  # 数据工程 → 老三
        "review": "atomcode",  # 评审 → 老五
        "compliance": "atomcode",  # 合规 → 老五
        "monitor": "niuma",  # 监控 → 牛马
        "alert": "niuma",  # 告警 → 牛马
    }
    
    # 关键词匹配（用于自动路由）
    KEYWORD_ROUTES = {
        "opencode": ["代码", "修复", "实现", "回测", "数据", "脚本", "模块", "重构"],
        "atomcode": ["评审", "审查", "风控", "合规", "参数", "校验", "验证"],
        "niuma": ["监控", "告警", "情绪", "备份", "检查", "健康度"]
    }
    
    def __init__(self):
        self.roles = self._load_roles()
        self.queue = self._load_queue()
    
    def _load_roles(self) -> Dict:
        """加载角色定义"""
        if not ROLES_FILE.exists():
            return {}
        with open(ROLES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get("roles", {})
    
    def _load_queue(self) -> Dict:
        """加载任务队列"""
        if not TASK_QUEUE_FILE.exists():
            return {"pending": [], "in_progress": [], "review": [], "done": []}
        with open(TASK_QUEUE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _save_queue(self):
        """保存任务队列"""
        with open(TASK_QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.queue, f, ensure_ascii=False, indent=2)
    
    def route_task(self, task_desc: str, task_type: Optional[str] = None) -> str:
        """路由任务到对应角色"""
        # 优先使用显式类型
        if task_type and task_type in self.TASK_TYPES:
            return self.TASK_TYPES[task_type]
        
        # 关键词匹配
        for role, keywords in self.KEYWORD_ROUTES.items():
            if any(kw in task_desc for kw in keywords):
                return role
        
        # 默认路由到老三（代码执行）
        return "opencode"
    
    def create_task(self, title: str, description: str, 
                    task_type: Optional[str] = None,
                    priority: str = "P2") -> Dict[str, Any]:
        """创建任务单"""
        assignee = self.route_task(description, task_type)
        task_id = f"T{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        task = {
            "id": task_id,
            "title": title,
            "description": description,
            "type": task_type or "general",
            "assignee": assignee,
            "priority": priority,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        self.queue["pending"].append(task)
        self._save_queue()
        
        return task
    
    def get_task_summary(self) -> str:
        """获取任务队列摘要"""
        lines = [
            "📋 任务队列状态",
            f"  待处理: {len(self.queue['pending'])}",
            f"  进行中: {len(self.queue['in_progress'])}",
            f"  评审中: {len(self.queue['review'])}",
            f"  已完成: {len(self.queue['done'])}",
            ""
        ]
        
        if self.queue['pending']:
            lines.append("📌 待处理任务:")
            for t in self.queue['pending'][:5]:
                lines.append(f"  [{t['priority']}] {t['id']}: {t['title']} → {t['assignee']}")
        
        return "\n".join(lines)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="任务路由分发器")
    parser.add_argument("--title", "-t", help="任务标题")
    parser.add_argument("--desc", "-d", help="任务描述")
    parser.add_argument("--type", choices=["code", "backtest", "data", "review", "compliance", "monitor", "alert"],
                        help="任务类型")
    parser.add_argument("--priority", choices=["P0", "P1", "P2"], default="P2", help="优先级")
    parser.add_argument("--list", action="store_true", help="显示任务队列")
    parser.add_argument("--route", help="测试任务路由")
    
    args = parser.parse_args()
    
    router = TaskRouter()
    
    # 显示队列
    if args.list:
        return
    
    # 测试路由
    if args.route:
        role = router.route_task(args.route, args.type)
        print(f"任务: {args.route}")
        print(f"路由到: {role}")
        if role in router.roles:
            print(f"角色定义: {router.roles[role]['name']} ({router.roles[role]['persona']})")
        return
    
    # 创建任务
    if args.title and args.desc:
        task = router.create_task(args.title, args.desc, args.type, args.priority)
        print(f"✅ 任务已创建:")
        print(f"   ID: {task['id']}")
        print(f"   标题: {task['title']}")
        print(f"   描述: {task['description']}")
        print(f"   分配给: {task['assignee']} ({router.roles.get(task['assignee'], {}).get('name', '未知')})")
        print(f"   优先级: {task['priority']}")
        print(f"\n使用 --list 查看队列状态")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
