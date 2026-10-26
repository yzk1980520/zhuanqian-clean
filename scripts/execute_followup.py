# -*- coding: utf-8 -*-
"""
执行后续监控 - 综合评估脚本
"""

import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta


PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'data'
LOG_DIR = PROJECT_ROOT / 'logs'


def load_daily_signal() -> dict:
    """加载每日信号"""
    signal_file = DATA_DIR / 'daily_signal.json'
    if signal_file.exists():
        with open(signal_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def load_rank_data() -> list:
    """加载最新排名"""
    # 查找最新的rank文件
    rank_files = sorted(LOG_DIR.glob('rank_*.json'), key=lambda x: x.stat().st_mtime, reverse=True)
    if rank_files:
        with open(rank_files[0], 'r', encoding='utf-8') as f:
            return json.load(f).get('items', [])
    return []


def calculate_remaining_days() -> int:
    """计算冷却期剩余天数"""
    cooldown_file = DATA_DIR / 'cooldown.json'
    if cooldown_file.exists():
        with open(cooldown_file, 'r', encoding='utf-8') as f:
            cooldown = json.load(f)
            end_date = datetime.strptime(cooldown.get('cooldown_end', '2026-09-28'), '%Y-%m-%d')
            today = datetime.now()
            return max(0, (end_date - today).days)
    return 0


def generate_alert(level: str, message: str) -> dict:
    """生成告警"""
    return {
        'level': level,  # 'info', 'warning', 'critical'
        'timestamp': datetime.now().isoformat(),
        'message': message
    }


def main():
    
    # 1. 加载数据
    signal = load_daily_signal()
    rank_data = load_rank_data()
    remaining_days = calculate_remaining_days()
    
    # 2. 分析市场状态
    market_score = signal.get('market_score', 0)
    gate_status = signal.get('gate', {}).get('status', 'unknown')
    position_ratio = signal.get('gate', {}).get('position_ratio', 1.0)
    
    print(f"\n📈 市场状态:")
    print(f"   综合评分: {market_score}/100")
    print(f"   环境门: {gate_status}")
    print(f"   建议仓位: {int(position_ratio*100)}%")
    
    # 3. 分析候选股
    print(f"\n🎯 TOP5候选股:")
    top5 = rank_data[:5] if rank_data else []
    for i, stock in enumerate(top5, 1):
        score = stock.get('final_score', 0)
        code = stock.get('code', '未知')
        name = stock.get('name', '未知')
        status = "⭐推荐" if i == 1 and score >= 70 else "✅" if score >= 70 else "⚠️"
        print(f"   #{i} {code} {name}: {score:.1f}分 {status}")
    
    # 4. 计算冷却期
    print(f"\n📅 冷却期状态:")
    print(f"   剩余天数: {remaining_days}天")
    print(f"   状态: {'⏸️ 观望中' if remaining_days > 0 else '✅ 可交易'}")
    
    # 5. 评估触发条件
    alerts = []
    
    # 条件1: 市场评分≥60
    if market_score >= 60:
        alerts.append(generate_alert('info', f'市场评分已达{market_score}分，进入强势区间'))
    
    # 条件2: TOP1评分≥70且市场信号强化
    if top5 and top5[0].get('final_score', 0) >= 70 and market_score >= 50:
        alerts.append(generate_alert('warning', f'TOP1候选{top5[0]["name"]}评分{top5[0]["final_score"]:.1f}分，信号强度提升'))
    
    # 条件3: 冷却期即将到期
    if remaining_days <= 2 and remaining_days > 0:
        alerts.append(generate_alert('warning', f'冷却期仅剩{remaining_days}天，准备重新评估'))
    
    # 条件4: 冷却期已满
    if remaining_days == 0:
        alerts.append(generate_alert('critical', '冷却期已满，可启动新信号！'))
    
    # 6. 输出告警
    if alerts:
        print(f"\n🚨 触发告警 ({len(alerts)}条):")
        for alert in alerts:
            icon = {'info': 'ℹ️', 'warning': '⚠️', 'critical': '🔴'}[alert['level']]
            print(f"   {icon} [{alert['level'].upper()}] {alert['message']}")
    else:
        print(f"\n✅ 无触发条件，继续观望")
    
    # 7. 生成决策建议
    print(f"\n💡 决策建议:")
    if remaining_days == 0:
        pass
    elif remaining_days <= 2:
        pass
    elif market_score >= 60 and top5 and top5[0].get('final_score', 0) >= 80:
        pass
    else:
        pass
    # 8. 保存报告
    report = {
        'scan_time': datetime.now().isoformat(),
        'market_score': market_score,
        'gate_status': gate_status,
        'position_ratio': position_ratio,
        'remaining_cooldown_days': remaining_days,
        'top_candidates': top5,
        'alerts': alerts,
        'recommendation': 'buy' if remaining_days == 0 else 'watch'
    }
    
    report_file = LOG_DIR / f"monitor_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 报告已保存: {report_file}")
    
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
