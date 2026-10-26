#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三方讨论自动化框架 v1.0

功能：
1. 加载角色定义
2. 调用各角色模型发表意见
3. 生成结构化会议纪要
4. 推送至飞书群

用法：
  python scripts/team_discussion.py --topic "策略参数调整" --actions "止损放宽"
  python scripts/team_discussion.py --meeting-type monthly
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

ROLES_FILE = PROJECT_ROOT / ".hermes" / "roles" / "definitions.json"
MEETING_DIR = PROJECT_ROOT / "docs" / "meetings"


def load_roles():
    """加载角色定义"""
    if not ROLES_FILE.exists():
        print(f"错误: 角色定义文件不存在: {ROLES_FILE}")
        sys.exit(1)
    
    with open(ROLES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def format_role_prompt(role_name, role_def, topic, context=""):
    """格式化角色发言提示词"""
    return f"""你是{role_name}（{role_def['persona']}）。

任务：针对以下议题发表专业意见。

议题：{topic}
背景：{context}

请按以下格式发言：
1. 核心观点（一句话）
2. 论据（2-3条，带数据来源）
3. 风险评估（如适用）
4. 行动建议（P0/P1/P2）

注意：只从你的角色视角出发，保持独立性。"""


def generate_meeting_report(role_name, role_output, topic, timestamp):
    """生成会议纪要条目"""
    return {
        "role": role_name,
        "timestamp": timestamp,
        "topic": topic,
        "output": role_output,
        "status": "submitted"
    }


def save_meeting_report(meeting_data):
    """保存会议纪要"""
    MEETING_DIR.mkdir(parents=True, exist_ok=True)
    
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"meeting_{date_str}_{datetime.now().strftime('%H%M%S')}.json"
    filepath = MEETING_DIR / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(meeting_data, f, ensure_ascii=False, indent=2)
    
    return filepath


def push_to_feishu(report_path):
    """推送会议纪要到飞书"""
    try:
        from scripts.reporter import send_to_feishu
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        message = f"📋 三方会议纪要\n\n见附件: {report_path.name}\n\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # 实际推送（需要飞书API配置）
        # send_to_feishu(message, attachments=[report_path])
        print(f"✅ 会议纪要已准备推送: {report_path}")
        
    except ImportError:
        print(f"🔴 [scripts\team_discussion.py] CR-01: except ImportError:", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ 飞书推送失败: {e}")


def main():
    """主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="三方讨论自动化框架")
    parser.add_argument("--topic", "-t", required=True, help="讨论议题")
    parser.add_argument("--context", "-c", default="", help="背景信息")
    parser.add_argument("--mode", "-m", choices=["simulate", "real"], default="simulate",
                        help="模拟模式（输出prompt）vs 真实模式（调用API）")
    parser.add_argument("--roles", "-r", nargs="*", help="指定角色（默认全部）")
    
    args = parser.parse_args()
    
    # 加载角色定义
    config = load_roles()
    roles = config["roles"]
    
    # 确定要调用的角色
    target_roles = args.roles if args.roles else list(roles.keys())
    
    print(f"📋 三方会议开始")
    print(f"议题: {args.topic}")
    print(f"背景: {args.context}")
    print(f"参与角色: {', '.join(target_roles)}")
    
    meeting_data = {
        "meeting_id": datetime.now().isoformat(),
        "topic": args.topic,
        "context": args.context,
        "participants": [],
        "report_generated": None
    }
    
    # 模拟模式：输出各角色提示词
    if args.mode == "simulate":
        for role_key in target_roles:
            if role_key not in roles:
                print(f"⚠️ 未知角色: {role_key}")
                continue
            
            role_def = roles[role_key]
            prompt = format_role_prompt(role_def["name"], role_def, args.topic, args.context)
            
            print(f"\n{'='*50}")
            print(f"【{role_def['name']}】提示词:")
            print(f"{'='*50}")
            print(f"{'='*50}")
            
            meeting_data["participants"].append({
                "role": role_key,
                "name": role_def["name"],
                "status": "prompt_generated"
            })
    
    # 真实模式：调用各角色模型（需要实现API调用）
    elif args.mode == "real":
        pass
    # 保存会议纪要
    report_path = save_meeting_report(meeting_data)
    print(f"\n✅ 会议纪要已保存: {report_path}")
    
    # 尝试推送
    push_to_feishu(report_path)
    


if __name__ == "__main__":
    main()
