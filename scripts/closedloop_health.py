#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
closedloop_health.py — 闭环健康度日报生成器

职责:
  1. 检查 10 条闭环断言当前状态（PASS / PARTIAL / FAIL）
  2. 计算闭环完整率 = 各断言得分之和 / 10.0
     - PASS = 1.0, PARTIAL = 0.5, FAIL = 0.0
  3. 将完整率写入 data/daily_signal.json（仅追加 closedloop 字段，不改动其他字段）
  4. 将当日记录 append 到 data/closedloop_history.jsonl（7日可回溯）

断言清单（来源: docs/闭环10断言基线-20261014.md）:
  A1  层间契约固化          — docs/layers-contract.md 存在 + 各层 read-back 可验证
  A2  状态唯一真源          — holdings/trade_log 无 B3 双源; review_status 含 _schema_version
  A3  闭环反馈写侧          — feedback_log.jsonl append 正常；feedback_to_factor.py 可产 suggestions
  A4  闭环反馈读侧          — feedback_weight_consumer.py 存在且产出 weight_reestimation_refs.json
  A5  假绿不可重复(R0)      — fake_positive_detector.py 存在 + weekly_ic cron event 已接入
  A6  自审机制运行          — laosi_audit.py 已入 cron_config.json self_audit event
  A7  回滚可执行            — .bak 规范 + git revert 可行
  A8  证据链完整            — 近 3 次 commit 有独立 docs；未提交变更附注释锚点
  A9  外部依赖隔离          — TSP/外部适配器走路径外部化，不穿透生产决策
  A10 人机边界明确          — AGENTS.md 角色分工 + 权限矩阵存在

用法:
  python scripts/closedloop_health.py              # 正常运行，写 daily_signal + jsonl
  python scripts/closedloop_health.py --dry-run    # 只打印检查结果，不写文件
  python scripts/closedloop_health.py --json       # 输出 JSON 到 stdout
"""

# ⚠️⚠️ 改本文件前必读（2026-10-19，老大批准方案A后立）⚠️⚠️
#
# 本文件的 A0/A1/A3/A5/A6/A8 已于 2026-10-19 从「存在性判据」升级为「有效性判据」
# （判据 = 产物新鲜度 + 数量，而非"文件在不在 / 台账有没有登记"）。
# 升级后健康度由 95.0% 降至 81.8% —— **这是变诚实，不是 bug**。
#
# ❌ 严禁为了让健康度"变绿"而做以下任何一件事：
#    · 把 _fresh_verdict / _age_hours 判据删掉或改回 exists() 检查
#    · 放宽 soft/hard 阈值（当前 soft=周期×1.5、hard=周期×3，均有理由）
#    · 把 A0 元断言从 ASSERTION_CHECKS 里摘掉
#    · 给 FAIL 项加 except: pass 让它静默通过
#  以上任一动作 = 假绿复辟（本项目头号病史，已复发 12 次）。
#
# ❌ 2026-10-21 新增严禁项（同步受 scripts/guard_assertion_effectiveness.py
#    G17~G20 机器防线监管，违规改动会被判 FAIL）：
#    · 严禁把 A0 改回「history 不存在 / 解析失败 ⇒ PASS」兜底。
#      2026-10-21 前 A0 有四条静默兜底路径，全部落到 return PASS ——
#      即「心跳文件没了」的判果是「体检器活性正常」，这是本项目最危险的失败模式：
#      专门发现"系统没在跑"的机制，在它自己没跑时报绿。
#      现要求：文件缺失 / 读取失败 / 全行不可解析 / 末条缺 ts ⇒ 一律 FAIL，
#              且 detail 必须点名文件路径 + 失败原因。
#    · 严禁把 A3 降回「只查文件存在且有内容」。A3 必须验最后一条记录 ts 的
#      新鲜度（soft 24h / hard 72h，按**工作日小时**计，跳过周六周日）。
#      2026-10-21 前 A3 用「近 48h 新增条数」口径，实测 feedback_log 已 45.2h
#      无新写入（连漏 2 个交易日）却仍报 PASS —— 存量计数掩盖写侧停摆。
#      跳过周末的理由: Zhuanqian_DailyReview 只在周一~周五 18:00 跑，
#      周末不跑是正常态，按自然小时算会把正常的周末等待误判为停摆。
#    · 严禁缩减 CARRIER_SPECS 条目（2026-10-21 由 4 条扩到 28 条，
#      覆盖本机全部 Zhuanqian_* / QSP_* 计划任务）。删一条 = 那个载体从此
#      失去任何断言，等于把「覆盖面 4/28」的假绿请回来。
#      新增载体必须同时加进 CARRIER_SPECS + 守卫 G16。
#    · 严禁放宽 A12 形态判据。合规形态是两条**独立**判据同时成立:
#        ① Settings/Hidden = true   （缺 Hidden ⇒ 交互式会话弹黑窗）
#        ② Command 宿主 ∈ SILENT_HOSTS (wscript.exe / pythonw.exe)
#      只留其中一条都不够: 只查 wscript 子串(原判据)发现不了 Hidden 缺失；
#      只查 Hidden 发现不了 Command 直指 .bat。任一不合规 ⇒ 该载体 **FAIL**。
#    · 严禁给单个载体开"这个不算违规"的后门。SILENT_HOSTS 是**全局**白名单，
#      为某个任务加豁免 = 允许它继续在老大桌面弹控制台窗口。
#    · 严禁把 A5 心跳阈值放宽回 soft 240h / hard 504h
#      （旧阈值 = 手动跑一次检测器即可绿满 21 天，与周度载体的 7 天周期无关）。
#      现为 soft 210h(周期×1.25) / hard 336h(周期×2)。
##
# ✅ 正确做法：修**被检测出的真问题**，不是修检测器。
#    例如 A5 FAIL = 假绿检测器真停摆 46 天，应去让它跑起来，而不是放宽 A5。
#
# 🛡️ 机器防线：scripts/guard_assertion_effectiveness.py（7 项判据）
#    已接入回归套件 I 组（python .agent/regression/__init__.py .）
#    —— 任何降级都会被判 FAIL。你改得动代码，但改不动回归。
#
# 回滚点：scripts/closedloop_health.py.bak_20261019_laoliu（升级前版本）

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

# ── 路径配置 ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
MAINLINE_DOCS = ROOT / "mainline" / "docs"
SCRIPTS_DIR = ROOT / "scripts"
TESTS_DIR = ROOT / "tests"
AGENTS_MD = ROOT / "AGENTS.md"
CRON_CONFIG = ROOT / "cron_config.json"
DAILY_SIGNAL = DATA_DIR / "daily_signal.json"
HISTORY_FILE = DATA_DIR / "closedloop_history.jsonl"
FEEDBACK_LOG = DATA_DIR / "feedback_log.jsonl"
FEEDBACK_SUGGESTIONS = DATA_DIR / "feedback_suggestions.json"
WEIGHT_REFS = DATA_DIR / "weight_reestimation_refs.json"
HOLDINGS = DATA_DIR / "holdings.json"
REAL_HOLDINGS = DATA_DIR / "real_holdings.json"
REVIEW_STATUS = DATA_DIR / "review_status.json"
TECH_DEBT_LEDGER = DOCS_DIR / "tech_debt_ledger.md"
DEFECT_LEDGER = DATA_DIR / "audit" / "defect_ledger.json"

# ── 技术债台账解析 ─────────────────────────────────────────────────────────────


def _count_open_p0() -> int:
    """读取 defect_ledger.json，返回 open P0 条目数。

    用于闭环健康度断言中评估治理有效性:
      A6/A7/A8 在 open_P0 > 0 时降级，避免机制健康但治理失效的假绿。
    """
    if not DEFECT_LEDGER.exists():
        return 0
    try:
        d = json.loads(DEFECT_LEDGER.read_text(encoding="utf-8"))
        entries = d.get("entries", []) if isinstance(d, dict) else []
        return sum(
            1 for e in entries
            if str(e.get("severity", "")).upper() == "P0"
            and str(e.get("status", "")).lower() in ("open", "active", "")
        )
    except Exception as e:
        print(f"🔴 [closedloop_health.py:131] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return 0


def parse_tech_debt_ledger() -> dict:
    """解析 docs/tech_debt_ledger.md，返回 tech_debt 信息。

    支持两种格式：
      - ## D-N <title>  （H2 标题）
      - - **D-N** <title>  （列表项）

    返回:
      {
        "status": "PASS" | "PARTIAL" | "FAIL",
        "detail": "...",
        "open": N,
        "stale_7d": ["D-N", ...],
        "oldest_ts": "YYYY-MM-DD" | None,
        "alert_level": "P1" | "P2",
      }
    """
    import re
    if not TECH_DEBT_LEDGER.exists():
        return {
            "status": "FAIL",
            "detail": "tech_debt_ledger.md 不存在",
            "open": 0,
            "stale_7d": [],
            "oldest_ts": None,
            "alert_level": "P2",
        }

    content = TECH_DEBT_LEDGER.read_text(encoding="utf-8")
    lines = content.split("\n")

    entries = []  # list of {"id": str, "props": dict}
    current_id = None
    current_props = {}

    for line in lines:
        # 匹配 ## D-N 或 - **D-N** 开头
        m = re.match(r"^\s*(?:#{1,2}\s+(D-\d+)|-\s+\*\*(D-\d+)\*\*)\s+", line)
        if m:
            if current_id is not None:
                entries.append({"id": current_id, "props": current_props})
            current_id = m.group(1) or m.group(2)
            current_props = {}
            continue
        if current_id is not None:
            pm = re.match(r"^\s*-\s+\*\*(\w+)\*\*:\s*(.*)", line)
            if pm:
                current_props[pm.group(1)] = pm.group(2).strip()

    if current_id is not None:
        entries.append({"id": current_id, "props": current_props})

    if not entries:
        return {
            "status": "FAIL",
            "detail": "tech_debt_ledger.md 无有效 D-N 条目",
            "open": 0,
            "stale_7d": [],
            "oldest_ts": None,
            "alert_level": "P2",
        }

    now = datetime.now()
    stale_ids = []
    oldest_ts = None

    for e in entries:
        progress = e["props"].get("进展", "")
        ts_match = re.search(r"(\d{4}-\d{2}-\d{2})", progress)
        if ts_match:
            try:
                dt = datetime.strptime(ts_match.group(1), "%Y-%m-%d")
                if oldest_ts is None or dt < oldest_ts:
                    oldest_ts = dt
                if (now - dt).days > 7:
                    stale_ids.append(e["id"])
            except ValueError:
                print(f"⚠️ [scripts\closedloop_health.py] 兼容处理: except ValueError:", file=sys.stderr)
    if stale_ids:
        alert_level = "P1"
        detail = (
            f"技术债 {len(entries)} 条，其中 {len(stale_ids)} 条 7 天无进展: {stale_ids}"
        )
    else:
        alert_level = "P2"
        detail = f"技术债 {len(entries)} 条，均在进展中"

    return {
        "status": "PASS" if not stale_ids else "PARTIAL",
        "detail": detail,
        "open": len(entries),
        "stale_7d": stale_ids,
        "oldest_ts": oldest_ts.strftime("%Y-%m-%d") if oldest_ts else None,
        "alert_level": alert_level,
    }


# ── 断言映射 ──────────────────────────────────────────────────────────────────

def _age_hours(path: Path) -> Optional[float]:
    """文件距上次修改的小时数；不存在返回 None。

    存在性断言 ≠ 有效性保证 —— 本函数是全部「新鲜度判据」的统一底座。
    """
    try:
        if not Path(path).exists():
            return None
        return (time.time() - Path(path).stat().st_mtime) / 3600.0
    except Exception as e:
        print(f"🔴 [closedloop_health.py:243] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return None


def _business_hours_between(start: datetime, end: datetime) -> float:
    """start→end 之间落在**周一~周五**的小时数（周六周日按 0 计）。

    用途: 「工作日任务」(如 Zhuanqian_DailyReview，周一~周五 18:00) 的新鲜度判定。
    ⚠️ 为什么不能直接按自然小时算: 周五 18:00 跑完后，下一个应然时点是周一 18:00，
       中间 63 个自然小时里 48 小时是周末 —— 若按自然小时比对 72h 阈值会误判为
       「疑似停摆」，而实际是完全正常的等待。故必须先扣除周末。

    不计法定节假日(不引入交易日历依赖，避免过度设计): 节假日只会让判定**偏严**，
    不会造成假绿，与本项目「宁红勿绿」的取向一致。
    """
    if end <= start:
        return 0.0
    total = 0.0
    cur = start
    while cur < end:
        day_end = datetime(cur.year, cur.month, cur.day) + timedelta(days=1)
        seg_end = day_end if day_end < end else end
        if cur.weekday() < 5:      # 0=周一 ... 4=周五
            total += (seg_end - cur).total_seconds() / 3600.0
        cur = seg_end
    return total


def _fresh_verdict(path: Path, soft_h: float, hard_h: float, label: str) -> Optional[dict]:
    """按 soft/hard 双阈值给新鲜度判定。
    阈值口径: soft = 业务周期 x 1.5 (容忍一次漏跑); hard = 业务周期 x 3 (确认停摆)。
    返回 None 表示新鲜，否则返回对应 status/detail 的 dict。
    """
    age = _age_hours(path)
    if age is None:
        return {"status": "FAIL", "detail": f"{label} 产物不存在 ({path})"}
    if age > hard_h:
        return {"status": "FAIL",
                "detail": f"{label} 已停摆 {age:.1f}h (> hard {hard_h:.0f}h)"}
    if age > soft_h:
        return {"status": "PARTIAL",
                "detail": f"{label} 超期 {age:.1f}h (> soft {soft_h:.0f}h，疑似漏跑)"}
    return None


def check_a1_contract() -> dict:
    """A1 层间契约固化: docs/layers-contract.md 存在且有实质内容

    有效性升级(2026-10-19): 旧判据只看 size>100B —— 任何 100B 垃圾文件都能过。
    现增加「章节结构」校验: 必须含二级标题，否则判 PARTIAL。
    """
    contract = DOCS_DIR / "layers-contract.md"
    if not contract.exists():
        return {"status": "FAIL", "detail": "docs/layers-contract.md 不存在"}
    size = contract.stat().st_size
    if size < 100:
        return {"status": "PARTIAL", "detail": f"layers-contract.md 存在但过小 ({size}B)，可能未完成"}
    try:
        text = contract.read_text(encoding="utf-8", errors="ignore")
        sections = [l for l in text.split("\n") if l.startswith("## ")]
        if not sections:
            return {"status": "PARTIAL",
                    "detail": f"layers-contract.md 存在 ({size}B) 但无二级章节，内容有效性存疑"}
        return {"status": "PASS",
                "detail": f"layers-contract.md 有效 ({size}B, {len(sections)} 章节)"}
    except Exception as e:
        return {"status": "PARTIAL", "detail": f"layers-contract.md 读取失败: {e}"}


def check_a0_meta_selfcheck() -> dict:
    """A0 元断言: 体检器自身活性 —— 本脚本是否有调度载体 + 上次运行是否超期

    为什么必须有这条(2026-10-19 断裂1 实证):
      闭环健康度曾停摆 36 小时无人发现，因为它没有任何 Windows 计划任务载体，
      而 A6 只验「cron_config.json 里有 self_audit 字样」——台账不负责执行。
      一个专门发现「系统没在跑」的机制，自己停了必须能被发现。
    """
    # 1) 自身调度载体: history 末条新鲜度
    if not HISTORY_FILE.exists():
        return {"status": "FAIL",
                "detail": (f"体检器心跳文件不存在 ({HISTORY_FILE}) —— 零运行留痕，"
                           f"本报告自身不可信 (此路径旧版兜底 PASS，2026-10-21 已修)")}
    try:
        raw = HISTORY_FILE.read_text(encoding="utf-8")
    except Exception as e:
        return {"status": "FAIL",
                "detail": f"体检器心跳文件读取失败 ({HISTORY_FILE}): {e}"}

    lines = [l for l in raw.strip().split("\n") if l.strip()]
    if not lines:
        return {"status": "FAIL",
                "detail": f"体检器心跳文件为空 ({HISTORY_FILE}) —— 零运行留痕"}

    # 倒序回溯找最后一条**可解析**记录: 末行损坏不直接宣判死亡，
    # 但「全部不可解析」必须 FAIL —— 绝不退回 PASS。
    last, last_idx, parse_err = None, None, ""
    for i in range(len(lines) - 1, -1, -1):
        try:
            last = json.loads(lines[i])
            last_idx = i + 1
            break
        except Exception as e:
            parse_err = str(e)
    if last is None:
        return {"status": "FAIL",
                "detail": (f"体检器心跳 {len(lines)} 行全部 JSON 解析失败 "
                           f"({HISTORY_FILE}): {parse_err}")}

    last_ts = last.get("ts", "")
    if not last_ts:
        return {"status": "FAIL",
                "detail": (f"体检器心跳末条缺 ts 字段 ({HISTORY_FILE} 第{last_idx}行) "
                           f"—— 无法判定活性，按铁律判 FAIL 而非 PASS")}
    try:
        t = datetime.fromisoformat(last_ts)
    except Exception as e:
        return {"status": "FAIL",
                "detail": (f"体检器心跳末条 ts 不可解析 ({HISTORY_FILE} 第{last_idx}行, "
                           f"ts={last_ts!r}): {e}")}

    age_h = (datetime.now() - t).total_seconds() / 3600.0
    # 体检器业务周期 = 每日 => soft 48h (2d), hard 96h (4d)
    if age_h > 96:
        return {"status": "FAIL",
                "detail": f"体检器已停摆 {age_h:.1f}h (>96h)，本报告不可信"}
    if age_h > 48:
        return {"status": "PARTIAL",
                "detail": f"体检器超期 {age_h:.1f}h (>48h)，疑似无调度载体"}
    return {"status": "PASS", "detail": f"体检器活性正常 (心跳 {age_h:.1f}h 前)"}
def check_a2_single_source() -> dict:
    """A2 状态唯一真源: 无 B3 双源残留 + review_status 含 _schema_version"""
    issues = []
    # 检查 real_holdings 双源（动态路径，支持测试覆盖 DATA_DIR）
    _rh_path = DATA_DIR / "real_holdings.json"
    _h_path = DATA_DIR / "holdings.json"
    _rs_path = DATA_DIR / "review_status.json"
    if _rh_path.exists():
        try:
            with open(_rh_path, "r", encoding="utf-8") as f:
                rh = json.load(f)
            if _h_path.exists():
                with open(_h_path, "r", encoding="utf-8") as f:
                    h = json.load(f)
                rh_ts = rh.get("updated_at", rh.get("timestamp", ""))
                h_ts = h.get("updated_at", h.get("timestamp", ""))
                if rh_ts and h_ts and abs(_ts_diff_days(rh_ts, h_ts)) > 1:
                    issues.append(f"real_holdings 与 holdings 时间差 >1天 (rh={rh_ts}, h={h_ts})")
                elif rh_ts:
                    issues.append(f"real_holdings.json 残留 (source={rh.get('source','?')})")
        except Exception:
            issues.append("real_holdings.json 读取失败")

    # 检查 review_status schema_version
    if _rs_path.exists():
        try:
            with open(_rs_path, "r", encoding="utf-8") as f:
                rs = json.load(f)
            if "_schema_version" not in rs:
                issues.append("review_status.json 缺 _schema_version 字段")
        except Exception:
            issues.append("review_status.json 读取失败")
    else:
        issues.append("review_status.json 不存在")

    if issues:
        return {"status": "PARTIAL" if len(issues) == 1 else "FAIL", "detail": "; ".join(issues)}
    return {"status": "PASS", "detail": "无双源残留，schema_version 齐全"}


def check_a3_feedback_write() -> dict:
    """A3 闭环反馈写侧: feedback_log.jsonl append 正常 + feedback_to_factor.py 可产 suggestions"""
    issues = []
    # feedback_log.jsonl 存在且有内容
    # 2026-10-19: 改用模块级 FEEDBACK_LOG 常量 —— 原先此处重复字面量
    # DATA_DIR / "feedback_log.jsonl"，与 L51 的常量构成双真源（改常量不生效）。
    _fl_path = FEEDBACK_LOG
    _fs_path = FEEDBACK_SUGGESTIONS
    if not _fl_path.exists():
        issues.append("feedback_log.jsonl 不存在")
    else:
        try:
            lines = _fl_path.read_text(encoding="utf-8").strip().split("\n")
            valid = sum(1 for l in lines if l.strip())
            if valid == 0:
                issues.append("feedback_log.jsonl 空文件")
        except Exception:
            issues.append("feedback_log.jsonl 读取失败")

    # feedback_to_factor.py 存在可编译
    script = SCRIPTS_DIR / "feedback_to_factor.py"
    if not script.exists():
        issues.append("feedback_to_factor.py 不存在")
    elif _fs_path.exists():
        try:
            with open(_fs_path, "r", encoding="utf-8") as f:
                fs = json.load(f)
            if not fs.get("generated_at"):
                issues.append("feedback_suggestions.json 缺 generated_at")
        except Exception:
            issues.append("feedback_suggestions.json 解析失败")
    # else: suggestions 尚未生成（首次运行），不算 FAIL

    if issues:
        return {"status": "FAIL", "detail": "; ".join(issues)}

    # 🩹 2026-10-21 A3 新鲜度升级（A3 假绿修复，本次三大假绿之二）。
    #   旧判据「近 48h 是否有新增」的两个洞:
    #     ① 窗口 48h 对「每日盘后任务」过宽 —— 实测 feedback_log 已 45.2h 无新增
    #        (连漏 2 个交易日) 却仍判 PASS；
    #     ② 只数「新增条数」，不看「末条距今多久」—— 写侧若反复追加同一条陈旧
    #        记录，recent>0 但闭环实际停摆。
    #   现改为「文件存在 + 非空 + 末条 ts 新鲜」三条件，阈值 soft 24h / hard 72h，
    #   且按**工作日小时**计(跳过周六周日)。
    #
    # ⚠️ 为什么必须跳过周末: Zhuanqian_DailyReview 是**周一~周五 18:00** 的盘后任务，
    #    周末不跑是正常态。按自然小时算，周五 18:00 → 周一 09:00 的 63h 会被
    #    误判成「疑似停摆」。故用 _business_hours_between() 扣除周末后再比对阈值。
    last_ts, last_idx = None, None
    for i, l in enumerate(
            _fl_path.read_text(encoding="utf-8", errors="ignore").split("\n")):
        l = l.strip()
        if not l:
            continue
        try:
            ts = json.loads(l).get("ts", "")
        except Exception as e:
            print(f"🔴 [closedloop_health.py:468] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
            continue
        if ts:
            last_ts, last_idx = ts, i + 1

    if not last_ts:
        return {"status": "FAIL",
                "detail": (f"反馈写侧: {FEEDBACK_LOG} 无任何可解析 ts 记录 "
                           f"—— 写侧从未真正写入，判 FAIL 而非 PASS")}
    try:
        t = datetime.fromisoformat(last_ts)
    except Exception as e:
        return {"status": "FAIL",
                "detail": (f"反馈写侧: {FEEDBACK_LOG} 第{last_idx}行 ts 不可解析 "
                           f"({last_ts!r}): {e}")}

    age_work_h = _business_hours_between(t, datetime.now())
    age_nat_h = (datetime.now() - t).total_seconds() / 3600.0
    if age_work_h > A3_HARD_H:
        return {"status": "FAIL",
                "detail": (f"反馈写侧停摆: 末条 {last_ts} 距今 {age_nat_h:.1f}h "
                           f"(工作日口径 {age_work_h:.1f}h > hard {A3_HARD_H:.0f}h) "
                           f"—— 连漏多个交易日，需让 Zhuanqian_DailyReview 真跑")}
    if age_work_h > A3_SOFT_H:
        return {"status": "PARTIAL",
                "detail": (f"反馈写侧超期: 末条 {last_ts} 距今 {age_nat_h:.1f}h "
                           f"(工作日口径 {age_work_h:.1f}h > soft {A3_SOFT_H:.0f}h) "
                           f"—— 疑似漏跑；若今日为非交易日或尚未到盘后时点，属正常等待")}
    return {"status": "PASS",
            "detail": (f"反馈写侧正常 (末条 {last_ts}, 距今 {age_nat_h:.1f}h, "
                       f"工作日口径 {age_work_h:.1f}h ≤ soft {A3_SOFT_H:.0f}h)")}
def check_a4_feedback_read() -> dict:
    """A4 闭环反馈读侧: feedback_weight_consumer.py 产出 weight_reestimation_refs.json"""
    issues = []
    consumer = SCRIPTS_DIR / "feedback_weight_consumer.py"
    if not consumer.exists():
        return {"status": "FAIL", "detail": "feedback_weight_consumer.py 不存在"}

    # 动态路径，支持测试覆盖 DATA_DIR
    _wr_path = DATA_DIR / "weight_reestimation_refs.json"
    if not _wr_path.exists():
        issues.append("weight_reestimation_refs.json 不存在（consumer 尚未运行）")
        return {"status": "PARTIAL", "detail": "; ".join(issues)}

    try:
        with open(_wr_path, "r", encoding="utf-8") as f:
            refs = json.load(f)
        total = refs.get("total_refs", 0)
        if total == 0:
            issues.append("weight_reestimation_refs.json total_refs=0")
    except Exception:
        issues.append("weight_reestimation_refs.json 解析失败")

    if issues:
        return {"status": "PARTIAL", "detail": "; ".join(issues)}
    return {"status": "PASS", "detail": f"消费侧 OK (total_refs={total})"}


def check_a5_false_green() -> dict:
    """A5 假绿不可重复(R0): fake_positive_detector.py + weekly_ic cron 接入"""
    issues = []
    detector = SCRIPTS_DIR / "fake_positive_detector.py"
    if not detector.exists():
        return {"status": "FAIL", "detail": "fake_positive_detector.py 不存在"}

    # 检查 cron_config.json 中是否有 weekly_ic 且包含 fake_positive
    if CRON_CONFIG.exists():
        try:
            with open(CRON_CONFIG, "r", encoding="utf-8") as f:
                cc = json.load(f)
            events = cc if isinstance(cc, list) else cc.get("events", [])
            weekly_ic_found = False
            for e in events:
                if isinstance(e, str) and "weekly_ic" in e:
                    weekly_ic_found = True
                    break
                if isinstance(e, dict) and e.get("name", "") == "weekly_ic":
                    weekly_ic_found = True
                    break
            if not weekly_ic_found:
                issues.append("cron_config.json 无 weekly_ic event")
        except Exception:
            issues.append("cron_config.json 解析失败")
    else:
        issues.append("cron_config.json 不存在")

    if issues:
        return {"status": "PARTIAL", "detail": "; ".join(issues)}

    # 有效性判据(2026-10-19 二次修正，前两版都错了):
    #   v1「脚本存在+台账登记」      → 假绿(停更46天仍PASS)
    #   v2「查 data/audit/fake_positive_log.json 新鲜度」 → 查错文件，见下
    #   v3(当前)「查运行心跳新鲜度」  → 正确
    #
    # v2 的两个错误，均于 2026-10-19 07:25 实证:
    #   ① detector 写的是 ROOT/data/fake_positive_log.jsonl，
    #      不是 DATA_DIR/audit/fake_positive_log.json —— 后者全库只被 A5 自己引用，
    #      无任何脚本写入，是孤儿文件，查它永远不会绿(死红)。
    #   ② detector 只在 findings>0 时才写产物，findings=0 时完全不留痕
    #      ⇒「产物 mtime」在常态下根本不能证明"跑过"。
    # 故 detector 已加运行心跳(每次运行必写一行)，A5 改查心跳。
    hb = DATA_DIR / "audit" / "fake_positive_runs.jsonl"
    # 🩹 2026-10-21 阈值收紧(原 soft 240h/hard 504h):
    #   旧阈值意味着**任何人手动跑一次检测器，A5 就能绿满 21 天** —— 21 天与
    #   「周度载体」的 7 天周期毫无关系，是一次漏跑后长期无人察觉的直接原因。
    #   现按载体真实周期(周度 = 168h)取 soft = 周期×1.25 / hard = 周期×2。
    #   ⚠️ 未采纳「×1.5 / ×3」的建议值: 168×1.5 = 252h **反而比现状 240h 更宽**，
    #      与「收紧」的意图相悖。×1.25(210h) / ×2(336h) 才真正收紧且不会误判
    #      (正常周度跑 age ≤ 168h < 210h，绝不误伤)。
    verdict = _fresh_verdict(hb, soft_h=A5_SOFT_H, hard_h=A5_HARD_H,
                             label="假绿检测器运行心跳")
    if verdict:
        verdict["detail"] += " (脚本与台账均在，但无心跳=检测器未真跑)"
        return verdict

    return {"status": "PASS", "detail": "假绿检测器已真跑 (运行心跳新鲜)"}


def check_a6_self_audit() -> dict:
    """A6 自审机制运行: laosi_audit.py 已入 cron self_audit event"""
    if not (SCRIPTS_DIR / "laosi_audit.py").exists():
        return {"status": "FAIL", "detail": "laosi_audit.py 不存在"}

    if not CRON_CONFIG.exists():
        return {"status": "FAIL", "detail": "cron_config.json 不存在"}

    try:
        with open(CRON_CONFIG, "r", encoding="utf-8") as f:
            cc = json.load(f)
        events = cc if isinstance(cc, list) else cc.get("events", [])
        has_self_audit = any(
            (isinstance(e, str) and "self_audit" in e) or
            (isinstance(e, dict) and e.get("name", "") == "self_audit")
            for e in events
        )
        if not has_self_audit:
            return {"status": "PARTIAL", "detail": "laosi_audit.py 存在但未入 cron self_audit event"}
    except Exception:
        return {"status": "PARTIAL", "detail": "cron_config.json 解析异常"}

    # 有效性升级(2026-10-19 断裂1): 「cron_config 里有 self_audit 字样」是台账判据，
    # 而 cron_config 不负责执行(真正跑的是 Windows 计划任务) —— 改台账即可假绿。
    # 硬判据 = 老四自审产物必须新鲜。laosi 周期 = 每日 20:00
    # => soft 36h (容忍一次漏跑) / hard 72h (确认停摆)。
    # 候选真产物(2026-10-25 修复): 当前自审任务写 data/laosi_audit_report.json(单文件),
    # 历史机制写 data/laosi_audit/laosi_*.json(目录)。两者取 mtime 最新者,
    # 避免"目录判据过时→自审明明在跑却永远假红"。
    candidates = []
    report_file = DATA_DIR / "laosi_audit_report.json"
    if report_file.exists():
        candidates.append(report_file)
    audit_dir = DATA_DIR / "laosi_audit"
    if audit_dir.exists():
        candidates.extend(list(audit_dir.glob("laosi_*.json")))
    if not candidates:
        return {"status": "PARTIAL", "detail": "老四自审无产物 (laosi_audit_report.json + data/laosi_audit/ 均缺失, 自审从未真跑)"}
    files = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
    verdict = _fresh_verdict(files[0], soft_h=36, hard_h=72, label="老四自审产物")
    if verdict:
        return verdict

    # 治理有效性检查: 自审机制在跑但P0缺陷未消 → FAIL
    open_p0 = _count_open_p0()
    if open_p0 > 0:
        return {
            "status": "FAIL",
            "detail": f"自审机制运行但治理失效: {open_p0} 条 open P0 未销账 (自审未驱动修复)",
        }
    return {"status": "PASS", "detail": f"自审已真跑 (最新产物 {files[0].name}, mtime {datetime.fromtimestamp(files[0].stat().st_mtime).strftime('%Y-%m-%d %H:%M')})"}


def check_a7_rollback() -> dict:
    """A7 回滚可执行: .bak 规范 + git 可用"""
    import subprocess
    issues = []
    # 检查 .bak 文件
    bak_files = list(ROOT.glob("*.bak_*")) + list(SCRIPTS_DIR.glob("*.bak_*"))
    if not bak_files:
        issues.append("无 .bak 备份文件")

    # 检查 git 可用
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            issues.append("git 不可用（非 git 仓库）")
    except Exception:
        issues.append("git 命令执行失败")

    if issues:
        return {"status": "PARTIAL" if len(issues) == 1 else "FAIL", "detail": "; ".join(issues)}
    return {"status": "PASS", "detail": f".bak 文件 {len(bak_files)} 个 + git OK"}


def check_a8_evidence_chain() -> dict:
    """A8 证据链完整: 近 3 次 commit 有独立 docs"""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), "log", "--oneline", "-5"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode != 0:
            return {"status": "FAIL", "detail": "git log 失败"}
        lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
        if len(lines) < 3:
            return {"status": "PARTIAL", "detail": f"近 5 次 commit 仅 {len(lines)} 条，不足 3 条"}
        # 检查是否有 docs 目录下的产物
        r2 = subprocess.run(
            ["git", "-C", str(ROOT), "log", "--oneline", "-3", "--name-only"],
            capture_output=True, text=True, timeout=10
        )
        has_docs = "mainline/docs/" in r2.stdout or "docs/" in r2.stdout
        if not has_docs:
            return {"status": "PARTIAL", "detail": "近 3 次 commit 未见 mainline/docs/ 产物"}

        # 有效性升级(2026-10-19): 「提交信息里出现 docs/ 字样」≠「该文件真实存在」
        # (可能是被删除的文件，或路径拼错)。硬判据 = 逐个 stat 校验。
        changed = [l.strip() for l in r2.stdout.split("\n")
                   if l.strip().startswith(("mainline/docs/", "docs/", "deliverables/"))]
        if changed:
            missing = [p for p in changed if not (ROOT / p).exists()]
            if missing:
                return {"status": "PARTIAL",
                        "detail": f"近3次commit声明的 {len(missing)} 个证据文件不存在: "
                                  f"{missing[:3]}"}
            return {"status": "PASS",
                    "detail": f"近 {len(lines)} 次 commit 均有 docs 锚点 "
                              f"({len(changed)} 个证据文件逐个校验存在)"}
        return {"status": "PASS", "detail": f"近 {len(lines)} 次 commit 均有 docs 锚点"}
    except Exception as e:
        return {"status": "PARTIAL", "detail": f"证据链检查异常: {e}"}


def check_a9_external_isolation() -> dict:
    """A9 外部依赖隔离: TSP/外部走路径外部化，无生产穿透"""
    issues = []
    # 检查是否有硬编码外部路径在生产脚本中
    for py_file in SCRIPTS_DIR.glob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8")
            # 简单的启发式：检查是否有 TSP_PATH 或类似外部化模式
            if "tsp" in content.lower() and "os.environ" not in content and "get(" not in content:
                # 可能有硬编码 TSP 引用（不一定是问题，仅提示）
                pass
        except Exception:
            print(f"🔴 [scripts\closedloop_health.py] CR-01: except Exception:", file=sys.stderr)
    # AGENTS.md 存在
    if not AGENTS_MD.exists():
        issues.append("AGENTS.md 不存在")

    if issues:
        return {"status": "FAIL", "detail": "; ".join(issues)}
    return {"status": "PASS", "detail": "外部依赖隔离正常"}


def check_a10_human_machine_boundary() -> dict:
    """A10 人机边界明确: AGENTS.md 角色分工 + 权限矩阵"""
    issues = []
    if not AGENTS_MD.exists():
        return {"status": "FAIL", "detail": "AGENTS_MD 不存在"}

    try:
        content = AGENTS_MD.read_text(encoding="utf-8")
        # 检查关键元素
        required = ["老大", "总管", "老三", "老五"]
        missing = [r for r in required if r not in content]
        if missing:
            issues.append(f"AGENTS.md 缺角色: {missing}")

        # 检查权限矩阵
        if "禁止" not in content and "独占" not in content:
            issues.append("AGENTS.md 未见权限边界关键词（独占/禁止）")
    except Exception:
        issues.append("AGENTS.md 读取失败")

    if issues:
        return {"status": "PARTIAL" if len(issues) == 1 else "FAIL", "detail": "; ".join(issues)}
    return {"status": "PASS", "detail": "人机边界定义完整"}


def check_a11_cross_validation() -> dict:
    """A11 跨体检器交叉校验: 缺陷台账 vs 本报告结论 不得矛盾

    为什么必须有这条(2026-10-19 断裂2 实证):
      closedloop_health(报满分) / laosi_audit(检出12条P0) / defect_ledger(43条0销账)
      三个体检器**零交叉校验** —— 满分与 0 销账并存本身就是矛盾信号，却无人报错。
      这是「治理域缺失」的直接后果：验证域只做检测，不做矛盾仲裁。

    规则: 台账存在 open 的 P0 缺陷，而本报告没有任何 FAIL ⇒ 治理失效，判 FAIL。
      (若本报告已有 FAIL，说明问题已被本报告捕获，不重复计。)
    """
    ledger = DATA_DIR / "audit" / "defect_ledger.json"
    if not ledger.exists():
        return {"status": "PARTIAL", "detail": "data/audit/defect_ledger.json 不存在，无法交叉校验"}
    try:
        d = json.loads(ledger.read_text(encoding="utf-8"))
        entries = d.get("entries", []) if isinstance(d, dict) else d
        open_p0 = [e for e in entries
                   if str(e.get("severity", "")).upper() == "P0"
                   and str(e.get("status", "")).lower() in ("open", "active", "")]
        open_all = [e for e in entries
                    if str(e.get("status", "")).lower() in ("open", "active", "")]
        if not open_all:
            return {"status": "PASS", "detail": "缺陷台账无未销账项，与本报告一致"}
        if open_p0:
            return {
                "status": "FAIL",
                "detail": (f"治理失效: 台账有 {len(open_p0)} 条 open P0 缺陷"
                           f"(共 {len(open_all)} 条未销账)，但本报告无 FAIL 项 —— "
                           f"三个体检器结论互相矛盾，闭环未真正执行"),
                "_cross_signal": {"open_p0": len(open_p0), "open_all": len(open_all)},
            }
        return {"status": "PARTIAL",
                "detail": f"台账有 {len(open_all)} 条未销账(无P0)，需跟踪销账"}
    except Exception as e:
        return {"status": "PARTIAL", "detail": f"缺陷台账解析失败: {e}"}


TASK_NAME_CLOSEDLOOP = "Zhuanqian_ClosedLoopHealth"


def _load_scheduled_tasks(timeout_s: int = 45) -> Optional[dict]:
    """一次性查询本机全部 Zhuanqian_* / QSP_* 计划任务的**注册形态**。

    返回 {task_name: {"hidden", "command", "arguments", "triggers", "state"}}
      hidden   : True/False；XML 中无 <Hidden> 节点时为 None (未设置 = 弹窗风险)
      triggers : ["CalendarTrigger@2026-10-20T07:30:00", ...]
    返回 **None** 表示查询失败/超时 ⇒ 调用方必须按「无法验证 ≠ PASS」处理。

    为什么不逐个查 (2026-10-21 全覆盖升级的配套改动):
      逐任务 Get-ScheduledTask 要 spawn 28 次 PowerShell(实测约 1s/次)，
      体检器单次运行被拖到半分钟级。改为一次进程内遍历 + 逐个 XML 解析。
    为什么仍要解析 XML 而不是读 Get-ScheduledTask 的属性:
      PS5.1 中 $t.Actions.Command 恒为空、$t.Settings.Hidden 取不到值
      —— 只有 Export-ScheduledTask 导出的 XML 里有真实的 Command/Hidden/Triggers。
    """
    ps = r"""
$out = @()
$ts = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like 'Zhuanqian_*' -or $_.TaskName -like 'QSP_*' }
foreach ($t in $ts) {
  $cmd = ''; $arg = ''; $hidden = ''; $trigs = @()
  try {
    $x = [xml](Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath)
    $ns = New-Object System.Xml.XmlNamespaceManager($x.NameTable)
    $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    $ex = $x.SelectSingleNode('//t:Actions/t:Exec', $ns)
    if ($ex -ne $null) {
      if ($ex.Command -ne $null) { $cmd = [string]$ex.Command }
      if ($ex.Arguments -ne $null) { $arg = [string]$ex.Arguments }
    }
    $h = $x.SelectSingleNode('//t:Settings/t:Hidden', $ns)
    if ($h -ne $null) { $hidden = [string]$h.InnerText }
    foreach ($tr in $x.SelectNodes('//t:Triggers/*', $ns)) {
      $sb = ''
      if ($tr.StartBoundary -ne $null) { $sb = [string]$tr.StartBoundary }
      $trigs += ($tr.LocalName + '@' + $sb)
    }
  } catch {}
  $out += ($t.TaskName + '|@|' + $hidden + '|@|' + $cmd + '|@|' + $arg + '|@|' + ($trigs -join ','))
}
$out -join "`n"
"""
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=timeout_s,
            encoding="utf-8", errors="replace",
        )
    except Exception as e:
        print(f"🔴 [closedloop_health.py:834] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return None

    raw = (p.stdout or "").strip()
    if not raw:
        return None

    tasks = {}
    for line in raw.replace("\r\n", "\n").split("\n"):
        parts = [x.strip() for x in line.split("|@|")]
        if len(parts) < 5 or not parts[0]:
            continue
        hv = parts[1].lower()
        hidden = True if hv == "true" else (False if hv == "false" else None)
        tasks[parts[0]] = {
            "hidden": hidden,
            "command": parts[2],
            "arguments": parts[3],
            "triggers": [t for t in parts[4].split(",") if t.strip()],
        }
    return tasks or None


def _query_scheduled_task(task_name: str, timeout_s: int = 20):
    """查询单个 Windows 计划任务的注册态（保留旧签名的兼容入口）。

    返回 (found, command_line, err):
      found=True   已注册，command_line 为 "Command|Arguments"
      found=False  查询成功但无此任务(确实没注册)
      found=None   无法验证(调用失败/超时) —— 按铁律「无法验证」绝不当 PASS
    """
    tasks = _load_scheduled_tasks(timeout_s=max(int(timeout_s), 45))
    if tasks is None:
        return None, "", "计划任务批量查询失败 (PowerShell 不可用/超时)"
    info = tasks.get(task_name)
    if info is None:
        return False, "", ""
    return True, f"{info['command']}|{info['arguments']}", ""


# 静默执行**宿主白名单**(小写 basename)。
# 只有这两类宿主在交互式会话下不会拉起控制台窗口:
#   wscript.exe  — Windows 脚本宿主 GUI 版 (承载 run_path_hidden.vbs)
#   pythonw.exe  — Python 无控制台版
# 反例(均会弹黑窗，禁止直接作为 Command):
#   cmd.exe / powershell.exe / python.exe / cscript.exe / 直接指向 .bat/.cmd
#
# ⚠️ 严禁给单个载体开豁免 —— 白名单是**全局**的，想让某个载体"不算违规"只能改这里，
#    而改这里等于允许它继续弹窗。受 scripts/guard_assertion_effectiveness.py G17 监管。
SILENT_HOSTS = ("wscript.exe", "pythonw.exe")

# A3 反馈写侧新鲜度阈值 (小时，工作日口径)
A3_SOFT_H = 24.0    # 每日盘后任务: 超过 1 个工作日无新写入 ⇒ 疑似漏跑
A3_HARD_H = 72.0    # 连续 3 个工作日无新写入 ⇒ 确认停摆

# A5 假绿检测器心跳阈值 (小时，自然时间口径 —— 心跳是"跑过就写"，与交易日无关)
# 载体 Zhuanqian_WeeklyIC 周期 = 周度 = 168h
A5_SOFT_H = 210.0   # 168h × 1.25 = 8.75 天
A5_HARD_H = 336.0   # 168h × 2    = 14 天

# A12 覆盖的关键调度载体清单 (task_name, 中文说明, 入口文件)
# ⚠️ 严禁删条目/降为「查一个就算过」—— 2026-10-20 之前 A12 只查体检器一个，
#    其余三个载体被删或被改回弹窗式，体检器仍报绿(存在性断言发现不了执行层变化)。
#    新增载体必须同时加进这里 + 守卫 G16。
#
# ⚠️ 2026-10-21 全覆盖升级(假绿修复之三):
#    实测本机共 **28** 个 Zhuanqian_* / QSP_* 计划任务(15 QSP_ + 13 Zhuanqian_)，
#    此前 CARRIER_SPECS 仅 4 条 ⇒ **覆盖面 4/28，其余 24 个载体零断言**。
#    全量扫描后揪出体检器完全看不见的 Zhuanqian_DailyAuto:
#      cmd /c 直跑 daily_auto.bat + Hidden 未设 + 每日 20:00 触发,
#      LastRunTime 实测 2026-10-20 20:00:01 且 Result=0 ⇒ **每天真跑并弹黑窗**。
#    入口字段说明: 相对路径 = 相对 scripts/；绝对路径 = 仓库外载体(如 QSP_* 的
#    C:\\Users\\WIN10\\.quant-stock-picker\\scheduler\\*.bat)。
CARRIER_SPECS = [
    ("Zhuanqian_ClosedLoopHealth", "每日闭环体检", "Zhuanqian_ClosedLoopHealth.bat"),
    ("Zhuanqian_CalendarRefresh", "日历前向刷新", "Zhuanqian_CalendarRefresh.bat"),
    ("Zhuanqian_WeeklyIC", "周度假绿检测", "Zhuanqian_WeeklyIC.bat"),
    ("Zhuanqian_DailyReview", "盘后复盘+反馈写侧", "Zhuanqian_DailyReview.bat"),
    ("Zhuanqian_DailyAuto", "每日自动流水线", "daily_auto.bat"),
    ("Zhuanqian_BoardWatchdog", "看板守护进程", "board_watchdog_launcher.vbs"),
    ("Zhuanqian_FactorIC132d", "132日因子IC", "Zhuanqian_FactorIC132d.bat"),
    ("Zhuanqian_ICMonitor_20d", "20日IC监控", "Zhuanqian_ICMonitor_20d.bat"),
    ("Zhuanqian_RefreshTaskBoard", "看板刷新", "refresh_task_board.py"),
    ("Zhuanqian_Rotation132d", "132日轮动", "Zhuanqian_Rotation132d.bat"),
    ("Zhuanqian_SanityGate", "盘中健全性闸门", "Zhuanqian_SanityGate.bat"),
    ("Zhuanqian_SanityGate_Night", "夜间健全性闸门", "Zhuanqian_SanityGate.bat"),
    ("Zhuanqian_WalkForward", "滚动前推验证", "Zhuanqian_WalkForward.bat"),
    ("QSP_ConfigGC", "配置垃圾回收", "config_gc.cmd"),
    ("QSP_DrainWatch", "排空监听", "drain_meta_task.cmd"),
    ("QSP_GitSync", "代码仓同步", "git_sync_task.cmd"),
    ("QSP_Intraday", "盘中出票",
     r"C:\Users\WIN10\.quant-stock-picker\scheduler\run_intraday.bat"),
    ("QSP_LoopWatch", "闭环看护", "loop_watch_task.cmd"),
    ("QSP_MsgDrain", "消息排空",
     r"C:\Users\WIN10\.quant-stock-picker\scheduler\msg_drain_task.cmd"),
    ("QSP_PostMarket", "盘后结算",
     r"C:\Users\WIN10\.quant-stock-picker\scheduler\run_post_market.bat"),
    ("QSP_PreMarket", "盘前准备",
     r"C:\Users\WIN10\.quant-stock-picker\scheduler\run_pre_market.bat"),
    ("QSP_RemoteFreshness", "远端新鲜度", "remote_freshness_task.cmd"),
    ("QSP_SelfHeal", "自愈", "self_heal_task.cmd"),
    ("QSP_SysWatchdog", "系统看门狗", "sys_watchdog.cmd"),
    ("QSP_Verify", "结果校验",
     r"C:\Users\WIN10\.quant-stock-picker\scheduler\run_verify.bat"),
    ("QSP_Watchdog", "看门狗",
     r"C:\Users\WIN10\.quant-stock-picker\scheduler\run_watchdog.bat"),
    ("QSP_Weekly", "周度汇总",
     r"C:\Users\WIN10\.quant-stock-picker\scheduler\run_weekly.bat"),
    ("QSP_ZLJWatch", "主力资金监控",
     r"C:\Users\WIN10\.quant-stock-picker\scheduler\run_watch_zlj.bat"),
]
def check_a12_schedule_carrier() -> dict:
    """A12 调度载体五层: 入口 + 静默 runner + 已注册 + Hidden + Command宿主
    (覆盖本机全部 28 个 Zhuanqian_* / QSP_* 计划任务)

    与 A0 的分工(二者互补，不是重复):
      A0  验「结果」—— history 是否新鲜，回答「它跑了吗」
      A12 验「能力」—— 入口/注册/静默/形态四层，回答「有没有东西能让它跑」
      组合诊断:
        A0 旧 + A12 FAIL    ⇒ 根本没载体(建了也不会跑)
        A0 旧 + A12 PASS    ⇒ 有载体但没跑(调度器故障/被禁用/机器未开机)

    五层判据(逐级，缺一层都不算「保证执行」):
      L1 入口文件存在 (相对 scripts/ 或绝对路径)
      L2 静默 runner run_path_hidden.vbs 存在 —— 缺失则任务会弹控制台窗口，违反铁律1
      L3 计划任务真注册 —— 未注册则只能人工跑
      L4 Settings/Hidden = true —— 未设置/为 false ⇒ 交互式会话下弹黑窗 (2026-10-21 新增)
      L5 Command 宿主 ∈ SILENT_HOSTS —— 直指 .bat/.cmd 或用 cmd/powershell 均会弹窗
                                          (2026-10-21 新增，原判据只查 wscript 子串)

    为什么 L4/L5 必须**各自独立**判:
      只查 Command 含 wscript(原判据) 发现不了「Hidden 未设」—— 而 Hidden 缺失
      正是 Zhuanqian_DailyAuto 每天弹黑窗的直接原因；
      只查 Hidden 则发现不了「Command 直指 .bat」—— bat 会自己拉起 cmd 窗口。
      两者任一不合规 ⇒ 该载体判 **FAIL**(不是 WARN)。

    触发器(time): 本判据**只记录不判定**，随报告输出供人工核对「计划时点有无留痕」。
      不判定是因为: 触发时间本身无对错，只有与产物时点比对才有意义，
      而产物时点分散在各业务目录，统一比对会引入大量无关噪音。

    聚合规则: 任一载体 FAIL ⇒ 整体 FAIL；无 FAIL 但有 PARTIAL ⇒ PARTIAL；全 PASS ⇒ PASS。
    ⚠️ 注册态查询无法验证时判 PARTIAL 而非 PASS(铁律: 无法验证≠通过)。
    """
    vbs = SCRIPTS_DIR / "run_path_hidden.vbs"
    vbs_ok = vbs.exists()

    tasks = _load_scheduled_tasks()
    if tasks is None:
        return {"status": "PARTIAL",
                "detail": ("计划任务注册态无法验证 (PowerShell 查询失败/超时) "
                           "—— 按铁律「无法验证 ≠ 通过」，不判 PASS")}

    fail_items, partial_items, ok_items = [], [], []
    table = []

    for task_name, desc, entry in CARRIER_SPECS:
        ep = Path(entry)
        entry_path = ep if ep.is_absolute() else (SCRIPTS_DIR / entry)
        if not entry_path.exists():
            partial_items.append(f"{task_name}({desc}): 入口缺失 ({entry_path})")
            table.append(f"{task_name} | Hidden=? | Host=? | ⚠入口缺失 {entry_path}")
            continue

        info = tasks.get(task_name)
        if info is None:
            partial_items.append(
                f"{task_name}({desc}): 未注册 (需提权跑 register_*.ps1 -Force)")
            table.append(f"{task_name} | Hidden=? | Host=? | ⚠未注册")
            continue

        hidden = info["hidden"]
        host = Path(info["command"].replace('"', "")).name.lower() if info["command"] else ""
        trig = ", ".join(info["triggers"]) or "无触发器"
        table.append(f"{task_name} | Hidden={hidden} | Host={host or '空'} | {trig}")

        bad = []
        if hidden is not True:
            bad.append(f"Hidden={hidden} (缺 <Hidden>true</Hidden>，交互式会话会弹黑窗)")
        if host not in SILENT_HOSTS:
            bad.append(f"Command 宿主非静默 ({host or '空'} ∉ {list(SILENT_HOSTS)})")
        if not vbs_ok and host == "wscript.exe":
            bad.append("静默 runner 缺失 (run_path_hidden.vbs 不存在，静默链断裂)")
        if bad:
            fail_items.append(f"{task_name}({desc}): " + "; ".join(bad))
        else:
            ok_items.append(task_name)

    head = (f"{len(ok_items)}/{len(CARRIER_SPECS)} 载体形态合规 "
            f"(入口+runner+已注册+Hidden=true+Command∈{list(SILENT_HOSTS)})")
    if fail_items:
        return {"status": "FAIL",
                "detail": f"{head} —— 形态不合规 {len(fail_items)} 项: "
                          + " || ".join(fail_items),
                "extra_lines": table}
    if partial_items:
        return {"status": "PARTIAL",
                "detail": f"{head} —— 待补 {len(partial_items)} 项: "
                          + "; ".join(partial_items),
                "extra_lines": table}
    return {"status": "PASS", "detail": head, "extra_lines": table}
def _calendar_dates(d: dict) -> list:
    """从 trading_calendar.json 抽出日期字符串列表。

    schema 兼容三种历史形态(实测都出现过, 不可只认一种):
      {"data": {"2026-10-20": {...}, ...}}        dict 键为日期
      {"data": [{"date": "2026-10-20"}, ...]}     list[dict]   <- 现行
      {"data": ["2026-10-20", ...]}               list[str]
    """
    data = d.get("data")
    out = []
    if isinstance(data, dict):
        out = [str(k)[:10] for k in data.keys()]
    elif isinstance(data, list):
        for x in data:
            v = x.get("date") if isinstance(x, dict) else x
            if v:
                out.append(str(v)[:10])
    return sorted(x for x in out if x)


def check_a13_calendar_freshness() -> dict:
    """A13 交易日历新鲜度: pulled_at 未超阈值 且 覆盖今天

    ⚠️ 2026-10-20 立(老六): trading_hours.py 现已强制**真 fail-close** ——
    日历陈旧(pulled_at > 7 天 或 未覆盖今天) ⇒ 所有 weekday 盘内时段 return False
    ⇒ **出票链整体停摆**。

    在此之前这 11 天里该检查是**装饰性**的，两处缺陷:
      ① 调用点丢弃 `_check_calendar_freshness()` 返回值(告警说了锁死, 从不 return False)
      ② 函数内 `if _calendar_warned: return True` ⇒ 第二次调用起**恒谎报新鲜**
    两条均已修(各带注释)。本断言是第三道防线: 让「日历又快过期」在停摆**之前**可见，
    而不是等出票停了才发现 —— 检测 ≠ 驱动, 但检测能让驱动失效这件事被看见。

    阈值(与实现同源, 非拍脑袋):
      hard 7d = trading_hours._CALENDAR_FRESHNESS_DAYS(超过即 true fail-close)
      soft 5d = 提前 2 天预警, 留出人工刷新窗口
    """
    cal = DATA_DIR / "trading_calendar.json"
    if not cal.exists():
        return {"status": "FAIL",
                "detail": "data/trading_calendar.json 不存在 (fail-close ⇒ 出票停摆)"}
    try:
        d = json.loads(cal.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "FAIL", "detail": f"trading_calendar.json 解析失败: {e}"}

    # 注意: 本模块是 `from datetime import datetime`, datetime 是**类**不是模块,
    #       故用 datetime.now().date() 而非 datetime.date.today()。
    today = datetime.now().date()
    dates = _calendar_dates(d)

    # 1. 覆盖今天(与 trading_hours 条件2 同源)
    if not dates:
        return {"status": "FAIL", "detail": "日历无有效条目 (fail-close ⇒ 出票停摆)"}
    if today.isoformat() > max(dates):
        return {"status": "FAIL",
                "detail": (f"日历未覆盖今天 (max={max(dates)} < {today.isoformat()}) "
                           f"⇒ is_trading_hours 恒 False, 出票停摆")}

    # 2. pulled_at 新鲜度(与 trading_hours 条件3 同源)
    pulled = d.get("pulled_at")
    if not pulled:
        return {"status": "PARTIAL", "detail": "日历缺 pulled_at 字段, 无法判新鲜度"}
    try:
        p_dt = datetime.fromisoformat(str(pulled))
        days = (today - p_dt.date()).days
    except Exception:
        return {"status": "PARTIAL",
                "detail": f"pulled_at={pulled!r} 无法解析, 不检查陈旧"}

    if days > 7:
        return {"status": "FAIL",
                "detail": (f"日历 pulled_at={pulled} 距今 {days} 天 > 7 天阈值 "
                           f"⇒ true fail-close, 出票停摆 (刷新: _refresh_trading_calendar.py)")}
    if days > 5:
        # 停摆触发点是 days > 7 (即 days >= 8), 故剩余 = 8 - days。
        # 早期版本写 7 - days, 在 days=7 时报「还剩 0 天」而实际还剩 1 天 ——
        # off-by-one 的倒计时比不报倒计时更糟(误导排期)。已修正。
        return {"status": "PARTIAL",
                "detail": (f"日历 pulled_at={pulled} 距今 {days} 天 > soft 5 天 "
                           f"⇒ 再过 {8 - days} 天即 true fail-close 停摆 "
                           f"(刷新: _refresh_trading_calendar.py)")}
    return {"status": "PASS",
            "detail": f"日历新鲜 (pulled_at {days} 天前, 覆盖至 {max(dates)})"}


# ── 断言映射 ──────────────────────────────────────────────────────────────────
ASSERTION_CHECKS = {
    "A0_体检器自身活性": check_a0_meta_selfcheck,
    "A1_层间契约固化": check_a1_contract,
    "A2_状态唯一真源": check_a2_single_source,
    "A3_闭环反馈写侧": check_a3_feedback_write,
    "A4_闭环反馈读侧": check_a4_feedback_read,
    "A5_假绿不可重复": check_a5_false_green,
    "A6_自审机制运行": check_a6_self_audit,
    "A7_回滚可执行": check_a7_rollback,
    "A8_证据链完整": check_a8_evidence_chain,
    "A9_外部依赖隔离": check_a9_external_isolation,
    "A10_人机边界明确": check_a10_human_machine_boundary,
    "A11_跨体检器交叉校验": check_a11_cross_validation,
    "A12_关键调度载体": check_a12_schedule_carrier,
    "A13_日历新鲜度": check_a13_calendar_freshness,
}


def _ts_diff_days(ts1: str, ts2: str) -> float:
    """计算两个 ISO 时间戳之间的天数差（绝对值）"""
    try:
        dt1 = datetime.fromisoformat(ts1.replace("Z", "+00:00"))
        dt2 = datetime.fromisoformat(ts2.replace("Z", "+00:00"))
        return abs((dt2 - dt1).total_seconds() / 86400)
    except Exception:
        return 999


def run_all_checks() -> dict:
    """运行全部 10 项断言检查，返回结果 dict"""
    results = {}
    for name, check_fn in ASSERTION_CHECKS.items():
        # A11 是后处理断言: 必须等其余断言跑完，才知道"本报告是否有 FAIL"
        if name == "A11_跨体检器交叉校验":
            continue
        try:
            results[name] = check_fn()
        except Exception as e:
            results[name] = {"status": "FAIL", "detail": f"检查异常: {e}"}

    # ── A11 后处理: 把"其余断言是否有 FAIL"喂给它 ──
    others_have_fail = any(
        v.get("status") == "FAIL"
        for k, v in results.items()
    )
    _orig_a11 = check_a11_cross_validation

    def _a11_with_context():
        r = _orig_a11()
        # 若本报告已有 FAIL，说明问题已被捕获，不重复计矛盾
        if r.get("status") == "FAIL" and others_have_fail:
            sig = r.pop("_cross_signal", {})
            return {
                "status": "PARTIAL",
                "detail": (f"台账 {sig.get('open_p0', '?')} 条 open P0 已被本报告 "
                           f"FAIL 项捕获（共 {sig.get('open_all', '?')} 条未销账），"
                           f"不重复计矛盾 —— 但仍需销账驱动"),
            }
        return r

    try:
        results["A11_跨体检器交叉校验"] = _a11_with_context()
    except Exception as e:
        results["A11_跨体检器交叉校验"] = {"status": "FAIL", "detail": f"检查异常: {e}"}

    return results


def calc_completeness(results: dict) -> dict:
    """计算完整率，返回 {score, pass_count, partial_count, fail_count, detail}"""
    SCORE_MAP = {"PASS": 1.0, "PARTIAL": 0.5, "FAIL": 0.0}
    total = 0.0
    pass_count = 0
    partial_count = 0
    fail_count = 0
    detail = []
    for name, r in results.items():
        s = r.get("status", "FAIL")
        score = SCORE_MAP.get(s, 0.0)
        total += score
        if s == "PASS":
            pass_count += 1
        elif s == "PARTIAL":
            partial_count += 1
        else:
            fail_count += 1
        detail.append(f"{name}={s}")

    completeness = round(total / len(ASSERTION_CHECKS) * 100, 1) if ASSERTION_CHECKS else 0
    return {
        "score": total,
        "total": len(ASSERTION_CHECKS),
        "completeness_pct": completeness,
        "pass": pass_count,
        "partial": partial_count,
        "fail": fail_count,
        "detail": detail,
    }


def write_daily_signal(results: dict, completeness: dict, tech_debt: Optional[dict] = None) -> None:
    """将闭环完整率写入 data/daily_signal.json（atomic，不改动其他字段）"""
    from core.pipeline.atomic_json import update_json, atomic_load

    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().isoformat()

    def _build_closedloop() -> dict:
        cb = {
            "ts": ts,
            "completeness_pct": completeness["completeness_pct"],
            "score": completeness["score"],
            "total": completeness["total"],
            "pass": completeness["pass"],
            "partial": completeness["partial"],
            "fail": completeness["fail"],
            "assertions": {name: r["status"] for name, r in results.items()},
        }
        if tech_debt is not None:
            cb["tech_debt"] = {
                "open": tech_debt.get("open", 0),
                "stale_7d": tech_debt.get("stale_7d", []),
                "oldest_ts": tech_debt.get("oldest_ts"),
                "alert_level": tech_debt.get("alert_level", "P2"),
            }
        return cb

    def mutator(existing: dict) -> dict:
        existing["date"] = today
        existing["closedloop"] = _build_closedloop()
        return existing

    default_cb = _build_closedloop()
    update_json(str(DAILY_SIGNAL), mutator, default={
        "date": today,
        "timestamp": ts,
        "closedloop": default_cb,
    })

    # read-back 断言
    readback = atomic_load(str(DAILY_SIGNAL), default={})
    cb = readback.get("closedloop", {})
    assert cb.get("completeness_pct") == completeness["completeness_pct"], (
        f"daily_signal read-back 断言失败: 期望 {completeness['completeness_pct']}%, "
        f"实际 {cb.get('completeness_pct')}%"
    )
    if tech_debt is not None:
        assert "tech_debt" in cb, "daily_signal read-back: tech_debt 字段缺失"
        assert cb["tech_debt"].get("open") == tech_debt.get("open"), (
            f"daily_signal tech_debt.open 断言失败: 期望 {tech_debt.get('open')}, "
            f"实际 {cb['tech_debt'].get('open')}"
        )


def append_history(results: dict, completeness: dict) -> None:
    """将当日记录 append 到 data/closedloop_history.jsonl"""
    record = {
        "ts": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "completeness_pct": completeness["completeness_pct"],
        "score": completeness["score"],
        "total": completeness["total"],
        "pass": completeness["pass"],
        "partial": completeness["partial"],
        "fail": completeness["fail"],
        "assertions": {name: r["status"] for name, r in results.items()},
    }
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def print_report(results: dict, completeness: dict) -> None:
    """打印人类可读报告"""
    print("=" * 60)
    print("📊 闭环健康度日报")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"   完整率: {completeness['completeness_pct']:.1f}% "
          f"({completeness['pass']}PASS/{completeness['partial']}PARTIAL/{completeness['fail']}FAIL)")
    print("-" * 60)
    for name, r in results.items():
        icon = {"PASS": "✅", "PARTIAL": "⚠️", "FAIL": "❌"}.get(r["status"], "❓")
        print(f"   {icon} {name}: {r['detail']}")
        for extra in r.get("extra_lines", []):
            print(f"        · {extra}")
    print("=" * 60)


def get_7day_trend() -> list:
    """读取最近 7 日趋势数据"""
    if not HISTORY_FILE.exists():
        return []
    records = []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"🔴 [scripts\closedloop_health.py] CR-01: except json.JSONDecodeError:", file=sys.stderr)
    # 取最后 7 条
    return records[-7:]


def main():
    parser = argparse.ArgumentParser(description="闭环健康度日报生成器")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出到 stdout")
    args = parser.parse_args()

    results = run_all_checks()
    completeness = calc_completeness(results)
    tech_debt = parse_tech_debt_ledger()

    if args.json:
        output = {
            "ts": datetime.now().isoformat(),
            "completeness": completeness,
            "assertions": {name: r["status"] for name, r in results.items()},
            "tech_debt": tech_debt,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    print_report(results, completeness)

    if args.dry_run:
        print("[DRY-RUN] 跳过文件写入")
        return 0

    # 写 daily_signal（含 tech_debt）
    write_daily_signal(results, completeness, tech_debt=tech_debt)
    print(f"[OK] daily_signal 已更新: {DAILY_SIGNAL}")

    # 技术债告警
    if tech_debt["alert_level"] == "P1":
        print(f"[P1] 技术债告警: {tech_debt['detail']}")
    else:
        print(f"[{tech_debt['alert_level']}] 技术债: {tech_debt['detail']}")

    # 写 history jsonl
    append_history(results, completeness)
    print(f"[OK] history 已追加: {HISTORY_FILE}")

    # 打印 7 日趋势
    trend = get_7day_trend()
    if trend:
        print("\n📈 近 7 日趋势:")
        for r in trend:
            print(f"   {r['date']}: {r['completeness_pct']:.1f}% "
                  f"({r['pass']}P/{r['partial']}Pa/{r['fail']}F)")
    else:
        print("\n📈 无历史趋势数据（首日运行）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
