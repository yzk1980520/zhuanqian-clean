# -*- coding: utf-8 -*-
"""T1 (t_5457c400) 双源原子登记: 3 个新因子 -> data/factor_ic/factor_registry.json

AC3 双源登记: ① IC 数据真源 factor_ic_latest.json (t1_append_authority_card.py 追加)
             ② 注册元数据 factor_registry.json (本脚本, atomic_json.update_json 直写,
                不经 FactorRegistry 全量保存, 防扩展字段被洗 — 见 factor-registry 技能)

用法:
  python scripts/t1_register_factor_registry.py --run-card data/factor_ic/factor_ic_132d_refresh_<ts>.json
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

if "PYTHONPATH" in os.environ:
    del os.environ["PYTHONPATH"]

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import atomic_json  # noqa: E402

REG = ROOT / "data" / "factor_ic" / "factor_registry.json"

DEFS = {
    "RSRS_TREND": {
        "description": "RSRS 择时信号: 上证指数 close/open 比率 10 日 OLS 斜率 (全市场常数, "
                       "截面 IC 退化无定义, 如实记 dead; 序列证据 data/factor_ic/rsrs_trend_132d.json)",
        "direction": "market_timing",
        "notes": "T1 t_5457c400 入池: 截面退化属口径限制非实现缺陷, 择时消费另议",
    },
    "RESID_MOM_20": {
        "description": "行业中性残差动量: 20日收益对申万一级行业哑变量+1 回归残差 "
                       "(行业内去均值; 映射 data/industry_mapping.json, 2000股池可映射率73.7%)",
        "direction": "momentum",
        "notes": "T1 t_5457c400 入池: 市值中性出局 (TDX 无市值字段, 数据不出本机约束)",
    },
    "REV_5D": {
        "description": "5日反转候选: REV_5D = -(chg5), 与 factor_weights.json 既有 0.0 权重键 "
                       "chg5_rev/momentum_reversal 对应, 132d 再裁定方向",
        "direction": "reversal",
        "notes": "T1 t_5457c400 入池: 与存量 chg5 Spearman 互为镜像 (浮点秩汇总近似)",
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-card", required=True)
    args = ap.parse_args()

    run = json.load(open(args.run_card, encoding="utf-8"))
    fac = {f["name"]: f for f in run["factors"]}
    today = datetime.now().strftime("%Y-%m-%d")

    def _mut(d):
        reg = d.setdefault("registry", {})
        added = []
        for n, spec in DEFS.items():
            f = fac.get(n)
            if f is None:
                raise SystemExit(f"[FAIL] 运行卡缺 {n}")
            entry = reg.get(n) or {
                "name": n, "description": spec["description"],
                "direction": spec["direction"],
                "ic_threshold": 0.03, "ir_threshold": 0.3,
                "weight": 0, "status": "dead",
                "ic_history": [], "registered_at": today,
            }
            entry["description"] = spec["description"]
            entry["direction"] = spec["direction"]
            entry["weight"] = 0  # 本卡 D3: 权重定标留三方裁定, 注册 weight=0
            entry["status"] = f.get("status")
            entry["ic_mean"] = f.get("ic")  # 原始带符号 IC (负向因子填负值; RSRS=None)
            entry["icir_nw"] = f.get("icir_nw")
            entry["source"] = f"{run.get('source')} [t_5457c400 T1 双源登记]"
            entry["notes"] = spec["notes"]
            hist = entry.setdefault("ic_history", [])
            hist.append({"date": today, "ic": f.get("ic"),
                         "engine": run.get("source"),
                         "universe": run.get("universe_size")})
            if "registered_at" not in entry:
                entry["registered_at"] = today
            reg[n] = entry
            added.append(n)
        d["updated_at"] = datetime.now().isoformat()
        d["update_summary"] = (f"T1 t_5457c400 双源原子登记: 新增 {len(added)} 因子 "
                               f"({', '.join(added)}), weight=0 待三方裁定; "
                               f"engine={run.get('source')}")
        return d

    atomic_json.update_json(str(REG), _mut, default={})
    rb = json.load(open(REG, encoding="utf-8"))
    for n in DEFS:
        e = rb["registry"][n]
        print(f"[OK] {n}: status={e['status']} ic_mean={e['ic_mean']} icir_nw={e.get('icir_nw')}")
    print(f"registry 现 {len(rb['registry'])} 项, update_summary: {rb['update_summary'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
