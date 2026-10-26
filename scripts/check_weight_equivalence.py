#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T2 权重通道收敛 — 回测/实盘 z-score 权重等价检查 (2026-10-26, 老三)

任务单 T2 (R0): 回测链与实盘链的因子 z-score 权重源收敛到 factor_weights.json v2.6 (单一真源)。
本脚本为任务单步骤2的机判证据链: 对 >=20 只(股,日)对, 比较两条链路的 z-score 加权因子分:

  实盘路径 (live):   config_loader.get_factor_weights() → 仓库根 factor_weights.json (v2.6 单一真源)
  回测路径 (backtest): 收敛前 = 静态 STRATEGIES 表 (tdx_strategies.py, 旧通道);
                     收敛后 = config_loader.get_backtest_factor_weights() → 同一 factor_weights.json
  (静态表列始终保留, 作为收敛前历史证据打印)

z-score 公式 = 实盘 auto_live_pipeline.py L520-546 原样 (总体std / None→z=0 / std<1e-9→1.0 /
有效值<2 → z 全 0), 加权分 = Σ_{k: w_k≠0} w_k · z_k。

样本: data/history_daily/ 12 只 × 3 个扫描日 = 36 对 (>=20 达标)。
截面 z-score 在样本池内计算 (生产截面=全候选池; 本脚本用固定样本池保证可复现, 属文档化近似)。

退出码: 0 = 回测通道与实盘通道逐对 |差| < 0.01 (通道已收敛); 1 = 存在 >=0.01 差异 (通道仍分叉)。
"""
import json
import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

# ── 固定样本 (可复现; 均覆盖 3 个扫描日, 全历史>=2500根) ──
SAMPLE_STOCKS = [
    "sh600000", "sh600004", "sh600009", "sh600010", "sh600016", "sh600018",
    "sz000001", "sz000002", "sz000063", "sz000069", "sz000333", "sh600028",
]
SAMPLE_DATES = ["2024-06-28", "2025-06-30", "2026-06-30"]
HISTORY_DIR = os.path.join(PROJECT, "data", "history_daily")
THRESHOLD = 0.01


def _history_up_to(code, asof):
    """读 history_daily 截至 asof 的记录 (date <= asof, ISO 日期串直接可比较)"""
    p = os.path.join(HISTORY_DIR, code + ".json")
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        recs = json.load(f)
    out = [r for r in recs
           if isinstance(r, dict) and r.get("date")
           and str(r["date"])[:10] <= asof
           and r.get("close", 0) and r.get("open", 0) and r.get("high", 0) and r.get("low", 0)]
    return out or None


def cross_section_zscores(inds_list, factor_keys):
    """实盘同款 z-score 公式 (auto_live_pipeline L520-546 原样拷贝):
    总体标准差 / None→z=0 / 有效值<2 → 全0 / std<1e-9 → std:=1.0。
    返回 {factor_key: [z 与 inds_list 同序]}。
    """
    zs = {}
    for k in factor_keys:
        all_raw = []
        for inds in inds_list:
            v = inds.get(k) if isinstance(inds, dict) else None
            if v is None:
                all_raw.append(None)
            else:
                try:
                    all_raw.append(float(v))
                except (TypeError, ValueError):
                    all_raw.append(None)
        vals = [v for v in all_raw if v is not None]
        if len(vals) < 2:
            zs[k] = [0.0] * len(inds_list)
            continue
        mean_v = sum(vals) / len(vals)
        std_v = (sum((v - mean_v) ** 2 for v in vals) / len(vals)) ** 0.5
        std_v = std_v if std_v > 1e-9 else 1.0
        zs[k] = [0.0 if v is None else (v - mean_v) / std_v for v in all_raw]
    return zs


def weighted_factor_score(inds_list, weights, factor_keys):
    """Σ_{k: w_k≠0} w_k · z_k — 逐股 (与 inds_list 同序)。缺失键跳过 (权重=0, 不臆造)。"""
    zs = cross_section_zscores(inds_list, factor_keys)
    out = []
    for i, _ in enumerate(inds_list):
        s = 0.0
        for k in factor_keys:
            w = weights.get(k, 0.0)
            if w != 0:
                s += w * zs[k][i]
        out.append(s)
    return out


def backtest_channel_weights():
    """回测侧 z-score 权重通道 (T2 收敛点):
    收敛后 = config_loader.get_backtest_factor_weights() (读 factor_weights.json 单一真源);
    收敛前 = 静态 STRATEGIES 表 (旧通道, 本函数自动回退并打标)。
    返回 (weights_dict, label)。
    """
    try:
        from core.pipeline.config_loader import get_backtest_factor_weights
        return dict(get_backtest_factor_weights()), "收敛后通道 get_backtest_factor_weights() → factor_weights.json"
    except (ImportError, AttributeError):
        from core.scoring.tdx_strategies import STRATEGIES, load_strategy
        _s, name = load_strategy()  # config.json strategy=综合
        return dict(STRATEGIES[name]), "收敛前通道 静态 STRATEGIES['%s'] 表 (tdx_strategies.py)" % name


def main():
    from core.pipeline.config_loader import get_factor_weights
    from core.scoring.tdx_strategies import STRATEGIES, load_strategy

    # 三条权重通道
    w_live = get_factor_weights()  # factor_weights.json v2.6 单一真源 (实盘)
    w_bt, bt_label = backtest_channel_weights()
    _s, static_name = load_strategy()
    w_static = dict(STRATEGIES[static_name])

    print("=" * 78)
    print("T2 权重通道收敛 — z-score 等价检查 (股,日)对: %d 只 × %d 日 = %d 对" %
          (len(SAMPLE_STOCKS), len(SAMPLE_DATES), len(SAMPLE_STOCKS) * len(SAMPLE_DATES)))
    print("=" * 78)
    print("[实盘通道] get_factor_weights() → factor_weights.json v2.6, 非零权重: %s"
          % {k: v for k, v in w_live.items() if v != 0})
    print("[回测通道] %s, 非零权重(截取前8): %s" %
          (bt_label, {k: v for k, v in w_bt.items() if v != 0 and k in ("chg5", "chg10", "overnight_sum20", "momentum_20") or (v != 0 and k in w_live)}))
    print("[静态表]  STRATEGIES['%s'] 非零因子键数: %d (技术权重键不参与 z-score 通道比较, 无 z 值)"
          % (static_name, sum(1 for v in w_static.values() if v != 0)))

    # 权重源结构差异 (任务单步骤3: 识别分叉因子)
    live_nonzero = {k for k, v in w_live.items() if v != 0}
    static_nonzero = {k for k, v in w_static.items() if v != 0}
    print("-" * 78)
    print("[结构差异] v2.6 非零键 ∩ 静态表键: %s" % sorted(live_nonzero & static_nonzero))
    print("[结构差异] v2.6 非零键仅存在于 JSON (静态表缺失, 收敛前 z 无来源): %s" % sorted(live_nonzero - static_nonzero))
    print("[结构差异] 静态表非零键未进 v2.6 (收敛后权重=0 跳过): %s"
          % sorted(k for k in static_nonzero if w_live.get(k, 0) == 0)[:12], "...共",
          len([k for k in static_nonzero if w_live.get(k, 0) == 0]))

    from core.scoring.tdx_indicators import compute_indicators
    rows = []          # (date, code, z_static, z_bt, z_live)
    unavailable = {}   # factor_key → 全样本无值的键
    for d in SAMPLE_DATES:
        pairs = []
        for code in SAMPLE_STOCKS:
            recs = _history_up_to(code, d)
            if recs is None or len(recs) < 30:
                continue
            inds = compute_indicators(recs[-400:])  # 与回测 LOOKBACK_DAYS=400 同窗
            if inds is None:
                continue
            pairs.append((code, inds))
        if len(pairs) < 2:
            print(f"[警告] {d} 有效样本不足, 跳过")
            continue
        codes, inds_list = [p[0] for p in pairs], [p[1] for p in pairs]
        # 因子键 = 三通道非零键并集 ∩ 有实际 z 值来源的键 (缺失键跳过, 不臆造权重)
        union_keys = sorted((set(w_live) | set(w_bt) | set(w_static)))
        factor_keys = []
        for k in union_keys:
            if w_live.get(k, 0) == 0 and w_bt.get(k, 0) == 0 and w_static.get(k, 0) == 0:
                continue
            if any(isinstance(inds.get(k), (int, float)) and not isinstance(inds.get(k), bool)
                   for inds in inds_list):
                factor_keys.append(k)
            else:
                unavailable.setdefault(k, d)
        sc = weighted_factor_score(inds_list, w_static, factor_keys)
        sb = weighted_factor_score(inds_list, w_bt, factor_keys)
        sl = weighted_factor_score(inds_list, w_live, factor_keys)
        for i, code in enumerate(codes):
            rows.append((d, code, sc[i], sb[i], sl[i]))
        print(f"[截面] {d}: 样本 {len(codes)} 只, 参与 z 计算因子键 {len(factor_keys)} 个"
              + (f", 全样本无值键(跳过): {sorted(unavailable)}" if unavailable else ""))

    if unavailable:
        print("[结构差异] 非零权重键但样本全无 z 值 (两通道同置 0, 不构成差异): %s" % sorted(unavailable))

    print("-" * 78)
    print("%-11s %-9s | %12s | %12s | %12s | %8s" %
          ("日期", "代码", "z静态表", "z回测通道", "z实盘", "|回测-实盘|"))
    print("-" * 78)
    max_diff, worst = 0.0, None
    for d, code, sc_, sb_, sl_ in rows:
        diff = abs(sb_ - sl_)
        max_diff = max(max_diff, diff)
        if diff > 0.01 and worst is None:
            worst = (d, code, sb_, sl_)
        print("%-11s %-9s | %12.4f | %12.4f | %12.4f | %8.4f" % (d, code, sc_, sb_, sl_, diff))
    print("-" * 78)
    print(f"样本对数: {len(rows)} | 最大 |回测-实盘| 差: {max_diff:.4f} "
          f"(阈值 {THRESHOLD}) → 回测通道: {bt_label}")
    if max_diff < THRESHOLD:
        print("✅ 等价: 回测 z-score 通道与实盘 factor_weights.json 单一真源逐对一致 (diff < %s)" % THRESHOLD)
        return 0
    print("❌ 分叉: 回测 z-score 通道与实盘不一致, 最大差在 %s" % ((worst,) if worst else ("?",)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
