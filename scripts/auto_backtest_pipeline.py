#!/usr/bin/env python3
"""
auto_backtest_pipeline.py - 回测流水线自动化脚本

功能:
- 执行全量回测（1351扫描日）
- 生成回测报告
- 触发老五评审
- 推送飞书通知

用法:
    python auto_backtest_pipeline.py --mode weekly
    python auto_backtest_pipeline.py --mode monthly
    python auto_backtest_pipeline.py --mode quarterly

⛔ 严禁清单（2026-10-21 立，改一处即触发 scripts/guard_assertion_effectiveness.py G21 报红）:
  1. 严禁把 trigger_review() 里对 final_verdict 的覆写改回**无条件执行**——
     即严禁把 compute_final_verdict 的覆写赋值挪出 if/else 分支写成顶格语句。
     周度回测 findings 三项全命中时该式必然算出 'FAIL'，无条件覆写 = 机器单方面
     推翻人工解冻裁决，实盘出票被重新冻结（当前系统最大的单点资金风险）。
  2. 严禁删除/放宽「有效解冻记录」判定 `_is_valid_unlock_record()` 的任一条件
     （freeze_unlock_record 为 dict / 有 unlocked_at / final_verdict == "PASS" /
       无 `_freeze_` 前缀活跃冻结标记）。删一条 = 解冻态守不住或被假解冻蒙混。
  3. 严禁删掉 `_final_verdict_override_skipped` 记录与醒目告警打印 ——
     跳过覆写必须留痕可查，不能静默跳过。
  允许保留的语义: pending_review=True（周度回测确实要求人重新评审，照写不误）。
"""
import sys
import os
import json
import argparse
import subprocess
from datetime import datetime, date
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_backtest():
    """执行回测"""
    
    # 导入回测模块
    from backtest.backtest_rotation import main as run_backtest_main
    
    # 执行回测
    run_backtest_main()
    return True


def generate_report():
    """生成回测报告"""
    
    result_file = PROJECT_ROOT / "data" / "rotation_backtest_result.json"
    if not result_file.exists():
        return False
    
    with open(result_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 生成摘要报告
    report = {
        "generated": str(datetime.now()),
        "window": data.get("window"),
        "scan_step": data.get("scan_step"),
        "total_strategies": len(data.get("results", [])),
        "best_strategy": None,
        "summary": []
    }
    
    # 找出最佳策略
    best_return = float('-inf')
    for r in data.get("results", []):
        config = r.get("config", "")
        trades = r.get("trades", 0)
        win_rate = r.get("win_rate", 0)
        total_return = r.get("total_return_pct", 0)
        max_drawdown = r.get("max_drawdown_pct", 0)
        profit_factor = r.get("profit_factor", 0)
        
        report["summary"].append({
            "config": config,
            "trades": trades,
            "win_rate": win_rate,
            "total_return": total_return,
            "max_drawdown": max_drawdown,
            "profit_factor": profit_factor
        })
        
        if total_return > best_return:
            best_return = total_return
            report["best_strategy"] = config
    
    # 保存报告
    report_file = PROJECT_ROOT / "data" / "backtest_report.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 报告已保存: {report_file}")
    return True


def _has_active_freeze_marker(existing: dict) -> bool:
    """是否存在活跃冻结标记 (键名以 `_freeze_` 开头且值为真)。

    不硬编码 `_freeze_20261018` 单键 —— 后续任何一次新冻结都能被认出来。
    """
    for k, v in existing.items():
        if isinstance(k, str) and k.startswith("_freeze_") and v:
            return True
    return False


def _is_valid_unlock_record(existing: dict) -> bool:
    """「有效人工解冻记录」四条件全满足才算成立 (缺一即 False)。

    成立 ⇒ 周度回测不得单方面覆写 final_verdict (机器不能推翻人的解冻裁决)。
    """
    rec = existing.get("freeze_unlock_record")
    if not isinstance(rec, dict):
        return False
    if not rec.get("unlocked_at"):
        return False
    if existing.get("final_verdict") != "PASS":
        return False
    if _has_active_freeze_marker(existing):
        return False
    return True


def trigger_review(review_file=None):
    """触发老五评审 (P0排雷 2026-10-08 总管: 合并写, 禁止整文件覆盖 — 原实现 open('w') 只写4键,
    会清空 trial_unlock_conditions/trial_circuit_breaker 等57键台账, weekly_backtest cron 一触发即丢失三重门控)

    ⛔ 2026-10-21 铁律: 存在有效人工解冻记录时**不得覆写** final_verdict (见文件头严禁清单)。
    review_file 可注入, 便于用 tempfile 做三档自证 (生产 data/review_status.json 永不拿来做实验)。
    """
    if review_file is None:
        review_file = PROJECT_ROOT / "data" / "review_status.json"
    review_file = Path(review_file)

    # 更新评审状态 (读旧 -> 合并4键 -> 原子替换)
    try:
        existing = json.loads(review_file.read_text(encoding='utf-8')) if review_file.exists() else {}
        if not isinstance(existing, dict):
            existing = {}
    except Exception:
        existing = {}
    review_status = {**existing,
        "_schema_version": "1.0",
        "laowu_approved": False,
        "last_updated": str(date.today()),
        "pending_review": True,
        "review_type": "weekly_backtest"
    }
    # R0b(K47 §二 B3): 落 final_verdict 唯一仲裁字段 (B1 否决权 + laowu_approved 回落)。
    # ⛔ 2026-10-21 修正: 该式在 findings 三项全命中时必然算出 'FAIL'，无条件覆写会
    #    把 2026-10-20 总管执笔/老大签批的人工解冻(final_verdict="PASS") 打回冻结，
    #    出票被重新卡死。故先判「有效人工解冻记录」—— 成立则保留原裁决，只留痕+告警。
    import review_gate
    computed_verdict = review_gate.compute_final_verdict(review_status)

    if _is_valid_unlock_record(existing):
        # 不覆写 final_verdict: {**existing} 已带原值 "PASS"，此处显式重抄一遍防止后人误删
        review_status["final_verdict"] = existing.get("final_verdict")
        review_status["final_verdict_basis"] = (
            "有效人工解冻记录保护: 未随本次周度回测覆写, "
            "保留原 final_verdict=%r (解冻 %s)" % (
                existing.get("final_verdict"),
                existing.get("freeze_unlock_record", {}).get("unlocked_at")))
        review_status["_final_verdict_override_skipped"] = {
            "skipped_at": str(datetime.now()),
            "would_have_been": computed_verdict,
            "retained": existing.get("final_verdict"),
            "reason": ("周度回测待评审(laowu_approved=False)本应把 final_verdict 重算为 "
                       "%r，但 existing 存在有效人工解冻记录(freeze_unlock_record.unlocked_at=%s)，"
                       "机器不得单方面推翻人的解冻裁决，故跳过覆写"
                       % (computed_verdict,
                          existing.get("freeze_unlock_record", {}).get("unlocked_at"))),
            "pending_review": True,
            "action_required": "人工介入重新评审 (周度回测已要求, 但出票未被自动冻结)",
        }
        print("=" * 72)
        print("⚠️⚠️ 醒目告警: 周度回测要求重新评审，但存在【有效人工解冻记录】，"
              "未自动冻结出票")
        print("=" * 72)
        print(f"  · 本次周度回测按原逻辑会算出 final_verdict = {computed_verdict!r}")
        print(f"    (B1 findings 否决权 + laowu_approved 回落)")
        print(f"  · 但检测到有效人工解冻记录:")
        print(f"      unlocked_at   = {existing.get('freeze_unlock_record', {}).get('unlocked_at')}")
        print(f"      unlocked_by   = {existing.get('freeze_unlock_record', {}).get('unlocked_by')}")
        print(f"      final_verdict = {existing.get('final_verdict')!r} (人工放行, 保留未改)")
        print(f"  · 因此**跳过覆写**，出票保持解冻态；pending_review=True 照写。")
        print(f"  · 留痕字段: _final_verdict_override_skipped (含 would_have_been="
              f"{computed_verdict!r})")
        print(f"  · 👉 请人工介入重新评审，不要依赖机器自动冻结。")
        print("=" * 72)
    else:
        # 无有效解冻记录 ⇒ 走原逻辑覆写 (保留 fail-close: 真出问题且无人解冻时仍自动冻结)
        review_status["final_verdict"] = review_gate.compute_final_verdict(review_status)
        review_status["final_verdict_basis"] = "B1(findings否决权)+laowu_approved回落 (review_gate.compute_final_verdict)"
        review_status.pop("_final_verdict_override_skipped", None)

    review_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = review_file.with_name(review_file.name + ".tmp_review")
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(review_status, f, indent=2)
    os.replace(tmp, review_file)  # 原子替换: 失败不破坏原文件

    print(f"✅ 评审状态已合并更新({len(review_status)}键保留): {review_file.name}")
    return True


def send_notification(message):
    """发送飞书通知"""
    print(f"发送飞书通知: {message}")
    
    # TODO: 集成飞书推送
    # 这里需要调用feishu-cli或HTTP API
    
    return True


def main():
    parser = argparse.ArgumentParser(description="回测流水线自动化")
    parser.add_argument("--mode", choices=["weekly", "monthly", "quarterly"], 
                        default="weekly", help="运行模式")
    args = parser.parse_args()
    
    print(f"\n模式: {args.mode}")
    print(f"时间: {datetime.now()}")
    
    # 执行流水线
    success = True
    
    if not run_backtest():
        success = False
    
    if success:
        if not generate_report():
            success = False
    
    if success:
        if not trigger_review():
            success = False
    
    if success:
        send_notification(f"{args.mode}回测完成")
    
    if success:
        pass
    else:
        # P4 (2026-10-26, t_64c8bbf0): 回测 FAIL → 自动 post-mortem 诊断 (宪法 VII: 失败不静默, 留痕 data/post_mortem_*.json)
        # 只在 FAIL 分支末尾追加; 诊断本身失败不阻塞流水线, 打警告留痕
        result_file = PROJECT_ROOT / "data" / "rotation_backtest_result.json"
        try:
            proc = subprocess.run(
                [sys.executable,
                 str(PROJECT_ROOT / "scripts" / "post_mortem_diagnose.py"),
                 "--result", str(result_file)],
                timeout=30,
            )
            if proc.returncode != 0:
                print(f"⚠️ post_mortem_diagnose 退出码 {proc.returncode} (诊断非阻塞)")
        except subprocess.TimeoutExpired:
            print("⚠️ post_mortem_diagnose 超时 (>30s), 跳过 (诊断非阻塞)")
        except subprocess.SubprocessError as e:
            print(f"⚠️ post_mortem_diagnose 调用异常 {type(e).__name__}: {e} (诊断非阻塞)")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
