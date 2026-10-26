# -*- coding: utf-8 -*-
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""e_variant_checkpoint.py — E 变体观察期检查点判定 (2026-08-09)
按 docs/variant-DE-report.md 第九节预注册规则输出"接受/拒绝/继续观察"。

数据: trade_log.json 的 variant_reference(E, signal_return_pct 由 e_variant_backfill 回填)
      + 同日 A 推荐(type=recommendation, 信号收益用 _calc_signal_return 现算配对)
正号 = E 参考票 5日信号收益 > 同日 A 推荐票 5日信号收益

用法:
  python e_variant_checkpoint.py            # 输出检查点判定 (供 cron/日报)
  python e_variant_checkpoint.py demo       # 合成数据自检
"""
import os
import sys
import json
from datetime import datetime

PROJECT = os.path.dirname(os.path.abspath(__file__))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

from e_variant_backfill import _calc_signal_return

TRADE_LOG = os.path.join(PROJECT, "trade_log.json")


def load_e_references():
    """E 参考列表 (已回填 signal_return_pct 的, 日期升序) + 同日 A 配对收益"""
    data = json.load(open(TRADE_LOG, encoding="utf-8"))
    recs = data.get("recommendations", [])
    e_refs = [r for r in recs
              if r.get("type") == "variant_reference"
              and r.get("variant") == "E"
              and r.get("signal_return_pct") is not None]
    e_refs.sort(key=lambda r: str(r.get("date", "")))
    # 同日 A 推荐: {date: signal}
    a_by_date = {}
    for r in recs:
        if r.get("type") == "recommendation" and r.get("date"):
            a_by_date.setdefault(str(r.get("date")), []).append(r)
    rows = []
    for r in e_refs:
        d = str(r.get("date", ""))
        e_ret = r.get("signal_return_pct")
        a_ret = None
        for a in a_by_date.get(d, []):
            a_ret = _calc_signal_return(a.get("code", ""), d)  # A 侧现算配对
            if a_ret is not None:
                break
        rows.append({"date": d, "code": r.get("code"), "name": r.get("name", ""),
                     "e_ret": e_ret, "a_ret": a_ret,
                     "market_label": r.get("market_label", "")})
    return rows


def judge(rows):
    """按预注册规则判定 (docs/variant-DE-report.md 第九节)"""
    n = len(rows)
    if n == 0:
        return "观察期未开始 (0 笔 E 参考, 空仓日推荐后自动积累)", None
    valid = [r for r in rows if r["a_ret"] is not None]
    if len(valid) < min(n, 3):
        return "等待配对数据 (E 参考 %d 笔, 配对 %d 笔 — 需等 A 推荐 5 日后可算)" % (n, len(valid)), None
    signs = [1 if r["e_ret"] > r["a_ret"] else -1 for r in valid]
    diffs = [r["e_ret"] - r["a_ret"] for r in valid]
    pos = sum(1 for s in signs if s > 0)
    rate = pos / len(valid)
    mean_diff = sum(diffs) / len(diffs)
    detail = {"n": n, "paired": len(valid), "pos": pos, "pos_rate": round(rate, 2),
              "mean_diff": round(mean_diff, 2)}
    # 检查点 3/5/8/满10
    if n == 3:
        if rate == 1.0 and mean_diff > 0:
            return "接受E(3/3正, 进入小仓试点切换)", detail
        if rate == 0.0 and mean_diff < 0:
            return "拒绝E(3/3负, 维持A)", detail
    if n == 5:
        if pos >= 4 and mean_diff > 0:
            return "接受E(≥4/5正)", detail
        if pos <= 1:
            return "拒绝E(≤1/5正)", detail
    if n == 8:
        if pos >= 6 and mean_diff > 0:
            return "接受E(≥6/8正)", detail
        if pos <= 2:
            return "拒绝E(≤2/8正)", detail
    if n >= 10:
        if rate >= 0.7 and mean_diff > 0:
            return "接受E(正号率≥70%)", detail
        if rate < 0.4:
            return "拒绝E(正号率<40%)", detail
        return "延长观察至15笔", detail
    return "继续观察 (检查点未到: %d/10 笔, 正号率%.0f%% 平均差%+.2fpp)" % (n, rate * 100, mean_diff), detail


def main():
    print("=" * 56)
    print("  🔬 E变体观察期检查点 (预注册规则, docs/variant-DE-report.md)")
    print("=" * 56)
    rows = load_e_references()
    verdict, detail = judge(rows)
    if rows:
        print("E 参考 %d 笔:" % len(rows))
        for r in rows[-8:]:
            a = ("%+.2f%%" % r["a_ret"]) if r["a_ret"] is not None else "--"
            sign = "正" if (r["a_ret"] is not None and r["e_ret"] > r["a_ret"]) else ("负" if r["a_ret"] is not None else "?")
            print("  %s %s %s E=%+.2f%% A=%s [%s] 市:%s" % (
                r["date"], r["code"], r["name"][:6], r["e_ret"], a, sign, r["market_label"]))
    if detail:
        print("  配对=%d 正号=%d 正号率=%.0f%% 平均差=%+.2fpp" % (
            detail["paired"], detail["pos"], detail["pos_rate"] * 100, detail["mean_diff"]))
    print("\n判定: %s" % verdict)


def demo():
    """自检: 判定逻辑"""
    mk = lambda n, pos, mdiff: [{"e_ret": 3.0, "a_ret": 2.0}] * pos + [{"e_ret": 1.0, "a_ret": 2.0}] * (n - pos)
    # 3/3 正 → 接受
    v, d = judge(mk(3, 3, 0))  # mean_diff 合成需实际, 用模拟: 全部 e>a
    rows3 = [{"e_ret": 3.0, "a_ret": 2.0}, {"e_ret": 4.0, "a_ret": 2.0}, {"e_ret": 5.0, "a_ret": 2.0}]
    v3, _ = judge(rows3)
    assert "接受" in v3, v3
    # 3/3 负 → 拒绝
    rows3n = [{"e_ret": 1.0, "a_ret": 3.0}, {"e_ret": 1.5, "a_ret": 3.0}, {"e_ret": 2.0, "a_ret": 3.0}]
    v3n, _ = judge(rows3n)
    assert "拒绝" in v3n, v3n
    # 5 笔 3/5 正 → 继续
    rows5 = [{"e_ret": 3.0, "a_ret": 2.0}] * 3 + [{"e_ret": 1.0, "a_ret": 2.0}] * 2
    v5, _ = judge(rows5)
    assert "继续" in v5, v5
    # 空 → 未开始
    v0, _ = judge([])
    assert "未开始" in v0, v0
    print("demo OK: 检查点判定逻辑正确")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    else:
        main()
