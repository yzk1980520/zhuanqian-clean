# -*- coding: utf-8 -*-
"""T1 (t_5457c400) 权威卡原子追加: 3 个新因子条目 -> data/factor_ic/factor_ic_latest.json

契约: 只追加 (factors 列表 + diagnostics), 绝不改动/覆盖既有 71 条目与既有字段;
atomic_json.update_json 原子写 + 写后读回断言 (既有条目数/哈希不变)。

用法:
  python scripts/t1_append_authority_card.py --run-card data/factor_ic/factor_ic_132d_refresh_<ts>.json
       [--q6 data/factor_ic/factor_ic_q6_t1_20261026.json]
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

if "PYTHONPATH" in os.environ:
    del os.environ["PYTHONPATH"]

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import atomic_json  # noqa: E402

AUTH = ROOT / "data" / "factor_ic" / "factor_ic_latest.json"
NEW = ("RSRS_TREND", "RESID_MOM_20", "REV_5D")


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-card", required=True, help="本次 dry-run 产出的 ts 卡")
    ap.add_argument("--q6", default="data/factor_ic/factor_ic_q6_t1_20261026.json")
    args = ap.parse_args()

    run = json.load(open(args.run_card, encoding="utf-8"))
    new_factors = {f["name"]: f for f in run["factors"] if f["name"] in NEW}
    missing = [n for n in NEW if n not in new_factors]
    if missing:
        print(f"[FAIL] 运行卡缺新因子: {missing}")
        return 2
    q6 = {}
    q6_path = ROOT / args.q6
    if q6_path.exists():
        q6 = json.load(open(q6_path, encoding="utf-8")).get("factors", {})

    before = json.load(open(AUTH, encoding="utf-8"))
    before_names = [f["name"] for f in before["factors"]]
    before_diag_keys = sorted((before.get("diagnostics") or {}).keys())
    before_blob = json.dumps(before, ensure_ascii=False, sort_keys=True)
    before_hash = _sha_of = hashlib.sha256(before_blob.encode("utf-8")).hexdigest()[:16]
    print(f"追加前: {len(before['factors'])} 因子, 诊断 {len(before_diag_keys)} 项, 内容指纹 {before_hash}")

    entries_added = []

    def _mut(d):
        names = {f["name"] for f in d["factors"]}
        for n in NEW:
            if n in names:
                continue  # 幂等: 已有则不重复追加
            f = new_factors[n]
            diag = (run.get("diagnostics") or {}).get(n, {})
            entry = {
                "name": n,
                "ic": f.get("ic"),
                "status": f.get("status"),
                "icir": f.get("icir"),
                "icir_nw": f.get("icir_nw"),
                "sample_size": f.get("sample_size"),
                "weight": None,
                # T1 扩展字段 (原子直写盘, 不经 FactorRegistry 全量保存, 防洗扩展字段)
                "source": f"{run.get('source')} [t_5457c400 T1 追加, 权威卡既有 71 条目不变]",
                "t_nw": diag.get("t_nw"),
                "ic_lag1_autocorr": diag.get("ic_lag1_autocorr"),
                "ic_std": diag.get("ic_std"),
                "q_means_6": (q6.get(n) or {}).get("q6", {}).get("q_means"),
                "q6_monotonic": (q6.get(n) or {}).get("q6", {}).get("monotonic"),
                "q5_engine": (q6.get(n) or {}).get("q5", {}).get("q_means"),
                "note": diag.get("note"),
            }
            if n == "RSRS_TREND":
                entry["note"] = "全市场常数信号(上证RSRS): 截面退化 IC 无定义, 如实记 dead; " \
                                 "序列证据 data/factor_ic/rsrs_trend_132d.json"
            d["factors"].append(entry)
            dg = d.setdefault("diagnostics", {})
            dg[n] = {
                "icir": f.get("icir"), "icir_nw": f.get("icir_nw"), "t_nw": diag.get("t_nw"),
                "ic_lag1_autocorr": diag.get("ic_lag1_autocorr"), "ic_std": diag.get("ic_std"),
                "n_dates": f.get("sample_size"), "note": entry["note"],
            }
            d.setdefault("diagnostics", {})
            entries_added.append(n)
        return d  # R3: mutator 必须返回 data, 返回 None 会被 update_json 视为放弃修改

    atomic_json.update_json(str(AUTH), _mut, default={})

    # 读回断言
    after = json.load(open(AUTH, encoding="utf-8"))
    after_names = [f["name"] for f in after["factors"]]
    kept = [n for n in before_names]
    assert set(kept).issubset(set(after_names)), "既有因子丢失!"
    assert len(after["factors"]) == len(before["factors"]) + len([n for n in NEW if n not in before_names]), \
        "追加数量不符"
    for n in before_names:
        bf = next(f for f in before["factors"] if f["name"] == n)
        af = next(f for f in after["factors"] if f["name"] == n)
        assert json.dumps(bf, sort_keys=True) == json.dumps(af, sort_keys=True), f"既有条目被改: {n}"
    print(f"[OK] 追加 {entries_added or '(幂等: 已存在)'}; 现 {len(after['factors'])} 因子")
    for n in NEW:
        f = next(f for f in after["factors"] if f["name"] == n)
        print(f"  {n}: ic={f.get('ic')} status={f.get('status')} icir_nw={f.get('icir_nw')} "
              f"t_nw={f.get('t_nw')} q6={f.get('q_means_6')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
