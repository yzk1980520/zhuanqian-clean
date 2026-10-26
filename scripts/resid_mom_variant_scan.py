# -*- coding: utf-8 -*-
"""Task A (t_db07d09b, 2026-10-26): RESID_MOM 族窗口扩展/变体 IC 复测

老三 · 只读取证: 复用 scripts/factor_ic_132d_refresh.py 的口径
(逐日截面 Spearman IC + Newey-West lag=5 + T1 行业去均值 hook),
仅测量, 不注册因子, 不碰权威源 factor_ic_latest.json。

变体:
  V0   RESID_MOM_20 @ 132d 窗口 (基线复算, 锚定 T1 权威卡 -0.0295 口径)
  V1a  RESID_MOM_20 @ 200d 窗口
  V1b  RESID_MOM_20 @ 300d 窗口
  V3   RESID_MOM_10 @ 132d 窗口 (占位=原始10日动量, 截面hook行业去均值,
       与 RESID_MOM_20 完全同构, 仅窗口 20->10)

口径与权威源一致: forward_days=5, min_bars=60, min_section=50,
universe=前 2000 只(与权威卡 universe_size=2000 对齐, 同 _load_universe 逻辑),
align=0, 阈值真源 core/scoring/factor_gate_v2.GATE_CONFIG (ic 0.03 / ir 0.3)。

数据件: data/history_daily 于 2026-10-26 06:13 离失, 已用本机 TDX 真源重建
(scripts/rebuild_history_daily_from_tdx.py), 报告内挂 data_as_of 与 engine_commit。

输出: data/audit/aa_resid_mom_variant_scan_20261026.json
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "data" / "audit" / "aa_resid_mom_variant_scan_20261026.json"

# ── 载入 refresh 模块 (作为库导入, 不触发 main) ──────────────────────────────
spec = importlib.util.spec_from_file_location(
    "f132", ROOT / "scripts" / "factor_ic_132d_refresh.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# 阈值真源 (m.exec_module 已把仓库根加入 sys.path)
GATE_CONFIG = m.GATE_CONFIG
IC_TH = GATE_CONFIG["ic_threshold"]
IR_TH = GATE_CONFIG["ir_threshold"]


def _momentum_10(c, o=None, h=None, l=None, v=None, a=None):
    """与 _momentum_20 同构, 窗口 10 日 (占位原始动量, hook 后为行业中性残差)"""
    if len(c) < 10:
        return None
    if c[-10] <= 0:
        return None
    return (c[-1] - c[-10]) / c[-10] * 100


def _patch_hook_for(fn_keys):
    """hook: RESID_MOM_20/RESID_MOM_10 整截面行业去均值; RSRS_TREND 保持原行为"""
    orig = m._t1_cross_section_hook

    def hook(cols, codes, d):
        if codes:
            for k in fn_keys:
                if k in cols:
                    cols[k] = m._t1_industry_demean(cols[k], codes)
        orig(cols, codes, d)

    m._t1_cross_section_hook = hook
    m._T1_HOOK_FACTORS = tuple(list(fn_keys) + ["RSRS_TREND"])


def _quantile_means(pairs_by_date, n_q=6):
    """逐截面日 6 分位平均前瞻收益(跨日再平均); pairs_by_date: [[(val, fwd)]]"""
    sums = [[] for _ in range(n_q)]
    for day_pairs in pairs_by_date:
        if len(day_pairs) < n_q:
            continue
        order = sorted(day_pairs, key=lambda p: p[0])
        k = len(order)
        for q in range(n_q):
            lo = (q * k) // n_q
            hi = ((q + 1) * k) // n_q
            if hi > lo:
                chunk = order[lo:hi]
                sums[q].append(sum(p[1] for p in chunk) / len(chunk))
    return [round(sum(s) / len(s), 4) if s else None for s in sums]


def run_variant(tag, factor_key, factor_fn, window_days, mono_key):
    dates = m._target_dates(m.__dict__["__universe__"], window_days)
    m.FACTOR_FUNCTIONS = {factor_key: factor_fn}
    ic_series, dates_with_ic, mono_pairs = m.compute(
        m.__dict__["__universe__"], dates, m.FORWARD_DAYS, m.MIN_SECTION,
        progress=False, mono_factors={mono_key})
    series = ic_series[factor_key]
    n = len(series)
    q6 = _quantile_means(mono_pairs[mono_key])
    stats = {"variant": tag, "window_days": window_days,
             "n_target_dates": len(dates),
             "date_range": [dates_with_ic[0], dates_with_ic[-1]] if dates_with_ic else None}
    if n >= m.MIN_IC_DATES:
        mean = sum(series) / n
        var = sum((x - mean) ** 2 for x in series) / n
        std = math.sqrt(var)
        icir = abs(mean) / std if std > 1e-12 else 0.0
        t_nw = m.newey_west_t(series, lag=m.FORWARD_DAYS)
        icir_nw = (t_nw / math.sqrt(n)) if (t_nw is not None and n > 0) else None
        q6_clean = [x for x in q6 if x is not None]
        stats.update({
            "n_dates": n,
            "ic": round(mean, 4),
            "ic_std": round(std, 4),
            "icir": round(icir, 4),
            "icir_nw": round(icir_nw, 4) if icir_nw is not None else None,
            "t_nw": round(t_nw, 4) if t_nw is not None else None,
            "ic_lag1_autocorr": (round(m.lag1_autocorr(series), 4)
                                 if m.lag1_autocorr(series) is not None else None),
            "q_means_6": q6,
            "q6_mono_up": (all(a <= b for a, b in zip(q6_clean, q6_clean[1:]))
                           if len(q6_clean) >= 2 else None),
            "q6_mono_down": (all(a >= b for a, b in zip(q6_clean, q6_clean[1:]))
                             if len(q6_clean) >= 2 else None),
            "ic_pass": abs(mean) >= IC_TH,
            "icir_nw_pass": (icir_nw is not None and abs(icir_nw) >= IR_TH),
            "verdict": "PASS" if (abs(mean) >= IC_TH) else "FAIL",
            "verdict_gate2": ("PASS" if ((abs(mean) >= IC_TH)
                                         and (icir_nw is not None and abs(icir_nw) >= IR_TH))
                              else "FAIL"),
        })
    else:
        stats.update({"n_dates": n, "ic": None, "verdict": "INSUFFICIENT_DATES",
                      "note": f"有效截面日 {n} < {m.MIN_IC_DATES}"})
    return stats


def main():
    import os
    import subprocess
    os.environ.pop("PYTHONPATH", None)
    # universe 钉扎: t_bbc3444e slot 口径 = 旧 2000 槽 ∩ 纯A股 (probe 件逐码留存)
    # 重建件(9606文件)中 _load_universe(2000) 的 slot 关闭点已漂移(bj/新上市文件入序),
    # 故钉扎到 T1 时代 2000 槽的 A 股子集, 与权威卡/纯度修复件可比; 缺失码如实记。
    probe_path = m.ROOT / "data" / "audit" / "aa_universe_probe_old_20261026.json"
    pin_codes = None
    if probe_path.exists():
        probe = json.load(open(probe_path, encoding="utf-8"))
        pin_codes = [c for c in probe.get("universe_codes", [])
                     if m._is_ashare_stock(c)]
    print(f"[1/4] 载入 universe ... (pin={len(pin_codes) if pin_codes else 'native'})")
    if pin_codes:
        H = m.HISTORY_DIR
        pin_set = set(pin_codes)
        pinned = {}
        for code in pin_set:
            fp = H / f"{code}.json"
            if not fp.exists():
                continue
            recs = json.load(open(fp, encoding="utf-8"))
            if not isinstance(recs, list) or len(recs) < m._MIN_BARS + m.FORWARD_DAYS + 1:
                continue
            recs = sorted(recs, key=lambda x: x.get("date", ""))
            pinned[code] = recs
        missing = pin_set - set(pinned)
        universe = pinned
        print(f"  pinned universe = {len(universe)} (T1 2000槽∩纯A股), 本地缺失 {len(missing)} 只: "
              f"{sorted(missing)[:10]}")
    else:
        missing = set()
        universe = m._load_universe(2000)  # 无 probe 件时的原生口径
    print(f"  universe_size = {len(universe)}")
    if not universe:
        print("[FAIL] 无历史数据"); return 2
    m.__dict__["__universe__"] = universe
    as_of = max(recs[-1].get("date", "") for recs in universe.values())

    # universe 组成诊断 (数据溯源: 重建后 bj/基金债券段是否混入截面)
    def _seg(c):
        return c[:5] if c.startswith("bj") else c[:4]
    comp = {}
    for c in universe:
        comp[_seg(c)] = comp.get(_seg(c), 0) + 1
    top_comp = dict(sorted(comp.items(), key=lambda kv: -kv[1])[:15])

    # V2: 行业映射覆盖率 — 三口径
    imap = m._t1_load_industry_map() or {}
    mapped = [c for c in universe if imap.get(c)]
    coverage = len(mapped) / len(universe)
    # 全池口径: history_daily 全部个股文件 (t_bbc3444e 纯度过滤层同规则: 纯A股白名单)
    H = m.HISTORY_DIR
    pool = [fp.stem for fp in H.glob("*.json")
            if fp.stem not in ("download_errors", "sh_index")
            and m._is_ashare_stock(fp.stem)]
    pool_set = set(pool)
    print(f"[2/4] 行业映射: universe {len(mapped)}/{len(universe)} = {coverage:.2%} | "
          f"全池 {len(pool_set & set(imap))}/{len(pool)} = {len(pool_set & set(imap)) / max(1, len(pool)):.2%} | "
          f"映射5220键本地可解析 {len(set(imap) & pool_set)}/{len(set(imap))}")

    results = []
    print("[3/4] 跑 IC 扫描 ...")
    fn20 = m.FACTOR_FUNCTIONS.get("RESID_MOM_20")  # 模块内占位 lambda (MOM_20)
    if fn20 is None:
        print("  [FAIL] RESID_MOM_20 占位函数缺失, 无法测量"); return 2
    _patch_hook_for(["RESID_MOM_20", "RESID_MOM_10"])
    for tag, key, fn, w, mono in (
        ("V0_RESID_MOM_20@132d_基线复算", "RESID_MOM_20", fn20, 132, "RESID_MOM_20"),
        ("V1a_RESID_MOM_20@200d", "RESID_MOM_20", fn20, 200, "RESID_MOM_20"),
        ("V1b_RESID_MOM_20@300d", "RESID_MOM_20", fn20, 300, "RESID_MOM_20"),
        ("V3_RESID_MOM_10@132d", "RESID_MOM_10", _momentum_10, 132, "RESID_MOM_10"),
    ):
        print(f"  扫描 {tag} ...")
        st = run_variant(tag, key, fn, w, mono)
        print(f"    ic={st.get('ic')} icir_nw={st.get('icir_nw')} "
              f"t_nw={st.get('t_nw')} -> {st.get('verdict')}")
        results.append(st)

    # 引擎 commit 回填 (git rev-parse --short HEAD, 本机读取)
    engine_commit = None
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, cwd=str(m.ROOT), timeout=30)
        if r.returncode == 0:
            engine_commit = r.stdout.strip()
    except Exception:
        pass
    print(f"[4/4] 落盘 + 引擎commit={engine_commit}")
    report = {
        "task": "t_db07d09b Task A (RESID_MOM 族窗口扩展/变体复测)",
        "engine_commit": engine_commit,
        "data_as_of": as_of,
        "data_source": "data/history_daily (TDX重建件, scripts/rebuild_history_daily_from_tdx.py)",
        "gate": {"ic_threshold": IC_TH, "ir_threshold": IR_TH,
                 "source": "core/scoring/factor_gate_v2.GATE_CONFIG"},
        "caliber": {
            "forward_days": m.FORWARD_DAYS, "min_bars": m.MIN_BARS,
            "min_section": m.MIN_SECTION, "align": 0,
            "universe_size": len(universe),
            "universe_pin": ("T1 2000槽∩纯A股 (aa_universe_probe_old_20261026.json, "
                             "t_bbc3444e slot 口径)" if pin_codes else "native _load_universe(2000)"),
            "native_note": ("重建件上 native _load_universe(2000) slot 关闭点漂移=1226只"
                           "(bj/新上市文件入序占槽), 故钉扎 T1 口径; 见 aa_resid_mom_variant_retest_t_db07d09b.md §7"),
            "pinned_missing_codes": sorted(missing) if pin_codes else [],
            "engine_tag": m.ENGINE_TAG,
            "hook": "T1 行业去均值 (resid = y - industry_mean(y), UNMAPPED_ASHARE/UNMAPPED 分组去均值)",
        },
        "industry_coverage": {
            "universe": {  # 钉扎 universe (T1 2000槽∩纯A股)
                "mapped": len(mapped), "universe": len(universe),
                "coverage": round(coverage, 4), "map_total_keys": len(imap),
                "verdict": "PASS(>=80%)" if coverage >= 0.80 else "FAIL(<80%)"},
            "full_pool": {  # 全池: history_daily 全部个股(剔指数/ETF)
                "local_pool": len(pool),
                "pool_mapped": len(pool_set & set(imap)),
                "pool_coverage": round(len(pool_set & set(imap)) / max(1, len(pool)), 4)},
            "mapping_availability": {  # 映射 5220 键在本机数据中的可解析数
                "map_total_keys": len(imap),
                "locally_resolvable": len(set(imap) & pool_set)},
        },
        "universe_composition_top15": top_comp,
        "variants": results,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"[OK] 结果 -> {OUT_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
