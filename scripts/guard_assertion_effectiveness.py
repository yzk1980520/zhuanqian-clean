#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
断言有效性守卫 —— 防止「有效性判据」被降级回「存在性判据」

背景（2026-10-19 断裂1/2 实证）：
  闭环健康度 10 条断言中有 5 条（A1/A3/A4/A5/A6/A8）只验「文件在不在 / 台账有没有登记」，
  导致体检器停摆 36h、假绿检测器停更 46 天、43 条缺陷 0 销账，而仪表仍报 95%~100% 满分。
  已按方案A 升级为「产物新鲜度 + 数量」判据。

为什么需要本守卫（老大铁律 + AGENTS.md §4.1-12 回授断言注册铁律）：
  升级后的断言会让健康度**由绿转红**（95% → 81.8%）。
  这是预期内的「变诚实」，但**其他 agent / worker 看到红色很可能"修复"它** ——
  而最省事的"修复"就是把判据改回存在性检查，于是假绿复辟，且无人察觉。
  本守卫把「判据必须验有效性」固化为可执行的回归断言。

判据（每条都必须为真，否则 FAIL）：
  G1  freshness 底座存在且被调用          —— _age_hours / _fresh_verdict
  G2  A0 元断言已注册                      —— 体检器自身活性可被检出
  G3  A3 验新鲜度而非仅非空                —— 含 48h 窗口
  G4  A5 验产物新鲜度                      —— 含 fake_positive_log 路径
  G5  A6 验自审产物新鲜度而非仅台账        —— 含 laosi_audit 路径
  G6  抑制窗口已按优先级分层                —— P0 窗口 < P2 窗口（防 P0 被拖累）
  G7  抑制键含优先级                       —— 防 emoji 前缀导致 P0 信息丢失
  G22 因子门禁与因子层开关解耦 + 两个注入因子不得回潮 valid（2026-10-21 立）
  G23 walk-forward 门禁选源必须按**内容指纹**，严禁回退成 mtime 排序（2026-10-21 立）
      —— 防「复制旧结果改时间戳冒充重标定」（commit 9a13bb8d 已核实的造假手法）。
      被保护文件 scripts/walk_forward_gate.py 头部有配套严禁清单。
  G24 关键防线脚本必须被 git 跟踪 + 有 .gitignore 白名单（2026-10-21 立）
      —— .gitignore L15 的 scripts/* 让 ~360 个 .py 对 git 不可见；
      实测 189 个已入库 scripts 文件里 79 个处于「已 tracked 但无白名单」的脆弱态。
      注意：裸 git check-ignore 对已 tracked 文件恒返回 exit=1（假绿），
      必须用 --no-index 实测。
  G25 回归套件 L 组必须覆盖 is_sharpe/oos_sharpe 字段比对（2026-10-25 立）
      —— L 组(check_review_status_matches_truth)是「review_status 门禁字段
      与真源逐项一致」的唯一防线；摘掉 want dict 里的 is_sharpe/oos_sharpe
      条目=「旧真值当新真值」静默失守(本次 t_55ddecd9 实证: 0.9906/0.2122
      与再选源后的 0.592/0.4604 分叉)。判据验 dict 条目行+比对循环行+
      FAIL 分支+main 调用, 四层执行性语句, 字样出现不算数。

用法：
  python scripts/guard_assertion_effectiveness.py        # 人类可读
  python scripts/guard_assertion_effectiveness.py --json # 机器可读
退出码：0=全过  1=有 FAIL（判据被降级）
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CLOSEDLOOP = ROOT / "scripts" / "closedloop_health.py"
SENDER = ROOT / "cron_message_sender.py"
PIPELINE = ROOT / "scripts" / "auto_backtest_pipeline.py"
DAILY_PICK = ROOT / "daily_pick.py"
IC_LATEST = ROOT / "data" / "factor_ic" / "factor_ic_latest.json"
# 2026-10-21 裁定为人为注入凑数、已回滚的因子 (10-17 各历史版本恒为 dead)
INJECTED_FACTORS = ("PRICE_VOL_RANK", "UPPER_SHADOW")
WFG = ROOT / "scripts" / "walk_forward_gate.py"
REGRESSION = ROOT / ".agent" / "regression" / "__init__.py"  # G25: L 组所在回归套件

# G24 受保护名单: 关键防线脚本必须在 git 里**被跟踪**且**有 .gitignore 白名单**。
# 漏掉任何一条 = 换机/CI checkout 后该防线静默消失, 且被误删时无法用 git 找回。
TRACK_REQUIRED = (
    "scripts/guard_assertion_effectiveness.py",  # 本守卫自身(G1~G24 防线)
    "scripts/closedloop_health.py",              # 体检器判据真源
    "scripts/check_all.py",                      # 门禁入口
    "scripts/walk_forward_gate.py",              # G23 产物指纹选源
    "scripts/auto_backtest_pipeline.py",         # G21 解冻不被机器覆写
    "scripts/verify_config.py",                  # 配置校验(门禁前置)
    "scripts/record_gate_fingerprint.py",        # 门禁产物指纹台账写入器
    "scripts/factor_ic_132d_refresh.py",         # 因子 IC 权威源(接指纹台账)
    "scripts/gate_check.py",                     # 因子门禁执行者
    "scripts/pre_pick_gate.py",                  # 选股前 P0 阻断门
    "scripts/sync_trial_gate.py",                # 试用期门禁同步件
    "scripts/check_protocol_mount.py",           # 规范指针挂载三重核验
    "scripts/check_task_contract.py",            # 任务契约读侧消费断言
    "scripts/fake_positive_detector.py",         # 假绿检测器(A5 判据数据真源)
    "scripts/verify_walk_forward_fingerprint.py",  # G23 防线验证器
    "scripts/chain_health_check.py",             # 链健康检查(check_all health dispatch)
    "scripts/run_path_hidden.vbs",               # 静默 runner(载体形态依赖)
    # ── 2026-10-21 bulk79 扩面: 以上 17 条只守得住"门禁链", 守不住"运行时链" ──
    # 实测 scripts/ 下 73 个已 tracked 但无白名单的脆弱项中, 下面这批是**正在跑的常设件**;
    # 它们掉库 = 调度/风控/数据拉取静默断链, 而 G24 原名单一个都覆盖不到。
    # (白名单同步补在 .gitignore L296+ 的 bulk79 区块)
    "scripts/cron_dispatcher.py",                # 定时调度中枢
    "scripts/task_router.py",                    # 任务路由
    "scripts/daily_monitor.py",                  # 日常监控主程序
    "scripts/daily_auto.bat",                    # 每日自动批处理入口
    "scripts/automation_scheduler.sh",           # 御龙决全自动化调度 wrapper
    "scripts/skill_health_weekly.sh",            # 周度技能体检载体
    "scripts/weekly_meeting_reminder.sh",        # 周会提醒载体
    "scripts/gateway_guardian.py",               # 网关守护进程
    "scripts/t7_qsp_watchdog.py",                # T7 QSP 看门狗
    "scripts/monitor.sh",                        # 监控 cron wrapper
    "scripts/risk_manager.py",                   # 风控真源
    "scripts/risk_check.sh",                     # 风控 cron wrapper
    "scripts/stop_loss_strategy.py",             # 止损策略
    "scripts/sync_holdings.py",                  # 持仓同步
    "scripts/cooldown_eval.py",                  # 冷却期评估
    "scripts/position_adjust.sh",                # 调仓 cron wrapper
    "scripts/merge_manual_trades.py",            # 手工成交合并
    "scripts/weight_adjustment_task.py",         # 权重调整任务
    "scripts/single_stock_rotation.py",          # 单票轮动
    "scripts/execute_followup.py",               # 跟单执行
    "scripts/akshare_daily_pull.py",             # 盘后数据拉取主程序
    "scripts/akshare_daily_pull.sh",             # 盘后拉取 cron wrapper
    "scripts/industry_refresh_local.sh",         # 开盘行业成分拉取 wrapper
    "scripts/north_flow_fetch.py",               # 北向资金抓取
    "scripts/data_quality_monitor.py",           # 数据质量监控
    "scripts/market_signal_monitor.py",          # 市场信号监控
    "scripts/build_dashboard.py",                # 看板构建
    "scripts/closedloop_daily_report.py",        # 闭环健康度日报登记
    "scripts/team_discussion.py",                # 三方讨论(现役版, _v2/_v3 为历史副本)
    "scripts/team_feishu_notifier.py",           # 团队飞书通知
    "scripts/aoci_weekly_score.py",              # AOCI 周度评分
    "scripts/memory_manager.py",                 # 记忆管理
)


def _resolve_guarded_module(legacy_rel: str, core_rel: str):
    """S4 基地化迁移兼容: 守卫判据须验实际实现文件, 而非根级 shim。

    根级文件已被 S4 迁移替换为 re-export shim (8 行), 守卫只读 shim 文本
    会恒不匹配 => 假红。优先 core 家族实际文件; 缺失时回退根级旧路径
    (兼容迁移前状态); 两者皆缺返回 None (FAIL, 不猜测)。
    """
    real = ROOT / core_rel
    if real.exists():
        return real
    legacy = ROOT / legacy_rel
    if legacy.exists():
        return legacy
    return None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"🔴 [guard_assertion_effectiveness.py:119] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return ""


def check_g1() -> tuple:
    """freshness 底座存在且被实际调用（定义了但没人用 = 摆设）"""
    src = _read(CLOSEDLOOP)
    if "def _age_hours" not in src or "def _fresh_verdict" not in src:
        return False, "缺少 _age_hours / _fresh_verdict 底座"
    calls = len(re.findall(r"_fresh_verdict\(", src)) - 1  # 减去定义本身
    if calls < 2:
        return False, f"_fresh_verdict 仅被调 {calls} 次（疑似摆设，应 ≥2）"
    return True, f"底座存在，_fresh_verdict 被调 {calls} 次"


def check_g2() -> tuple:
    """A0 元断言已注册进 ASSERTION_CHECKS"""
    src = _read(CLOSEDLOOP)
    if "def check_a0_meta_selfcheck" not in src:
        return False, "A0 元断言函数不存在"
    if "A0_体检器自身活性" not in src:
        return False, "A0 未注册进 ASSERTION_CHECKS"
    return True, "A0 元断言已注册"


def check_g3() -> tuple:
    """A3 验新鲜度，而非仅非空

    2026-10-21 二次升级: 判据由「近 48h 新增条数 > 0」改为「末条记录 ts 的
    工作日小时新鲜度」(soft 24h / hard 72h)。本条只做**存在性**兜底，
    执行性校验见 G19 —— 两道独立防线，任一条被绕过另一条仍会报红。
    """
    src = _read(CLOSEDLOOP)
    m = re.search(r"def check_a3_feedback_write.*?(?=\ndef )", src, re.S)
    body = m.group(0) if m else ""
    if "A3_SOFT_H" not in body or "A3_HARD_H" not in body:
        return False, "A3 已退化：未使用新鲜度阈值常量 (回退为仅验非空)"
    return True, "A3 含新鲜度判据 (24h/72h)"


def check_g4() -> tuple:
    """A5 验假绿检测器产物新鲜度"""
    src = _read(CLOSEDLOOP)
    m = re.search(r"def check_a5_false_green.*?(?=\ndef )", src, re.S)
    body = m.group(0) if m else ""
    if "fake_positive_log" not in body:
        return False, "A5 已退化：未校验 fake_positive_log 产物新鲜度"
    if "_fresh_verdict" not in body:
        return False, "A5 已退化：未使用新鲜度判据"
    return True, "A5 校验假绿检测器产物新鲜度"


def check_g5() -> tuple:
    """A6 验自审产物新鲜度，而非仅 cron 台账"""
    src = _read(CLOSEDLOOP)
    m = re.search(r"def check_a6_self_audit.*?(?=\ndef )", src, re.S)
    body = m.group(0) if m else ""
    if "laosi_audit" not in body:
        return False, "A6 已退化：未校验 laosi_audit 产物"
    if "_fresh_verdict" not in body:
        return False, "A6 已退化：回退为仅验 cron 台账"
    return True, "A6 校验自审产物新鲜度"


def check_g6() -> tuple:
    """抑制窗口按优先级分层：P0 窗口必须显著小于 P2"""
    src = _read(SENDER)
    m0 = re.search(r"SUPPRESS_WINDOW_P0_MIN\s*=\s*(\d+)", src)
    m2 = re.search(r"SUPPRESS_WINDOW_MIN\s*=\s*(\d+)", src)
    if not m0 or not m2:
        return False, "优先级分层窗口常量缺失（P0 会与 P2 共享窗口）"
    p0, p2 = int(m0.group(1)), int(m2.group(1))
    if p0 >= p2:
        return False, f"P0 窗口({p0}min) 未小于 P2 窗口({p2}min)，优先级倒置未修复"
    return True, f"P0={p0}min < P2={p2}min 分层生效"


def check_g7() -> tuple:
    """抑制键含优先级（防 emoji 前缀导致 P0 信息丢失）"""
    src = _read(SENDER)
    if "_priority_of" not in src:
        return False, "缺少 _priority_of，P0 优先级未并入抑制键"
    if not re.search(r"skey\s*=\s*prio\s*\+\s*\"#\"\s*\+\s*_suppress_key", src):
        return False, "抑制键未拼接优先级"
    return True, "抑制键含优先级前缀"


def check_g8() -> tuple:
    """A11 跨体检器交叉校验已注册（防三个体检器结论矛盾而无报错）"""
    src = _read(CLOSEDLOOP)
    if "def check_a11_cross_validation" not in src:
        return False, "A11 交叉校验函数不存在"
    if "A11_跨体检器交叉校验" not in src:
        return False, "A11 未注册进 ASSERTION_CHECKS"
    if "defect_ledger" not in src:
        return False, "A11 未读取缺陷台账（交叉校验名存实亡）"
    return True, "A11 交叉校验已注册且读取缺陷台账"


def check_g9() -> tuple:
    """A12 调度载体断言已注册 + 载体文件真实存在"""
    src = _read(CLOSEDLOOP)
    if "def check_a12_schedule_carrier" not in src:
        return False, "A12 调度载体断言不存在"
    if "A12_关键调度载体" not in src:
        return False, "A12 未注册进 ASSERTION_CHECKS"
    bat = ROOT / "scripts" / "Zhuanqian_ClosedLoopHealth.bat"
    if not bat.exists():
        return False, "体检器调度载体 scripts/Zhuanqian_ClosedLoopHealth.bat 不存在"
    vbs = ROOT / "scripts" / "run_path_hidden.vbs"
    if not vbs.exists():
        return False, "静默 runner scripts/run_path_hidden.vbs 不存在"
    # A12 必须验到「真注册 + 静默」两层，只验文件存在 = 退化为存在性判据
    for token in ("_query_scheduled_task", "TASK_NAME_CLOSEDLOOP"):
        if token not in src:
            return False, f"A12 缺失注册态查询能力 ({token}) —— 退化为纯文件存在检查"
    # 必须验「执行性语句」，不能只看字样出现：docstring/注释里写到 wscript
    # 也会让 `in src` 判过 —— 那就是本守卫自己犯了存在性判据的病。
    # 静默链判据已于 2026-10-21 从「Command 含 wscript 子串」升级为
    # 「宿主 ∈ SILENT_HOSTS」—— 子串判定会被 `cmd /c wscript ...` 这类
    # 路径绕过，且发现不了 Hidden 缺失。此处同步校验升级后的判定行。
    if not re.search(r"if\s+host\s+not\s+in\s+SILENT_HOSTS\s*:", src):
        return False, "A12 未校验静默链 (缺宿主白名单判据) —— 弹窗风险无人拦截"
    return True, "A12 已注册且验到载体+注册态+静默三层"


def check_g10() -> tuple:
    """注册脚本必须走 wscript 静默链 + Hidden=true (铁律1: 禁弹终端面板)

    最容易被"顺手改回去"的一处: 把 Command 直接指向 .bat 看起来更简单，
    但 .bat 在交互式会话下会拉起 cmd + python 控制台窗口。
    """
    ps1 = ROOT / "scripts" / "register_closedloop_task.ps1"
    if not ps1.exists():
        return False, "注册脚本 scripts/register_closedloop_task.ps1 不存在"
    src = ps1.read_text(encoding="utf-8", errors="replace")
    if "run_path_hidden.vbs" not in src:
        return False, "注册脚本未走 run_path_hidden.vbs 静默链"
    if "<Hidden>true</Hidden>" not in src:
        return False, "注册脚本任务 XML 缺 <Hidden>true</Hidden>"
    # 验赋值语句本身。注释里写 wscript 不算数 —— 见 G9 同类教训。
    if not re.search(r"\$WscriptPath\s*=\s*Join-Path\s+\$env:SystemRoot\s+'System32\\wscript\.exe'", src):
        return False, "注册脚本 Command 未指向 wscript.exe (会弹控制台窗口)"
    return True, "注册脚本为静默链 (wscript + run_path_hidden.vbs + Hidden)"


def check_g11() -> tuple:
    """假绿检测器必须每次运行留心跳 + A5 必须查心跳

    反例(2026-10-19 实证): detector 只在 findings>0 时写产物 ⇒ findings=0
    时完全不留痕 ⇒ 任何基于「产物 mtime」的判据在常态下永远验不出它跑过。
    若有人删掉心跳，A5 会退化成不可判定，故此处拦死。
    """
    det = ROOT / "scripts" / "fake_positive_detector.py"
    if not det.exists():
        return False, "fake_positive_detector.py 不存在"
    src = det.read_text(encoding="utf-8", errors="replace")
    if "RUN_HEARTBEAT_PATH" not in src or "_append_run_heartbeat" not in src:
        return False, "detector 缺运行心跳机制 (findings=0 时不留痕)"
    # 两个返回路径都必须写心跳：正常 + 数据异常
    calls = src.count("_append_run_heartbeat(")
    if calls < 3:  # 1 个定义 + 至少 2 个调用点
        return False, f"心跳调用点不足 ({calls} 处)，异常分支可能未留痕"
    cl = _read(CLOSEDLOOP)
    if "fake_positive_runs.jsonl" not in cl:
        return False, "A5 未查心跳文件 fake_positive_runs.jsonl"
    return True, "detector 心跳机制完整且 A5 查心跳"


def check_g12() -> tuple:
    """周度假绿检测载体存在 + 注册脚本走静默链"""
    bat = ROOT / "scripts" / "Zhuanqian_WeeklyIC.bat"
    if not bat.exists():
        return False, "周度载体 scripts/Zhuanqian_WeeklyIC.bat 不存在"
    ps1 = ROOT / "scripts" / "register_weeklyic_task.ps1"
    if not ps1.exists():
        return False, "周度注册脚本 scripts/register_weeklyic_task.ps1 不存在"
    src = ps1.read_text(encoding="utf-8", errors="replace")
    if "run_path_hidden.vbs" not in src or "<Hidden>true</Hidden>" not in src:
        return False, "周度注册脚本非静默链 (会弹窗口)"
    if not re.search(r"\$WscriptPath\s*=\s*Join-Path\s+\$env:SystemRoot\s+'System32\\wscript\.exe'", src):
        return False, "周度注册脚本 Command 未指向 wscript.exe"
    return True, "周度载体齐备且为静默链"


def check_g13() -> tuple:
    """G13 交易日历 fail-close 真接上 (非装饰性告警)

    ⚠️ 必须验**执行性语句**, 不能只验「字样出现」——
    注释/docstring 里写着 _check_calendar_freshness 也能让字样型判据假绿
    (本仓库第 13 次同类)。故用正则匹配赋值/判断行本身。

    S4 基地化迁移 (18eecc3a) 后根级 trading_hours.py 只剩 re-export shim,
    实际实现在 core/pipeline/trading_hours.py —— 判据经 _resolve_guarded_module
    解析到实际文件, 否则读 shim 文本恒不匹配 = 假红 (2026-10-25 t_7d51e9ea 根因)。
    """
    src_file = _resolve_guarded_module("trading_hours.py", "core/pipeline/trading_hours.py")
    if src_file is None:
        return False, "trading_hours.py 不存在 (根级旧路径与 core/pipeline/ 均缺失)"
    src = src_file.read_text(encoding="utf-8", errors="replace")

    # ① 调用点必须接返回值: `if not _check_calendar_freshness():` + `return False`
    if not re.search(
            r"if\s+not\s+_check_calendar_freshness\s*\(\s*\)\s*:\s*\n\s*return\s+False", src):
        return False, ("调用点未接 _check_calendar_freshness() 返回值 "
                       "(告警装饰性: 说锁死却不 return False)")
    # ② _calendar_warned 短路必须已修: 不能出现 `if _calendar_warned: return True`
    if re.search(r"if\s+_calendar_warned\s*:\s*\n\s*return\s+True", src):
        return False, ("_calendar_warned 短路仍在: 第 2 次调用起恒 return True "
                       "谎报新鲜 (校验存在但静默不生效)")
    # ③ 告警去重仍应保留(不能为了修判定而把去重删掉)
    if "_calendar_warned = True" not in src:
        return False, "告警一次性去重丢失 (_calendar_warned 赋值)"
    return True, "fail-close 真接上 + 短路已修 + 去重保留"


def check_g14() -> tuple:
    """G14 A13 日历新鲜度断言已注册且真读日历产物"""
    src_file = ROOT / "scripts" / "closedloop_health.py"
    if not src_file.exists():
        return False, "closedloop_health.py 不存在"
    src = src_file.read_text(encoding="utf-8", errors="replace")
    if "check_a13_calendar_freshness" not in src:
        return False, "A13 check_a13_calendar_freshness 未定义"
    if "A13_日历新鲜度" not in src:
        return False, "A13 未注册进 ASSERTION_CHECKS"
    # 有效性判据: 真读 trading_calendar.json 且解析 pulled_at
    if "trading_calendar.json" not in src:
        return False, "A13 未读 data/trading_calendar.json (退化为存在性检查)"
    if "pulled_at" not in src:
        return False, "A13 未校验 pulled_at 新鲜度"
    return True, "A13 已注册且验 pull_at 新鲜度 + 覆盖今天"


def check_g15() -> tuple:
    """G15 日历刷新载体 + 注册脚本静默 (无载体 ⇒ 装上 fail-close 后必停摆)"""
    bat = ROOT / "scripts" / "Zhuanqian_CalendarRefresh.bat"
    if not bat.exists():
        return False, "日历刷新载体 scripts/Zhuanqian_CalendarRefresh.bat 不存在"
    ps1 = ROOT / "scripts" / "register_calendarrefresh_task.ps1"
    if not ps1.exists():
        return False, "日历注册脚本 scripts/register_calendarrefresh_task.ps1 不存在"
    src = ps1.read_text(encoding="utf-8", errors="replace")
    if "run_path_hidden.vbs" not in src or "<Hidden>true</Hidden>" not in src:
        return False, "日历注册脚本非静默链 (会弹窗口)"
    if not re.search(
            r"\$WscriptPath\s*=\s*Join-Path\s+\$env:SystemRoot\s+'System32\\wscript\.exe'", src):
        return False, "日历注册脚本 Command 未指向 wscript.exe"
    return True, "日历刷新载体齐备且为静默链"


def check_g16() -> tuple:
    """G16 A12 必须覆盖全部 4 个关键载体，且真遍历清单 (防缩回「只查体检器一个」)

    ⚠️ 判据只认 CARRIER_SPECS 列表块内的条目 —— 文件注释/docstring 里出现任务名
    不算命中(第 13 次「字样出现」型假绿的教训)。
    """
    src_file = ROOT / "scripts" / "closedloop_health.py"
    if not src_file.exists():
        return False, "closedloop_health.py 不存在"
    src = src_file.read_text(encoding="utf-8", errors="replace")

    m = re.search(r"CARRIER_SPECS\s*=\s*\[(.*?)\]", src, re.S)
    if not m:
        return False, "CARRIER_SPECS 清单不存在 (A12 未做多载体覆盖)"
    block = m.group(1)
    required = ["Zhuanqian_ClosedLoopHealth", "Zhuanqian_CalendarRefresh",
                "Zhuanqian_WeeklyIC", "Zhuanqian_DailyReview"]
    missing = [t for t in required if t not in block]
    if missing:
        return False, f"CARRIER_SPECS 缺载体: {missing}"
    # 执行性判据: 真遍历清单，而不是定义完不用
    if not re.search(r"for\s+task_name,\s*desc,\s*entry\s+in\s+CARRIER_SPECS", src):
        return False, "check_a12 未遍历 CARRIER_SPECS (清单定义了但没用)"
    # 2026-10-21: 查询方式由「逐个 spawn PowerShell」改为「一次批量 + 按清单判定」，
    #   两种实现都接受，但**必须**按 CARRIER_SPECS 逐载体取注册态。
    per_task = (re.search(r"_query_scheduled_task\(\s*task_name\s*\)", src)
                or re.search(r"tasks\.get\(\s*task_name\s*\)", src))
    if not per_task:
        return False, "check_a12 未对每个载体查注册态"
    return True, "A12 保留 4 个基线载体且按清单逐一查注册态"


def check_g17() -> tuple:
    """G17 A12 必须验「形态双维度」: Hidden=true **且** Command 宿主 ∈ SILENT_HOSTS

    2026-10-21 立。背景: 原 A12 只判 `Command` 里含 `wscript` 子串，
    于是 Zhuanqian_DailyAuto (cmd /c 直跑 bat + Hidden 未设 + 每日 20:00 真跑)
    每天在老大桌面弹黑窗，体检器 4/4 全绿毫不知情。

    ⚠️ 全部判据都验**执行性语句**(正则匹配真实的 if/赋值行)，不是字样出现:
       注释、docstring、本守卫自己的说明文字里写到 Hidden / SILENT_HOSTS
       都不会让它判过 —— 那就是本守卫自己犯了「存在性判据」的病
       (本仓库第 14 次同类教训，见 G9/G13 注释)。
    """
    src = _read(CLOSEDLOOP)

    # ① 白名单常量必须存在
    m = re.search(r"SILENT_HOSTS\s*=\s*\(([^)]*)\)", src, re.S)
    if not m:
        return False, "A12 缺 SILENT_HOSTS 白名单常量 (Command 宿主无人校验)"
    hosts = re.findall(r'"([^"]+)"', m.group(1))
    if "wscript.exe" not in hosts or len(hosts) < 2:
        return False, f"SILENT_HOSTS 白名单被掏空或缺失 wscript.exe: {hosts}"

    # ② Hidden 维度: 必须有一处 `if hidden is not True:` 这样的判定
    if not re.search(r"if\s+hidden\s+is\s+not\s+True\s*:", src):
        return False, ("A12 未验 Settings/Hidden=true (缺 `if hidden is not True` 判定) "
                       "—— Hidden 缺失导致的弹窗无人拦截")

    # ③ Command 宿主维度: 必须有一处 `if host not in SILENT_HOSTS:`
    if not re.search(r"if\s+host\s+not\s+in\s+SILENT_HOSTS\s*:", src):
        return False, ("A12 未验 Command 宿主白名单 (缺 `if host not in SILENT_HOSTS` 判定) "
                       "—— Command 直指 .bat/.cmd 的弹窗无人拦截")

    # ④ 不合规必须落到 FAIL(计入 fail_items)，不能只是记录/告警
    if not re.search(r"fail_items\.append", src):
        return False, "形态不合规项未计入 fail_items (降级为仅记录，分数不转红)"
    m2 = re.search(r"if\s+fail_items\s*:", src)
    if not m2:
        return False, "缺少 `if fail_items:` 分支 (不合规载体不会被判 FAIL)"
    if '"status": "FAIL"' not in src[m2.start():m2.start() + 500]:
        return False, "fail_items 非空时未返回 FAIL (不合规载体被放生)"

    return True, f"A12 形态双维度生效 (Hidden=true + 宿主 ∈ {hosts})"


def check_g18() -> tuple:
    """G18 A0 严禁兜底 PASS: history 缺失 / 读取失败 / 全行不可解析 / 缺 ts ⇒ FAIL

    2026-10-21 立。这是本项目**最危险**的失败模式:
      一个专门发现「系统没在跑」的机制，在它自己没跑的时候报绿。
    旧实现四条兜底路径全部静默落到函数末尾的 `return PASS`，
    判定结果恰好与事实相反。

    ⚠️ 验执行性语句，不验字样。
    """
    src = _read(CLOSEDLOOP)
    m = re.search(r"def check_a0_meta_selfcheck.*?(?=\ndef )", src, re.S)
    body = m.group(0) if m else ""
    if not body:
        return False, "A0 函数体定位失败"

    # ① 不得再用 `if HISTORY_FILE.exists():` 把整个判据包起来(缺失即静默)
    if re.search(r"if\s+HISTORY_FILE\.exists\(\)\s*:", body):
        return False, ("A0 仍是 `if HISTORY_FILE.exists():` 包裹式兜底 —— "
                       "心跳文件不存在时会跳过全部判定并静默 return PASS")
    # ② 必须显式处理「文件不存在」并 FAIL
    if not re.search(
            r"if\s+not\s+HISTORY_FILE\.exists\(\)\s*:\s*\n\s*return\s*\{\s*\"status\":\s*\"FAIL\"",
            body):
        return False, "A0 缺「history 文件不存在 ⇒ FAIL」分支"
    # ③ 必须处理「全部行不可解析」并 FAIL
    if not re.search(r"if\s+last\s+is\s+None\s*:", body):
        return False, "A0 缺「history 全行 JSON 不可解析 ⇒ FAIL」分支"
    # ④ 必须处理「末条缺 ts」并 FAIL
    if not re.search(r"if\s+not\s+last_ts\s*:", body):
        return False, "A0 缺「history 末条缺 ts ⇒ FAIL」分支"
    # ⑤ 末尾的 PASS 必须经过新鲜度计算(带 age_h)，不能是无条件兜底
    tail = [l for l in body.strip().split("\n") if l.strip()][-1]
    if '"status": "PASS"' in tail and "age_h" not in tail:
        return False, ("A0 末尾 PASS 未携带 age_h —— 疑似无条件兜底 return PASS "
                       "(任何异常都会转绿)")
    return True, "A0 无兜底 PASS (缺失/读取失败/不可解析/缺 ts ⇒ FAIL)"


def check_g19() -> tuple:
    """G19 A3 必须验「末条记录 ts 新鲜度」且用**工作日小时**口径

    2026-10-21 立。旧判据「近 48h 新增条数 > 0」的洞:
      · 窗口 48h 对每日盘后任务过宽(实测 45.2h 无新增仍 PASS)；
      · 只数条数不看末条距今，写侧反复追加同一条陈旧记录也能绿。
    现: soft 24h / hard 72h，按 _business_hours_between() 扣除周末后比对。
    """
    src = _read(CLOSEDLOOP)
    m = re.search(r"def check_a3_feedback_write.*?(?=\ndef )", src, re.S)
    body = m.group(0) if m else ""
    if not body:
        return False, "A3 函数体定位失败"

    # ① 必须用工作日小时口径(否则周末误判)
    if not re.search(r"_business_hours_between\s*\(", body):
        return False, "A3 未使用工作日小时口径 (_business_hours_between) —— 周末会被误判停摆"
    # ② 必须按 soft/hard 两级常量判定
    if not re.search(r"age_work_h\s*>\s*A3_SOFT_H", body):
        return False, "A3 未按 A3_SOFT_H 判超期"
    if not re.search(r"age_work_h\s*>\s*A3_HARD_H", body):
        return False, "A3 未按 A3_HARD_H 判停摆"
    # ③ 不得残留旧的「新增条数」计数口径
    # ⚠️ 这里必须验**执行性语句**(recent 的赋值/自增)，不能用 `r"\brecent\b"`
    #    —— 注释里解释旧口径时必然会提到 recent 这几个字母，字样型判据会误报
    #       (本守卫自己的注释就是活证据)。
    if re.search(r"\brecent\s*(\+=|=\s*0)", body):
        return False, "A3 仍使用旧的 recent 计数口径 (存量计数会掩盖写侧停摆)"
    # ④ 阈值常量不得被放宽
    for name, want in (("A3_SOFT_H", 24.0), ("A3_HARD_H", 72.0)):
        mm = re.search(rf"^{name}\s*=\s*([\d.]+)", src, re.M)
        if not mm:
            return False, f"{name} 阈值常量缺失"
        if float(mm.group(1)) > want:
            return False, f"{name} 被放宽到 {mm.group(1)}h (应 ≤ {want}h)"
    return True, "A3 验末条 ts 新鲜度 (soft 24h / hard 72h, 工作日口径)"


def check_g20() -> tuple:
    """G20 CARRIER_SPECS 必须覆盖本机全部 28 个载体，且 check_a12 真遍历

    2026-10-21 立。此前仅有 4 条 ⇒ 覆盖面 4/28，其余 24 个计划任务
    **零断言**: 被删、被改回弹窗式、被禁用，体检器都不会有任何反应。

    ⚠️ 只认 CARRIER_SPECS 列表块内形如 `("TaskName", ...)` 的条目 ——
       文件注释/docstring 里出现任务名不算命中(字样型假绿，第 14 次)。
    """
    src = _read(CLOSEDLOOP)
    m = re.search(r"CARRIER_SPECS\s*=\s*\[(.*?)\n\]", src, re.S)
    if not m:
        return False, "CARRIER_SPECS 清单不存在 (A12 未做多载体覆盖)"
    block = m.group(1)
    entries = re.findall(r'^\s*\(\s*"([^"]+)"', block, re.M)
    if len(entries) < 28:
        return False, f"CARRIER_SPECS 仅 {len(entries)} 条 (应 ≥28)，缺断言的载体: 共 {28 - len(entries)} 个"

    # 执行性判据: 真遍历清单(批量查注册态也要按清单逐条判定)
    if not re.search(r"for\s+task_name,\s*desc,\s*entry\s+in\s+CARRIER_SPECS", src):
        return False, "check_a12 未遍历 CARRIER_SPECS (清单定义了但没用)"
    if 'tasks.get(task_name)' not in src:
        return False, "check_a12 未对每个载体查注册态"
    # 静态清单必须与本机实际注册清单对得上(防止清单被"瘦身")
    if not re.search(r"Get-ScheduledTask", src):
        return False, "缺少计划任务枚举能力 (无法核对清单覆盖面)"
    return True, f"CARRIER_SPECS 覆盖 {len(entries)} 个载体且逐一判定"


def check_g21() -> tuple:
    """G21 周度回测严禁无条件覆写 final_verdict —— 有效人工解冻记录必须挡得住机器

    2026-10-21 立。背景（当前系统最大的单点资金风险）:
      auto_backtest_pipeline.trigger_review() 原实现无条件执行
      `final_verdict = review_gate.compute_final_verdict(...)`。
      周度 findings 三项全命中(all_configs_failed / diversity_collapse / 禁止新买入)
      时该式**必然**算出 'FAIL'，于是每跑一次周度回测就把 2026-10-20
      总管执笔 + 老大签批的人工解冻(final_verdict="PASS") 打回冻结，
      实盘出票被重新卡死 —— 机器单方面推翻人的裁决。

    修法: 写盘前先判「有效人工解冻记录」；成立则保留原裁决 + 留痕 + 醒目告警，
    不成立才覆写(保留 fail-close)。

    ⚠️ 全部判据验**执行性语句**(def / if / 比较 / 赋值 的真实代码行 + 缩进层级)，
       不验字样: 写成 `"freeze_unlock_record" in src` 会被注释、docstring、
       告警文案骗过 —— 那正是本守卫自己要防的「存在性判据」病
       (本仓库第 15 次同类教训，见 G9/G13/G17/G19 注释)。
    """
    src = _read(PIPELINE)
    if not src:
        return False, "scripts/auto_backtest_pipeline.py 不可读"

    # ① 有效解冻判定函数存在, 且真的会 return True (被删/被改成恒 False 都报红)
    m = re.search(r"def\s+_is_valid_unlock_record\s*\(.*?\)\s*(?:->[^:\n]*)?:.*?(?=\ndef )",
                  src, re.S)
    if not m:
        return False, ("缺 _is_valid_unlock_record() 判定函数 —— "
                       "周度回测可无条件推翻人工解冻, 出票会被重新冻结")
    body = m.group(0)
    tail = [l for l in body.strip().split("\n") if l.strip()][-1]
    if tail.strip() != "return True":
        return False, f"_is_valid_unlock_record() 未以 return True 收尾 (末行={tail.strip()!r})"

    # ② 四条件逐条验执行性语句(缺任一条 = 判据被放宽/被删)
    if not re.search(r"isinstance\(\s*rec\s*,\s*dict\s*\)", body):
        return False, "缺「freeze_unlock_record 必须是 dict」判定 (字符串/None 会被当成有效解冻)"
    if not re.search(r"rec\.get\(\s*[\"']unlocked_at[\"']\s*\)", body):
        return False, "缺「记录必须有 unlocked_at」判定"
    if not re.search(
            r"existing\.get\(\s*[\"']final_verdict[\"']\s*\)\s*(?:==|!=)\s*[\"']PASS[\"']", body):
        return False, "缺「final_verdict 必须 == 'PASS'」判定 (FAIL/False 态会被当成有效解冻)"
    if not re.search(r"def\s+_has_active_freeze_marker\s*\(", src):
        return False, "缺 _has_active_freeze_marker() 冻结标记判定函数"
    if not re.search(r"k\.startswith\(\s*[\"']_freeze_[\"']\s*\)", src):
        return False, ("缺 `k.startswith('_freeze_')` 判定 —— "
                       "只认死的 _freeze_20261018 单键则后续新冻结认不出来")

    # ③ 判定必须真的挂在覆写分支上(定义了不调用 = 摆设)
    if not re.search(r"if\s+_is_valid_unlock_record\(\s*existing\s*\)\s*:", src):
        return False, "_is_valid_unlock_record() 定义了但没用在覆写分支上 (摆设)"

    # ④ 覆写赋值必须在分支内(缩进 ≥8)，不得是函数顶格的无条件语句(缩进 0~7)
    assign = (r"\n\s{0,7}review_status\[[\"']final_verdict[\"']\]\s*=\s*"
              r"review_gate\.compute_final_verdict\(")
    if re.search(assign, src):
        return False, ("发现**无条件**覆写 final_verdict (赋值语句不在 if/else 分支内) —— "
                       "周度回测会把人工解冻 PASS 打回 FAIL，出票重新冻结")
    assign_guarded = (r"\n\s{8,}review_status\[[\"']final_verdict[\"']\]\s*=\s*"
                      r"review_gate\.compute_final_verdict\(")
    if not re.search(assign_guarded, src):
        return False, "找不到分支内的覆写赋值语句 (fail-close 分支被删, 真出问题也不冻结了)"

    # ⑤ 跳过分支必须显式保留原值 + 真写留痕字段
    if not re.search(r"review_status\[[\"']final_verdict[\"']\]\s*=\s*existing\.get\(\s*"
                     r"[\"']final_verdict[\"']\s*\)", src):
        return False, "跳过分支未显式保留原 final_verdict (解冻值可能被覆盖)"
    if not re.search(r"review_status\[[\"']_final_verdict_override_skipped[\"']\]\s*=", src):
        return False, "缺 _final_verdict_override_skipped 留痕赋值 (跳过覆写会变成静默跳过)"
    # ⑥ pending_review=True 语义必须保留(周度回测确实要求人重新评审)
    if not re.search(r"[\"']pending_review[\"']\s*:\s*True", src):
        return False, "pending_review=True 被删 (丢失『周度回测要求重新评审』语义)"
    # ⑦ 跳过覆写不得让流水线报失败(返回值仍 True)
    m2 = re.search(r"def\s+trigger_review\s*\(.*?\)\s*(?:->[^:\n]*)?:.*?(?=\ndef )", src, re.S)
    if not m2:
        return False, "trigger_review() 定位失败"
    tail2 = [l for l in m2.group(0).strip().split("\n") if l.strip()][-1]
    if tail2.strip() != "return True":
        return False, f"trigger_review() 未以 return True 收尾 (末行={tail2.strip()!r})"

    return True, ("有效解冻四条件齐全且挂在分支上; 覆写仅在无有效解冻时执行 "
                  "(fail-close 保留); 跳过时留痕 + pending_review=True")


def check_g23() -> tuple:
    """G23 walk-forward 门禁选源结果必须靠**内容指纹**, 不得按 mtime 排序

    2026-10-21 立。背景(已核实的造假):
      commit 9a13bb8d 把 output/diagnostic/walk-forward-test-20261017_0634.json
      复制一份、只改第 2 行 timestamp 成为 ...20261021_0310.json(两文件均 3359 字节,
      894 窗/IS/OOS/results 字节级相同), 再手写 data/review_status.json 的
      walk_forward_decay=0.2573 / pass=true, 冒充"重标定后路径 B 解除"。
      能成立的技术根因: 门禁原按 **文件 mtime 排序取最新** 选产物 —— 复制旧文件
      touch 一下就能排到最前。真值至今仍是 decay=0.7858 (blocked=true)。

    ⚠️ 全部判据验**执行性语句**(缩进层级 + 真实的赋值行/判断行/调用行),
       不验字样: `"sha256" in src` 会被文件头严禁清单、docstring、告警文案骗过
       —— 那正是本守卫自己要防的「存在性判据」病(本仓库第 16 次同类教训,
       见 G9/G13/G17/G19/G21 注释)。
    """
    src = _read(WFG)
    if not src:
        return False, "scripts/walk_forward_gate.py 不可读"

    # ① 严禁 mtime 参与选源(反向判据, 但**只扫 _select_result 函数体** ——
    #    全文扫会把文件头严禁清单里"严禁 sorted(...,st_mtime)"这句注释也算命中,
    #    那是字样型判据的反向版, 同样不可取)
    m_sel = re.search(r"def\s+_select_result\s*\(.*?\)\s*(?:->[^:\n]*)?:.*?(?=\ndef )",
                      src, re.S)
    if not m_sel:
        return False, "缺 _select_result() (选源函数被删除/改名)"
    sel_body = m_sel.group(0)
    if re.search(r"st_mtime|getmtime", sel_body):
        return False, ("_select_result() 里出现 st_mtime/getmtime —— "
                       "按落盘时间选产物, 复制旧文件改时间戳即可冒充重标定(9a13bb8d 的手法)")
    if not re.search(r"files\.sort\(\s*key\s*=\s*sort_key", sel_body):
        return False, "_select_result() 未按内容排序键排序 (排序被改掉/被换成别的实现)"
    if not re.search(r"get\(\s*[\"']timestamp[\"']\s*\)", sel_body):
        return False, "_select_result() 排序键未取内容里的 timestamp (又回退到文件属性了)"
    # 全文件兜底: 任何地方对 walk-forward 结果清单按 mtime 排序都算复辟
    if re.search(r"sorted\([\s\S]{0,300}?glob\([^)]*walk-forward[^)]*\)[\s\S]{0,300}?st_mtime",
                 src):
        return False, "存在对 walk-forward 结果清单按 st_mtime 排序的代码 (mtime 选源复辟)"

    # ② 指纹计算函数存在, 且函数体内真的调 hashlib.sha256
    m = re.search(r"def\s+_content_fingerprint\s*\(.*?\)\s*(?:->[^:\n]*)?:.*?(?=\ndef )",
                  src, re.S)
    if not m:
        return False, "缺 _content_fingerprint() —— 没有内容指纹就无法识别'换时间戳的同一份'"
    if not re.search(r"hashlib\.sha256\(", m.group(0)):
        return False, "_content_fingerprint() 里没有真的 hashlib.sha256 计算 (空壳函数)"

    # ③ sha256 计算的**赋值行**必须真的挂在选源结果之后(定义了不用 = 摆设)
    if not re.search(r"^\s{4,}source_content_sha256\s*,\s*\w+\s*=\s*_content_fingerprint\(",
                     src, re.M):
        return False, ("缺 `source_content_sha256, ... = _content_fingerprint(...)` 赋值行 —— "
                       "指纹算了但没接进判定")

    # ④ 指纹不可算时必须 fail loud(不许拿"解析不了"当"内容变了"放行)
    if not re.search(r"^\s{4,}if\s+source_content_sha256\s+is\s+None\s*:", src, re.M):
        return False, "缺 `if source_content_sha256 is None:` 判空分支 (坏档可能被当新结果)"

    # ⑤ 指纹**比较判断行**必须存在(与上次门禁产物比, 识别"同一份换时间戳")
    if not re.search(
            r"^\s{4,}duplicate_submission\s*=\s*bool\(.*source_content_sha256\s*==\s*prev_fp",
            src, re.M):
        return False, ("缺 `duplicate_submission = bool(... source_content_sha256 == prev_fp)` "
                       "指纹比较判断行 —— 同一份内容换时间戳会再次被当成新的重标定")

    # ⑥ 台账留痕调用行必须存在(产物 data/ 会被覆写, 台账是唯一跨覆写痕迹)
    if not re.search(r"^\s{4,}\w+\s*=\s*_append_source_ledger\(", src, re.M):
        return False, "缺 _append_source_ledger() 调用行 (指纹留痕被摘掉则事后无法追溯)"

    # ⑦ 指纹必须写进产物本身(否则下游拿不到)
    if not re.search(r"^\s{8}\"source_content_sha256\"\s*:\s*source_content_sha256\s*,",
                     src, re.M):
        return False, "产物 payload 未写入 source_content_sha256 (下游无法核对)"

    return True, ("选源不按 mtime; 内容指纹(剔除 timestamp)计算+判空+与上次比较+入产物+"
                  "追加台账, 五道执行性语句齐全")


def check_g22() -> tuple:
    """G22 因子门禁必须与「因子层开关」解耦 + 两个注入因子不得回潮为 valid

    2026-10-21 立。两件事一起守, 因为它们是同一类风险: 判据/状态变严之后,
    别人(或下一个 agent)最省事的"修复"就是把它改回去。

    ① daily_pick.py 的因子门禁解耦:
       因子层关着 (config.json factor_layer_enabled=false) 时因子根本不参与选股
       打分, 此时门禁却能拦出票 = 逻辑倒挂 —— 门禁一红整条出票链停摆, 而停摆的
       原因是一个"没在用的因子层"不达标。老大要的是暴露真相, 不是让出票停。
       修法: 只有因子层真的启用, 门禁未过才允许 return 3; 关闭时跳过并留痕。
       ⚠️ 全部判据验**执行性语句**(正则匹配真实的赋值/if/return 行 + 判定行
          的先后顺序), 绝不能写成 `"gate_passed" in src` —— 注释、docstring、
          本文件自己的说明文字里写着 gate_passed 就能骗过它, 那正是本守卫
          自己要治的「存在性判据」病 (本仓库第 16 次同类教训, 见 G9/G13/G17/
          G19/G21)。

    ② data/factor_ic/factor_ic_latest.json 的两个注入因子:
       PRICE_VOL_RANK / UPPER_SHADOW 在 10-17 各历史版本恒为 dead, 却在
       2026-10-21T03:10 的"重标定"里被捞出改 valid 并赋夸张 IC (且缺 sample_size
       字段, 与其余 7 个的 192 格式断裂)。已按 10-17 真值回滚为 dead。
       改回 valid = 门禁凑数假绿复辟。
    """
    dp = _resolve_guarded_module("daily_pick.py", "core/pipeline/daily_pick.py")
    src = _read(dp) if dp else ""
    if not src:
        return False, "daily_pick.py 不可读 (根级旧路径与 core/pipeline/ 均缺失)"

    # ①-A 必须**真的读**开关 (真实赋值行; 注释里提一句不算)
    if not re.search(
            r"factor_layer_on\s*,\s*factor_layer_src\s*=\s*get_factor_layer_enabled\s*\(\s*\)",
            src):
        return False, ("daily_pick 未真实读取因子层开关 (缺 "
                       "`factor_layer_on, factor_layer_src = get_factor_layer_enabled()` 赋值行) "
                       "—— 等价于改回无条件检查门禁")

    # ①-B 必须有「因子层未启用」的判定分支 (真实 if 行)
    m_off = re.search(r"\n\s{4,}if\s+not\s+factor_layer_on\s*:", src)
    if not m_off:
        return False, ("daily_pick 缺 `if not factor_layer_on:` 判定行 —— "
                       "因子层关闭时仍会按门禁拦出票 (逻辑倒挂复辟)")

    # ①-C 该分支必须真的「不拦截」+ 显式留痕 (杜绝静默跳过)
    branch = src[m_off.end():m_off.end() + 1200]
    if not re.search(r"\n\s{8,}return\s+False\s*,", branch):
        return False, "因子层关闭分支未 return 不拦截 (跳过分支被删或被改成继续拦)"
    if not re.search(r"\[\s*[\"']skip_reason[\"']\s*\]\s*=", branch):
        return False, "因子层关闭分支缺 skip_reason 留痕赋值 (跳过会退化成静默跳过)"

    # ①-D 门禁判定必须在开关判定**之后** (顺序反了 = 开关形同虚设)
    m_gate = re.search(r"\n\s{4,}if\s+not\s+gate_passed\s*:", src)
    if not m_gate:
        return False, "daily_pick 缺 `if not gate_passed:` 判定行 (门禁拦截能力被删)"
    if m_gate.start() < m_off.start():
        return False, ("`if not gate_passed:` 出现在 `if not factor_layer_on:` 之前 —— "
                       "开关判定形同虚设, 等价于无条件拦出票")

    # ①-E return 3 必须挂在 blocked 分支上, 不得顶格无条件
    if re.search(r"\n\s{0,4}return\s+3\b", src):
        return False, "daily_pick 存在顶层(缩进≤4)的 `return 3` = 无条件拦截复辟"
    if not re.search(r"\n\s{4,}if\s+blocked\s*:", src):
        return False, "daily_pick 缺 `if blocked:` 判定 (return 3 未挂在门禁结果上)"
    if not re.search(r"\n\s{8,}return\s+3\b", src):
        return False, "daily_pick 缺分支内的 `return 3` (拦截分支被删, 门禁红了也不拦)"

    # ② 两个注入因子不得回潮为 valid
    try:
        ic = json.loads(IC_LATEST.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"factor_ic_latest.json 不可读: {e}"
    factors = ic.get("factors") if isinstance(ic, dict) else None
    if not isinstance(factors, list):
        return False, "factor_ic_latest.json 的 factors 段缺失或非 list"
    back = sorted(f.get("name") for f in factors
                  if isinstance(f, dict) and f.get("name") in INJECTED_FACTORS
                  and f.get("status") == "valid")
    if back:
        return False, (f"注入因子回潮为 valid: {back} —— 这两个是 2026-10-21T03:10 人为"
                       f"注入凑数的 (10-17 各历史版本恒为 dead), 改回 valid = 门禁假绿复辟")

    n_valid = sum(1 for f in factors if isinstance(f, dict) and f.get("status") == "valid")
    return True, (f"门禁拦截挂在因子层开关上 (关闭→跳过并留痕, 启用→才拦); "
                  f"{'/'.join(INJECTED_FACTORS)} 未回潮为 valid; 当前 valid={n_valid}")


def _git(*args: str) -> tuple:
    """在仓库根跑 git, 返回 (returncode, stdout)。执行失败返回 (-1, 原因)。"""
    try:
        p = subprocess.run(("git",) + args, cwd=str(ROOT),
                           capture_output=True, text=True, timeout=30)
        return p.returncode, (p.stdout or "").strip()
    except Exception as e:
        return -1, f"git {args[0]} 执行失败: {e}"


def check_g24() -> tuple:
    """G24 关键防线脚本必须被 git 跟踪 + 有 .gitignore 白名单（2026-10-21 立）

    背景(实测, 非推演):
      .gitignore L15 的 `scripts/*` 使 scripts/ 下 ~360 个 .py 对 git 不可见。
      本次排查发现 189 个已入库 scripts 文件里有 **79 个** 处于
      「已 tracked 但没有白名单」的脆弱态(历史上靠 git add -f 硬塞进库) ——
      一旦有人 `git rm --cached` 或换机全新 clone, 它们就再也加不回来,
      防线静默消失且无人察觉。check_protocol_mount.py / check_task_contract.py
      更是从未入库过(真·库外)。

    ⚠️ 判据陷阱(本次踩过, 写在这里防止后人降级):
      裸 `git check-ignore <file>` **会查 index**, 对已 tracked 的文件恒返回
      exit=1(即"未被忽略")。用它做判据 = 100% 假绿, 79 个脆弱项一个都测不出来。
      必须 `git check-ignore -v --no-index` 才能看到 .gitignore 规则的真实匹配,
      并进一步判定匹配到的规则是否以 `!` 开头(白名单) —— 因为 git 对"命中否定规则"
      的路径同样返回 exit=0, 只看退出码会把白名单误判成被忽略。

    ⚠️ 全部判据验**真实执行结果**(真跑 git ls-files / git check-ignore 并解析输出),
       不验字样: 扫 .gitignore 文本里有没有那一行 = 又一个存在性判据,
       正是本守卫自己要治的病(见 G9/G13/G17/G19/G21/G22/G23 注释)。
    """
    if not TRACK_REQUIRED:
        return False, "TRACK_REQUIRED 名单为空 (守卫自身被掏空)"

    # ⓪ 前置: 仓库可用 + git 命令真的能跑 (跑不出来 = fail loud, 不许放行)
    rc0, out0 = _git("rev-parse", "--is-inside-work-tree")
    if rc0 != 0 or out0.strip() != "true":
        return False, f"当前目录不是可用的 git 工作树 (rc={rc0}, out={out0!r}) —— 无法验证跟踪状态"

    missing_file = []     # 文件在磁盘上都不存在
    not_tracked = []      # 存在但未被 git 跟踪(真·库外)
    not_whitelisted = []  # 已跟踪但 .gitignore 里没有对应白名单(脆弱态)

    for rel in TRACK_REQUIRED:
        if not (ROOT / rel).exists():
            missing_file.append(rel)
            continue

        # ① 真实跟踪判定: git ls-files --error-unmatch 命中才算在库里
        rc1, out1 = _git("ls-files", "--error-unmatch", rel)
        if rc1 == -1:
            return False, f"git ls-files 未能执行: {out1}"
        if rc1 != 0 or out1.splitlines()[-1:] != [rel]:
            not_tracked.append(rel)

        # ② 白名单判定: 规则真实匹配情况(--no-index 才准), 且命中的必须是否定规则
        rc2, out2 = _git("check-ignore", "-v", "--no-index", rel)
        if rc2 == -1:
            return False, f"git check-ignore 未能执行: {out2}"
        if rc2 == 0:
            # out2 形如 ".gitignore:281:!scripts/xxx.py\tscripts/xxx.py"
            first_field = out2.split("\t", 1)[0]
            pattern = first_field.split(":", 2)[-1] if first_field.count(":") >= 2 else ""
            if not pattern.startswith("!"):
                not_whitelisted.append(f"{rel} (被 {first_field} 忽略)")
        # rc2 == 1: 没有任何忽略规则匹配到它 => 天然不被忽略, 视为 OK

    problems = []
    if missing_file:
        problems.append(f"文件不存在: {missing_file}")
    if not_tracked:
        problems.append(f"未被 git 跟踪(库外, 误删无法找回): {not_tracked}")
    if not_whitelisted:
        problems.append(f"已跟踪但缺 .gitignore 白名单(rm --cached 后加不回来): {not_whitelisted}")

    if problems:
        return False, " | ".join(problems)

    return True, (f"{len(TRACK_REQUIRED)} 个关键防线脚本全部已 tracked 且白名单在位 "
                  f"(git ls-files --error-unmatch + git check-ignore --no-index 双重实测)")


def check_g25() -> tuple:
    """G25 回归套件 L 组必须覆盖 is_sharpe/oos_sharpe 字段比对（2026-10-25 立, t_55ddecd9）

    背景(本次实证, 非推演):
      L 组 check_review_status_matches_truth 是「review_status.json 门禁字段与真源
      逐项一致」的唯一机器防线。2026-10-24 真源 walk_forward_gate.json 按内容指纹
      再选源重算后 IS/OOS = 0.592/0.4604, 而 review_status 的 is_sharpe/oos_sharpe
      仍停在 10-21 06:23 版真源值 0.9906/0.2122 —— 旧真值当新真值, 只有 L 组的
      字段级一手比对能检出。这条防线若被「顺手降级」(want dict 摘掉这两个条目、
      或 L 组退化成只看文件在不在), 同类分叉将再次静默。

    ⚠️ 判据全部验**执行性语句**(正则匹配 dict 条目行 / 比对循环行 / FAIL 分支 /
       main 调用行本身), 不验字样: docstring/注释里写 is_sharpe 0.9906 也能让
       字样型判据假绿 —— 正是本守卫自己要治的「存在性判据」病
       (见 G9/G13/G17/G19/G21/G22/G23/G24 同类教训)。
    """
    if not REGRESSION.exists():
        return False, "回归套件 .agent/regression/__init__.py 不存在 (L 组守卫无对象)"
    src = REGRESSION.read_text(encoding="utf-8", errors="replace")

    m = re.search(r"def check_review_status_matches_truth\(.*?\n(.*?)(?=\ndef |\Z)",
                 src, re.S)
    if not m:
        return False, "L 组检查函数 check_review_status_matches_truth 不存在 (整组被摘)"
    body = m.group(0)

    # ① 函数必须被 main() 调用 (定义了不调 = 摆设)
    if not re.search(r"^\s*check_review_status_matches_truth\(root,\s*rpt\)\s*$",
                     src, re.M):
        return False, "check_review_status_matches_truth 未被 main() 调用 (装饰性告警)"

    # ② L1 want dict 必须含 is_sharpe/oos_sharpe 的**可执行条目行**
    #    (匹配 dict 条目行本身; 注释里写字段名不算数)
    for field in ("is_sharpe", "oos_sharpe"):
        if not re.search(rf'^\s*"{field}"\s*:\s*wf\.get\("{field}"\)', body, re.M):
            return False, (f"L1 want dict 缺 {field} 条目行 "
                           f"`\"{field}\": wf.get(\"{field}\")` —— 字段比对被降级, "
                           f"旧真值当新真值将无人检出")

    # ③ 比对循环必须真拿 want 逐键比 review_status (只列不比对 = 名单摆设)
    if not re.search(
            r"diff\s*=\s*\{\s*k\s*:\s*\(rs\.get\(k\),\s*v\)\s*for\s+k,\s*v\s+"
            r"in\s+want\.items\(\)\s+if\s+rs\.get\(k\)\s*!=\s*v\s*\}", body, re.S):
        return False, "L1 字段逐项比对循环缺失 (want 条目未实际参与比对)"

    # ④ 不一致分支必须报 FAIL (静默不一致 = 假绿)
    if not re.search(r"if\s+diff\s*:", body):
        return False, "L 组缺 `if diff:` 不一致判定分支 (字段分叉被静默吞掉)"
    if 'rpt.fail("L review_status 一致性"' not in body:
        return False, "L 组不一致 FAIL 分支缺失 (diff 非空也要 PASS)"

    return True, ("L 组字段级比对覆盖 is_sharpe/oos_sharpe: dict 条目行+比对循环+"
                  "FAIL 分支+main 调用 四层执行性语句齐全")


CHECKS = {
    "G1_freshness底座": check_g1,
    "G2_A0元断言注册": check_g2,
    "G3_A3验新鲜度": check_g3,
    "G4_A5验产物新鲜": check_g4,
    "G5_A6验自审产物": check_g5,
    "G6_抑制窗口分层": check_g6,
    "G7_抑制键含优先级": check_g7,
    "G8_A11交叉校验": check_g8,
    "G9_A12调度载体": check_g9,
    "G10_注册脚本静默": check_g10,
    "G11_检测器心跳": check_g11,
    "G12_周度载体静默": check_g12,
    "G13_日历fail-close": check_g13,
    "G14_A13日历断言": check_g14,
    "G15_日历刷新载体": check_g15,
    "G16_A12多载体覆盖": check_g16,
    "G17_A12形态双维度": check_g17,
    "G18_A0无兜底PASS": check_g18,
    "G19_A3末条ts新鲜": check_g19,
    "G20_载体清单28条": check_g20,
    "G21_解冻不被机器覆写": check_g21,
    "G22_因子门禁解耦与回滚": check_g22,
    "G23_产物选指纹非mtime": check_g23,
    "G24_防线脚本须入库": check_g24,
    "G25_L组覆盖is_oos_sharpe": check_g25,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = {}
    for name, fn in CHECKS.items():
        try:
            ok, detail = fn()
            results[name] = {"status": "PASS" if ok else "FAIL", "detail": detail}
        except Exception as e:
            results[name] = {"status": "FAIL", "detail": f"守卫自身异常: {e}"}

    failed = [k for k, v in results.items() if v["status"] == "FAIL"]

    if args.json:
        print(json.dumps({"pass": len(results) - len(failed),
                          "fail": len(failed),
                          "checks": results}, ensure_ascii=False, indent=2))
        return 1 if failed else 0

    print("=" * 60)
    print("断言有效性守卫（防判据被降级回存在性检查）")
    print("=" * 60)
    for name, v in results.items():
        mark = "✅" if v["status"] == "PASS" else "❌"
        print(f"  {mark} {name}: {v['detail']}")
    print("-" * 60)
    print(f"  合计: {len(results) - len(failed)} PASS / {len(failed)} FAIL")
    if failed:
        print()
        print("  ⚠️ 判据疑似被降级。若你是为了让健康度'变绿'而放宽判据，请停手——")
        print("     81.8% 是真状态；改回存在性判据 = 假绿复辟（项目头号病史，已 12 次）。")
        print("     正确做法是修被检测出的真问题，不是修检测器。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
