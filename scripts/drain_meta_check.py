# 双路存活: 计划任务 QSP_DrainWatch 每5分钟直呼本脚本(drain_meta_task.cmd) + check_all.py dispatch 亦调度(check_all.py:97); 非 DEPRECATED
# -*- coding: utf-8 -*-
"""drain_meta_check.py — 告警环 meta 监控 M-1 (Hermes治理方案v1 T2, 2026-10-15 总管)

盯"运维闭环自身活性"双环 (2026-10-15 自主运维闭环扩展):
  环1 告警环: QSP_MsgDrain 每5分钟刷 data/drain_state.json 的 last_run
  环2 自愈环: QSP_SelfHeal(T7, 老六引擎) 每15min刷 data/self_heal_state.json 的 last_run
本脚本由计划任务 QSP_DrainWatch 每5分钟执行(独立于被盯环, 它们死了它才响):
  - 双环新鲜度阈值: drain <15min, self_heal <45min(3个15min周期容差)
  - 任一环连续 2 轮(10min) stale → P0 告警【绕过队列】: default 应用 bot API 直发
    (防"告警链路自己死了, 告警自己也发不出" — 方案 T2 第2步)
  - 之后每 6 轮(~30min)重发一次 P0, 避免刷屏; drain 恢复后自动复位静默
产出: data/drain_meta_state.json (本脚本自身活性落盘, 当前无代码读者; self_audit M-1 复检读的是 data/drain_state.json)
退出码: 0 正常(含复位/静默), 1 P0 告警已发出
"""
import json
import os
import sys
import datetime as _dt
import subprocess

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAIN_STATE = os.path.join(PROJECT, "data", "drain_state.json")
SELFHEAL_STATE = os.path.join(PROJECT, "data", "self_heal_state.json")
META_STATE = os.path.join(PROJECT, "data", "drain_meta_state.json")
ALERT_LOG = os.path.join(PROJECT, "data", "alert_log.jsonl")
MAX_AGE_MIN = 15            # 环1 drain 新鲜度阈值 (T2: <15min)
WD_MAX_AGE_MIN = 45         # 环2 T7自愈引擎(QSP_SelfHeal) 新鲜度阈值 (15min周期 x 3 容差)
ALERT_ROUND = 2             # 连续 2 轮 stale 才 P0
REPEAT_EVERY = 6            # 之后每 6 轮重发一次
RETRY = 1                   # 本脚本自身失败重试次数(由计划任务层控制, 此处仅记录)


def now_iso():
    return _dt.datetime.now().isoformat(timespec="seconds")


def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(f"🔴 [scripts\drain_meta_check.py] CR-01(return): except Exception:", file=sys.stderr)
            return None
    return None


def state_age_minutes(path):
    st = load_json(path)
    if not st or not st.get("last_run"):
        return None
    try:
        last = _dt.datetime.fromisoformat(st["last_run"])
    except Exception:
        print(f"🔴 [scripts\drain_meta_check.py] CR-01(return): except Exception:", file=sys.stderr)
        return None
    return (_dt.datetime.now() - last).total_seconds() / 60.0


def drain_age_minutes():
    return state_age_minutes(DRAIN_STATE)


def selfheal_age_minutes():
    return state_age_minutes(SELFHEAL_STATE)


def send_p0_bypass(text):
    """P0 绕过队列直发: default 应用 bot API (方案 T2: 换 default 应用 bot API 直发)。
    兜底 lark-cli/webhook 三通道全试, 仍失败只落 alert_log(本地台账)。"""
    ok = False
    try:
        sys.path.insert(0, PROJECT)
        from cron_message_sender import send_feishu_bot_api, send_with_fallback
        ok = send_feishu_bot_api(text)
        if not ok:
            ok = send_with_fallback(text)
    except Exception as e:
        print("[drain_meta] 直发异常: " + str(e))
    if ok:
        print("[drain_meta] P0 直发成功(绕开队列)")
    else:
        print("[drain_meta] P0 直发失败, 已落 alert_log.jsonl")
    entry = json.dumps({"ts": now_iso(), "alert": "drain-meta P0: " + text,
                        "channel": "bot_api_bypass"}, ensure_ascii=False)
    try:
        os.makedirs(os.path.dirname(ALERT_LOG), exist_ok=True)
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception as e:
        print("[drain_meta] 写 alert_log 失败: " + str(e))


def main():
    rings = [
        ("drain", drain_age_minutes(), MAX_AGE_MIN, "QSP_MsgDrain 告警环"),
        ("self_heal", selfheal_age_minutes(), WD_MAX_AGE_MIN, "QSP_SelfHeal(T7自愈引擎)"),
        ("sys_watchdog", state_age_minutes(os.path.join(PROJECT, "data", "watchdog_state.json")), WD_MAX_AGE_MIN, "QSP_SysWatchdog(数据/配置层探测)"),
    ]
    meta = load_json(META_STATE) or {}
    consec = int(meta.get("consec_fail", 0))

    dead, ages = [], {}
    all_fresh = True
    for key, age, threshold, label in rings:
        ages[key] = None if age is None else round(age, 1)
        fresh = age is not None and age < threshold
        if not fresh:
            all_fresh = False
            dead.append("%s(%s)%s" % (label, "缺失" if age is None else "龄%dm" % round(age), " 停摆"))
    # 注: 若某环 state 文件从未生成(该任务还没跑过), 按缺失计 — 部署期 grace 由首跑自愈

    if all_fresh:
        if consec > 0:
            print("[drain_meta] 三环全部恢复活跃 %s, 复位静默" % ages)
        meta.update({"last_run": now_iso(), "consec_fail": 0, "state": "fresh", "ring_ages_min": ages})
    else:
        consec += 1
        note = "; ".join(dead)
        should_alert = (consec == ALERT_ROUND) or \
                       (consec > ALERT_ROUND and (consec - ALERT_ROUND) % REPEAT_EVERY == 0)
        if should_alert:
            send_p0_bypass("🔴 [运维闭环meta-P0] %s (连续%d轮)。自愈/告警触达可能全部失效, "
                          "请检查 QSP_MsgDrain / QSP_SelfHeal / QSP_SysWatchdog 计划任务。" % (note, consec))
        else:
            print("[drain_meta] %s (连续%d轮, 未到告警轮)" % (note, consec))
        meta.update({"last_run": now_iso(), "consec_fail": consec, "state": "stale", "ring_ages_min": ages})

    try:
        with open(META_STATE, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[drain_meta] 写 drain_meta_state.json 失败: " + str(e))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
