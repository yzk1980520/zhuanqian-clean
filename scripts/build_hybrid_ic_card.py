#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_hybrid_ic_card.py — C→A 混合 IC 卡重建 (老五数据面, @atomcode 修正1 形态)
===============================================================================
背景: 候选 132s 卡 (061aa417 修键, asof=10/23) valid 池=0 ≠ 权威 192s 卡 valid=6
     → A 放行对象不得直接推候选卡, 须双证混合卡:
       ① z 检坐实口径差件 (value_proxy/chg5/chg10, |z|<2) → 恢复 valid, IC/icir/weight 取权威值
       ② 候选池无同名件 NA 件 (price_reversal_5d/rsi_oversold/low_volatility) → fail-closed 保留权威值
       ③ vol_ratio (frozen→dead 池间移动, z 检面外) → 取候选值 (老五对照表"规则自洽"注记在案)
       ④ 其余因子池 → 取候选值
确定性: 同输入两次运行输出 SHA 相等 (无 wall-clock 字段)。
晋升 (覆盖权威源) 不走本脚本直推: --promote 需先经 @atomcode ③复核 + @总管 裁定,
     晋升时旧权威 append-only 归档 (factor_ic_latest_<ts>.json), 不删。
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTH = os.path.join(ROOT, "data", "factor_ic", "factor_ic_latest.json")
CAND = os.path.join(ROOT, "data", "factor_ic", "factor_ic_132d_refresh_20261024_214842.json")
ZCHK = os.path.join(ROOT, "data", "factor_ic", "zcheck_20261024.json")
OUT = os.path.join(ROOT, "data", "factor_ic", "factor_ic_hybrid_20261024.json")

FLIP3 = ("value_proxy", "chg5", "chg10")   # z 检坐实口径差件 → 恢复 valid 取权威值
NA3 = ("price_reversal_5d", "rsi_oversold", "low_volatility")  # NA → 保留权威值 fail-closed
VOl = ("vol_ratio",)                        # 池间移动件 → 取候选值


def build():
    a = json.load(open(AUTH, encoding="utf-8"))
    c = json.load(open(CAND, encoding="utf-8"))
    z = json.load(open(ZCHK, encoding="utf-8"))
    af = {f["name"]: f for f in a.get("factors", [])}
    cf = {f["name"]: f for f in c.get("factors", [])}
    zrows = {r["factor"]: r for r in z.get("rows", [])}

    names = sorted(set(af) | set(cf))
    out_f, evidence = [], []
    for n in names:
        A, C = af.get(n), cf.get(n)
        Z = zrows.get(n, {})
        if n in FLIP3 and A and Z.get("verdict") not in ("NA_missing_in_candidate", None) and abs(Z.get("z", 99)) < 2.0:
            row = dict(A)                      # 恢复 valid, 值取权威
            row["evidence"] = f"zcheck z={Z.get('z')}<2 坐实窗口口径差 → 恢复 valid 取权威值 (asof 对齐 {c.get('asof')})"
            row["evidence_ref"] = os.path.relpath(ZCHK, ROOT)
            out_f.append(row); evidence.append(f"{n}: z={Z.get('z')} → valid 恢复(权威值)")
        elif n in NA3 and A and Z.get("verdict") == "NA_missing_in_candidate":
            row = dict(A)                      # 无对证≠有证 → fail-closed 保留权威值
            row["evidence"] = "候选池无同名件 NA → fail-closed 保留权威值 (裁定权 @atomcode ③)"
            row["evidence_ref"] = os.path.relpath(ZCHK, ROOT)
            out_f.append(row); evidence.append(f"{n}: NA → 权威值保留")
        else:
            if n in VOl:
                row = dict(C) if C else (dict(A) if A else {"name": n})
                row["evidence"] = "frozen→dead 池间移动 (z 检面外), 老五对照表'规则自洽'注记在案 → 取候选值"
                out_f.append(row); evidence.append(f"{n}: 规则自洽 → 候选值(dead)")
            elif C:
                out_f.append(dict(C))
            elif A:
                row = dict(A)
                row["evidence"] = "仅权威池在件, 候选无对证 → 保留权威值 (池外件, 不进 valid 池)"
                out_f.append(row)

    valid_pool = [f for f in out_f if f.get("status") == "valid"]
    card = {"asof": c.get("asof"), "last_date": c.get("last_ic_date") or c.get("last_date"),
            "total_samples": c.get("total_samples"), "forward_days": c.get("forward_days"),
            "source": "hybrid_recon_v1 (权威 W1/192d valid 池 + 候选 pure_python_v10/132d 余件, @atomcode 修正1 形态)",
            "cards": {"authority": os.path.basename(AUTH), "candidate": os.path.basename(CAND),
                      "zcheck": os.path.basename(ZCHK)},
            "factors": out_f,
            "recon_evidence": evidence,
            "compliance": "混合卡=证据重建件; 晋升权威源须 @atomcode ③复核 + @总管 裁定; 权重件走 K45 评审循环"}
    return card


def main(argv):
    card = build()
    body = json.dumps(card, sort_keys=True, ensure_ascii=False, indent=1)
    _ = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if "--promote" in argv:
        raise SystemExit("[REFUSED] --promote 不直推: 须 @atomcode ③复核 + @总管 裁定后人工执行归档+覆盖 (append-only), 本脚本只产卡")
    open(OUT, "w", encoding="utf-8").write(body + "\n")
    n_valid = sum(1 for f in card["factors"] if f.get("status") == "valid")
    print(f"[hybrid] {os.path.relpath(OUT, ROOT)} | 因子池 {len(card['factors'])} | valid={n_valid} | asof={card['asof']}")
    for e in card["recon_evidence"]:
        print("  ", e)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
