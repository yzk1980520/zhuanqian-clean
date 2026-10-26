#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""machine_wake_state.py — 机器清醒状态感知 (t_51e04b30 B案, 2026-10-20 老三)

背景: QSP_MsgDrain/QSP_DrainWatch 设 StopOnIdleEnd=true 空闲即停, 机器夜间休眠
时整环静默, self_heal 按 15min 机械判 P0 -> P0 误报风暴 (10-17 consec_p0=32,
根因与时间线见 docs/drain告警环-空闲静默窗口诊断-20261017.md)。本模块给
self_heal P-01/P-02 检测层提供"机器最近唤醒/输入时间", 让 P0 判定区分
"真断链(机器醒着)→P0" 与 "机器睡了(按设计静默)→降级 INFO"。

双源:
  1. 最近唤醒: Windows System 日志 Kernel-Power 42(Wake)/507(Resume)
     (实勘 2026-10-20: 本机无独立 "Power-Troubleshooter" 通道, 该 provider 挂在
      System 日志下; 诊断文档"事件日志 Power-Troubleshooter 42/507"=同一组事件)
  2. 最近输入: user32.GetLastInputInfo + kernel32.GetTickCount64

判定语义 (老六会签条件①固化 — 取最保守值=最可能清醒一侧, 防改回 AND):
    清醒 = (最近输入 < 30min) 或 (最近唤醒 < 15min)
    休眠 = 双源均未命中
    任一源不可用 = 该源不命中(绝不可把"不可用"当"休眠"证据; 双源全不可用
    时 probe 标记 available=False, 消费方保守照报 P0)。
    ⚠️ AND 语义 = 双源都命中才判清醒 = 漏报真 P0(比休眠期误报恶劣), 禁止。
    守卫: guard_semantics() 在 CI 跑, 防回归改回 AND。

用法:
  python scripts/machine_wake_state.py   # 打印当前双源快照(探针自检)
"""
import datetime as _dt
import re
import subprocess
import sys
import time

# 清醒判定阈值 (分钟) — 判据口径由诊断文档B案/老六会签①固化, 改动须走会签
AWAKE_INPUT_MAX_MIN = 30   # 最近输入 < 30min -> 判清醒
AWAKE_WAKE_MAX_MIN = 15    # 最近唤醒 < 15min -> 判清醒
# 第5态"刚醒"窗口 (老六会签条件②): 唤醒后第一个 self_heal 周期内,
# stale 时间戳整体落在休眠窗内的复检不得升 P0
JUST_WOKEN_MAX_MIN = 15

_POWERSHELL = "powershell"
_PS_PROBE = (
    "Get-WinEvent -FilterHashtable "
    "@{LogName='System';ProviderName='Microsoft-Windows-Kernel-Power';Id=@(42,507)} "
    "-MaxEvents 1 | ForEach-Object { $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss') }"
)
# 唤醒事件时间戳: PS 侧固定输出 yyyy-MM-dd HH:mm:ss(防 zh-CN 文化输出 '2026年6月29日' 形态)
_TS_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})")


def last_wake_time(now=None):
    """最近一次 42(Wake)/507(Resume) 事件时间(datetime, 本地)。不可用 -> None。
    只读事件日志, 不碰任何任务本体(红线: 方案A WakeToRun 已否, 此处零动作)。"""
    try:
        p = subprocess.run(
            [_POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", _PS_PROBE],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = p.stdout.decode("gbk", errors="replace")
        m = _TS_RE.search(out)
        if not m:
            return None
        now = now or _dt.datetime.now()
        base = _dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            int(m.group(4)), int(m.group(5)), int(m.group(6)))
        # 跨年修正: 事件时间不会"在未来"(日志时区=本地), 未来 -> 上一年
        if base > now + _dt.timedelta(minutes=5):
            base = base.replace(year=base.year - 1)
        return base
    except Exception:
        # 具名异常兜底: 查询失败(非 Windows/日志缺失/超时) -> None,
        # 语义=该源不可用(不可当"休眠"证据), get_wake_state 会标 available=False
        return None


def last_input_time(now=None):
    """最近一次键盘/鼠标输入时间(datetime, 本地)。不可用 -> None。
    GetLastInputInfo.LastInput 与 GetTickCount64 同基准(系统启动ms)。"""
    import ctypes
    now = now or _dt.datetime.now()
    try:
        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint32), ("dwTime", ctypes.c_uint32)]
        li = _LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        ok = ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
        tick64 = ctypes.windll.kernel32.GetTickCount64()
        if not ok:
            return None
        idle_s = (tick64 - li.dwTime) / 1000.0
        return now - _dt.timedelta(seconds=idle_s)
    except Exception:
        return None  # 非 Windows / API 不可用 -> 该源不可用


def get_wake_state(last_input=None, last_wake=None, now=None):
    """纯判定层(可注入双源值, 供单测): 返回清醒/休眠判定 dict。

    语义固化 (老六会签①):
      awake     = (input_age < 30min) 或 (wake_age < 15min)   # OR, 严禁 AND
      just_woken = wake_age 非空 且 < 15min (第5态用)
      available = 至少一个源给出了可判定的时间戳; 双源全 None -> False
      awake 在 available=False 时恒 False (调用方按"不可证明休眠"保守照报)
    """
    now = now or _dt.datetime.now()
    if last_input is not None:
        input_age_min = (now - last_input).total_seconds() / 60.0
        in_hit = input_age_min < AWAKE_INPUT_MAX_MIN
    else:
        input_age_min, in_hit = None, False  # 源不可用 = 不命中, 绝不能当"休眠"证据
    if last_wake is not None:
        wake_age_min = (now - last_wake).total_seconds() / 60.0
        wk_hit = wake_age_min < AWAKE_WAKE_MAX_MIN
    else:
        wake_age_min, wk_hit = None, False

    # OR 语义固化点: 任一源命中即清醒(漏报防线), 见模块 docstring 守卫说明
    awake = in_hit or wk_hit
    just_woken = wk_hit  # wake_age 在 (0,15) 或负值(刚醒, 事件解析容差) -> 判刚醒
    return {
        "available": last_input is not None or last_wake is not None,
        "awake": awake,
        "just_woken": just_woken,
        "last_input": last_input.isoformat() if last_input else None,
        "last_wake": last_wake.isoformat() if last_wake else None,
        "input_age_min": round(input_age_min, 1) if input_age_min is not None else None,
        "wake_age_min": round(wake_age_min, 1) if wake_age_min is not None else None,
        "reasons": ([s for s, h in (("input<%dmin" % AWAKE_INPUT_MAX_MIN, in_hit),
                                     ("wake<%dmin" % AWAKE_WAKE_MAX_MIN, wk_hit)) if h]
                    or (["no-recent-input", "no-recent-wake"]
                        if (last_input is not None or last_wake is not None) else ["sources-unavailable"])),
    }


def probe_wake_state():
    """实采双源(Windows API + 事件日志), 返回 get_wake_state 判定 dict。
    双源全部不可用 -> available=False, 消费方按 fail-safe 保守照报 P0。"""
    return get_wake_state(last_input=last_input_time(),
                          last_wake=last_wake_time(),
                          now=_dt.datetime.now())


def guard_semantics():
    """守卫断言: 双源"取最保守值"=OR 语义 (老六会签①防改回 AND)。
    任一单源证据即判清醒; 若实现被改成 AND, 本函数/对应单测必须失败。"""
    base = _dt.datetime(2026, 10, 20, 12, 0, 0)
    # 仅输入源命中 -> 必须判清醒
    assert get_wake_state(last_input=base - _dt.timedelta(minutes=5),
                          last_wake=None, now=base)["awake"] is True, \
        "OR守卫失败: 仅输入源命中却判非清醒(疑似改回 AND)"
    # 仅唤醒源命中 -> 必须判清醒
    assert get_wake_state(last_input=None,
                          last_wake=base - _dt.timedelta(minutes=5), now=base)["awake"] is True, \
        "OR守卫失败: 仅唤醒源命中却判非清醒(疑似改回 AND)"
    # 双源均未命中 -> 休眠
    assert get_wake_state(last_input=base - _dt.timedelta(minutes=120),
                          last_wake=base - _dt.timedelta(minutes=120), now=base)["awake"] is False
    # 双源不可用 -> 不可证明清醒(available=False, 消费方 fail-safe)
    st = get_wake_state(last_input=None, last_wake=None, now=base)
    assert st["awake"] is False and st["available"] is False


if __name__ == "__main__":
    st = probe_wake_state()
    print("machine_wake_state probe @ %s" % _dt.datetime.now().isoformat(timespec="seconds"))
    for k, v in st.items():
        print("  %s: %s" % (k, v))
