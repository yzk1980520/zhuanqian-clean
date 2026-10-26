#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/review_four_criteria.py - 老六复审判据四件套核验

用途: 总管验收老六复审时，逐条核验四件套是否齐备
打回判据: 任一缺失 → 打回 (见AGENTS.md §4.1-13 四方审查环)

【四件套】
1. ✅已挂一手证据
2. ✅回归已跑 (回归全绿)
3. ✅数字验证声明引擎commit
4. ✅读侧断言完整 (消费方/周期/告警路径)

使用方法:
from scripts.review_four_criteria import check_four_criteria

result = check_four_criteria(
    commit_hash="e7f93f05",
    evidence_path="docs/reviews/xxx.md",
    regression_status="pass",  # pass/fail/unknown
    commit_declared="abc1234",
    assertions={"consumer": "cron_daily_monitor", "cycle": "daily", "alert_path": "message_queue"}
)

if not result["passed"]:
    for missing in result["missing"]:
        print(f"打回: {missing}")
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
import os


def check_four_criteria(
    commit_hash: str,
    evidence_path: Optional[str],
    regression_status: str,  # pass/fail/unknown
    commit_declared: str,
    assertions: Dict,
) -> Dict:
    """
    核验老六复审四件套是否齐备
    
    Returns:
    {
        "passed": bool,
        "missing": List[str],  # 缺失的项
        "evidence_ref": str,
        "commit_hash": str,
    }
    """
    missing = []
    
    # 1. 一手证据
    if not evidence_path or not os.path.exists(evidence_path):
        missing.append("C1_未挂一手证据")
    
    # 2. 回归已跑
    if regression_status != "pass":
        missing.append("C2_回归未跑或未全绿")
    
    # 3. 数字验证声明引擎commit
    if not commit_declared or commit_declared != commit_hash:
        missing.append("C3_引擎commit未声明或与实际不一致")
    
    # 4. 读侧断言完整
    required_assertion_fields = ["consumer", "cycle", "alert_path"]
    for field in required_assertion_fields:
        if field not in assertions or not assertions.get(field):
            missing.append(f"C4_断言缺{field}")
    
    result = {
        "passed": len(missing) == 0,
        "missing": missing,
        "evidence_ref": evidence_path or "未提供",
        "commit_hash": commit_hash,
    }
    
    return result


def format_review_verdict(result: Dict) -> str:
    """格式化核验结论 (用于飞书/报告)"""
    if result["passed"]:
        return f"✅ 四件套核验通过 (commit {result['commit_hash'][:8]})"
    else:
        lines = [f"❌ 四件套缺失，打回 (commit {result['commit_hash'][:8]}):"]
        for item in result["missing"]:
            lines.append(f"  • {item}")
        lines.append("复验方式: 补全后重新提交 commit + evidence")
        return "\n".join(lines)


if __name__ == "__main__":
    # 自检
    test_cases = [
        {
            "name": "全四件满足",
            "commit_hash": "abc1234",
            "evidence_path": "/tmp/exist.md",
            "regression_status": "pass",
            "commit_declared": "abc1234",
            "assertions": {
                "consumer": "cron_daily_monitor",
                "cycle": "daily",
                "alert_path": "message_queue.json"
            },
            "expected_passed": True
        },
        {
            "name": "缺读侧断言",
            "commit_hash": "def5678",
            "evidence_path": "/tmp/exists.md",
            "regression_status": "pass",
            "commit_declared": "def5678",
            "assertions": {},  # 空
            "expected_passed": False
        }
    ]
    
    print("=== 自检 ===")
    for tc in test_cases:
        result = check_four_criteria(
            tc["commit_hash"],
            tc["evidence_path"],
            tc["regression_status"],
            tc["commit_declared"],
            tc["assertions"]
        )
        status = "✅" if result["passed"] else "❌"
        print(f"{status} {tc['name']}: passed={result['passed']}, missing={result['missing']}")
        assert result["passed"] == tc["expected_passed"], f"{tc['name']} 结果不符合预期"
    
    print("自检通过 ✅")
