#!/usr/bin/env python3
# 4 翻转因子 + 权威 6 valid 件全集 z 检 (老三, C→A 序列②, @atomcode 扩面修正件)
# 口径: z=(ic_a - ic_c)/sqrt(se_a^2 + se_c^2); se ≈ |ic|/|icir| (icir=ic/se 定义反推, icir≈0 记 se=inf 该件 NA)
# 判据 (@老五 冻结口径): |z|<2 = 窗口口径差 (A 混合卡: 该件恢复 valid, IC 取权威值) / ≥2 = regime 翻转 (确认 dead, 挂 regime 标记)
# 只读卡, 写 data/factor_ic/zcheck_20261024.json (供 @atomcode 复核+混合卡重建消费). 方法版注卡内.
import json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTH = ROOT / "data/factor_ic/factor_ic_latest.json"
CAND = ROOT / "data/factor_ic/factor_ic_132d_refresh_20261024_214842.json"
OUT = ROOT / "data/factor_ic/zcheck_20261024.json"

a = json.loads(AUTH.read_text(encoding="utf-8"))
c = json.loads(CAND.read_text(encoding="utf-8"))
fa = {f["name"]: f for f in a.get("factors", [])}
fc = {f["name"]: f for f in c.get("factors", [])}
valid_names = [n for n, f in fa.items() if f.get("status") == "valid"]
print(f"权威 valid 池 {len(valid_names)}: {valid_names}")

Z_TH = 2.0
rows = []
for name in valid_names:  # @atomcode 扩面: 权威 6 valid 全集 (含 4 翻转件)
    A, C = fa[name], fc.get(name)
    if C is None:
        print(f"{name}: NA (候选卡无此因子, 无法 z 检) → 混合卡保留权威值")
        rows.append({"factor": name, "verdict": "NA_missing_in_candidate", "keep": "auth"})
        continue
    ic_a, icir_a = A.get("ic"), A.get("icir") or 0.0
    ic_c, icir_c = C.get("ic"), C.get("icir") or 0.0
    se_a = abs(ic_a) / abs(icir_a) if icir_a else math.inf
    se_c = abs(ic_c) / abs(icir_c) if icir_c else math.inf
    na = math.isinf(se_a) or math.isinf(se_c)
    z = (ic_a - ic_c) / math.sqrt(se_a ** 2 + se_c ** 2) if not na else float("nan")
    verdict = "NA_se_inf" if na else ("caliber_gap" if abs(z) < Z_TH else "regime_flip")
    keep = "auth" if verdict in ("caliber_gap", "NA_se_inf") else "dead"
    rows.append({"factor": name, "ic_auth": ic_a, "ic_cand": ic_c, "n_auth": A.get("sample_size"),
                 "n_cand": C.get("sample_size"), "z": None if na else round(z, 3),
                 "abs_z_lt_2": verdict == "caliber_gap", "verdict": verdict, "keep": keep,
                 "note": f"status {A.get('status')}->{C.get('status')}"})
    print(f"{name}: {A.get('status')}->{C.get('status')} ic {ic_a}->{ic_c} z={z if not na else 'NA'} "
          f"|z|<2={verdict=='caliber_gap'} => {'恢复valid(权威值)' if keep=='auth' else '确认dead(regime标记)'}")

n_cal = sum(1 for r in rows if r.get("verdict") == "caliber_gap")
n_reg = sum(1 for r in rows if r.get("verdict") == "regime_flip")
payload = {
    "method": "z=(ic_a-ic_c)/sqrt(se_a^2+se_c^2), se=|ic|/|icir| (icir 定义反推, 卡内无 ic_std 字段)",
    "threshold": Z_TH, "cards": {"auth": str(AUTH.name), "cand": str(CAND.name),
                                  "auth_asof": a.get("asof") or "last=10/21(卡内 asof 缺失)",
                                  "cand_asof": c.get("asof")},
    "rows": rows,
    "summary": {"valid_set": len(valid_names), "caliber_gap": n_cal, "regime_flip": n_reg,
                "na": len(rows) - n_cal - n_reg},
    "engine_commit": "zcheck_20261024 (老三)", "date": "2026-10-24",
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"\nsummary: 口径差={n_cal} regime翻转={n_reg} NA={len(rows)-n_cal-n_reg} | 出 {OUT.relative_to(ROOT)}")
print(f"A 放行条件机械面: 全 口径差/NA -> 混合卡=权威 valid 全保留 (A 强); 任一 regime_flip -> 该件挂 regime 标记")
