# -*- coding: utf-8 -*-
"""
S3-10 P2 因子层 132日回测 runner（总管代做, 10-01）
────────────────────────────────────────────────────────
背景: 老三 atomcode 通道 10054 断连两轮, 熔断后 P3 规则总管代做。
红线合规:
  - 引擎零改动 (R0 线): 经 backtest_rotation.score_fn 注入通道 (T-20260816-006) 换评分, 不改 backtest_rotation.py / risk_rules.py
  - 统一退出模型: 4 变体同一 S3主候选 config (止损10% + TREND_TP_LADDER[up] + 追高CHASE_BAN_PCT + 120d), 只有评分不同 → 胜率差可归因因子层
  - sanity gate: 结果 json schema 对齐 check_backtest_sanity.py (CALIB_WINDOW 2021-01-04~2026-09-18), FAIL 禁引用
  - 数字守恒: 归一化全用固定参考界 (无样本内拟合, 无前视), 每个统计量落 json 可追
  - 异常不静默吞: score_fn 异常首现打 traceback + 计数, 超限大声告警 (与引擎 sc_fail 同口径)

口径裁决 (总管, 10-01, 落台账):
  任务单"132日全量" vs sanity gate CALIB_WINDOW(1386交易日):
  → 主回测窗口 = 全窗口 (gate 标定, 滚动窗口会被 gate 拒绝套用)
  → "近132交易日" = 全窗口交易明细按 buy_date 切末132日 作补充指标 (报告双报, 注明口径)

用法:
  python scripts/s3_10_p2_run.py --variants baseline,v2_lowvol_reversal,v3_dynamic,v4_interaction [--limit N] [--out PATH]
  --limit N: 冒烟用, 只跑前 N 只 (数据加载全量不可省, 评分/模拟全量)
"""
import sys, os, json, math, time, argparse
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import backtest.backtest_rotation as BR
import backtest as BT
import core.pipeline.atomic_json as atomic_json  # 2026-10-24 [t_laosan_r5_bare_import]: 原裸 import 只绑定 core, 下方 atomic_json.* 会 NameError, 补 as 别名
from risk_rules import CHASE_BAN_PCT, TREND_TP_LADDER

# ══════════════════════════════════════════════════════
#  因子池 (P1 清单 25 可算因子中, 引擎预计算 inds 直接可用的 10 个)
#  参考界 = 固定常数 (A股单票物理域), 无样本内拟合
#  dir: +1=值越高分越高, -1=值越低位 (负IC反转用法)
# ══════════════════════════════════════════════════════
FACTOR_REF = {
    # key: (lo, hi, 方向) — lo/hi 为 clip 参考界
    "pos_vs_ma20":  (-30.0, 30.0),   # 偏离MA20%, Phase1 IC5=-0.23 → 反转(低)
    "std20":        (0.0,  25.0),    # 20日波动%, Phase1 IC10=-0.33 → 低
    "vol_ratio":    (0.0,  4.0),     # 量比, Phase1 IC5=+0.10 → 高
    "rsi14":        (0.0,  100.0),   # Phase1 IC5=-0.16 → 低(均值回归)
    "vol_price_corr_20": (-1.0, 1.0),  # Phase1 IC5=-0.07 → 低
    "max_ret5":     (0.0,  20.0),    # T2 IC=-0.173 → 低
    "vol_shrink20": (0.0,  4.0),     # IC=-0.056 → 低
    "upside_vol_ratio": (-1.0, 1.0),  # 生产8分权重同源 → 高
    "alpha16_fix":  (-1.0, 1.0),     # -corr(high,vol,5) → 高
    "chg20":        (-40.0, 40.0),   # B10动量不可直接迁移 → 低(轮动均值回归假设, 报告注明)
}
CR_KEYS = {"chg5", "vol_ratio", "rsi14", "pos_vs_ma20", "max_ret5", "vol_shrink20"}  # 有截面rank的键
DIR = {"pos_vs_ma20": -1, "std20": -1, "vol_ratio": +1, "rsi14": -1,
       "vol_price_corr_20": -1, "max_ret5": -1, "vol_shrink20": -1,
       "upside_vol_ratio": +1, "alpha16_fix": +1, "chg20": -1}

def _fval(inds, key):
    v = inds.get(key)
    if v is None or not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return float(v)

def _unit(inds, cr, key):
    """因子 → [0,1] 方向化单位分 (值越大越好=已按DIR方向)。缺数据=None。
    优先用截面rank cr (6键), 其余用固定参考界 min-max (无拟合无前视)。"""
    if key in CR_KEYS and cr and key in cr:
        r = cr.get(key)
        if r is not None:
            return r if DIR[key] > 0 else (1.0 - r)
    v = _fval(inds, key)
    if v is None:
        return None
    lo, hi = FACTOR_REF[key]
    u = (max(lo, min(hi, v)) - lo) / (hi - lo)
    return u if DIR[key] > 0 else (1.0 - u)

# 异常计数 (不静默吞)
_score_fail = {"n": 0, "first": None}

def make_score_fn(w):
    """w: {key: 权重} → score_fn(code, inds, weekly, cr, ms) -> (sc, sigs_placeholder)
    缺失因子: 该因子权重按比例摊给其余可用因子 (因子退化不崩评分, 口径注明)"""
    total_w = sum(w.values())
    def fn(code, inds, weekly, cr, ms):
        acc, got = 0.0, 0.0
        for k, wt in w.items():
            u = _unit(inds, cr, k)
            if u is not None:
                acc += wt * u; got += wt
        if got <= 0:
            return 0.0, None
        sc = 60.0 * (acc / got)   # 0~60 统一量纲 (4变体同量纲可对照; min_score=-100 恒过门槛层)
        return sc, None
    # 包一层异常哨兵 (pick_candidates 内部 try/except 会把异常吞成 sc=0 — 必须在外层记)
    def guard(code, inds, weekly, cr, ms):
        try:
            return fn(code, inds, weekly, cr, ms)
        except Exception as e:
            _score_fail["n"] += 1
            if _score_fail["first"] is None:
                import traceback
                _score_fail["first"] = f"{code}: {e}\n{traceback.format_exc()}"
                print(f"⚠️ P2 score_fn 首次异常 ({code}): {e!r}", flush=True)
            if _score_fail["n"] % 500 == 0:
                print(f"⚠️ P2 score_fn 异常累计 {_score_fail['n']} 次 — 评分不可信!", flush=True)
            return 0.0, None
    return guard

W_V2 = {k: w for k, w in [   # V2 低波-反转交互 (10因子全权重, 和=1.00)
    ("pos_vs_ma20", .18), ("std20", .15), ("vol_ratio", .15), ("rsi14", .10),
    ("vol_shrink20", .08), ("max_ret5", .07), ("vol_price_corr_20", .08),
    ("upside_vol_ratio", .07), ("alpha16_fix", .05), ("chg20", .07)]}
def _v3_weights(ms):
    bullish = ms in ("牛", "强", "突破")
    if bullish:  # 动量-趋势组
        return {"chg20": .25, "vol_ratio": .25, "pos_vs_ma20": .15, "rsi14": .10,
                "upside_vol_ratio": .10, "std20": .15}
    return {  # 弱势/恐慌/未知 → 均值回归-低波组 (pos_vs_ma20/rsi14 反转方向)
        "pos_vs_ma20": .25, "std20": .25, "rsi14": .15,
        "vol_shrink20": .15, "max_ret5": .10, "vol_price_corr_20": .10}
def make_v3_score_fn():
    def fn(code, inds, weekly, cr, ms):
        w = _v3_weights(ms)
        total = sum(w.values())
        acc, got = 0.0, 0.0
        for k, wt in w.items():
            u = _unit(inds, cr, k)
            if u is not None:
                acc += wt * u; got += wt
        if got <= 0:
            return 0.0, None
        return 60.0 * (acc / got), None
    def guard(code, inds, weekly, cr, ms):
        try:
            return fn(code, inds, weekly, cr, ms)
        except Exception as e:
            _score_fail["n"] += 1
            if _score_fail["first"] is None:
                import traceback
                _score_fail["first"] = f"{code}: {e}\n{traceback.format_exc()}"
                print(f"⚠️ P2 V3 score_fn 首次异常 ({code}): {e!r}", flush=True)
            if _score_fail["n"] % 500 == 0:
                print(f"⚠️ P2 score_fn 异常累计 {_score_fail['n']} 次", flush=True)
            return 0.0, None
    return guard

def make_v4_score_fn():
    """V4 基线6因子cross-rank均值 + 交互项 (双低: max_ret5低×chg5低; 趋势确认: dif/dea>0)"""
    base6 = ["chg5", "vol_ratio", "rsi14", "pos_vs_ma20", "max_ret5", "vol_shrink20"]
    # 方向化: chg5低/pos_vs_ma20低(反转)/rsi14低/max_ret5低/vol_shrink20低 → 1-rank; vol_ratio高 → rank
    DIR4 = {"chg5": -1, "vol_ratio": +1, "rsi14": -1, "pos_vs_ma20": -1, "max_ret5": -1, "vol_shrink20": -1}
    def fn(code, inds, weekly, cr, ms):
        vals = {}
        for k in base6:
            r = cr.get(k) if (cr and k in cr) else None
            if r is not None:
                vals[k] = r if DIR4[k] > 0 else (1.0 - r)
        if len(vals) < 4:
            return 0.0, None
        base = sum(vals[k] for k in vals) / len(vals)
        # 交互: 双低 (max_ret5低 × chg5低) — 两个方向化rank相乘=双低共振
        inter = 0.0
        if "max_ret5" in vals and "chg5" in vals:
            inter = vals["max_ret5"] * vals["chg5"]
        # 趋势确认 (DIF>DEA 且 MACD柱>0)
        trend = 0.0
        dif, dea, hist = _fval(inds, "dif"), _fval(inds, "dea"), _fval(inds, "macd_hist")
        if None not in (dif, dea, hist):
            trend = (1.0 if dif > dea else 0.0) * (1.0 if hist > 0 else 0.0)
        std_u = _unit(inds, cr, "std20")
        comp = {"base6": base, "inter": inter, "trend": trend, "std20": std_u if std_u is not None else 0.5}
        sc = 60.0 * (0.55 * comp["base6"] + 0.25 * comp["inter"] + 0.10 * comp["trend"] + 0.10 * (1.0 - comp["std20"]))
        return sc, None
    def guard(code, inds, weekly, cr, ms):
        try:
            return fn(code, inds, weekly, cr, ms)
        except Exception as e:
            _score_fail["n"] += 1
            if _score_fail["first"] is None:
                import traceback
                _score_fail["first"] = f"{code}: {e}\n{traceback.format_exc()}"
                print(f"⚠️ P2 V4 score_fn 首次异常 ({code}): {e!r}", flush=True)
            if _score_fail["n"] % 500 == 0:
                print(f"⚠️ P2 score_fn 异常累计 {_score_fail['n']} 次", flush=True)
            return 0.0, None
    return guard

SCORE_FNS = {
    "baseline": None,  # 生产 score_stock (现行系统评分 = S3 39%胜率来源)
    "v2_lowvol_reversal": make_score_fn(W_V2),
    "v3_dynamic": make_v3_score_fn(),
    "v4_interaction": make_v4_score_fn(),
}
VARIANT_LABEL = {
    "baseline": "P2-基线对照-生产评分S3主候选退出",
    "v2_lowvol_reversal": "P2-V2低波反转交互10因子S3主候选退出",
    "v3_dynamic": "P2-V3市场状态动态权重S3主候选退出",
    "v4_interaction": "P2-V4基线6因子+交互项S3主候选退出",
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="baseline,v2_lowvol_reversal,v3_dynamic,v4_interaction")
    ap.add_argument("--limit", type=int, default=0, help="冒烟: 只取前N只")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "s3-10-p2-backtest-result.json"))
    a = ap.parse_args()
    variants = a.variants.split(",")
    assert all(v in SCORE_FNS for v in variants), f"未知变体: {variants}"

    t0 = time.time()
    # ── Step 1: 数据加载 + 指标预计算 (复刻 main() 同口径, 非R0) ──
    all_stocks = BT.collect_all_stocks()
    cache = BT.load_name_cache()
    stocks_data = {}
    for code, mkt in sorted(all_stocks.items()):
        name = cache.get(code, "")
        if BT.is_st_stock(name):
            continue
        tdx_records = BT.get_tdx_data(code, 3000)
        ext_records = BT.get_extended_data(code) or []
        if tdx_records is None:
            tdx_records = []
        if ext_records:
            ext_dates = {r["date"] for r in ext_records}
            tdx_history = [r for r in tdx_records if r["date"] not in ext_dates]
            records = (tdx_history + ext_records)
        else:
            records = tdx_records
        records.sort(key=lambda r: r["date"])
        records = [r for r in records
                   if (r["date"] if isinstance(r["date"], date) else date.fromisoformat(str(r["date"]))) >= date(2020, 3, 2)]
        if records and len(records) >= 30:
            stocks_data[code] = records
    if a.limit > 0:
        keep = sorted(stocks_data.keys())[:a.limit]
        stocks_data = {c: stocks_data[c] for c in keep}
    print(f"  ✅ 有效 {len(stocks_data)} 只 ({time.time()-t0:.0f}s)", flush=True)

    sh_records = BR.BT._load_sh_index_records(0)
    print(f"  ✅ 指数 {len(sh_records)} 条", flush=True)

    from backtest.backtest_fast_inds import fast_compute_all, build_sorted_index
    _timeline_keep = []
    for _r in sh_records:
        _d = _r["date"]
        if not isinstance(_d, date):
            _d = date.fromisoformat(str(_d))
        if BR.BACKTEST_START <= _d <= BR.BACKTEST_END:
            _timeline_keep.append(_d)
    _keep_dates = set(str(_timeline_keep[i]) for i in range(0, len(_timeline_keep), BR.SCAN_STEP))
    print(f"  📌 扫描日截面: {len(_keep_dates)} 天", flush=True)
    inds_cache = {}
    for i, (code, records) in enumerate(sorted(stocks_data.items()), 1):
        res = fast_compute_all(records, keep_dates=_keep_dates)
        if res:
            inds_cache[code] = res
        if i % 500 == 0:
            print(f"    预计算 {i}/{len(stocks_data)}", flush=True)
    sorted_codes, all_dates = build_sorted_index(inds_cache)
    print(f"  ✅ 预计算 {time.time()-t0:.0f}s, 指数 {time.time()-t0:.0f}s 段完成", flush=True)

    # ── Step 2: 逐变体模拟 (统一 S3主候选 退出模型, 只有 score_fn 不同) ──
    cfg_tmpl = dict(stop_pct=0.10, trailing={"ladder": TREND_TP_LADDER["up"]},
                    max_hold_days=120, chase_ban_pct=CHASE_BAN_PCT, min_score=-100)
    results = []
    for v in variants:
        cfg = BR.RotationConfig(VARIANT_LABEL[v], **cfg_tmpl)
        print(f"\n🔄 运行 {v} ({cfg.name})...", flush=True)
        tv0 = time.time()
        trades, eq = BR.simulate_rotation(stocks_data, cache, sh_records, cfg,
                                          pool=None, use_mp=False,
                                          score_fn=SCORE_FNS[v],
                                          inds_cache=inds_cache, all_dates=all_dates,
                                          sorted_codes=sorted_codes)
        s = BR.summarize(trades, eq, cfg)
        s["variant_id"] = v
        s["elapsed_s"] = round(time.time() - tv0, 1)
        results.append(s)
        if trades:
            print(f"  ✅ {s['trades']}笔 胜率{s['win_rate']:.1f}% 总收益{s['total_return_pct']:+.1f}% "
                  f"年化{s['annual_pct']:+.1f}% 回撤{s['max_drawdown_pct']:.1f}% 盈亏比{s['profit_factor']:.2f} "
                  f"({s['elapsed_s']}s)", flush=True)
        else:
            print(f"  ❌ {v}: 0笔成交 — sanity 必挂, 停下排查 (状态机冻结/评分全灭)", flush=True)

    # ── Step 3: 近132交易日补充口径 (从全窗口明细切, 非另开窗口回测) ──
    tl = [r["date"] for r in sh_records if BR.BACKTEST_START <= r["date"] <= BR.BACKTEST_END]
    win132_start = str(tl[-132]) if len(tl) >= 132 else str(tl[0])
    for s in results:
        tl132 = [t for t in s.get("trade_list", []) if str(t.get("buy_date", "")) >= win132_start]
        w = [t for t in tl132 if t["pnl"] > 0]
        s["win132"] = {
            "window": [win132_start, str(tl[-1])],
            "trades": len(tl132),
            "win_rate": round(len(w) / len(tl132) * 100, 1) if tl132 else None,
            "total_pnl": round(sum(t.get("pnl", 0) for t in tl132), 2) if tl132 else None,
        }

    # engine commit (与 main() L1210 同口径, 溯源引擎+参数同commit)
    _engine_commit = "unknown"
    try:
        import subprocess as _sp
        _r = _sp.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                     capture_output=True, text=True, timeout=10)
        if _r.returncode == 0 and _r.stdout.strip():
            _engine_commit = _r.stdout.strip()
        else:
            _engine_commit = "unknown(git_fail:%s)" % (_r.stderr.strip() or _r.returncode)
    except Exception as _ge:
        _engine_commit = "unknown(%s)" % _ge
    out = {
        "type": "rotation_backtest_s3_10_p2",
        "generated": str(date.today()),
        "engine_commit": _engine_commit,
        "window": [str(BR.BACKTEST_START), str(BR.BACKTEST_END)],
        "scan_step": BR.SCAN_STEP,
        "init_capital": BR.INIT_CAPITAL,
        "author": "总管代做 (老三atomcode 10054断连两轮, P3规则代做, 实名zongguan)",
        "p2_meta": {
            "factor_pool": list(FACTOR_REF.keys()),
            "factor_ref_bounds": FACTOR_REF,
            "factor_dir": DIR,
            "unified_exit": "S3主候选 (stop10% + TREND_TP_LADDER[up] + chase_ban + 120d), 仅评分不同",
            "win132_caliber": "全窗口回测明细按buy_date切末132交易日 (gate标定窗口不可滚动, 132日=补充口径)",
            "score_fail_count": _score_fail["n"],
            "score_fail_first": _score_fail["first"],
            "variants": {v: VARIANT_LABEL[v] for v in variants},
        },
        "results": results,
    }
    atomic_json.atomic_dump(out, a.out, ensure_ascii=False, indent=2, encoding="utf-8")
    print(f"\n💾 {a.out}  | 总耗时 {time.time()-t0:.0f}s | score_fn异常 {_score_fail['n']} 次", flush=True)
    if _score_fail["n"] > 0:
        pass
if __name__ == "__main__":
    main()
