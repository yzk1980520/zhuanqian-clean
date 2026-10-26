#!/usr/bin/env python
import core.pipeline.atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
audit_trigger_check.py — P2 回测异常自动审查触发器 (2026-08-04)
检测 data/audit_trigger.json (回测异常标记):
  - 存在且 status=pending → 启动 hermes agent 执行深度审查 (delegate 子agent)
  - 审查完成后将 status 置为 reviewed (由 agent 输出处理)
用法:
  python audit_trigger_check.py          # 检测并触发
  python audit_trigger_check.py --status # 仅查看状态
"""
import json, os, sys, subprocess

PROJECT = r"D:\open code\zhuanqian"
HERMES_HOME = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
TRIGGER_FILE = os.path.join(PROJECT, "data", "audit_trigger.json")
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

def main():
    if "--status" in sys.argv:
        if os.path.exists(TRIGGER_FILE):
            t = json.load(open(TRIGGER_FILE, encoding="utf-8"))
            print(f"审查标记: status={t.get('status')} 触发于{t.get('triggered_at')} 原因={t.get('reason')}")
        else:
            print("审查标记: 无 (回测正常)")
        return

    if not os.path.exists(TRIGGER_FILE):
        print("✅ 无回测异常标记, 无需审查")
        return

    t = json.load(open(TRIGGER_FILE, encoding="utf-8"))
    if t.get("status") != "pending":
        print(f"⏭️ 标记状态={t.get('status')}, 跳过")
        return

    # 2026-08-13 P0-1 修复: 死循环防护 — pending 超过3天视为过期(人工裁决), 避免每天反复spawn hermes子进程
    try:
        from datetime import datetime as _dt
        trig_dt = _dt.strptime(t.get("triggered_at", ""), "%Y-%m-%d %H:%M")
        age_days = (_dt.now() - trig_dt).days
        if age_days > 3:
            t["status"] = "expired"
            atomic_json.atomic_dump(t, TRIGGER_FILE, ensure_ascii=False, indent=2, encoding="utf-8")
            print(f"⏭️ 标记过期({age_days}天前), 置 expired 防死循环 — 需人工确认回测已重跑")
            return
    except Exception:
        pass  # 日期解析失败不阻断, 继续按正常流程

    print(f"🚨 检测到回测异常标记: {t.get('reason')}")
    print(f"   触发时间: {t.get('triggered_at')}")
    print("🔍 启动 hermes agent 深度审查...")

    # 用 hermes one-shot 模式启动审查 (agent 会派子agent并行审计)
    prompt = (
        "回测异常自动审查触发: backtest_result.json 显示胜率/超额低于阈值。"
        f"详情: {json.dumps(t, ensure_ascii=False)}。"
        "请审查 D:\\open code\\zhuanqian 的评分系统(tdx_core.py/integrated_picker.py/backtest.py)，"
        "找出导致回测恶化的原因(权重漂移/数据问题/逻辑bug)，修复后重跑回测验证。"
        "审查完成后将 data/audit_trigger.json 的 status 改为 reviewed。"
    )
    try:
        env = os.environ.copy()
        env["HERMES_HOME"] = HERMES_HOME
        r = subprocess.run(
            ["hermes", "chat", "-z", prompt],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=1800, env=env, cwd=HERMES_HOME
        )
        print(f"审查 agent 退出码: {r.returncode}")
        if r.stdout:
            print(f"输出尾部: {r.stdout[-300:]}")
        if r.returncode != 0:
            # 2026-08-13 P0-1 修复: agent 失败置 error, 防止死循环; 下次不再spawn, 人工查看
            t["status"] = "error"
            atomic_json.atomic_dump(t, TRIGGER_FILE, ensure_ascii=False, indent=2, encoding="utf-8")
            print(f"⚠️ 审查 agent 失败(退出码{r.returncode}), 标记置 error — 需人工处理")
    except Exception as e:
        print(f"⚠️ agent 启动失败: {e}")
        # 失败不置 reviewed, 下次重试

if __name__ == "__main__":
    main()
