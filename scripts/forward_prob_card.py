#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
forward_prob_card.py — 买入后涨跌概率卡 (组件 3, 老五数据切片)
================================================================
@user 2026-10-24 需求件 "买入后趋势分析涨跌概率" 的数据面交付。

两层证据 (明示叠加, 不出单一"胜率%"数字 — 校准不可行, 样本有限):
  L1 自史基率层: 该股 "5日涨幅>=3%" 事件日后 5 日收益分布
     事件定义 (冻结口径, 2026-10-24 老五规格):
       事件日 = 日线 close 满足 close[i]/close[i-5] >= +3% 的日 i
       后5日  = close[i+4] / close[i] - 1
       窗口   = 全史 (库件全部 bars) + 近2年 (>=2024-10-01) 双口径
       计数   = 重叠事件独立计数 (n 不剔重)
     小样本闸: n<30 → L1 标"弱(小样本)"; n<10 → L1 只显均值不显占比
  L2 因子条件层: (10/25 WeeklyIC 新卡后并入, 本件先留接口)
     L2 硬依赖 = data/factor_ic/factor_ic_latest.json asof<=7d
     过期/缺失 → L2=null + reason_code=STALE_IC (fail-closed, 防过期卡误亮灯, 老三防过期卡规则)
     IR<0.3 因子贡献显式标"弱证据"; 失效触发: 因子 IC 连续20d<0.03 → L2 摘牌只留 L1

合规边界: 本件只读, 输出 JSON 证据卡供 board 消费; 不产生任何下单动作 (R0 订单权恒归 @user)。
确定性: 同输入两次运行 SHA256 相等 (无 wall-clock 字段, asof 取自数据) — 老三对照组①断言。

用法:
  python forward_prob_card.py sh600312              # 出卡 JSON (stdout)
  python forward_prob_card.py --selftest            # P-C2 形态 b: 合成仓确定性 + 过期卡拒渲染 + 锚值对照
  python forward_prob_card.py sh600312 --out x.json # 落盘
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "data", "history_daily")
IC_FILE = os.path.join(ROOT, "data", "factor_ic", "factor_ic_latest.json")

# 冻结口径 (2026-10-24 老五规格, 老三对照组②按此 4 条重算可比)
EVENT_TH = 0.03          # 事件日: 5日涨幅 >= +3%
FORWARD = 4              # 后5日 = close[i+4]
RECENT_SINCE = "2024-10-01"
L1_WEAK_N = 30          # n<30 弱(小样本)
L1_TINY_N = 10          # n<10 只显均值不显占比
L2_ASOF_MAX_DAYS = 7    # IC 卡 asof 鲜度闸


def _load_bars(code):
    p = os.path.join(HIST, f"{code}.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    rs = d if isinstance(d, list) else (d.get("records") or d.get("data") or [])
    rs = [r for r in rs if isinstance(r, dict) and r.get("close") and r.get("date")]
    rs.sort(key=lambda r: str(r["date"]))          # 读侧排序防御 (10/5 排序缺陷同源规则)
    return rs


def _pct(x):
    return round(x * 100, 2)


def _stats(vals):
    """均值/中位/P10/P95 + 亏钱占比 (vals=后5日收益 list, 确定性排序后分位, 无随机)"""
    import statistics as st
    n = len(vals)
    out = {"n": n, "mean_pct": _pct(st.mean(vals)) if n else None,
           "median_pct": _pct(st.median(vals)) if n else None}
    if n:
        s = sorted(vals)
        out["p10_pct"] = _pct(s[max(0, int(n * 0.10) - (1 if n > 1 else 0))])
        out["p90_pct"] = _pct(s[min(n - 1, int(n * 0.90))])
        out["neg_pct"] = round(100.0 * sum(1 for v in vals if v < 0) / n, 1)
    return out


def build_l1(code):
    """L1 自史基率层 — 冻结口径 4 条"""
    rs = _load_bars(code)
    if not rs or len(rs) < 10:
        return {"layer": "L1", "state": "NO_DATA", "reason_code": "NO_LIBRARY"}
    full, recent = [], []
    for i in range(5, len(rs) - FORWARD):
        chg5 = rs[i]["close"] / rs[i - 5]["close"] - 1
        if chg5 < EVENT_TH:
            continue
        fwd = rs[i + FORWARD]["close"] / rs[i]["close"] - 1
        full.append(fwd)
        if str(rs[i]["date"]) >= RECENT_SINCE:
            recent.append(fwd)
    full_s, rec_s = _stats(full), _stats(recent)
    weak = (full_s["n"] < L1_WEAK_N)
    tiny = (full_s["n"] < L1_TINY_N)
    card = {"layer": "L1", "state": "OK", "definition": {
        "event": f"close/close[-5]>={EVENT_TH:.0%}", "forward": f"close[i+{FORWARD}]",
        "windows": ["full_hist", f"recent_since_{RECENT_SINCE}"], "counting": "overlapping_events_independent"},
        "full_hist": full_s, "recent_2y": rec_s,
        "weak_small_sample": weak, "tiny_mean_only": tiny}
    if weak:
        card["note"] = f"L1 弱证据(小样本 n={full_s['n']}<30)" + ("; n<10 只显均值不显占比" if tiny else "")
    return card


def build_l2(asof_date):
    """L2 因子条件层 — 硬依赖 IC 卡; 过期/缺失 → fail-closed (STALE_IC)"""
    if not os.path.exists(IC_FILE):
        return {"layer": "L2", "state": "STALE_IC", "reason_code": "IC_MISSING", "value": None}
    ic = json.load(open(IC_FILE, encoding="utf-8"))
    last = str(ic.get("last_date", ""))
    # 鲜度: 简单自然日差 (10/25 WeeklyIC 新卡 asof=10/23 后此闸放行)
    from datetime import date
    def _d(s):
        p = s[:10].split("-")
        return date(int(p[0]), int(p[1]), int(p[2]))
    try:
        days = (_d(asof_date) - _d(last)).days
    except Exception:
        days = 999
    if days > L2_ASOF_MAX_DAYS or days < 0:
        return {"layer": "L2", "state": "STALE_IC", "reason_code": f"ASOF_GAP_{days}d", "value": None}
    factors = ic.get("factors", [])
    rows, weak_rows = [], []
    for f in factors:
        if f.get("status") != "valid":
            continue
        ir = abs(f.get("icir") or 0)
        row = {"factor": f["name"], "ic": f.get("ic"), "ir": f.get("icir"),
               "weight": f.get("weight"), "evidence": "strong" if ir >= 0.3 else "WEAK"}
        (weak_rows if ir < 0.3 else rows).append(row)
    return {"layer": "L2", "state": "OK", "ic_card_asof": last, "ic_samples": ic.get("total_samples"),
            "ic_source": ic.get("source"), "factors": rows + [dict(r, weak=True) for r in weak_rows],
            "note": "IR<0.3 因子显式标弱证据; 失效触发: IC 连续20d<0.03 → L2 摘牌只留 L1"}


def build_card(code, asof_date=None, with_l2=True):
    rs = _load_bars(code)
    asof = asof_date or (str(rs[-1]["date"]) if rs else "UNKNOWN")
    card = {"code": code, "asof": asof, "method_version": "v1.0-frozen-20261024",
            "l1": build_l1(code)}
    card["l2"] = build_l2(asof) if with_l2 else None
    card["compliance"] = "只读证据卡; 买卖动作恒归 @user R0; 不构成投资建议"
    return card


def _sha(card):
    return hashlib.sha256(json.dumps(card, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def main(argv):
    if "--selftest" in argv:
        # P-C2 形态 b: 确定性 + 锚值 + 过期卡拒渲染
        c1 = build_card("sh600312")
        c2 = build_card("sh600312")
        assert _sha(c1) == _sha(c2), "selftest FAIL: 同输入两次 SHA 不等 (确定性断言)"
        f, r = c1["l1"]["full_hist"], c1["l1"]["recent_2y"]
        assert f["n"] >= 1700 and abs(f["neg_pct"] - 52.6) <= 0.5, f"600312 全史锚 n/占比错位: {f['n']}/{f['neg_pct']}"
        assert r["n"] >= 125 and abs(r["neg_pct"] - 56.4) <= 0.5, f"600312 近2年锚错位: {r['n']}/{r['neg_pct']}"
        # 过期卡拒渲染: 无库代码 (动态挑一个确实不存在的码, 999xxx=指数meta 在库, 不可硬编码)
        import glob, re as _re
        have = set(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(HIST, "*.json")))
        fake = next(f for f in ("sh807001", "sh807002", "sz807003") if f not in have)
        stale = build_card(fake)
        assert stale["l2"]["state"] == "STALE_IC", "过期/缺失卡未 fail-closed"
        assert stale["l1"]["state"] == "NO_DATA"
        print(f"[selftest] PASS: 确定性 SHA={_sha(c1)[:12]} | 600312 全史 n={f['n']} neg={f['neg_pct']}% | 近2年 n={r['n']} neg={r['neg_pct']}% | STALE_IC fail-closed ✓")
        return 0
    code = next((a for a in argv if a.startswith(("sh", "sz", "bj"))), None)
    if not code:
        print(__doc__); return 2
    card = build_card(code)
    out = json.dumps(card, ensure_ascii=False, indent=1, sort_keys=True)
    if "--out" in argv:
        _op = argv[argv.index("--out") + 1]
        _opd = os.path.dirname(_op)
        if _opd:
            os.makedirs(_opd, exist_ok=True)   # 消费面目录不存在自创 (面板批消费防 FileNotFoundError)
        open(_op, "w", encoding="utf-8").write(out + "\n")
        print(f"[card] {code} asof={card['asof']} L1={card['l1']['state']} L2={card['l2']['state']} → {_op}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
