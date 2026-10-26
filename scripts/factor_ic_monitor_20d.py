# -*- coding: utf-8 -*-
"""factor_ic_monitor_20d.py — v2因子 20日滚动IC生产监控 (老三 2026-09-27)

老五第3件: 20日因子IC滚动监控进生产, 补 factor_v2.json 只有"笔数/回撤"两条触发器的缺口.
口径: 复用活跃真源单一算术源 (2026-10-23 归档裁决: .scratch/factor_ic_scan.py 已下线):
    IC = core/scoring/factor_gate_v2.spearman_ic, 因子函数 = scripts/factor_ic_132d_refresh.FACTOR_FUNCTIONS
    (逐字提升自 factor_ic_scan FACTORS, 同一算术, 不另造IC口径).
    截面日/股票抽样步长与门禁扫描一致(SCAN_STEP=5, STOCK_STRIDE=2), 保 IC 可比.
只监控 v2 启用的 6 因子: low60_dist/vol_dryup/gap_down_cnt/amount_price_corr/red_ratio10/overnight_sum20.
失效条款: 最近20截面日, 某因子 |IC均值|<0.03 或 方向翻转(相对门禁IC符号) → 该因子告警;
          ≥3因子同时告警 → 建议 factor_v2.json enabled=false 回基线(人工/总管执行, 监控只写标志不自动翻).

用法:
  .venv/Scripts/python .scratch/factor_ic_monitor_20d.py [窗口交易日=100]
输出: data/audit/factor_ic_rolling_20d_<YYYYMMDD>.json (atomic_dump, 防并发)
退出码: 0=无告警, 3=有因子告警(需人工复核), 2=样本不足
"""
import sys, os, math, time, json
from datetime import date, timedelta
sys.path.insert(0, r"D:\open code\zhuanqian")
os.chdir(r"D:\open code\zhuanqian")

import backtest as BT
from core.scoring.factor_gate_v2 import spearman_ic as spearman  # 单一算术源 (2026-10-23 归档: factor_ic_scan 下线, [t_laosan_c1_test_alignment])
from scripts.factor_ic_132d_refresh import FACTOR_FUNCTIONS as FACTORS  # 31因子注册表, 逐字提升自 factor_ic_scan FACTORS, 同算术
from core.scoring.tdx_factor_v2 import DEFAULT_RULES
from core.pipeline.atomic_json import atomic_dump

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [scripts\factor_ic_monitor_20d.py] CR-01: except Exception:", file=sys.stderr)
# v2 启用 6 因子 (与 tdx_factor_v2.DEFAULT_RULES 一致) + 门禁IC符号 (来自 new_factor_ic_scan_20260926)
V2_FACTORS = ['low60_dist', 'vol_dryup', 'gap_down_cnt', 'amount_price_corr', 'red_ratio10', 'overnight_sum20']
GATE_IC_SIGN = {  # 20260926 全样本门禁 IC 符号 (负=反转/缩量系, 唯一 overnight 正)
    'low60_dist': -1, 'vol_dryup': -1, 'gap_down_cnt': -1,
    'amount_price_corr': -1, 'red_ratio10': -1, 'overnight_sum20': +1,
}
HORIZON = 20          # 前向 20d (老五"20日IC")
RECENT_N = 20         # 滚动窗口: 最近 20 个截面日
IC_MIN = 0.03         # 失效门槛 |IC|<0.03
ALERT_MAX = 3         # ≥3 因子同时告警 → 建议回基线
WARMUP = 170

WINDOW_DAYS = 100  # 回看交易日跨度(默认100≈半年, 保因子warmup)
if len(sys.argv) > 1:  # 命令行覆盖; pytest 导入时 argv[1] 非int → 保持默认, 不崩
    try:
        WINDOW_DAYS = int(sys.argv[1])
    except ValueError:
        WINDOW_DAYS = 100
STOCK_STRIDE = 2      # 与门禁同抽样口径


# ── 老五验收口径 + 防假绿守卫 (2026-09-27 P0 修复): 判定抽成纯函数, 供回归锁死判据 ──
def decide_exit_code(out_factors: dict, alerts: list, alert_max: int = 3) -> int:
    """IC 监控退出码判定（纯函数，供 tests/test_ic_monitor_guard.py 锁死假绿判据）。

    判据（老五 2026-09-27 口径，改回即视为 P0 回归）:
      - 有因子告警(方向翻转/IC过弱)              → 3（需人工复核）
      - 全因子无有效IC(n_valid==0)             → 4（假绿守卫：监控未真正工作，
                                                  绝不得当作"无告警 exit=0"）
      - 至少一因子产出非None IC 且无告警        → 0
    """
    n_valid = sum(1 for f in out_factors if "rolling20_ic_mean" in out_factors[f])
    if alerts:
        return 3
    if n_valid == 0:
        return 4
    return 0


def main():
    t0 = time.time()
    end = date(2026, 9, 18)  # 回测数据末端 (老五口径, 同 4 跑)
    start = end - timedelta(days=WINDOW_DAYS)
    print(f"### IC监控 窗口 {start}~{end} 前向{HORIZON}d 抽样{STOCK_STRIDE} {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

    all_stocks = BT.collect_all_stocks()
    cache = BT.load_name_cache()
    codes = sorted(all_stocks.items())[::STOCK_STRIDE]

    sh_records = BT._load_sh_index_records(0)
    timeline = []
    for r in sh_records:
        d = r["date"] if isinstance(r["date"], date) else date.fromisoformat(str(r["date"]))
        if start <= d <= end:
            timeline.append(d)
    # 最近 RECENT_N 个截面日 (每5交易日1个扫描日, 与轮动同源)
    scan_days = timeline[::5][-RECENT_N:]
    if len(scan_days) < 10:
        print(f"FAIL 截面日不足: {len(scan_days)} < 10", flush=True)
        return 2
    scan_set = set(scan_days)

    # 逐股收最近窗口的因子值 + 前向20d收益 (同 factor_ic_scan panel 算术)
    panels = {f: {} for f in V2_FACTORS}
    n_used = 0
    for k, (code, mkt) in enumerate(codes):
        if BT.is_st_stock(cache.get(code, "")):
            continue
        recs = BT.get_tdx_data(code, 3000) or []
        recs = [r for r in recs if (r["date"] if isinstance(r["date"], date) else date.fromisoformat(str(r["date"]))) >= date(2020, 3, 2)]
        if len(recs) < WARMUP + 25:
            continue
        dates = [r["date"] if isinstance(r["date"], date) else date.fromisoformat(str(r["date"])) for r in recs]
        c = [float(r["close"]) for r in recs]
        o = [float(r["open"]) for r in recs]
        h = [float(r["high"]) for r in recs]
        l = [float(r["low"]) for r in recs]
        v = [float(r["volume"]) for r in recs]
        a = [float(r.get("amount") or 0) for r in recs]
        n_used += 1
        for i, d in enumerate(dates):
            if d not in scan_set or i < WARMUP:
                continue
            # 前向20d (含退市: 不足一半用存续期收益, 同 factor_ic_scan)
            if i + HORIZON < len(c) and c[i] > 0:
                fwd = (c[i + HORIZON] / c[i] - 1) * 100
            elif i + HORIZON // 2 < len(c):
                fwd = (c[-1] / c[i] - 1) * 100
            else:
                continue
            cw, ow, hw, lw, vw, aw = c[:i+1], o[:i+1], h[:i+1], l[:i+1], v[:i+1], a[:i+1]
            for fname in V2_FACTORS:
                ffn = FACTORS.get(fname)
                if ffn is None:
                    continue
                try:
                    val = ffn(cw, ow, hw, lw, vw, aw)
                except Exception:
                    val = None
                if val is None or not math.isfinite(val):
                    continue
                panels[fname].setdefault(str(d), []).append((val, fwd))
        if (k + 1) % 300 == 0:
            print(f"    进度 {k+1}/{len(codes)} | 有效 {n_used}", flush=True)

    print(f"✅ 有效股票 {n_used} | 最近{len(scan_days)}截面日 {scan_days[0]}~{scan_days[-1]}", flush=True)

    # 逐因子: 每截面 Spearman IC → 最近20日均值 + 方向 + 失效判定
    out_factors = {}
    alerts = []
    for fname in V2_FACTORS:
        ics, ic_dates = [], []
        for d in scan_days:
            pairs = [p for p in panels[fname].get(str(d), []) if p[1] is not None]
            if len(pairs) < 50:
                continue
            ic = spearman([p[0] for p in pairs], [p[1] for p in pairs])
            if ic is None:
                continue
            ics.append(ic); ic_dates.append(str(d))
        if len(ics) < 10:
            out_factors[fname] = {"status": "样本不足", "n_sections": len(ics)}
            continue
        mic = sum(ics) / len(ics)
        sic = (sum((x - mic) ** 2 for x in ics) / (len(ics) - 1)) ** 0.5 if len(ics) > 1 else 0.0
        ir = mic / sic if sic > 0 else 0.0
        gate_sign = GATE_IC_SIGN[fname]
        direction_flip = (mic * gate_sign) < 0     # 与门禁符号相反=方向翻转
        weak = abs(mic) < IC_MIN                    # 太弱
        alert = direction_flip or weak
        if alert:
            alerts.append(fname)
        out_factors[fname] = {
            "rolling20_ic_mean": round(mic, 4), "ic_std": round(sic, 4), "ir": round(ir, 3),
            "n_sections": len(ics), "window": [str(d) for d in ic_dates],
            "gate_sign": gate_sign, "direction_flip": direction_flip, "ic_too_weak": weak,
            "alert": alert,
        }
        print(f"  {fname:20s} IC={mic:+.4f} IR={ir:+.2f} 方向翻转={direction_flip} 太弱={weak} {'⚠️告警' if alert else '正常'}", flush=True)

    # ── 老五验收口径 + 防假绿守卫 (2026-09-27 P0 修复): 判定抽到 decide_exit_code() 纯函数 ──
    #    (tests/test_ic_monitor_guard.py 直接锁死该函数, 改回假绿 exit=0 会被回归打回)
    n_valid = sum(1 for f in V2_FACTORS if "rolling20_ic_mean" in out_factors.get(f, {}))
    exit_code = decide_exit_code(out_factors, alerts, alert_max=ALERT_MAX)
    advise = "建议 factor_v2.json enabled=false 回基线" if len(alerts) >= ALERT_MAX else (
        "⚠️全部因子无有效IC, 监控无效, 需排查根因" if exit_code == 4 else "单因子告警, 人工复核")
    out = {
        "note": "v2因子20日滚动IC生产监控 | 算术复用 factor_gate_v2.spearman_ic + 132d FACTOR_FUNCTIONS | 前向20d | 抽样步长2",
        "window": [str(start), str(end)], "horizon": HORIZON, "recent_sections": len(scan_days),
        "n_stocks": n_used, "generated": time.strftime('%Y-%m-%d %H:%M:%S'),
        "ic_min": IC_MIN, "alert_max": ALERT_MAX,
        "factors": out_factors,
        "n_valid_factors": n_valid,
        "alerts": alerts, "n_alerts": len(alerts),
        "advise": advise,
        "exit_code": exit_code,
    }
    dst = f"data/audit/factor_ic_rolling_20d_{time.strftime('%Y%m%d')}.json"
    atomic_dump(out, dst, ensure_ascii=False, indent=2, encoding="utf-8")
    print(f"\n💾 {dst} | 告警{len(alerts)}因子 {alerts} | {advise}", flush=True)
    print(f"=== IC监控完成 用时 {(time.time()-t0)/60:.1f}min exit={out['exit_code']} ===", flush=True)
    return out["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
