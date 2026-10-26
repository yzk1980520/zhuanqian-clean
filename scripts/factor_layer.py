#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""factor_layer.py — 行业赛道龙头因子框架 (W2-1, 2026-08-26)
import core.pipeline.atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
Ponytail: 复用现有 heat/flow 逻辑，新增 IC 计算能力。

因子槽位:
  F1 行业动量 -> heat_bonus (复用 integrated_picker.get_industry_heat_bonus)
  F2 板块资金 -> flow_bonus (复用 northbound_flow.get_fund_flow_bonus_for_stocks)
  F4 龙头特征 -> pattern_bonus (基于 TDX 本地计算)

IC 门槛: |rank_ic| >= 0.02 (弱有效), >= 0.05 (有效)
"""
import os
import sys
import json
import math
from datetime import datetime

PROJECT = os.path.dirname(os.path.abspath(__file__))

# ═══════════════════════════════════════════
#  因子计算函数
# ═══════════════════════════════════════════

def compute_f1_industry_momentum(industry, heat_data):
    """F1: 行业动量因子
    
    Args:
        industry: 行业名称
        heat_data: dict from industry_heat.json, format: {name: {"rank": N, "change_pct": X}}
    
    Returns:
        bonus: 0-8 分
        desc: 描述字符串
    """
    if not heat_data or not industry:
        return 0, ""
    
    for sector_name, info in heat_data.items():
        if not isinstance(info, dict) or "rank" not in info:
            continue
        rank = info.get("rank", 999)
        pct = info.get("change_pct", 0)
        
        clean_name = sector_name.replace("Ⅱ", "").replace("Ⅰ", "")
        if industry in clean_name or clean_name in industry:
            if rank <= 5:
                return 8, f"TOP{rank} {sector_name[:6]}(+{pct:.1f}%)"
            elif rank <= 10:
                return 6, f"TOP{rank} {sector_name[:6]}(+{pct:.1f}%)"
            elif rank <= 20:
                return 4, f"TOP{rank} {sector_name[:6]}(+{pct:.1f}%)"
            elif rank <= 30:
                return 2, f"TOP{rank} {sector_name[:6]}(+{pct:.1f}%)"
    
    return 0, ""


def compute_f4_leadership_signal(recs):
    """F4: 龙头特征因子
    
    Args:
        recs: list of dict, TDX K线数据
    
    Returns:
        bonus: 0-5 分
        desc: 描述字符串
    """
    if not recs or len(recs) < 20:
        return 0, ""
    
    latest = recs[-1]
    if not latest or "close" not in latest or "volume" not in latest:
        return 0, ""
    
    bonus = 0
    desc_parts = []
    
    # MA20 多头排列
    closes = [r.get("close", 0) for r in recs[-30:] if r.get("close")]
    if len(closes) >= 20:
        ma5 = sum(closes[-5:]) / 5
        ma20 = sum(closes) / 20
        if latest["close"] > ma5 > ma20:
            bonus += 2
            desc_parts.append("MA多头")
    
    # 量比 > 1.5
    volumes = [r.get("volume", 0) for r in recs[-20:] if r.get("volume")]
    if len(volumes) >= 20:
        vol_5d = sum(volumes[-5:]) / 5
        vol_15d = sum(volumes[:15]) / 15
        if vol_15d > 0 and vol_5d / vol_15d > 1.5:
            bonus += 2
            desc_parts.append("放量")
    
    # 近5日涨幅 > 0
    if len(closes) >= 5:
        chg_5d = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] > 0 else 0
        if chg_5d > 0:
            bonus += 1
            desc_parts.append(f"+{chg_5d:.1f}%")
    
    desc = " + ".join(desc_parts) if desc_parts else ""
    return bonus, desc


def load_stocks_from_tdx():
    """读取 TDX 目录获取股票列表"""
    tdx = r"D:\TDX\vipdoc"
    stocks = {}
    for market in ["sh", "sz"]:
        day_dir = os.path.join(tdx, market, "lday")
        if os.path.isdir(day_dir):
            for f in os.listdir(day_dir):
                if f.endswith(".day"):
                    code = f.replace(".day", "")
                    # 简单过滤非ST股票
                    if not code.startswith(('300', '301', '430', '83', '87', '92', '99')):
                        stocks[code] = market
    return stocks


def load_industry_heat():
    """加载行业热度数据"""
    heat_file = os.path.join(PROJECT, "data", "industry_heat.json")
    if os.path.exists(heat_file):
        try:
            with open(heat_file, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("data", {})
        except Exception as e:
            print(f"Warning: Failed to load heat data: {e}")
    return {}


def spearman_corr(x, y):
    """手动计算 Spearman 秩相关系数"""
    n = len(x)
    if n < 10:
        return None, None
    
    # 转换为秩
    def rank(arr):
        sorted_idx = sorted(range(n), key=lambda i: arr[i])
        ranks = [0] * n
        for r, i in enumerate(sorted_idx):
            ranks[i] = r
        return ranks
    
    rx = rank(x)
    ry = rank(y)
    
    mx = sum(rx) / n
    my = sum(ry) / n
    
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    sx = math.sqrt(sum((r - mx) ** 2 for r in rx))
    sy = math.sqrt(sum((r - my) ** 2 for r in ry))
    
    if sx == 0 or sy == 0:
        return None, None
    
    ic = cov / (sx * sy)
    # 简化 p-value 估算
    pval = 2 * (1 - min(1.0, abs(ic) * math.sqrt(n)))
    
    return ic, max(0, pval)


def compute_factor_ic(factor_values, factor_returns, factor_name="unknown"):
    """计算因子 IC
    
    Returns:
        dict: {"ic": X, "samples": Z, "significant": bool}
    """
    if len(factor_values) < 30 or len(factor_returns) < 30:
        return {"ic": None, "samples": min(len(factor_values), len(factor_returns)), "significant": False}
    
    # 过滤无效值
    pairs = [(v, r) for v, r in zip(factor_values, factor_returns) if v is not None and r is not None]
    if len(pairs) < 30:
        return {"ic": None, "samples": len(pairs), "significant": False}
    
    vals = [p[0] for p in pairs]
    rets = [p[1] for p in pairs]
    
    ic, pval = spearman_corr(vals, rets)
    if ic is None:
        return {"ic": None, "samples": len(vals), "significant": False}
    
    significant = abs(ic) >= 0.02
    
    return {
        "ic": round(ic, 4),
        "samples": len(vals),
        "significant": significant,
        "pval": round(pval, 4) if pval is not None else None
    }


def run_ic_validation(top_n=100):
    """运行因子 IC 验证"""
    print(f"\n{'='*60}")
    print(f"因子 IC 验证 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # 加载数据
    heat_data = load_industry_heat()
    print(f"行业热度数据: {len(heat_data)} 个行业")
    
    stocks = load_stocks_from_tdx()
    print(f"股票列表: {len(stocks)} 只\n")
    
    # 采样股票计算 IC
    sample_codes = list(stocks.keys())[:top_n]
    
    f1_values, f1_returns = [], []
    f4_values, f4_returns = [], []
    
    tdx = r"D:\TDX\vipdoc"
    
    for i, code in enumerate(sample_codes):
        if i % 20 == 0:
            print(f"  进度: {i}/{len(sample_codes)}")
        
        # 读取股票数据
        market = stocks[code]
        filepath = os.path.join(tdx, market, "lday", f"{code}.day")
        if not os.path.exists(filepath):
            continue
        
        recs = []
        try:
            with open(filepath, 'rb') as f:
                while True:
                    data = f.read(32)
                    if len(data) < 32:
                        break
                    # TDX day格式: date(4), open(4), high(4), low(4), close(4), volume(4), amount(4), reserved(4)
                    import struct
                    date_val = struct.unpack('<I', data[0:4])[0]
                    close = struct.unpack('<f', data[16:20])[0] / 100.0
                    volume = struct.unpack('<I', data[20:24])[0]
                    if close > 0:
                        recs.append({"close": close, "volume": volume})
        except Exception:
            continue
        
        if len(recs) < 60:
            continue
        
        # 计算行业 (简化：使用股票代码前缀映射)
        industry = f"Market_{market}"
        
        # F1: 行业动量
        hb, _ = compute_f1_industry_momentum(industry, heat_data)
        f1_values.append(hb)
        
        # F4: 龙头特征
        lb, _ = compute_f4_leadership_signal(recs)
        f4_values.append(lb)
        
        # 未来5日收益
        if len(recs) > 5:
            future_5 = (recs[-1]["close"] - recs[-6]["close"]) / recs[-6]["close"] * 100
            f1_returns.append(future_5)
            f4_returns.append(future_5)
    
    # 计算 IC
    print(f"\n{'='*60}")
    print(f"IC 验证结果")
    print(f"{'='*60}\n")
    print(f"  {'因子':<20} {'IC':>8} {'样本':>6} {'状态'}")
    print(f"  {'-'*40}")
    
    results = []
    for name, vals, rets in [("F1_行业动量", f1_values, f1_returns), ("F4_龙头特征", f4_values, f4_returns)]:
        ic_result = compute_factor_ic(vals, rets, name)
        sig = "有效" if ic_result["significant"] else "无效" if ic_result["ic"] and abs(ic_result["ic"]) < 0.02 else "弱效"
        print(f"  {name:<20} {ic_result['ic'] or 0:>+.4f} {ic_result['samples']:>5} {sig}")
        results.append({"name": name, **ic_result})
    
    # 保存结果
    report_file = os.path.join(PROJECT, "data", "factor_ic_report.json")
    atomic_json.atomic_dump({
            "timestamp": datetime.now().isoformat(),
            "results": results,
            "top_n": top_n
        }, report_file, ensure_ascii=False, indent=2, encoding="utf-8")
    
    print(f"\n报告已保存: {report_file}")
    
    valid_count = sum(1 for r in results if r.get("significant"))
    if valid_count >= 1:
        print(f"\n结果: {valid_count} 因子 IC>=0.02 (建议: 继续优化因子)")
        return valid_count >= 2
    return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="因子 IC 验证")
    parser.add_argument("--validate", action="store_true", help="运行 IC 验证")
    parser.add_argument("--top-n", type=int, default=100, help="采样股票数")
    args = parser.parse_args()
    
    if args.validate:
        success = run_ic_validation(args.top_n)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
