#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/weight_adjustment_task.py - 权重调整消费闭环 (C1/C2销账)

目的: 补齐老六复审的两个销账条件
C1: 月度消费入口关闭 → 没有周期生产refs
C2: refs出口模糊 → 没有"权重调整"任务单承接

功能:
1. 读取 data/weight_reestimation_refs.json (上游consumer已生成)
2. 生成"权重调整评审任务单" (data/pending_weight_adjustments.jsonl)
3. 注册读侧断言 (cron每日检查 + 告警)

合规红线 (K45 §三):
- ❌ 自动流入实盘权重 = 新任务单 + 老五评审
- ✅ 本脚本只生成"任务单"，等待老五评审+老大拍板

使用方法:
$ python scripts/weight_adjustment_task.py --generate
$ python scripts/weight_adjustment_task.py --check-daily  # 读侧断言
"""
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 数据文件路径
PROJECT_ROOT = Path(__file__).parent.parent
REFS_PATH = PROJECT_ROOT / "data" / "weight_reestimation_refs.json"
TASKS_PATH = PROJECT_ROOT / "data" / "pending_weight_adjustments.jsonl"


def load_refs() -> Dict:
    """加载refs文件"""
    if not REFS_PATH.exists():
        logger.warning(f"refs文件不存在: {REFS_PATH}")
        return {}
    
    with open(REFS_PATH) as f:
        data = json.load(f)
    
    logger.info(f"加载refs成功: total_refs={data.get('total_refs', 0)}")
    return data


def generate_task_from_refs(refs: Dict) -> List[Dict]:
    """
    从refs生成"权重调整评审任务单"
    
    每类refs(weekly_ic/monthly_tune)生成1个任务单
    任务单包含:
    - task_id (唯一)
    - source_refs (引用的refs数)
    - candidate_weights (候选权重，来自refs)
    - evidence (数据依据摘要)
    - review_request (老五评审请求)
    - created_at
    """
    tasks = []
    
    # 遍历每类refs
    for ref_type, refs_list in refs.get("refs", {}).items():
        if not refs_list:
            continue
        
        task = {
            "task_id": f"wt-{ref_type}-{datetime.now().strftime('%Y%m%d%H%M')}",
            "source": ref_type,
            "source_refs": len(refs_list),
            "candidate_weights": extract_candidate_weights(refs_list),
            "evidence": build_evidence(refs_list),
            "review_request": {
                "reviewer": "laowu(老五)",
                "type": "weight_adjustment",
                "priority": "P2",
                "note": "需老大拍板实盘权重变更"
            },
            "created_at": datetime.now().isoformat(),
            "status": "pending"
        }
        
        tasks.append(task)
    
    return tasks


def extract_candidate_weights(refs_list: List) -> Dict:
    """提取候选权重 (从refs中推导)"""
    # 简化版: 统计每类refs的平均权重调整方向
    directions = {"up": 0, "down": 0, "hold": 0}
    for ref in refs_list:
        factor = ref.get("factor", "unknown")
        direction = ref.get("adjust_direction", "hold")
        directions[direction] = directions.get(direction, 0) + 1
    
    return {
        "factors_adjusted": len(refs_list),
        "direction_distribution": directions,
        "top_factors": [ref.get("factor") for ref in refs_list[:5]]
    }


def build_evidence(refs_list: List) -> Dict:
    """构建数据依据摘要"""
    return {
        "total_refs": len(refs_list),
        "ic_sources": [ref.get("source") for ref in refs_list[:3]],
        "window_days": refs_list[0].get("window_days", "unknown") if refs_list else None
    }


def write_tasks(tasks: List[Dict]) -> int:
    """写入任务单 (append-only防覆盖)"""
    if not tasks:
        logger.info("无新任务单")
        return 0
    
    # 确保目录存在
    TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # append模式
    with open(TASKS_PATH, 'a', encoding='utf-8') as f:
        for task in tasks:
            f.write(json.dumps(task, ensure_ascii=False) + '\n')
    
    logger.info(f"写入任务单: {len(tasks)} 项")
    return len(tasks)


def check_daily() -> Dict:
    """
    读侧断言: 每日10:00检查
    - 有新任务单 → 正常 (返回status=ok)
    - 无任务单 + refs有内容 → 告警 (C1条件未销账)
    - refs为空 → 正常 (C2待建)
    """
    refs = load_refs()
    
    # 检查refs
    has_refs = refs.get("total_refs", 0) > 0
    refs_count = refs.get("total_refs", 0)
    
    # 检查任务单
    has_tasks = TASKS_PATH.exists() and TASKS_PATH.stat().st_size > 0
    
    # 生成决策
    if has_refs and not has_tasks:
        alert = "refs存在但无任务单生成 (C1: 消费入口未激活)"
        status = "alert"
    elif has_refs and has_tasks:
        alert = None
        status = "ok"
    else:
        alert = "无refs (C2: 权重调整出口待建)"
        status = "info"
    
    return {
        "check_time": datetime.now().isoformat(),
        "refs_count": refs_count,
        "has_refs": has_refs,
        "has_tasks": has_tasks,
        "alert": alert,
        "status": status
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--generate', action='store_true', help='生成任务单')
    parser.add_argument('--check-daily', action='store_true', help='读侧断言检查')
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    if args.generate:
        refs = load_refs()
        tasks = generate_task_from_refs(refs)
        written = write_tasks(tasks)
        print(f"✅ 生成完成: {written} 项任务单")
    
    elif args.check_daily:
        result = check_daily()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
        # 告警写入
        if result["status"] == "alert":
            alert_file = PROJECT_ROOT / "data" / "message_queue.json"
            alert_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 读现有队列
            if alert_file.exists():
                with open(alert_file) as f:
                    queue = json.load(f)
            else:
                queue = []
            
            queue.append({
                "type": "weight_adjustment_alert",
                "message": result["alert"],
                "severity": "P2",
                "timestamp": datetime.now().isoformat()
            })
            
            with open(alert_file, 'w') as f:
                json.dump(queue, f, ensure_ascii=False)
            
            print(f"⚠️ 告警已写入: {alert_file}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
