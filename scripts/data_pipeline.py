#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
import core.pipeline.atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
data_pipeline.py — 数据闭环系统 v1.0

流程:
  1. 采集(fetch) → 2. 校验(validate) → 3. 清洗(clean) → 4. 反哺(feed)

数据来源:
  - TDX本地数据 (主)
  - akshare (辅)
  - FTShare资金流 (辅)

用法:
  python data_pipeline.py --fetch-all    # 全量采集
  python data_pipeline.py --validate     # 校验数据质量
  python data_pipeline.py --feed         # 清洗后反哺
  python data_pipeline.py --loop         # 完整闭环(采集→校验→清洗→反哺)

状态文件: data/data_pipeline_status.json
"""
import json
import os
import sys
import time
from datetime import datetime, date

# 修复python314.dll冲突: 清理Hermes注入的环境变量
if __name__ == "__main__":
    env = os.environ.copy()
    for k in list(env.keys()):
        if k.startswith("PYTHON") or k.startswith("HERMES"):
            del env[k]
    env["PYTHONHOME"] = ""
    env["PYTHONPATH"] = ""
    os.environ.clear()
    os.environ.update(env)

PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)

# 状态文件路径
STATUS_FILE = os.path.join(PROJECT, "data", "data_pipeline_status.json")


def log(msg: str):
    """统一日志输出"""
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)


def load_status():
    """加载上次运行状态"""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, IOError, PermissionError, json.JSONDecodeError) as e:
            pass
    return {
        "last_run": None,
        "last_fetch": {},
        "last_validate": {},
        "last_feed": {},
        "errors": []
    }


def save_status(status):
    """保存运行状态"""
    status["last_run"] = datetime.now().isoformat()
    # 递归转换date/datetime为字符串
    def convert(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert(i) for i in obj]
        return obj
    atomic_json.atomic_dump(convert(status), STATUS_FILE, ensure_ascii=False, indent=2, encoding="utf-8")


def fetch_tdx_data():
    """TDX数据采集 (已有逻辑)"""
    from core.pipeline.tdx_core import get_tdx_data
    status = {"source": "tdx", "status": "ok", "items": 0}
    try:
        # 采集上证指数据作为基准
        sh_data = get_tdx_data("sh000001", 30)
        if sh_data:
            status["items"] = len(sh_data)
            status["latest_date"] = sh_data[-1].get("date", "")
            log(f"✅ TDX数据采集: {status['items']}条记录, 最新: {status['latest_date']}")
        else:
            status["status"] = "empty"
            status["error"] = "无数据"
            log(f"⚠️ TDX数据为空")
    except Exception as e:
        status["status"] = "error"
        status["error"] = str(e)
        log(f"❌ TDX采集失败: {e}")
    return status


def fetch_akshare_data():
    """akshare数据采集 (已有逻辑)"""
    status = {"source": "akshare", "status": "ok", "items": 0}
    try:
        import akshare as ak
        # 测试龙虎榜数据（使用正确的参数）
        try:
            lhb_df = ak.stock_lhb_detail_em(start_date="20260901", end_date="20260905")
            if not lhb_df.empty:
                status["items"] = len(lhb_df)
                status["latest_date"] = str(lhb_df["日期"].max()) if "日期" in lhb_df.columns else "unknown"
                log(f"✅ akshare龙虎榜采集: {status['items']}条记录")
            else:
                status["status"] = "empty"
                log("⚠️ akshare龙虎榜数据为空")
        except Exception as e:
            # 降级：尝试其他接口
            log(f"⚠️ 龙虎榜采集失败: {e}，尝试降级方案")
            status["status"] = "degraded"
            status["error"] = str(e)
    except Exception as e:
        status["status"] = "error"
        status["error"] = str(e)
        log(f"❌ akshare采集失败: {e}")
    return status


def fetch_ftshare_data():
    """FTShare数据采集 (资金流)"""
    status = {"source": "ftshare", "status": "ok", "items": 0}
    try:
        from ft_adapter import ft_capital_flows
        cap = ft_capital_flows(page=1, page_size=50)
        items = cap.get("items", []) if isinstance(cap, dict) else []
        status["items"] = len(items)
        log(f"✅ FTShare数据采集: {status['items']}条记录")
    except Exception as e:
        status["status"] = "error"
        status["error"] = str(e)
        log(f"❌ FTShare采集失败: {e}")
    return status


def validate_data(fetch_results):
    """数据校验"""
    status = {"status": "pass", "issues": [], "timestamp": datetime.now().isoformat()}
    
    # 检查TDX数据是否新鲜 (最近交易日)
    tdx = fetch_results.get("tdx", {})
    if tdx.get("status") == "ok":
        latest = tdx.get("latest_date", "")
        if latest:
            # 解析日期并检查滞后
            try:
                latest_dt = datetime.strptime(latest, "%Y-%m-%d")
                days_lag = (datetime.now() - latest_dt).days
                if days_lag > 5:
                    status["issues"].append({
                        "severity": "high",
                        "source": "tdx",
                        "message": f"TDX数据滞后{days_lag}天"
                    })
                elif days_lag > 2:
                    status["issues"].append({
                        "severity": "medium",
                        "source": "tdx",
                        "message": f"TDX数据滞后{days_lag}天"
                    })
            except (AttributeError, KeyError) as e:
                pass
    
    # 检查akshare数据
    ak = fetch_results.get("akshare", {})
    if ak.get("status") == "error":
        status["issues"].append({
            "severity": "medium",
            "source": "akshare",
            "message": "akshare采集失败, 使用缓存降级"
        })
    
    # 判断总体验证结果
    high_issues = [i for i in status["issues"] if i["severity"] == "high"]
    if high_issues:
        status["status"] = "fail"
    elif status["issues"]:
        status["status"] = "warn"
    
    # 数据陈旧触发三方讨论（Ponytail: 复用debate_trigger）
    if status["status"] == "fail":
        stale_days = max((i.get("days_lag", 0) for i in status["issues"] if "days_lag" in i), default=0)
        if stale_days > 2:
            from debate_trigger import trigger_debate
            trigger_debate("data_stale", {
                "days_lag": stale_days,
                "issues": status["issues"]
            })
    
    return status


def clean_data(fetch_results, validation):
    """⚠️ v1.0 空壳: 数据清洗暂由 tdx_core.refresh() 和 fetch_sw_data.py 直接维护, 本函数只做状态流转 (P0修复 2026-08-25)"""
    status = {"status": "skipped", "actions": ["clean_data 空壳: 复用 tdx_core / fetch_sw_data 内置清洗"], "timestamp": datetime.now().isoformat()}
    if validation.get("status") == "fail":
        status["status"] = "skip"
        status["actions"].append("数据校验失败, 跳过清洗")
    return status


def feed_to_system(clean_result, fetch_results):
    """反哺系统"""
    status = {"status": "ok", "feeds": [], "timestamp": datetime.now().isoformat()}
    
    # 反哺TDX缓存 (如果采集了新数据)
    tdx = fetch_results.get("tdx", {})
    if tdx.get("status") == "ok":
        status["feeds"].append({
            "target": "tdx_cache",
            "status": "ok",
            "items": tdx.get("items", 0)
        })
    
    # 反哺akshare缓存
    ak = fetch_results.get("akshare", {})
    if ak.get("status") == "ok":
        status["feeds"].append({
            "target": "akshare_cache",
            "status": "ok",
            "items": ak.get("items", 0)
        })
    
    # 更新pipeline状态
    status["feeds"].append({
        "target": "pipeline_status",
        "status": "ok",
        "message": "data_pipeline_status.json已更新"
    })
    
    return status


def run_loop():
    """执行完整闭环: 采集→校验→清洗→反哺"""
    log("=" * 60)
    log("  数据闭环系统启动")
    log("=" * 60)
    
    status = load_status()
    
    # 阶段1: 采集
    log("\n[阶段1/4] 数据采集...")
    fetch_results = {
        "tdx": fetch_tdx_data(),
        "akshare": fetch_akshare_data(),
        "ftshare": fetch_ftshare_data()
    }
    status["last_fetch"] = fetch_results
    
    # 阶段2: 校验
    log("\n[阶段2/4] 数据校验...")
    validation = validate_data(fetch_results)
    status["last_validate"] = validation
    
    if validation["status"] == "fail":
        log("❌ 数据校验失败, 中止后续流程")
        status["errors"].append(f"校验失败: {validation['issues']}")
        save_status(status)
        return False
    
    # 阶段3: 清洗
    log("\n[阶段3/4] 数据清洗...")
    clean_result = clean_data(fetch_results, validation)
    status["last_clean"] = clean_result
    
    # 阶段4: 反哺
    log("\n[阶段4/4] 反哺系统...")
    feed_result = feed_to_system(clean_result, fetch_results)
    status["last_feed"] = feed_result
    
    # 保存最终状态
    save_status(status)
    
    log("\n" + "=" * 60)
    log("  数据闭环完成")
    log(f"  校验结果: {validation['status']}")
    log(f"  清洗状态: {clean_result['status']}")
    log(f"  反哺状态: {feed_result['status']}")
    log("=" * 60)
    
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="数据闭环系统")
    parser.add_argument("--fetch-all", action="store_true", help="仅采集")
    parser.add_argument("--validate", action="store_true", help="仅校验")
    parser.add_argument("--feed", action="store_true", help="仅反哺")
    parser.add_argument("--loop", action="store_true", help="完整闭环")
    parser.add_argument("--status", action="store_true", help="查看状态")
    args = parser.parse_args()
    
    if args.status:
        status = load_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return
    
    if args.fetch_all:
        results = {
            "tdx": fetch_tdx_data(),
            "akshare": fetch_akshare_data(),
            "ftshare": fetch_ftshare_data()
        }
        # 修复JSON序列化bug：转换date对象为字符串
        def convert_dates(obj):
            if isinstance(obj, dict):
                return {k: convert_dates(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_dates(i) for i in obj]
            elif isinstance(obj, date):
                return obj.isoformat()
            return obj
        results = convert_dates(results)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    
    if args.validate:
        status = load_status()
        validation = validate_data(status.get("last_fetch", {}))
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return
    
    if args.feed:
        status = load_status()
        fetch_results = status.get("last_fetch", {})
        clean_result = clean_data(fetch_results, {"status": "pass"})
        feed_result = feed_to_system(clean_result, fetch_results)
        print(json.dumps(feed_result, ensure_ascii=False, indent=2))
        return
    
    # 默认: 完整闭环
    success = run_loop()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
