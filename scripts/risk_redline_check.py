# -*- coding: utf-8 -*-
"""P-R1 红线状态一致性断言 (老五风控合规切片, 2026-10-23 自愈引擎v1.0 认领件)

只读断言版: 三查 + 持仓红线, 输出与 carrier_check 同构 {pass, p0, p1, detail},
@老六 台账 schema 直接消费。check_all 集成随 10/26 批次 (Opencode P-B 统一接)。

三查 (读盘不写盘, 全部 fail-loud 报不出=告警非静默):
  R1 门禁口径三方一致: gate_check.py 代码态 (GATE_STRICT_RULE)
     ↔ factor_gate.json (valid_rule/cross_check.status) ↔ 脱钩即 P1
  R2 持仓红线: 每只 active 持仓 止损线缓冲<1% / 止盈线压线 / price_asof 停更>1d /
     单股集中度>50% → P1 (博迈科 0.67% 缓冲=已知事实, 台账消费为预期告警)
  R3 放行态证据: review_status.laowu_approved=true 必须存在 review_report 实物;
     且 gate_passed=false 时放行位需有 launch_status 拍板注记, 否则 P0 (疑似脱钩)
"""
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

GATE_CHECK_PY = PROJECT_ROOT / "scripts" / "gate_check.py"
FACTORS_GATE = PROJECT_ROOT / "data" / "factor_ic" / "factor_gate.json"
REVIEW_STATUS = PROJECT_ROOT / "data" / "review_status.json"
HOLDINGS = PROJECT_ROOT / "data" / "holdings.json"

BUFFER_P1 = 0.01   # 止损/止盈线缓冲 <1% → P1
STALE_DAYS_P1 = 1  # price_asof 停更 >1 交易日 → P1
CONC_P1 = 0.50     # 单股集中度 >50% → P1 (S3 日检红线)


def _read_json(p: Path, detail, level="P1"):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        detail.append(f"{level} missing:{p.name} (文件缺失=状态不可证, fail-loud)")
        return None
    except Exception as e:
        detail.append(f"{level} parse:{p.name} ({e})")
        return None


def parse_gate_code_state(path: Path = GATE_CHECK_PY):
    """读 gate_check.py 的 GATE_STRICT_RULE 代码态; 读不出=None(告警)。"""
    try:
        src = path.read_text(encoding="utf-8")
        m = re.search(r"^GATE_STRICT_RULE\s*=\s*(True|False)", src, re.M)
        if not m:
            return None
        return m.group(1) == "True"
    except Exception:
        return None


def evaluate(code_strict, gate_report, review_status, holdings, today=None):
    """纯逻辑层 (P-C2 对照组门禁: 合成输入各断言必须命中)。"""
    today = today or date.today()
    p0, p1, detail = [], [], []

    # ---------- R1 门禁口径三方一致 ----------
    json_strict = None
    if isinstance(gate_report, dict):
        vr = str(gate_report.get("valid_rule", ""))
        cc = (gate_report.get("cross_check") or {}).get("status")
        json_strict = vr.startswith("strict")
        if json_strict and cc != "in_effect":
            p1.append("gate: cross_check.status != in_effect 但 valid_rule=strict (文件内部脱钩)")
        elif not json_strict and cc == "in_effect":
            p1.append("gate: valid_rule 非 strict 但 cross_check.status=in_effect (文件内部脱钩)")
    if code_strict is None:
        p1.append("gate: GATE_STRICT_RULE 代码态不可解析 (gate_check.py 被改坏/缺常量)")
    elif json_strict is None:
        p1.append("gate: factor_gate.json 口径字段缺失 (脚本未跑过?)")
    elif code_strict != json_strict:
        p1.append(f"gate: 代码态(strict={code_strict}) ↔ 文件态(strict={json_strict}) 脱钩 — 口径翻转只改了一侧")

    # ---------- R3 放行态证据 (先算, R2 报告用) ----------
    gate_fail = isinstance(gate_report, dict) and gate_report.get("gate_passed") is False
    if isinstance(review_status, dict):
        approved = review_status.get("laowu_approved")
        if approved is True:
            rep = review_status.get("review_report")
            rep_path = (PROJECT_ROOT / rep) if rep else None
            if rep_path is None or not rep_path.exists():
                p1.append(f"release: laowu_approved=true 但 review_report 证据缺失/不可定位 ({rep})")
            if gate_fail:
                launch = str(review_status.get("launch_status", ""))
                if not launch.strip():
                    p0.append("release: 放行位=true 且 门禁FAIL 且 无 launch_status 拍板注记 (疑似脱钩, 需会签复核)")
                else:
                    detail.append(f"info release: 门禁FAIL下放行位=true — 拍板覆盖态 launch_status='{launch[:40]}' (S3 已知态)")
    elif review_status is None:
        p1.append("release: review_status.json 缺失/不可解析")

    # ---------- R2 持仓红线 ----------
    if isinstance(holdings, dict):
        hl = holdings.get("holdings", holdings.get("positions", []))
        if not hl:
            p1.append("holdings: 无 active 持仓记录 (空组合=状态不可证, 与 daily_review 失明同型)")
        for h in hl:
            if h.get("status") != "active":
                continue
            name = h.get("name", h.get("symbol", "?"))
            lp = h.get("last_price") or h.get("current_price")
            sl = h.get("stop_loss") or h.get("stop_loss_price") or (h.get("risk_control") or {}).get("stop_loss_price")
            if lp and sl:
                buf = (lp - sl) / lp
                if buf < BUFFER_P1:
                    p1.append(f"hold:{name} 止损缓冲 {buf*100:.2f}% < {BUFFER_P1*100:.0f}% (last={lp} stop={sl})")
            tl = (h.get("risk_control") or {}).get("trailing_tp") or {}
            lines = tl.get("lines") or []
            broken_key = [k for k in tl if k.startswith("broken_lines_asof_")]
            if broken_key and lp:
                asof_key = sorted(broken_key)[-1]
                broken = set(tl.get(asof_key, []))
                above = [x for x in lines if x > lp and x not in broken]
                nearest = min(above) if above else None
                if nearest and (nearest - lp) / nearest < BUFFER_P1:
                    p1.append(f"hold:{name} 压移动止盈线 {nearest} (距 {(nearest-lp)/nearest*100:.1f}%, {asof_key.split('_')[-1]} 口径)")
            pa = str(h.get("price_asof") or "")
            if pa:
                try:
                    days = (today - date.fromisoformat(pa)).days
                    if days > STALE_DAYS_P1:
                        p1.append(f"hold:{name} price_asof={pa} 停更 {days}d > {STALE_DAYS_P1}d")
                except ValueError:
                    p1.append(f"hold:{name} price_asof 格式不可解析: {pa}")
        pr = holdings.get("position_ratio")
        if pr is not None and pr > CONC_P1:
            p1.append(f"hold: 单股/总集中度 position_ratio={pr:.2f} > {CONC_P1} (S3 日检红线)")
    elif holdings is None:
        p1.append("holdings: holdings.json 缺失/不可解析")

    return {"pass": not p0 and not p1, "p0": p0, "p1": p1, "detail": detail}


def selftest():
    """P-C2 对照组门禁 (形态 b): 合成故障各断言必须命中, 健康基线必须全绿.

    纯逻辑层 (evaluate 不触盘), 每故障例断言预期标记出现, 健康例断言 p0=p1=0。
    任一断言不中 → exit=1 (对照组缺失/逻辑退化即被抓)。"""
    from datetime import date as _d
    today = _d.today()
    def iso(days_ago):
        from datetime import timedelta
        return (today - timedelta(days=days_ago)).isoformat()

    def healthy_holding():
        return {"position_ratio": 0.3, "holdings": [
            {"status": "active", "name": "H1", "last_price": 20.0,
             "stop_loss": 18.0, "price_asof": iso(0)}]}

    cases = []
    # 0) 健康基线: 全绿
    cases.append(("baseline", {
        "code": True,
        "gate": {"valid_rule": "strict", "cross_check": {"status": "in_effect"}, "gate_passed": True},
        "review": {"laowu_approved": False},
        "hold": healthy_holding(),
        "expect_pass": True,
    }))
    # 1) R1 口径脱钩: 代码态 False ↔ 文件态 strict(True) → P1
    cases.append(("R1_decoupled", {
        "code": False,
        "gate": {"valid_rule": "strict", "cross_check": {"status": "in_effect"}, "gate_passed": True},
        "review": {"laowu_approved": False},
        "hold": healthy_holding(),
        "expect_pass": False, "marker": "脱钩",
    }))
    # 2) R3 放行态脱钩: 门禁FAIL + 放行位true + 无 launch_status 拍板 → P0
    cases.append(("R3_release_decouple", {
        "code": True,
        "gate": {"valid_rule": "strict", "cross_check": {"status": "in_effect"}, "gate_passed": False},
        "review": {"laowu_approved": True},
        "hold": healthy_holding(),
        "expect_pass": False, "marker": "疑似脱钩",
    }))
    # 3) R2 止损缓冲<1%: last=20 stop=19.9 → P1
    cases.append(("R2_stop_buffer", {
        "code": True,
        "gate": {"valid_rule": "strict", "cross_check": {"status": "in_effect"}, "gate_passed": True},
        "review": {"laowu_approved": False},
        "hold": {"position_ratio": 0.3, "holdings": [
            {"status": "active", "name": "H2", "last_price": 20.0, "stop_loss": 19.9,
             "price_asof": iso(0)}]},
        "expect_pass": False, "marker": "止损缓冲",
    }))
    # 4) R2 price_asof 停更>1d → P1
    cases.append(("R2_stale_asof", {
        "code": True,
        "gate": {"valid_rule": "strict", "cross_check": {"status": "in_effect"}, "gate_passed": True},
        "review": {"laowu_approved": False},
        "hold": {"position_ratio": 0.3, "holdings": [
            {"status": "active", "name": "H3", "last_price": 20.0, "stop_loss": 18.0,
             "price_asof": iso(4)}]},
        "expect_pass": False, "marker": "停更",
    }))
    # 5) R2 单股集中度>50% → P1
    cases.append(("R2_concentration", {
        "code": True,
        "gate": {"valid_rule": "strict", "cross_check": {"status": "in_effect"}, "gate_passed": True},
        "review": {"laowu_approved": False},
        "hold": {"position_ratio": 0.6, "holdings": [
            {"status": "active", "name": "H4", "last_price": 20.0, "stop_loss": 18.0,
             "price_asof": iso(0)}]},
        "expect_pass": False, "marker": "集中度",
    }))

    results = []
    all_ok = True
    for name, c in cases:
        res = evaluate(c["code"], c.get("gate"), c.get("review"), c.get("hold"), today)
        ok = bool(res["pass"]) == c["expect_pass"]
        if "marker" in c:
            blob = " | ".join(res["p0"] + res["p1"])
            ok = ok and (c["marker"] in blob)
        results.append({"case": name, "hit": ok,
                        "p0": len(res["p0"]), "p1": len(res["p1"])})
        if not ok:
            all_ok = False
    out = {"domain": "redline_selftest", "pass": all_ok,
           "cases": results,
           "note": "P-C2 对照组(形态b): 6 例含健康基线+5 合成故障各断言命中"}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if all_ok else 1)


def main():
    if "--selftest" in sys.argv[1:]:
        selftest()
    detail_out = []
    code_strict = parse_gate_code_state()
    if code_strict is None:
        detail_out.append("P1 gate: GATE_STRICT_RULE 不可解析")
    gate_report = _read_json(FACTORS_GATE, detail_out)
    review_status = _read_json(REVIEW_STATUS, detail_out)
    holdings = _read_json(HOLDINGS, detail_out)
    res = evaluate(code_strict, gate_report, review_status, holdings)
    res["detail"] = detail_out + res["detail"]
    res["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()
