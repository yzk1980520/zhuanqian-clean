#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
失效触发器监控脚本
功能：自动监控S3策略失效条件，触发降级或暂停
监控项：
1. 滚动120d胜率<45%
2. S3口径回撤>50%
3. 单股浮盈>30%组合
"""

import schedule
import time
import json
from datetime import datetime, timedelta
from pathlib import Path

class FailureTriggerMonitor:
    def __init__(self, check_interval=1800):
        """
        初始化失效触发器监控器
        
        参数:
            check_interval: 检查间隔（秒），默认30分钟
        """
        self.check_interval = check_interval
        self.trigger_log = []
        self.current_strategy = 'S3'
        self.win_rate_120d = 0.39  # 当前胜率39%
        self.max_drawdown_120d = 0.37  # 当前回撤37%
        self.top_stock_concentration = 0.426  # 中国海油42.6%
        self.top_stock_code = "sh600938"
        self.top_stock_name = "中国海油"
        
    def start_monitoring(self):
        """启动实时监控"""
        print(f"🚀 失效触发器监控启动，检查间隔{self.check_interval}秒")
        print(f"   - 当前策略: {self.current_strategy}")
        print(f"   - 滚动120d胜率: {self.win_rate_120d:.1%}")
        print(f"   - 滚动120d回撤: {self.max_drawdown_120d:.1%}")
        print(f"   - 最大单股权重: {self.top_stock_concentration:.1%}")
        print()
        
        # 立即执行一次检查
        self.check_and_act()
        
        # 定时调度
        schedule.every(self.check_interval // 60).minutes.do(self.check_and_act)
        
        # 持续运行
        while True:
            schedule.run_pending()
            time.sleep(1)
    
    def check_and_act(self):
        """检查并执行降级动作"""
        print(f"[{datetime.now()}] 检查失效触发器...")
        
        actions = []
        
        # 1. 胜率/回撤触发
        if self.win_rate_120d < 0.45 or self.max_drawdown_120d > 0.50:
            action = {
                'type': 'strategy_downgrade',
                'from': self.current_strategy,
                'to': 'S2',
                'reason': f'胜率{self.win_rate_120d:.1%}<45%或回撤{self.max_drawdown_120d:.1%}>50%',
                'timestamp': datetime.now().isoformat(),
                'severity': 'P0'
            }
            actions.append(action)
        
        # 2. 集中度触发
        if self.top_stock_concentration > 0.30:
            action = {
                'type': 'position_reduce',
                'stock': self.top_stock_code,
                'stock_name': self.top_stock_name,
                'action': 'halve',
                'reason': f'单股集中度{self.top_stock_concentration:.1%}>30%',
                'timestamp': datetime.now().isoformat(),
                'severity': 'P1'
            }
            actions.append(action)
        
        # 3. 执行动作
        if actions:
            self.execute_actions(actions)
            self.notify_team(actions)
        else:
            print("✅ 无触发条件，策略正常运行")
        
        return actions
    
    def execute_actions(self, actions):
        """执行降级动作"""
        for action in actions:
            print(f"\n🔴 触发动作: {action['type']}")
            print(f"   原因: {action['reason']}")
            print(f"   严重程度: {action['severity']}")
            
            if action['type'] == 'strategy_downgrade':
                print(f"   动作: {action['from']} → {action['to']}")
                self.current_strategy = action['to']
            
            elif action['type'] == 'position_reduce':
                print(f"   动作: 强制减半 {action['stock_name']}({action['stock']})")
                self.top_stock_concentration /= 2
            
            # 写入触发日志
            self.trigger_log.append(action)
        
        # 保存触发日志
        self.save_trigger_log()
    
    def notify_team(self, actions):
        """通知团队"""
        message = "【失效触发器告警】\n"
        for action in actions:
            message += f"\n- [{action['severity']}] {action['type']}\n"
            message += f"  原因: {action['reason']}\n"
            message += f"  时间: {action['timestamp']}\n"
        
        message += "\n请总管汇总，老六验证拍板。"
        
        print("\n" + "="*60)
        print(message)
        print("="*60)
        
        # 保存到通知日志
        self.save_notification(message)
    
    def save_trigger_log(self):
        """保存触发日志"""
        log_path = Path('output/trigger_log.json')
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump({
                'last_check': datetime.now().isoformat(),
                'current_strategy': self.current_strategy,
                'trigger_count': len(self.trigger_log),
                'triggers': self.trigger_log
            }, f, ensure_ascii=False, indent=2)
        
        print(f"💾 触发日志已保存: {log_path}")
    
    def save_notification(self, message):
        """保存通知日志"""
        log_path = Path('output/notification.log')
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"{datetime.now().isoformat()}\n")
            f.write(message)
            f.write(f"\n{'='*60}\n")
        
        print(f"💾 通知日志已追加: {log_path}")

if __name__ == "__main__":
    # 测试模式：执行一次检查
    monitor = FailureTriggerMonitor(check_interval=1800)
    actions = monitor.check_and_act()
    
    if actions:
        print(f"\n⚠️ 共触发{len(actions)}个动作，请人工确认执行")
    else:
        print(f"\n✅ 无触发，策略正常运行")
