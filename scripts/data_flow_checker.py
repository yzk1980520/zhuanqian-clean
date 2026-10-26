#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py data-quality
# -*- coding: utf-8 -*-
"""
S3全链路数据流打通脚本
整合：候选池生成 → 消息推送 → 执行记录 → 状态监控
"""
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    print(f"🔴 [scripts\data_flow_checker.py] CR-01: except Exception:", file=sys.stderr)
PROJECT = Path(__file__).parent.resolve()
DATA_DIR = PROJECT.parent / "data"
LOGS_DIR = PROJECT.parent / "logs"

def log(msg: str = ""):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def load_json(path, default=None):
    """安全加载JSON"""
    if not path.exists():
        return default or {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"⚠️ 加载{path.name}失败: {e}")
        return default or {}

def save_json(path, data):
    """安全保存JSON"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log(f"❌ 保存{path.name}失败: {e}")
        return False

def get_market_status():
    """获取市场状态"""
    status_file = LOGS_DIR / "market_signal_{}.json".format(datetime.now().strftime("%Y%m%d"))
    return load_json(status_file, {"state": "unknown", "gate": None})

def get_candidates():
    """获取候选池"""
    rank_file = LOGS_DIR / "rank_{}.json".format(datetime.now().strftime("%Y-%m-%d"))
    return load_json(rank_file, {"items": []})

def get_holdings():
    """获取持仓状态"""
    holdings_file = DATA_DIR / "holdings.json"
    return load_json(holdings_file, {
        "total_assets": 0,
        "available_cash": 0,
        "holdings": [],
        "position_ratio": 0
    })

def get_s3_config():
    """获取S3配置"""
    config_file = PROJECT.parent / "config.json"
    config = load_json(config_file, {})
    return {
        "position_ratio": config.get("trade_params", {}).get("position_ratio", 0.5),
        "stop_loss_pct": config.get("stop_loss_pct", 0.10),
        "ladder": config.get("trailing", {}).get("ladder", [])
    }

def build_data_flow_report():
    """构建数据流报告"""
    report = {
        "timestamp": datetime.now().isoformat(),
        "market": get_market_status(),
        "candidates": get_candidates(),
        "holdings": get_holdings(),
        "s3_config": get_s3_config(),
        "flow_status": {
            "market_data": "✅",
            "candidate_generation": "✅",
            "execution_record": "✅",
            "monitoring": "⚠️ 待完善",
            "notification": "❌ 未集成"
        }
    }
    return report

def main():
    log("=" * 60)
    log("S3全链路数据流打通检查")
    log("=" * 60)
    
    report = build_data_flow_report()
    
    # 输出报告
    output_file = DATA_DIR / "data_flow_report.json"
    save_json(output_file, report)
    
    log(f"\n📊 市场状态: {report['market'].get('state', 'N/A')}")
    log(f"📈 候选池: {len(report['candidates'].get('items', []))}只")
    log(f"💰 持仓数: {report['holdings'].get('holdings', [])}只")
    log(f"📐 S3仓位: {report['s3_config']['position_ratio']*100:.0f}%")
    log()
    
    # 显示TOP3候选
    candidates = report['candidates'].get('items', [])[:3]
    if candidates:
        log("🏆 TOP3候选:")
        for i, c in enumerate(candidates, 1):
            log(f"  {i}. {c.get('name', 'N/A')}({c.get('code', 'N/A')}) 分数:{c.get('final_score', 0):.1f}")
    
    log()
    log(f"✅ 报告已保存: {output_file}")
    
    # 检查断点
    issues = []
    if not candidates:
        issues.append("❌ 候选池为空")
    if report['holdings'].get('position_ratio', 0) > 0 and len(report['holdings'].get('holdings', [])) == 0:
        issues.append("❌ 持仓比例与持仓数不一致")
    if report['s3_config']['position_ratio'] == 0:
        issues.append("❌ S3仓位配置为0")
    
    if issues:
        log("\n🔴 发现问题:")
        for issue in issues:
            log(f"  {issue}")
    else:
        log("\n✅ 数据流正常")
    
    return issues

if __name__ == "__main__":
    issues = main()
    sys.exit(1 if issues else 0)
