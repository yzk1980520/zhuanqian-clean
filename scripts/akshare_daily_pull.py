#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
akshare_daily_pull.py — 盘后外部数据采集
cron: 工作日 16:00

采集内容:
  1. 龙虎榜明细 (stock_lhb_detail_em) → data/akshare/get_lhb_detail_{YYYYMMDD}.json
  2. 行业资金流排名 (stock_fund_flow_industry) → data/akshare/industry_fund_flow_{YYYYMMDD}.json

兼容: integrated_picker.py 的 LHB 加载逻辑 (key: 代码, 净买额占总成交比)
      capital_flow_daily.pkl 的因子评分逻辑 (主力净额)
"""
import json
import os
import sys
import time
from datetime import datetime, date

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AKSHARE_DIR = os.path.join(PROJECT, "data", "akshare")
os.makedirs(AKSHARE_DIR, exist_ok=True)

TODAY = date.today()
TODAY_STR = TODAY.strftime("%Y%m%d")
LOG_PREFIX = f"[{datetime.now().strftime('%H:%M:%S')}] akshare_pull: "


def log(msg: str):
    print(f"{LOG_PREFIX}{msg}", flush=True)


def safe_json_save(path: str, data, desc: str) -> bool:
    """保存 JSON 并输出 HMAC 签名（与 data_quality_daily.py 兼容）"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 同步写 .hmac 避免数据质量检查报错
        try:
            import hmac as _hmac_mod
            import hashlib as _hashlib_mod
            with open(path, "rb") as _fb:
                _sig = _hmac_mod.new(
                    os.environ.get("DATA_QUALITY_HMAC_KEY", b"").encode() if os.environ.get("DATA_QUALITY_HMAC_KEY") else b"",
                    _fb.read(),
                    _hashlib_mod.sha256
                ).hexdigest()
            with open(path + ".hmac", "w") as _fh:
                _fh.write(_sig)
        except Exception:
            print(f"🔴 [scripts\akshare_daily_pull.py] CR-01: except Exception:", file=sys.stderr)
        log(f"✅ {desc}: {path} 已保存")
        return True
    except Exception as e:
        log(f"❌ {desc} 保存失败: {e}")
        return False


def fetch_lhb() -> bool:
    """拉取龙虎榜明细

    P0修复(2026-09-25): 原实现因 akshare 1.18+ 的 stock_lhb_detail_em 持续失败,
    完全跳过拉取且伪装成功(直接 return True), 致 Layer6/7 龙虎榜链路长期空转且无告警。
    实测 akshare 1.18.97 接口已恢复(2026-09-25 返回 231 行), 恢复真实拉取。
    查询窗口取近 7 天(收盘后当日榜单可能未发布, 下游消费方会取最新覆盖)。
    失败时返回 False → main 退出码 1 → cron 告警(不再静默)。
    """
    import akshare as ak
    from datetime import timedelta
    out_path = os.path.join(AKSHARE_DIR, f"get_lhb_detail_{TODAY_STR}.json")
    start = (TODAY - timedelta(days=7)).strftime("%Y%m%d")
    try:
        df = ak.stock_lhb_detail_em(start_date=start, end_date=TODAY_STR)
        if df is None or len(df) == 0:
            log("⚠️ 龙虎榜接口返回空数据(近7日无榜单?)")
            return False
        # to_dict 会保留 numpy 类型(np.int64/float64), json.dump 会中途 TypeError 写坏文件
        # → 用 to_json 中转, 归一化为纯 Python 类型
        payload = {"data": json.loads(df.to_json(orient="records", force_ascii=False))}
        return safe_json_save(out_path, payload, "龙虎榜明细")
    except Exception as e:
        log(f"⚠️ 龙虎榜拉取失败(接口异常): {type(e).__name__}: {str(e)[:100]}")
        return False


def fetch_industry_fund_flow() -> bool:
    """拉取行业资金流排名"""
    import akshare as ak
    out_path = os.path.join(AKSHARE_DIR, f"industry_fund_flow_{TODAY_STR}.json")

    for attempt in range(2):
        try:
            log("📊 拉取行业资金流排名...")
            df = ak.stock_fund_flow_industry()
            if df is None or len(df) == 0:
                log("⚠️ 行业资金流无数据")
                return True
            result = {
                "date": TODAY_STR,
                "count": len(df),
                "columns": list(df.columns),
                "data": df.to_dict(orient="records")
            }
            if safe_json_save(out_path, result, f"行业资金流 {TODAY_STR}"):
                top5 = df.head(5)
                log(f"   → {len(df)} 个行业, TOP5: {list(top5['行业'])}")
                return True
        except Exception as e:
            log(f"❌ 行业资金流错误: {type(e).__name__}: {str(e)[:100]}")
            if attempt == 0:
                time.sleep(3)
                continue
            return False
    return False


def main():
    log("=" * 50)
    log(f"akshare 盘后数据拉取开始 ({TODAY_STR})")
    log("=" * 50)

    success_count = 0
    total = 0

    # 1. 龙虎榜
    total += 1
    if fetch_lhb():
        success_count += 1

    # 2. 行业资金流
    total += 1
    if fetch_industry_fund_flow():
        success_count += 1

    log("-" * 50)
    log(f"完成: {success_count}/{total} 项成功")
    # LHB 接口故障为 akshare 已知问题，不阻断 cron
    if success_count < total:
        log("⚠️ 部分数据拉取失败（可能为 akshare 接口临时故障）")
    sys.exit(0 if success_count == total else 1)  # P0修复(2026-09-25): 原三目两边都是0, 失败永不告警


if __name__ == "__main__":
    main()
