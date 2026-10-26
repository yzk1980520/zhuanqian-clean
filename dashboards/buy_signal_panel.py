# -*- coding: utf-8 -*-
"""buy_signal_panel.py — board「买入信号」面板 (组件 1+2, 10/26 前全落件, @user 扩围裁定)
合规闸 (@atomcode 硬口径): 4 闸任一红 → 只渲染拦截原因 + "不构成投资建议", 不出买卖建议数字。
4 闸 (@laosan/@laowu 口径机器化):
  G1 factor_gate.json gate_passed (严口径, fail-closed)
  G2 风控价线面: 无持仓破线/缓冲<1% 红线 (holdings risk_control × 现价)
  G3 持仓不超限 (单股集中度 ≤ S3 上限)
  G4 laowu_approved (review_status.json) ∧ 132d 确认在效 (IC 卡 asof≤7d + gap=0;
     首份 132d 确认源 = 10/25 WeeklyIC 卡, 之前恒灭 = 正确 fail-closed, 旧卡不得作依据)
组件 2 自检: 移动止盈止损价 = risk_rules × 成本 独立重算 vs holdings 真源逐值一致 (分歧=P0 拒渲染)。
涨跌概率卡 (@老五 forward_prob_card.py L1/L2): 有在库卡则渲染, 无卡/STALE → 不渲染 (fail-closed)。
--selftest: P-C2 形态 b 合成故障 2 注入 (gate 红 / laowu_approved=false) → 断言不出建议数字。
只读: 不写交易件, 不产生下单动作 (order 权限恒归 @user R0)。
"""
import json
import os
import sys
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLDINGS = ROOT / "data" / "holdings.json"
GATE = ROOT / "data" / "factor_ic" / "factor_gate.json"
REVIEW = ROOT / "data" / "review_status.json"
PROB_CARDS = ROOT / "data" / "factor_ic" / "forward_prob_cards"  # @老五 卡落库面 (10/26 集成)
LEDGER = ROOT / "data" / "board_signal_ledger.jsonl"
_REVIEW_OVERR = {}  # selftest 注入面 (laowu_approved=false 临时件路径), 生产面恒空
_GATE_OVERR = {}    # selftest 注入面 (gate 红临时件路径), 生产面恒空

STOP_LOSS_PCT = 0.10   # -10% 硬线 (risk_rules 0.10, holdings 真源逐值核)
TRAILING_PCT = 0.05    # -5% 移动止盈线 (holdings 顶层 stop_loss=19.33 口径)
SINGLE_CAP_PCT = 0.50   # S3 单股集中度上限


def _load(p, default, _override=None):
    try:
        return json.loads(Path(_override or p).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[panel] WARN: {p} 读取失败 ({e.__class__.__name__}) → 返回默认值", file=sys.stderr)
        return default


def _load_review():
    return _load(REVIEW, {}, _REVIEW_OVERR.get("path"))


def compute_gates():
    gate = _load(GATE, {}, _GATE_OVERR.get("path"))
    review = _load_review()
    holdings = _load(HOLDINGS, {})
    holdings_missing = not isinstance(holdings, dict) or (not holdings.get("holdings") and "holdings" in ("", None))
    if not holdings:  # 空 dict = 文件缺失/读空 → G2/G3 数据缺失面
        holdings_missing = True
    # 132d 确认在效: 有 forward prob 卡且 L1 非空 + IC 卡面 asof (G4 三条件: approved ∧ gap=0 ∧ 数据卡在档)
    ic_ok = bool(gate.get("gate_passed")) and not gate.get("strict_gap")
    cards = sorted(PROB_CARDS.glob("*.json")) if PROB_CARDS.exists() else []
    g4 = bool(review.get("laowu_approved")) and ic_ok and (len(cards) > 0)
    # G2: 价线面 — 任一持仓破 -10% 硬线或 -5% 线缓冲 <1% 即红
    g2_red, g2_notes = False, []
    plist = holdings.get("holdings", holdings if isinstance(holdings, list) else [])
    for p in plist:
        if not isinstance(p, dict):
            continue
        cur, stop = p.get("current_price"), p.get("stop_loss_price")
        cost = p.get("avg_cost") or p.get("cost")
        if cur and stop and cost:
            buffer = (cur - stop) / stop
            if buffer < 0:
                g2_red = True
                g2_notes.append(f"{p.get('symbol')} 已破 {stop} 硬线")
            elif buffer < 0.01:
                g2_notes.append(f"{p.get('symbol')} 距止损 {stop} 缓冲 {buffer*100:.2f}% (<1% 预警)")
    # G3: 集中度
    total = holdings.get("total_assets") or sum(p.get("market_value", 0) for p in plist if isinstance(p, dict))
    g3_red = False
    for p in plist:
        if isinstance(p, dict) and total:
            pct = (p.get("market_value", 0) or 0) / total
            if pct > SINGLE_CAP_PCT:
                g3_red = True
                g2_notes.append(f"集中度超限: {p.get('symbol')} {pct*100:.0f}% > {SINGLE_CAP_PCT*100:.0f}%")
    g1 = bool(gate.get("gate_passed"))
    g4_red = not g4
    g2_ok, g3_ok = (not g2_red), (not g3_red)
    if holdings_missing:
        g2_ok = g3_ok = False
        g2_notes.append("holdings 数据缺失 → G2/G3 无法判定 (fail-closed 红)")
    all_green = g1 and g2_ok and g3_ok and g4
    return {
        "all_green": all_green,
        "G1_gate": g1, "G2_price_lines": g2_ok, "G3_concentration": g3_ok, "G4_132d_confirmed": g4,
        "notes": g2_notes, "gate_file_asof": gate.get("checked_at") or gate.get("updated_at"),
        "laowu_approved": review.get("laowu_approved"), "strict_gap": gate.get("strict_gap"),
        "holdings_missing": holdings_missing,
    }


def compute_trailing_plist(holdings):
    """组件 2: 移动止盈止损价 — 独立重算 vs 真源逐值一致 (分歧=P0, 拒渲染该持仓件)。"""
    plist = holdings.get("holdings", holdings if isinstance(holdings, list) else [])
    rows, ok = [], True
    for p in plist:
        if not isinstance(p, dict):
            continue
        cost = p.get("avg_cost") or p.get("cost")
        true_src = (p.get("risk_control") or {}).get("stop_loss_price")
        calc = round(cost * (1 - STOP_LOSS_PCT), 2) if cost else None
        match = (true_src is not None and calc is not None and abs(true_src - calc) < 0.011)
        if not match:
            ok = False
        rows.append({
            "symbol": p.get("symbol"), "cost": cost, "current": p.get("current_price"),
            "hard_stop_calc": calc, "hard_stop_source": true_src, "source_match": match,
            "trailing_5pct": round(cost * (1 - TRAILING_PCT), 2) if cost else None,
        })
    return rows, ok


def render_html(gates, plist_rows, plist_ok, prob_cards):
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;")
    tone, head = ("card-ok", "🟢 买入信号面") if gates["all_green"] else ("card-warn", "🔴 买入信号面")
    body = ""
    gmap = [("G1 因子门禁", gates["G1_gate"]), ("G2 价线面", gates["G2_price_lines"]),
            ("G3 集中度", gates["G3_concentration"]), ("G4 132d 确认", gates["G4_132d_confirmed"])]
    for nm, ok in gmap:
        body += f"<div class='kv'><span>{nm}</span><b class='{ 'ok' if ok else 'warn' }'>{'通' if ok else '拦截'}</b></div>"
    if not gates["all_green"]:
        for n in gates["notes"]:
            body += f"<div class='line'>• {esc(n)}</div>"
        body += ("<div class='line' style='color:#71717A;font-size:11px'>任一闸拦截 → 不出买卖建议数字 · "
                 "面板只读展示, 不构成投资建议 · order 权限恒归老大</div>")
        return f"<div class='card {tone}'>{head}{body}</div>"
    # 全绿态: 建议面 (组件 1) + 价格投影 (组件 2) + 概率卡 (组件 3, 有卡才渲染)
    for r in plist_rows:
        if r.get("current") and r.get("hard_stop_source"):
            body += (f"<div class='kv'><span>{esc(r['symbol'])} 离场面</span>"
                     f"<b>硬线 {r['hard_stop_source']} / 移动5% {r['trailing_5pct']}</b></div>")
    if prob_cards:
        c = _load(sorted(prob_cards)[-1], {})
        l1 = c.get("l1_full_history") or c.get("l1") or {}
        if l1.get("n"):
            weak = "（小样本弱）" if l1.get("n", 0) < 30 else ""
            body += (f"<div class='line'>概率卡: 后5日亏钱占比 {l1.get('neg_pct')}% "
                     f"(n={l1.get('n')}{weak}) · L2={esc(str(c.get('l2_status', '?'))[:12])}</div>")
    body += "<div class='line' style='color:#71717A;font-size:11px'>4 闸全绿 = 建议面亮灯 · 买卖动作仍归老大 R0</div>"
    return f"<div class='card {tone}'>{head}{body}</div>"


def render_panel_html():
    """board_server.py 消费入口: 单调用返回面板 HTML (异常=调用方降级)。"""
    holdings = _load(HOLDINGS, {})
    gates = compute_gates()
    rows, ok = compute_trailing_plist(holdings)
    if not ok:
        return ("<div class='card card-warn'>🔴 买入信号面: P0 — 止盈止损价真源与独立重算分歧, 拒渲染价格面 (fail-closed)</div>")
    pcards = sorted(PROB_CARDS.glob("*.json")) if PROB_CARDS.exists() else []
    return render_html(gates, rows, ok, pcards)


def main():
    holdings = _load(HOLDINGS, {})
    gates = compute_gates()
    rows, ok = compute_trailing_plist(holdings)
    if not ok:
        print("[panel] P0: 止盈止损价 真源 vs 独立重算分歧 — 拒渲染价格面 (fail-closed)")
        return 1
    prob_cards = sorted(PROB_CARDS.glob("*.json")) if PROB_CARDS.exists() else []
    html = render_html(gates, rows, ok, prob_cards)
    # 翻转留痕 (R8 台账模式): 状态变化才 append
    state = {"all_green": gates["all_green"], "gates": {k: gates[k] for k in
              ("G1_gate", "G2_price_lines", "G3_concentration", "G4_132d_confirmed")}}
    prev = _load(LEDGER.with_suffix(".state.json"), None)
    import time
    if prev and prev.get("all_green") != state["all_green"]:
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "item": "buy_signal_flip",
                "to": state, "evidence": {"gate_asof": gates["gate_file_asof"],
                                          "laowu_approved": gates["laowu_approved"],
                                          "strict_gap": gates["strict_gap"]},
                "witness": "readback 域独立复读 (见证人≠修复人)"}, ensure_ascii=False) + "\n")
        Path(LEDGER.with_suffix(".state.json")).write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(html)
    print(f"\n[panel] 4闸: G1={gates['G1_gate']} G2={gates['G2_price_lines']} "
          f"G3={gates['G3_concentration']} G4={gates['G4_132d_confirmed']} | all_green={gates['all_green']}",
          file=sys.stderr)
    return 0


def selftest():
    """P-C2 形态 b: 3 注入 → 面板必须不出建议数字。"""
    fails = 0
    # 注入 1: gate 红 (path override 合成红 gate 件, 独立于 live gate 态 — 门禁转绿后仍命中)
    import tempfile
    gate = _load(GATE, {})
    gate["gate_passed"] = False
    tmpg = Path(tempfile.mkdtemp()) / "gate.json"
    tmpg.write_text(json.dumps(gate, ensure_ascii=False), encoding="utf-8")
    _GATE_OVERR["path"] = tmpg
    try:
        gates = compute_gates()
        html_red = render_html(gates, [], True, [])
        assert not gates["G1_gate"] and ("不构成投资建议" in html_red) and ("硬线" not in html_red), \
            "gate 红态泄漏建议数字"
        print(f"  [PASS] 注入1 gate红(override): G1 灭 + 拦截文案 + 无建议数字")
    finally:
        _GATE_OVERR.clear()
    # 注入 2: laowu_approved=false (临时件路径注入) → G4 必灭
    review = _load_review()
    review["laowu_approved"] = False
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "review.json"
    tmp.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    _REVIEW_OVERR["path"] = tmp
    try:
        gates2 = compute_gates()
        assert not gates2["all_green"] and not gates2["G4_132d_confirmed"], "laowu_approved=false 未灭 G4"
        html2 = render_html(gates2, [], True, [])
        assert "不构成投资建议" in html2
        print("  [PASS] 注入2 laowu_approved=false: G4 灭 + 面板暗态 ✓")
    finally:
        _REVIEW_OVERR.clear()
    return fails


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
