# -*- coding: utf-8 -*-
"""data_quality_monitor.py — 数据质量监控模块
========================================================================
监控目标：
1. Akshare调用成功率
2. 行业热度数据时效性
3. 降级使用频率
4. 超时次数统计

输出：data/quality_monitor.json
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [scripts\data_quality_monitor.py] CR-01: except Exception:", file=sys.stderr)
import os
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 配置日志
logger = logging.getLogger(__name__)

# ── 配置 ──
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "quality_monitor.json")
HISTORY_DIR = os.path.join(DATA_DIR, "quality_history")

# 告警阈值
THRESHOLDS = {
    "akshare_fail_count": 3,  # 连续失败次数
    "data_stale_hours": 24,   # 数据过期时间（小时）
    "fallback_usage_rate": 0.5,  # 降级使用率阈值
}


class DataQualityMonitor:
    """数据质量监控器"""
    
    def __init__(self):
        self.metrics = {
            "last_check_time": None,
            "akshare_success_count": 0,
            "akshare_fail_count": 0,
            "akshare_timeout_count": 0,
            "fallback_usage_count": 0,
            "total_data_load_count": 0,
            "alerts": [],
            "status": "healthy"
        }
        self._load_state()
    
    def _load_state(self):
        """加载历史状态"""
        if os.path.exists(OUTPUT_FILE):
            try:
                with open(OUTPUT_FILE, encoding="utf-8") as f:
                    self.metrics = json.load(f)
                logger.info(f"加载监控状态: {self.metrics.get('last_check_time')}")
            except Exception as e:
                logger.warning(f"加载监控状态失败: {e}")
    
    def _save_state(self):
        """保存状态"""
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(self.metrics, f, ensure_ascii=False, indent=2)
    
    def _add_alert(self, level, message):
        """添加告警"""
        alert = {
            "time": datetime.now().isoformat(),
            "level": level,  # warning/error/critical
            "message": message
        }
        self.metrics["alerts"].append(alert)
        # 保留最近50条告警
        self.metrics["alerts"] = self.metrics["alerts"][-50:]
        logger.warning(f"[{level.upper()}] {message}")
    
    def check_akshare_status(self, success=True, timeout=False):
        """检查Akshare调用状态"""
        self.metrics["last_check_time"] = datetime.now().isoformat()
        
        if timeout:
            self.metrics["akshare_timeout_count"] += 1
            self.metrics["akshare_fail_count"] += 1
            logger.warning("Akshare调用超时")
        elif success:
            self.metrics["akshare_success_count"] += 1
            # 重置连续失败计数
            if self.metrics["akshare_fail_count"] > 0:
                self.metrics["akshare_fail_count"] = max(0, self.metrics["akshare_fail_count"] - 1)
        else:
            self.metrics["akshare_fail_count"] += 1
            logger.warning("Akshare调用失败")
        
        # 检查阈值
        if self.metrics["akshare_fail_count"] >= THRESHOLDS["akshare_fail_count"]:
            self._add_alert("error", f"Akshare连续失败{self.metrics['akshare_fail_count']}次")
        
        self._save_state()
    
    def check_data_freshness(self, data_file, max_age_hours=24):
        """检查数据时效性"""
        if not os.path.exists(data_file):
            self._add_alert("warning", f"数据文件不存在: {data_file}")
            return False
        
        mtime = os.path.getmtime(data_file)
        age_hours = (time.time() - mtime) / 3600
        
        if age_hours > max_age_hours:
            self._add_alert("warning", f"数据过期: {data_file} ({age_hours:.1f}小时)")
            return False
        
        return True
    
    def check_fallback_usage(self, use_fallback):
        """检查降级使用情况"""
        self.metrics["total_data_load_count"] += 1
        if use_fallback:
            self.metrics["fallback_usage_count"] += 1
            rate = self.metrics["fallback_usage_count"] / self.metrics["total_data_load_count"]
            
            if rate > THRESHOLDS["fallback_usage_rate"]:
                self._add_alert("warning", f"降级使用率过高: {rate:.1%}")
    
    def get_status(self):
        """获取系统状态"""
        status = "healthy"
        if self.metrics["akshare_fail_count"] >= THRESHOLDS["akshare_fail_count"]:
            status = "degraded"
        if self.metrics["akshare_fail_count"] >= THRESHOLDS["akshare_fail_count"] * 2:
            status = "critical"
        
        self.metrics["status"] = status
        return status
    
    def generate_report(self):
        """生成监控报告"""
        self.check_data_freshness(os.path.join(PROJECT_ROOT, "mainline", "data", "industry_heat_daily.json"))
        self.check_data_freshness(os.path.join(PROJECT_ROOT, "data", "industry_heat.json"))
        self.check_fallback_usage(False)  # 假设本次使用正常数据
        
        status = self.get_status()
        
        report = {
            "check_time": datetime.now().isoformat(),
            "status": status,
            "metrics": {
                "akshare_success": self.metrics["akshare_success_count"],
                "akshare_fail": self.metrics["akshare_fail_count"],
                "akshare_timeout": self.metrics["akshare_timeout_count"],
                "fallback_usage_rate": (
                    self.metrics["fallback_usage_count"] / self.metrics["total_data_load_count"]
                    if self.metrics["total_data_load_count"] > 0 else 0
                ),
            },
            "alerts": self.metrics["alerts"][-10:],  # 最近10条告警
            "thresholds": THRESHOLDS
        }
        
        return report


def main():
    """主函数（供cron调用）"""
    monitor = DataQualityMonitor()
    report = monitor.generate_report()
    
    # 输出JSON
    
    # 保存报告
    os.makedirs(HISTORY_DIR, exist_ok=True)
    history_file = os.path.join(HISTORY_DIR, f"quality_report_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    return report


if __name__ == "__main__":
    main()
