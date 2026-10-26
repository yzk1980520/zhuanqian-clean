#!/bin/bash
# 网关问题监控 + 催办脚本
# 每3分钟检查一次，当网关话题结束后自动催办

CHAT_ID="oc_100a06a1c71d5f8b1e58f1e420cadd1a"
LOG_FILE="docs/gateway-monitor.log"
REMINDER_SENT=false

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 启动网关话题监控..." >> "$LOG_FILE"

while true; do
    # 获取最新消息
    msgs=$(lark-cli im +messages-search --chat-id $CHAT_ID --limit 10 2>/dev/null)
    
    # 检查最后一条消息的时间和内容
    last_msg=$(echo "$msgs" | jq -r '.data.messages[0] // empty' 2>/dev/null)
    
    if [ -n "$last_msg" ]; then
        last_time=$(echo "$last_msg" | jq -r '.create_time' 2>/dev/null)
        last_sender=$(echo "$last_msg" | jq -r '.sender.name' 2>/dev/null)
        last_content=$(echo "$last_msg" | jq -r '.content' 2>/dev/null | head -c 100)
        
        # 检查是否还在讨论网关
        if echo "$last_content" | grep -qE "网关|gateway|重启|监控|计划任务|watchdog"; then
            current_status="网关讨论中"
        else
            current_status="网关讨论结束"
            # 检查是否需要催办
            if [ "$REMINDER_SENT" = "false" ]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] 检测到网关讨论结束，发送催办消息..." >> "$LOG_FILE"
                
                # 发送催办消息
                lark-cli im +messages-send --chat-id $CHAT_ID --text "📢 【催办】系统优化讨论

网关问题已处理完毕，请三方回到**系统优化讨论**：

📋 议题：胜率39%如何突破40%？
⏰ 截止：今日20:00（约$(($(20-$(date +%H)))小时)后）

请@老三 @老五 @牛马 按格式发言：
- 老三：技术可行性
- 老五：合规风险
- 牛马：市场情绪

详细框架：docs/team-discussion-framework-2026-09-30.md" 2>/dev/null
                
                REMINDER_SENT=true
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] 催办消息已发送" >> "$LOG_FILE"
            fi
        fi
        
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] $last_sender: $current_status - ${last_content:0:50}..." >> "$LOG_FILE"
    fi
    
    sleep 180  # 3分钟后再次检查
done
