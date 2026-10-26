# -*- coding: utf-8 -*-
"""factor_decay_monitor.py — 因子衰减监控挂表 (P2-O3, 2026-10-20 老三)

老五 R0 复审 t_7819f7e3 附观察 O3：v2.6 四活跃因子中 3 个 IR<0.3
(chg10=0.2118 / chg5=0.1836 / momentum_20=0.144，仅 overnight_sum20=0.3593 达标)
+ 20d 已示 2 翻转 + 1 衰减 42.4%。本脚本建因子衰减监控挂表。

读（只读）:
  data/factor_ic/factor_ic_latest.json   权威 132d 表 (diagnostics.{f}.icir)
  data/factor_ic/t2b_gate_20d_check.json 20d 对比 (comparison.{f}.direction_match / ic_retained_pct)
  data/trading_calendar.json             A股交易日历（交易日计数口径真源）
写（唯一写口）:
  data/decay_signals.json               追加型信号登记 + 连击计数器（防重复告警）
  data/message_queue.json               新信号 → message_queue.add_message() 唯一出口
                                        （feishu 由 QSP_MsgDrain drain 投递）

信号规则（触发 → 建议；本脚本只监控+建议，执行由老五拍板，不改 factor_weights.json）:
  R1 flip_persist   chg10 / momentum_20 方向翻转持续 >=20 交易日 → P1 重裁 v2.7 建议
  R2 low_retention  chg5 保留率 <40% 连续 2 周(10 交易日)       → P1 重裁 v2.7 建议
  R3 ir_all_low     所有活跃因子 ICIR <0.3 持续 >=30 交易日      → P2 重标 v2.8 建议

计数口径（防连击编造）:
  - 只在"数据 as-of 日推进"时计数：每规则记 last_obs_date（该次数据 as-of 日）。
    同 as-of 日重跑=幂等（不连击、不重置）。as-of 源：20d 检查用 computed_at 日期，
    132d 权威表用 last_date。
  - as-of 推进 Δ 时：条件真区间连击 += trading_days_between(last_obs, obs)
    （data/trading_calendar.json 区间 (last_obs, obs] 计数）。
  - 条件 假→真：连击保守记 1（中间区间不可证，不外推历史）。
  - 条件 真→假：连击清零 + active 信号标 cleared（追加 cleared event，不重报）。
  - 数据回退（新 as-of < 旧）：计数器不动，记 data_regressed 警告。
  - 数据文件缺失 / 契约字段缺失 → DataContractError loud fail (exit 2)，无静默默认值。

CLI:
  python scripts/factor_decay_monitor.py            # 正常跑（stdout=JSON 报告, 人话进 stderr）
  python scripts/factor_decay_monitor.py --no-queue # 不写 message_queue（测试/演练用）
退出码: 0=正常（含 fired 非空）; 2=数据契约断裂/队列写失败（loud）
"""
import argparse
import bisect
import json
import os
import sys
from datetime import datetime

# ---- 路径（以本文件位置定位仓库根，不信任 cwd）----
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LATEST_IC_PATH = os.path.join(DATA_DIR, "factor_ic", "factor_ic_latest.json")
GATE_20D_PATH = os.path.join(DATA_DIR, "factor_ic", "t2b_gate_20d_check.json")
CALENDAR_PATH = os.path.join(DATA_DIR, "trading_calendar.json")
SIGNALS_PATH = os.path.join(DATA_DIR, "decay_signals.json")
REPORT_PATH = os.path.join(DATA_DIR, "decay_monitor_report.json")

# 仓库根进 sys.path（atomic_json / message_queue 真源在根侧；
# tmp-repo 测试布局里则指向被拷贝的 tmp 根 —— 两种场景同一行生效）
sys.path.insert(0, PROJECT_ROOT)
import core.pipeline.atomic_json  # noqa: E402

# 告警阈值/规则配置（口径来源：P2-O3 任务单；改口径须老五拍板）
RULES = {
    "flip_persist": {
        "factors": ["chg10", "momentum_20"],
        "threshold_days": 20,
        "severity": "P1",
        "recommendation": "v2.7 重裁",
        "obs_source": "gate_20d",
    },
    "low_retention": {
        "factors": ["chg5"],
        "threshold_days": 10,          # 连续 2 周 × 5 交易日
        "retention_pct_lt": 40.0,
        "severity": "P1",
        "recommendation": "v2.7 重裁",
        "obs_source": "gate_20d",
    },
    "ir_all_low": {
        "factors": None,              # 全部 active_factors（来自 20d 检查）
        "threshold_days": 30,
        "ir_threshold": 0.3,
        "severity": "P2",
        "recommendation": "v2.8 重标",
        "obs_source": "ic_latest",
    },
}

STALE_FLAG_TRADING_DAYS = 4   # as-of 落后今日 >4 交易日 → stale 标记（仅告警，计数器自然冻结）


class DataContractError(RuntimeError):
    """输入数据契约被破坏：缺失文件 / 缺失字段 / 无法解析。loud fail，无静默默认值。"""


# ====================================================================
# 纯核（无 IO，可单测）
# ====================================================================

def trading_days_between(calendar_dates, start, end):
    """(start, end] 区间内的交易日数。calendar_dates=升序 YYYY-MM-DD 列表。
    end <= start 或区间无交易日 → 0。as-of 日不在日历内也按区间位置计数（不报错）。"""
    if not end or not start or end <= start:
        return 0
    return bisect.bisect_right(calendar_dates, end) - bisect.bisect_right(calendar_dates, start)


def fresh_state():
    return {"version": 1, "counters": {}, "signals": [], "cleared_events": []}


def _get_comparison(gate, factor):
    cmp = (gate.get("comparison") or {}).get(factor)
    if not isinstance(cmp, dict):
        raise DataContractError(
            f"t2b_gate_20d_check.json 缺少 comparison.{factor}（活跃因子契约字段）")
    return cmp


def _gate_obs_date(gate):
    ts = (gate.get("computed_at") or "")[:10]
    if not ts:
        raise DataContractError("t2b_gate_20d_check.json 缺 computed_at（无法定位 as-of 日）")
    return ts


def _latest_obs_date(latest):
    d = (latest.get("last_date") or "")[:10]
    if not d:
        raise DataContractError("factor_ic_latest.json 缺 last_date（无法定位 as-of 日）")
    return d


def _advance(st, key, cond, obs_date, calendar, warnings):
    """推进单条计数器（幂等/回退/假→真保守/真→假清零）。"""
    counters = st["counters"]
    cur = counters.get(key)
    if cur is None:
        counters[key] = {
            "streak_days": 1 if cond else 0,
            "first_cond_date": obs_date if cond else None,
            "last_obs_date": obs_date,
            "condition": cond,
        }
        return
    if obs_date == cur["last_obs_date"]:
        cur["condition"] = cond          # 同 as-of 日重跑：幂等
        return
    if obs_date < cur["last_obs_date"]:
        warnings.append(
            f"data_regressed:{key} 新as-of {obs_date} < 旧 {cur['last_obs_date']}，计数器保留不动")
        return
    delta = trading_days_between(calendar, cur["last_obs_date"], obs_date)
    prev = cur["streak_days"]
    if cond:
        if prev > 0:
            cur["streak_days"] = prev + delta
        else:
            # 假→真保守口径：只记 1（中间区间不可证），并复位 last_cleared 允许再次清零
            cur["streak_days"] = 1
            cur["first_cond_date"] = obs_date
            cur["last_cleared"] = False
    else:
        cur["streak_days"] = 0
        cur["first_cond_date"] = None
    cur["last_obs_date"] = obs_date
    cur["condition"] = cond


def _cond_flip(gate, factor):
    """R1: 20d 方向翻转（baseline 与 20d 均值异号，20d 检查已算好 direction_match）。"""
    cmp = _get_comparison(gate, factor)
    dm = cmp.get("direction_match")
    if dm is None:
        raise DataContractError(f"comparison.{factor} 缺 direction_match（契约字段）")
    return dm is False, cmp


def _cond_low_retention(gate):
    """R2: chg5 保留率 <40%。保留率缺失=数据缺口（skip 本条、不清零连击），非静默吞。
    返回 (cond, cmp, warnings, skip)。"""
    cmp = _get_comparison(gate, "chg5")
    r = cmp.get("ic_retained_pct")
    if r is None:
        return False, cmp, ["low_retention:chg5 保留率缺失，本条跳过（不清零连击、不计入）"], True
    return r < RULES["low_retention"]["retention_pct_lt"], cmp, [], False


def _cond_ir_all_low(latest, gate):
    """R3: 所有活跃因子 ICIR < 0.3（权威表 diagnostics 为准，活跃集=20d 检查 active_factors）。"""
    active = gate.get("active_factors")
    if not active:
        raise DataContractError("t2b_gate_20d_check.json 缺 active_factors（无法判定活跃集）")
    diag = latest.get("diagnostics") or {}
    icirs = {}
    for f in active:
        d = diag.get(f)
        if not isinstance(d, dict) or d.get("icir") is None:
            raise DataContractError(f"factor_ic_latest.json diagnostics 缺 {f}.icir（活跃因子契约字段）")
        icirs[f] = d["icir"]
    thr = RULES["ir_all_low"]["ir_threshold"]
    return all(v < thr for v in icirs.values()), icirs


def _check_trigger(st, rule, factor, obs_date, evidence, now_iso):
    """连击达阈值且无 active 信号 → 追加登记（防重复告警）。返回 fired/None。"""
    key = f"{rule}:{factor}"
    stc = st["counters"].get(key)
    if not stc or stc["streak_days"] < RULES[rule]["threshold_days"]:
        return None
    active = [s for s in st["signals"] if s.get("key") == key and s.get("status") == "active"]
    if active:
        return None
    sig = {
        "id": f"DEC-{rule}-{factor}-{obs_date}",
        "key": key,
        "rule": rule,
        "factor": factor,
        "severity": RULES[rule]["severity"],
        "recommendation": RULES[rule]["recommendation"],
        "streak_days": stc["streak_days"],
        "threshold_days": RULES[rule]["threshold_days"],
        "first_cond_date": stc.get("first_cond_date"),
        "data_asof": obs_date,
        "evidence": evidence,
        "triggered_at": now_iso,
        "status": "active",
        "queued": False,
    }
    st["signals"].append(sig)
    return sig


def _check_clear(st, rule, factor):
    """条件已清零 + 存在 active 信号 → 标 cleared（追加事件，不重报）。"""
    key = f"{rule}:{factor}"
    stc = st["counters"].get(key)
    if not stc or stc["streak_days"] != 0 or stc.get("last_cleared", False):
        return None
    active = [s for s in st["signals"] if s.get("key") == key and s.get("status") == "active"]
    if not active:
        return None
    for s in active:
        s["status"] = "cleared"
        s["cleared_at"] = stc.get("last_obs_date")
    ev = {
        "key": key,
        "cleared_at": stc.get("last_obs_date"),
        "note": f"{key} 条件清零（streak=0），信号关闭，不再重复告警",
    }
    st["cleared_events"].append(ev)
    stc["last_cleared"] = True
    return active[0]


def evaluate(latest, gate, calendar_dates, state, now_iso):
    """纯核：两表 + 日历 + 旧状态 → 原地更新 state，返回
    {"counters", "fired", "cleared", "warnings", "obs_dates"}。
    数据契约破坏 → DataContractError（调用方 loud fail，不静默）。"""
    warnings = []
    prev_sig_count = len(state["signals"])

    gate_obs = _gate_obs_date(gate)
    lat_obs = _latest_obs_date(latest)

    # R1: chg10 / momentum_20 翻转
    for f in RULES["flip_persist"]["factors"]:
        cond, cmp = _cond_flip(gate, f)
        _advance(state, f"flip_persist:{f}", cond, gate_obs, calendar_dates, warnings)
        ev = {
            "gate_computed_at": gate.get("computed_at"),
            "direction_match": cmp.get("direction_match"),
            "ic_retained_pct": cmp.get("ic_retained_pct"),
            "ic_20d_mean": (gate.get("recent_ic_20d") or {}).get(f, {}).get("ic_20d_mean"),
            "baseline_ic_mean": (gate.get("baseline_ic") or {}).get(f, {}).get("ic_mean"),
        }
        fired = _check_trigger(state, "flip_persist", f, gate_obs, ev, now_iso)
        if fired is None:
            _check_clear(state, "flip_persist", f)

    # R2: chg5 保留率（保留率缺失=数据缺口 → 跳过本条，不清零连击）
    cond, cmp, wr, skip = _cond_low_retention(gate)
    warnings.extend(wr)
    if not skip:
        _advance(state, "low_retention:chg5", cond, gate_obs, calendar_dates, warnings)
        ev = {"gate_computed_at": gate.get("computed_at"),
              "ic_retained_pct": cmp.get("ic_retained_pct"),
              "threshold_pct": RULES["low_retention"]["retention_pct_lt"]}
        fired = _check_trigger(state, "low_retention", "chg5", gate_obs, ev, now_iso)
        if fired is None:
            _check_clear(state, "low_retention", "chg5")

    # R3: 全部活跃因子 ICIR < 0.3（as-of = 权威表 last_date）
    cond, icirs = _cond_ir_all_low(latest, gate)
    _advance(state, "ir_all_low:ALL", cond, lat_obs, calendar_dates, warnings)
    ev = {"icir": icirs, "threshold": RULES["ir_all_low"]["ir_threshold"],
          "ic_latest_last_date": lat_obs}
    fired = _check_trigger(state, "ir_all_low", "ALL", lat_obs, ev, now_iso)
    if fired is None:
        _check_clear(state, "ir_all_low", "ALL")

    # 收集本轮新增（触发/清零已在各规则处就地处理；按追加位置切片，防同秒重跑误报旧信号）
    fired_all = state["signals"][prev_sig_count:]
    cleared_all = []
    for evc in state["cleared_events"]:
        if evc.get("reported_at") is None:
            evc["reported_at"] = now_iso
            cleared_all.append(evc)

    return {
        "counters": state["counters"],
        "fired": fired_all,
        "cleared": cleared_all,
        "warnings": warnings,
        "obs_dates": {"gate_20d": gate_obs, "ic_latest": lat_obs},
    }


# ====================================================================
# IO 层
# ====================================================================

def _load_json(path, what):
    if not os.path.exists(path):
        raise DataContractError(f"{what} 文件缺失: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise DataContractError(f"{what} 解析失败 {path}: {e}")


def load_calendar_dates(path):
    raw = _load_json(path, "交易日历")
    dates = raw.get("data") if isinstance(raw, dict) else raw
    if not isinstance(dates, list) or not dates:
        raise DataContractError("trading_calendar.json 结构异常（需 {data: [{date}] 或 [date,...]}）")
    out = sorted(str(d.get("date") if isinstance(d, dict) else d) for d in dates)
    return out


def load_state(path):
    if not os.path.exists(path):
        return fresh_state(), "fresh_init"
    raw = _load_json(path, "decay_signals.json")
    for k in ("counters", "signals", "cleared_events"):
        if k not in raw:
            raise DataContractError(f"decay_signals.json 缺 {k}（状态文件损坏不得静默重建，loud fail）")
    return raw, "loaded"


def queue_signals(signals, project_root=PROJECT_ROOT, queue_enabled=True):
    """新信号 → message_queue.json 唯一出口。返回 (queued_ids, failures)。
    add_message 自身吞异常返回 None → 这里必须检查，None=写失败=loud（不静默）。"""
    if not queue_enabled:
        return [], []
    sys.path.insert(0, project_root)
    import core.ops.message_queue as message_queue  # S4/S6迁移残留修复(2026-10-24 [t_laosan_c1_test_alignment]): 裸 import 只绑定 core, 下方 message_queue.add_message 会 NameError
    queued, failures = [], []
    for s in signals:
        lines = [
            f"⚠️ 【因子衰减监控 M-4 {s['severity']}】{s['rule']}:{s['factor']}",
            f"{s['severity']} 建议：{s['recommendation']}（执行由老五拍板，本项只监控不改 factor_weights.json）",
            f"连击 {s['streak_days']} 交易日 ≥ 阈值 {s['threshold_days']}（首证日 {s.get('first_cond_date')}，as-of {s['data_asof']}）",
            f"证据: {json.dumps(s.get('evidence', {}), ensure_ascii=False)}",
            f"登记: data/decay_signals.json id={s['id']}（追加型，防重复告警）",
            f"时间: {s.get('triggered_at')}",
        ]
        mid = message_queue.add_message(
            "factor_decay_monitor", "\n".join(lines),
            priority="critical" if s["severity"] == "P1" else "normal")
        if mid is None:
            failures.append(s["id"])
        else:
            s["queued"] = True
            queued.append(s["id"])
    return queued, failures


def run(queue_enabled=True, now=None, root=None, report_path=None):
    """IO 封装。返回 (rc, report)。rc: 0=正常（含 fired）, 2=契约断裂/队列写失败。"""
    now = now or datetime.now()
    now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
    report = {"ts": now_iso, "status": "ok", "fired": [], "cleared": [],
              "warnings": [], "error": None, "counters": {}, "obs_dates": {},
              "stale": {}}
    root = root or PROJECT_ROOT
    data_dir = os.path.join(root, "data")
    p_latest = os.path.join(data_dir, "factor_ic", "factor_ic_latest.json")
    p_gate = os.path.join(data_dir, "factor_ic", "t2b_gate_20d_check.json")
    p_cal = os.path.join(data_dir, "trading_calendar.json")
    p_sig = os.path.join(data_dir, "decay_signals.json")
    p_rep = report_path or os.path.join(data_dir, "decay_monitor_report.json")

    try:
        latest = _load_json(p_latest, "权威表 factor_ic_latest.json")
        gate = _load_json(p_gate, "20d 对比 t2b_gate_20d_check.json")
        calendar = load_calendar_dates(p_cal)
        state, state_note = load_state(p_sig)
        if state_note == "fresh_init":
            report["warnings"].append("decay_signals.json 首次初始化（无历史连击，计数器自本日起算）")
        res = evaluate(latest, gate, calendar, state, now_iso)
        report.update({"fired": res["fired"], "cleared": res["cleared"],
                       "warnings": report["warnings"] + res["warnings"],
                       "counters": res["counters"], "obs_dates": res["obs_dates"]})

        # stale 标记（仅告警；as-of 不推进时计数器自然冻结）
        today = now.strftime("%Y-%m-%d")
        for name, obs in res["obs_dates"].items():
            behind = trading_days_between(calendar, obs, today) if obs < today else 0
            report["stale"][name] = {"behind_trading_days": behind,
                                     "stale": behind > STALE_FLAG_TRADING_DAYS}

        # 队列先行（写成功才置 queued=True），再统一原子落盘 state+report ——
        # 顺序不可倒：先落盘再入队会让 queued flag 永远 False → 下轮重复入队（防重复告警失效）
        pending = list(res["fired"])
        for s in state["signals"]:
            if s.get("status") == "active" and not s.get("queued") and s not in res["fired"]:
                pending.append(s)
        queued, failures = queue_signals(pending, project_root=root,
                                         queue_enabled=queue_enabled)
        report["queued_ids"] = queued
        state["updated_at"] = now_iso
        # 原子写（团队 JSON 原子写规约）
        sys.path.insert(0, root)
        import core.pipeline.atomic_json as atomic_json  # 同上: 裸 import 只绑定 core, 下方 atomic_json.atomic_dump 会 NameError
        atomic_json.atomic_dump(state, p_sig, ensure_ascii=False, indent=2, encoding="utf-8")
        atomic_json.atomic_dump(report, p_rep, ensure_ascii=False, indent=2, encoding="utf-8")

        if failures:
            report["status"] = "queue_failed"
            report["error"] = f"message_queue 写入失败: {failures}（信号已登记 decay_signals.json，下轮重试）"
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return 2, report
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0, report
    except DataContractError as e:
        report["status"] = "error"
        report["error"] = str(e)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 2, report
    except Exception as e:  # 真异常 ≠ 契约错，同样 loud（不静默吞）
        report["status"] = "error"
        report["error"] = f"监控器异常: {type(e).__name__}: {e}"
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 2, report


def main(argv=None):
    ap = argparse.ArgumentParser(description="因子衰减监控挂表 (P2-O3)")
    ap.add_argument("--json", action="store_true",
                    help="stdout 输出 JSON 报告（默认即 JSON；本旗标为 self_audit M-4 复检调用契约）")
    ap.add_argument("--no-queue", action="store_true",
                    help="不写 message_queue.json（测试/演练用；生产默认写）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只算不写（不落 decay_signals.json / message_queue.json）")
    args = ap.parse_args(argv)

    if args.dry_run:
        # dry-run：纯计算，走内存 state，不写任何生产文件
        latest = _load_json(LATEST_IC_PATH, "权威表 factor_ic_latest.json")
        gate = _load_json(GATE_20D_PATH, "20d 对比 t2b_gate_20d_check.json")
        calendar = load_calendar_dates(CALENDAR_PATH)
        state, _ = load_state(SIGNALS_PATH)
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            res = evaluate(latest, gate, calendar, state, now_iso)
        except DataContractError as e:
            print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
            return 2
        for w in res["warnings"]:
            print(f"⚠️ {w}", file=sys.stderr)
        print(json.dumps({"dry_run": True, "fired": res["fired"], "cleared": res["cleared"],
                           "counters": res["counters"], "obs_dates": res["obs_dates"],
                           "warnings": res["warnings"]}, ensure_ascii=False, indent=1))
        return 0

    rc, report = run(queue_enabled=not args.no_queue)
    if report.get("fired"):
        for s in report["fired"]:
            print(f"🚨 [{s['severity']}] {s['rule']}:{s['factor']} 连击 {s['streak_days']}d ≥ "
                  f"阈值 {s['threshold_days']}d → {s['recommendation']}", file=sys.stderr)
    for w in report.get("warnings", []):
        print(f"⚠️ {w}", file=sys.stderr)
    if rc != 0:
        print(f"🚨 因子衰减监控 loud fail: {report.get('error')}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
