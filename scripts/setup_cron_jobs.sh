#!/bin/bash
# Cron任务配置脚本
# 用于配置5次关键跃迁的定时任务

echo "========================================"
echo "配置AI Agent量化系统Cron任务"
echo "========================================"

# 进入项目目录
cd "D:/open code/zhuanqian"

# 创建Cron任务配置目录
mkdir -p cron/jobs

# 定义Cron任务
echo ""
echo "【Cron任务配置】"

# 任务1: IC复利效应监控（每日17:00）
echo "1. IC复利效应监控 (0 17 * * 1-5)"
echo "   - 监控因子IC衰减情况"
echo "   - 生成IC复利效应报告"
echo "   - 触发失效因子替换"

# 任务2: 多Agent协同选股（每日15:00）
echo ""
echo "2. 多Agent协同选股 (0 15 * * 1-5)"
echo "   - 运行智能选股增强流水线v2.0"
echo "   - 生成TOP10选股结果"
echo "   - 输出交易计划"

# 任务3: OOS凸性风险检查（每日16:00）
echo ""
echo "3. OOS凸性风险检查 (0 16 * * 1-5)"
echo "   - 检查策略过拟合风险"
echo "   - 评估In/Out样本夏普比率"
echo "   - 生成风险报告"

# 任务4: 实盘闭环迭代（每周日晚20:00）
echo ""
echo "4. 实盘闭环迭代 (0 20 * * 0)"
echo "   - 收集本周交易数据"
echo "   - 计算损失梯度"
echo "   - 更新策略参数"

# 任务5: 系统健康检查（每日08:00）
echo ""
echo "5. 系统健康检查 (0 8 * * 1-5)"
echo "   - 检查Gateway状态"
echo "   - 检查数据新鲜度"
echo "   - 检查门禁状态"

echo ""
echo "========================================"
echo "配置完成！请手动添加到hermes cron"
echo "========================================"
echo ""
echo "使用方法："
echo "  hermes cron create '任务名' --cron '调度表达式' --workdir '工作目录' --prompt '执行命令' --deliver local"
echo ""
echo "示例："
echo "  hermes cron create 'IC复利监控' --cron '0 17 * * 1-5' --workdir 'D:/open code/zhuanqian' --prompt 'python scripts/ic_compound_monitor.py' --deliver local"
