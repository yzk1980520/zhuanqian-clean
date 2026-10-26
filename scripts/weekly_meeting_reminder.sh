#!/bin/bash
# 三方周会提醒 - 每周日发送周会提醒
# 提醒内容：每周一三方会议 + 本周工作总结

set -e

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_FILE="logs/weekly_meeting_reminder.log"
REPORT_FILE="mainline/docs/周会提醒-$(date '+%Y%m%d').md"

# 确保日志目录存在
mkdir -p logs
mkdir -p mainline/docs

echo "[$TIMESTAMP] === 周会提醒脚本开始执行 ===" >> "$LOG_FILE"

# 生成周会提醒内容
cat > "$REPORT_FILE" << EOF
# 三方周会提醒

**时间**: $TIMESTAMP
**周期**: 每周日提醒，周一开会

---

## 一、会议信息

| 项目 | 内容 |
|------|------|
| 会议时间 | 每周一 09:00 |
| 参会人员 | 老大、总管、老三、老五 |
| 会议形式 | 飞书群组讨论 |

---

## 二、本周待回顾事项

### 2.1 系统状态
- [ ] Gateway运行状态
- [ ] Cron任务执行情况
- [ ] 飞书连接状态
- [ ] 回测任务进度

### 2.2 持仓监控
- [ ] 当前持仓情况
- [ ] 止损止盈状态
- [ ] 环境门状态

### 2.3 项目进展
- [ ] Phase 1完成状态
- [ ] Phase 2验证进度
- [ ] 新因子权重效果

---

## 三、议程建议

1. **系统健康检查**（5分钟）
   - Gateway/Cron/飞书状态
   - 失败任务复盘

2. **持仓回顾**（10分钟）
   - 本周交易记录
   - 止损止盈触发情况
   - 浮盈浮亏分析

3. **项目进展**（15分钟）
   - Phase 1完成情况
   - Phase 2验证结果
   - 下周计划

4. **问题讨论**（10分钟）
   - 技术障碍
   - 策略调整建议
   - 资源需求

---

## 四、会前准备

- [ ] 检查本周数据完整性
- [ ] 准备回测结果报告
- [ ] 整理问题清单
- [ ] 提前发送会议议程

---

**生成时间**: $TIMESTAMP
**下次提醒**: 下周日

EOF

echo "[$TIMESTAMP] ✅ 周会提醒报告已生成: $REPORT_FILE" >> "$LOG_FILE"

# 输出报告路径（供cron delivery使用）
echo "周会提醒已生成: $REPORT_FILE"

echo "[$TIMESTAMP] === 周会提醒脚本执行完成 ===" >> "$LOG_FILE"
