#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py data-quality
# -*- coding: utf-8 -*-
"""
data_quality_checker.py — 数据质量检查脚本
版本: v0.1
作者: 老三
日期: 2026-10-04

功能:
  1. 检查历史数据完整性
  2. 检测价格异常
  3. 检测成交量异常
  4. 检查财务数据时效
  5. 生成质量报告

使用:
  python data_quality_checker.py [--date 2026-10-04]
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta
from collections import defaultdict

ROOT = r"D:/open code/zhuanqian"


def log(msg):
    """日志输出"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    
    log_file = os.path.join(ROOT, ".scratch", "data_quality.log")
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        print(f"🔴 [scripts\data_quality_checker.py] CR-01: except Exception:", file=sys.stderr)
def _gap005_exempt_codes(root) -> set:
    """GAP-005 退市/摘牌+源侧stub 豁免集 (老五 8971faec 注册, data/known_gaps.json)。

    读侧断言 (recovery_assertion 件): 豁免集 = delisted_classification_full.json
    (with_data 91 + st_skipped 66 = 157 源删) ∪ stale_alive_21.json (21 stub)。
    台账件缺失/条目缺失/状态非 open-exempt → fail-close 返回空集 (不豁免, 不误绿),
    由调用方留痕。返回码面不含 .json 后缀 (sh600068 形态)。
    """
    import os, json as _json
    d = os.path.join(root, "data")
    try:
        gaps = _json.load(open(os.path.join(d, "known_gaps.json"), encoding="utf-8"))
        g5 = next((g for g in gaps.get("gaps", []) if g.get("gap_id") == "GAP-005"), None)
        if not g5 or g5.get("status") != "open-exempt":
            return set()
        codes = set()
        cls = _json.load(open(os.path.join(d, "delisted_classification_full.json"),
                              encoding="utf-8"))
        for k in ("with_data", "st_skipped"):
            for x in cls.get(k, []):
                if isinstance(x, dict):
                    codes.add(x.get("code"))
                else:
                    codes.add(x)
        codes.update(_json.load(open(os.path.join(d, "stale_alive_21.json"),
                                     encoding="utf-8")))
        codes.discard(None)
        return codes
    except Exception as e:
        print(f"  ⚠️ [P2/GAP-005] 豁免表读取失败({e}) — fail-close 不豁免, 留痕",
              file=sys.stderr)
        return set()


def check_date_completeness(data_dir, target_date=None):
    """检查数据完整性

    P2修复(2026-10-24 老三): 缺陷=required_dates 用自然日近30天(周末/国庆/春节全算)
    + os.listdir 前100件把 index/元数据文件误计入股票面 (MISSING_DATES=10 误报样本:
    9 件 TDX 源缺日 09-25/26/27 混在 1 件 10-01/02 国庆 checker 缺陷里)。
    修复: ①required_dates 以 sh000001 指数文件实际在库日期为基准(=TDX 交易日历,
    自动排除休市日) ②仅检查 6位代码股票文件, index/元数据文件不入股票面。
    语义变化: TDX 源自身缺日仍会被报(基准有 源无→缺口), 但休市日不再误报。
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    issues = []

    # P2修复: 基准 = 上证指数文件在库实际日期 (交易日历随源, 无硬编码假期表)
    ref_file = os.path.join(data_dir, "sh000001.json")
    required_dates = set()
    try:
        with open(ref_file, "r", encoding="utf-8") as f:
            ref = json.load(f)
        if isinstance(ref, list):
            required_dates = set(r.get("date", "") for r in ref if r.get("date"))
    except Exception as e:
        print(f"  ⚠️ [P2] 交易日历基准读取失败({ref_file}): {e}", file=sys.stderr)

    if not required_dates:
        # 基准不可得=断言失明: fail-close 返回空(不误报自然日, 也不静默绿), 警告留痕
        print("  ⚠️ [P2] 交易日历基准为空, 日期完整性检查跳过(非缺陷, 留痕)", file=sys.stderr)
        return issues

    # P2修复: 完整性窗口=基准交易日历最近30个交易日(保留原30天语义, 但按交易日历计,
    # 自动排除周末/国庆等休市日). 全量历史(1990起)不作缺口要求——上市日前的日期
    # 对任何股票都缺失, 计入即假红(首跑实测 10 件全报 1990 缺口=该缺陷).
    required_dates = set(sorted(required_dates)[-30:])

    # 检查样本股票 (P2修复: 仅 A 股代码面, 排除 指数/债券/ETF/元数据 误计入——
    # sh1100xx 转债等自有交易面, 与股票面日历不可比, 计入即假红)
    stock_re = re.compile(
        r"^(sh(60[0-5]\d{3}|68[89]\d{3})|sz(00[0-4]\d{3}|30[01]\d{3})|bj([489]\d{5}))\.json$")
    # P2/GAP-005 (老五 8971faec 台账件 读侧断言): 退市/摘牌+源侧stub 178 件豁免集,
    # 停更末日属终态非缺口; 台账 fail-close=空集 (不误豁免, 留痕)
    # 台账根=仓库根 (调用方 ROOT 常量; 函数不猜 cwd)
    exempt = _gap005_exempt_codes(ROOT)
    if exempt:
        print(f"  ℹ️ [P2/GAP-005] 读侧豁免 {len(exempt)} 件 (退市/摘牌+源侧stub, known_gaps GAP-005)",
              file=sys.stderr)
    # P2修复: 先筛 A 股面再取样(原 listdir()[:100] 落在 sh0000xx 指数段会样本落空)
    sample_count = 0
    stock_files = [f for f in sorted(os.listdir(data_dir)) if stock_re.match(f)]
    for fname in stock_files[:100]:
        code = fname[:-5]  # 去 .json, 码面 sh600068
        if code in exempt:
            continue  # GAP-005 豁免件: 停更末日=终态, 非缺口
        
        fpath = os.path.join(data_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if isinstance(data, list):
                dates = set(record.get("date", "") for record in data)
                missing = required_dates - dates
                
                if missing:
                    issues.append({
                        "code": fname.replace(".json", ""),
                        "missing_dates": sorted(missing)[:5],  # 只记录前5个
                        "completeness": (len(required_dates) - len(missing)) / len(required_dates) * 100
                    })
                    
                    sample_count += 1
                    
                    if sample_count >= 10:  # 检查10个样本
                        break
        except Exception as e:
            issues.append({
                "code": fname.replace(".json", ""),
                "error": str(e)
            })
    
    return issues


def check_price_anomalies(data_dir, max_jump_pct=20.0):
    """检测价格异常"""
    anomalies = []
    
    # 检查样本股票
    check_count = 0
    for fname in os.listdir(data_dir)[:200]:
        if not fname.endswith(".json"):
            continue
        
        fpath = os.path.join(data_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if not isinstance(data, list) or len(data) < 10:
                continue
            
            # 检查价格跳跃
            for i in range(1, len(data)):
                prev_close = data[i-1].get("close", 0)
                curr_close = data[i].get("close", 0)
                
                if prev_close > 0 and curr_close > 0:
                    jump_pct = abs(curr_close - prev_close) / prev_close * 100
                    
                    if jump_pct > max_jump_pct:
                        anomalies.append({
                            "code": fname.replace(".json", ""),
                            "date": data[i].get("date", ""),
                            "prev_close": prev_close,
                            "curr_close": curr_close,
                            "jump_pct": round(jump_pct, 2)
                        })
            
            check_count += 1
            if check_count >= 50:
                break
        except Exception as e:
            anomalies.append({
                "code": fname.replace(".json", ""),
                "error": str(e)
            })
    
    return anomalies


def check_volume_anomalies(data_dir, min_volume_ratio=0.01, max_volume_ratio=100.0):
    """检测成交量异常"""
    anomalies = []
    
    check_count = 0
    for fname in os.listdir(data_dir)[:200]:
        if not fname.endswith(".json"):
            continue
        
        fpath = os.path.join(data_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if not isinstance(data, list) or len(data) < 10:
                continue
            
            # 检查成交量异常
            volumes = [record.get("volume", 0) for record in data]
            avg_volume = sum(volumes) / len(volumes) if volumes else 0
            
            for i, vol in enumerate(volumes):
                if avg_volume > 0:
                    ratio = vol / avg_volume
                    
                    if ratio < min_volume_ratio or ratio > max_volume_ratio:
                        anomalies.append({
                            "code": fname.replace(".json", ""),
                            "date": data[i].get("date", ""),
                            "volume": vol,
                            "avg_volume": round(avg_volume, 2),
                            "ratio": round(ratio, 2)
                        })
            
            check_count += 1
            if check_count >= 50:
                break
        except Exception as e:
            anomalies.append({
                "code": fname.replace(".json", ""),
                "error": str(e)
            })
    
    return anomalies


def check_financial_data_freshness():
    """检查财务数据时效性"""
    financial_file = os.path.join(ROOT, "data", "financial_cache.json")
    
    if not os.path.exists(financial_file):
        return {
            "status": "MISSING",
            "days_stale": 999,
            "message": "财务缓存不存在"
        }
    
    # 获取文件修改时间
    mtime = os.path.getmtime(financial_file)
    file_date = datetime.fromtimestamp(mtime)
    days_stale = (datetime.now() - file_date).days
    
    # 获取数据日期
    try:
        with open(financial_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        data_date = data.get("date", "N/A")
    except (FileNotFoundError, IOError, KeyError, PermissionError, json.JSONDecodeError) as e:
        data_date = "N/A"
    
    return {
        "status": "OK" if days_stale <= 7 else "STALE",
        "file_modified": file_date.strftime("%Y-%m-%d %H:%M:%S"),
        "data_date": data_date,
        "days_stale": days_stale
    }


def check_index_data_freshness():
    """检查指数数据时效性"""
    index_file = os.path.join(ROOT, "data", "sh_index_history.json")
    
    if not os.path.exists(index_file):
        return {
            "status": "MISSING",
            "days_stale": 999,
            "message": "指数历史数据不存在"
        }
    
    try:
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        records = data.get("data", [])
        if not records:
            return {
                "status": "EMPTY",
                "days_stale": 999,
                "message": "指数数据为空"
            }
        
        latest_date = records[-1].get("date", "")
        latest_record_date = datetime.strptime(latest_date, "%Y-%m-%d")
        days_stale = (datetime.now() - latest_record_date).days
        
        return {
            "status": "OK" if days_stale <= 1 else "STALE",
            "latest_date": latest_date,
            "days_stale": days_stale,
            "total_records": len(records)
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "error": str(e)
        }


def calc_quality_score(issues):
    """计算质量评分"""
    if not issues:
        return 100
    
    # 扣分规则
    deductions = {
        "MISSING_DATES": 10,      # 每个缺失日期的股票扣10分
        "PRICE_ANOMALY": 5,       # 每个价格异常扣5分
        "VOLUME_ANOMALY": 3,      # 每个成交量异常扣3分
        "STALE_FINANCIAL": 20,    # 财务数据过时扣20分
        "STALE_INDEX": 15         # 指数数据过时扣15分
    }
    
    total_deduction = 0
    for issue in issues:
        issue_type = issue.get("type", "UNKNOWN")
        count = issue.get("count", 1)
        total_deduction += deductions.get(issue_type, 5) * count
    
    return max(0, 100 - total_deduction)


def generate_report(check_date=None):
    """生成质量报告"""
    if check_date is None:
        check_date = datetime.now().strftime("%Y-%m-%d")
    
    log("=" * 60)
    log("数据质量检查")
    log("=" * 60)
    log(f"检查日期: {check_date}")
    log("")
    
    data_dir = os.path.join(ROOT, "data", "history_daily")
    all_issues = []
    
    # 1. 检查日期完整性
    log("【1. 日期完整性检查】")
    date_issues = check_date_completeness(data_dir)
    if date_issues:
        log(f"  ⚠️ 发现 {len(date_issues)} 个问题股票")
        for issue in date_issues[:3]:
            log(f"    - {issue.get('code')}: 缺失{len(issue.get('missing_dates', []))}天")
        all_issues.extend([{"type": "MISSING_DATES", "count": len(date_issues)}])
    else:
        log("  ✅ 日期完整")
    
    # 2. 检查价格异常
    log("\n【2. 价格异常检查】")
    price_issues = check_price_anomalies(data_dir)
    if price_issues:
        log(f"  ⚠️ 发现 {len(price_issues)} 个价格异常")
        for issue in price_issues[:3]:
            log(f"    - {issue.get('code')} @ {issue.get('date')}: {issue.get('jump_pct')}%")
        all_issues.extend([{"type": "PRICE_ANOMALY", "count": len(price_issues)}])
    else:
        log("  ✅ 价格正常")
    
    # 3. 检查成交量异常
    log("\n【3. 成交量异常检查】")
    volume_issues = check_volume_anomalies(data_dir)
    if volume_issues:
        log(f"  ⚠️ 发现 {len(volume_issues)} 个成交量异常")
        for issue in volume_issues[:3]:
            log(f"    - {issue.get('code')} @ {issue.get('date')}: 比率{issue.get('ratio')}")
        all_issues.extend([{"type": "VOLUME_ANOMALY", "count": len(volume_issues)}])
    else:
        log("  ✅ 成交量正常")
    
    # 4. 检查财务数据
    log("\n【4. 财务数据时效检查】")
    financial_status = check_financial_data_freshness()
    log(f"  状态: {financial_status.get('status')}")
    log(f"  数据日期: {financial_status.get('data_date')}")
    log(f"  过时天数: {financial_status.get('days_stale')}天")
    
    if financial_status.get("days_stale", 0) > 7:
        all_issues.append({"type": "STALE_FINANCIAL", "count": 1})
    
    # 5. 检查指数数据
    log("\n【5. 指数数据时效检查】")
    index_status = check_index_data_freshness()
    log(f"  状态: {index_status.get('status')}")
    log(f"  最新日期: {index_status.get('latest_date')}")
    log(f"  过时天数: {index_status.get('days_stale')}天")
    
    if index_status.get("days_stale", 0) > 1:
        all_issues.append({"type": "STALE_INDEX", "count": 1})
    
    # 6. 计算质量评分
    log("\n【6. 质量评分】")
    quality_score = calc_quality_score(all_issues)
    log(f"  评分: {quality_score}/100")
    
    if quality_score >= 90:
        grade = "A"
    elif quality_score >= 70:
        grade = "B"
    elif quality_score >= 50:
        grade = "C"
    else:
        grade = "D"
    
    log(f"  等级: {grade}")
    
    # 7. 保存报告
    report = {
        "check_date": check_date,
        "generated": datetime.now().isoformat(),
        "quality_score": quality_score,
        "grade": grade,
        "issues": all_issues,
        "details": {
            "date_completeness": len(date_issues),
            "price_anomalies": len(price_issues),
            "volume_anomalies": len(volume_issues),
            "financial_status": financial_status,
            "index_status": index_status
        }
    }
    
    report_file = os.path.join(ROOT, ".scratch", f"data_quality_{check_date}.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    log(f"\n  报告已保存: {report_file}")
    
    log("\n" + "=" * 60)
    log("检查完成")
    log("=" * 60)
    
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description="数据质量检查")
    parser.add_argument("--date", help="检查日期 (YYYY-MM-DD)")
    parser.add_argument("--output", help="输出文件路径")
    args = parser.parse_args()
    
    report = generate_report(args.date)
    
    # 输出摘要
    print("\n" + "=" * 60)
    print("数据质量检查摘要")
    print("=" * 60)
    print(f"评分: {report['quality_score']}/100 ({report['grade']})")
    print(f"问题数: {len(report['issues'])}")
    for issue in report['issues']:
        print(f"  - {issue.get('type')}: {issue.get('count')}个")
    print("=" * 60)
    
    # 返回状态码
    if report['quality_score'] >= 70:
        return 0
    elif report['quality_score'] >= 50:
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
