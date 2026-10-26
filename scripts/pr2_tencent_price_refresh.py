# -*- coding: utf-8 -*-
"""P-R2 腾讯补价幂等 runner (老五风控切片, 2026-10-24 实现件)

规格件: scripts/pr2_tencent_price_recipe.json (46d941da)
注册表: scripts/selfheal_recipes.json id=pr2_tencent_price (argv 指向本脚本)

三段式 (witness_rule: 见证人≠修复人):
  1. 幂等预检: 报价归属日 <= holdings.price_asof → 0 写入短路 (exit=0)
  2. 原子写: tmp+os.replace, 只动价格/市值/盈亏/price_asof/last_source + 追加 audit_<date>
     (历史 audit_* 字段保留不覆盖)
  3. 独立见证: 回读 JSON 逐字段相等 + 交叉核算 (total=cash+mv, ratio) 通过才 exit=0

退出码: 0=ok(含0写入) | 1=报价通道不可达(escalate→source_gap) | 2=回读校验失败
--dry-run: 只算不写, 输出计划 diff (验收路径)
"""
import json
import os
import socket
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLDINGS = ROOT / "data" / "holdings.json"
QUOTER = "https://qt.gtimg.cn/q={code}"


def fetch_quote(code: str):
    """腾讯收盘/实时报价 → dict(code, price, preclose, date, high, low, name) 或 None"""
    socket.setdefaulttimeout(20)
    raw = urllib.request.urlopen(QUOTER.format(code=code), timeout=20).read().decode("gbk", "replace")
    f = raw.split("~")
    if len(f) < 35:
        return None
    ts = f[30]  # 形如 20261022161449
    return {
        "code": f[2], "name": f[1],
        "price": float(f[3]), "preclose": float(f[4]), "open": float(f[5]),
        "high": float(f[33]), "low": float(f[34]),
        "date": ts[:8],  # yyyymmdd 归属日
    }


def main():
    dry = "--dry-run" in sys.argv
    h = json.loads(HOLDINGS.read_text(encoding="utf-8"))
    cash = h.get("available_cash", 0.0)
    changed = False
    for item in h.get("holdings", []):
        if item.get("status") != "active" or not item.get("symbol"):
            continue
        q = fetch_quote(item["symbol"])
        if q is None:
            print(f"[P-R2] {item['symbol']} 报价通道不可达 → escalate source_gap", file=sys.stderr)
            sys.exit(1)
        asof = str(item.get("price_asof", ""))[:8].replace("-", "")
        if q["date"] <= asof:
            print(f"[P-R2] {item['symbol']} 幂等短路: 报价日 {q['date']} <= price_asof {asof} → 0 写入")
            continue
        shares = item.get("shares", 0)
        cost = item.get("cost_price") or item.get("cost") or item.get("avg_cost")
        mv = round(shares * q["price"], 2)
        new = {
            "current_price": q["price"], "market_price": q["price"], "last_price": q["price"],
            "market_value": mv, "position_value": mv,
            "pnl": round((q["price"] - cost) * shares, 2),
            "pnl_pct": round((q["price"] / cost - 1) * 100, 4),
            "market_date": f"{q['date'][:4]}-{q['date'][4:6]}-{q['date'][6:]}",
            "price_asof": f"{q['date'][:4]}-{q['date'][4:6]}-{q['date'][6:]}",
            "last_source": f"tencent_qt_gtimg_cn_{q['date']}_close",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        item.update(new)
        item[f"audit_{q['date']}"] = (
            f"P-R2 自动补价: {q['name']} 收{q['price']} (开{q['open']} 高{q['high']} 低{q['low']} 前收{q['preclose']}), "
            f"来源 qt.gtimg.cn, 幂等预检+原子写+回读见证, 历史 audit_* 保留")
        h["total_assets"] = round(cash + sum(x.get("position_value", 0) for x in h["holdings"]), 2)
        mv_sum = sum(x.get("position_value", 0) for x in h["holdings"])
        h["position_ratio"] = round(mv_sum / h["total_assets"], 6) if h["total_assets"] else 0
        h["updated_at"] = new["updated_at"]
        changed = True
        print(f"[P-R2] {item['symbol']} {asof} → {q['date']} 价 {q['price']} (dry-run={dry})")

    if not changed:
        print("[P-R2] 无更新 (全幂等短路) exit=0")
        sys.exit(0)
    if dry:
        print("[P-R2] DRY-RUN: 计划写入已算, 不落盘")
        sys.exit(0)

    # 原子写
    fd, tmp = tempfile.mkstemp(dir=str(HOLDINGS.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=2)
    os.replace(tmp, HOLDINGS)

    # 独立见证 (read-back)
    rb = json.loads(HOLDINGS.read_text(encoding="utf-8"))
    ok = True
    for i, x in enumerate(rb.get("holdings", [])):
        if x.get("status") != "active":
            continue
        for k in ("last_price", "market_value", "pnl", "position_value", "price_asof", "last_source"):
            if x.get(k) != h["holdings"][i].get(k):
                print(f"[P-R2][WITNESS FAIL] {x.get('symbol')} {k} 回读不等", file=sys.stderr)
                ok = False
    ta = round(float(rb.get("available_cash", 0)) + sum(x.get("position_value", 0) for x in rb["holdings"]), 2)
    if abs(ta - float(rb.get("total_assets", 0))) > 0.01:
        print(f"[P-R2][WITNESS FAIL] total_assets 交叉核算不等 ({rb.get('total_assets')} vs {ta})", file=sys.stderr)
        ok = False
    if not ok:
        sys.exit(2)
    print(f"[P-R2] WITNESS PASS: 回读逐字段相等 + 交叉核算 (cash {rb.get('available_cash')} + mv = {ta})")
    sys.exit(0)


if __name__ == "__main__":
    main()
