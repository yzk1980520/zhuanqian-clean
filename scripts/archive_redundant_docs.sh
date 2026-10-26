#!/bin/bash
# 文档归档脚本 - 清理冗余文档到 archive/
cd "/d/open code/zhuanqian/mainline/docs"

ARCHIVE_DIR="archive"
mkdir -p "$ARCHIVE_DIR"

# 1. 归档旧版报告（9月15日及之前）
echo "=== 归档9月15日及之前旧报告 ==="
for f in *2026090[1-5]*.md *2026091[0-5]*.md; do
    [ -f "$f" ] && mv "$f" "$ARCHIVE_DIR/" && echo "  Moved: $f"
done

# 2. 归档 Compsio 配置报告
echo "=== 归档Compsio配置报告 ==="
for f in Composio*.md KIMI*.md Kimi*.md; do
    [ -f "$f" ] && mv "$f" "$ARCHIVE_DIR/" && echo "  Moved: $f"
done

# 3. 归档 P0 版本迭代稿（保留 v14）
echo "=== 归档P0版本迭代稿 ==="
for f in P0任务执行最终报告-20260913-v*.md; do
    [[ "$f" == *"v14"* ]] && continue
    [ -f "$f" ] && mv "$f" "$ARCHIVE_DIR/" && echo "  Moved: $f"
done

# 4. 归档回测诊断版本稿
echo "=== 归档回测诊断版本稿 ==="
for f in backtest-hang-diagnosis-20260917-v*.md; do
    [ -f "$f" ] && mv "$f" "$ARCHIVE_DIR/" && echo "  Moved: $f"
done

# 5. 归档 Mem0/Langfuse 配置报告
echo "=== 归档Mem0/Langfuse报告 ==="
for f in mem0*.md Langfuse*.md; do
    [ -f "$f" ] && mv "$f" "$ARCHIVE_DIR/" && echo "  Moved: $f"
done

# 6. 归档其他冗余报告
echo "=== 归档其他冗余报告 ==="
for f in bot-config* bot-free-model* cron_optimization* daily_summary_2026090[3-5]* daily_summary_2026091[0-2]* factor_winrate_diagnosis* gateway-auto-restart* hermes-auto-upgrade* hermes-upgrade* api-server-key* consensus_score*.json moa-final-verdict* sim-tracking-three-way-consensus*.md provider_health_monthly* resumen_optimizacion* exo-project-detection* factor_ic_fix_proposal* gateway-auth-diagnosis* gateway-auth-deep-diagnosis* gateway-auth-final-diagnosis* gateway-diagnosis* backtest_memory_check* backtest_status_update* web*; do
    [ -f "$f" ] && mv "$f" "$ARCHIVE_DIR/" && echo "  Moved: $f"
done

# 7. 归档辩论报告
echo "=== 归档辩论报告 ==="
for f in 三方辩论*.md 辩论*.md 辩论启动通知*.md; do
    [ -f "$f" ] && mv "$f" "$ARCHIVE_DIR/" && echo "  Moved: $f"
done

echo ""
echo "=== 归档完成 ==="
echo "Archive目录文件数: $(ls -1 "$ARCHIVE_DIR" | wc -l)"
echo "主目录文件数: $(ls -1 *.md *.json 2>/dev/null | wc -l)"
