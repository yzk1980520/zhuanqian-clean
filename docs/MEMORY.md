
## 飞书端问题联动审查 (2026-10-23)
### 已修复
1. LHB Cron job: enabled=true, state=active, paused=None, streak=0 ✓
2. Cron streak重置: 17✅ 0❌ 0⏸️ ✓
3. lhb_backfill.py在hermes-home/scripts/已存在+验证 ✓
4. profile_routes: zongguan配置完整 (zongguan/laosan/laowu/niuma→oc_032fc) ✓

### 根因
- Gateway 20:59→05:35休眠退出(VM休眠非崩溃)
- kanban dispatcher 08:03-08:28 71ticks卡死, zombie worker reaped后恢复
- gate_check失败: 因子数据滞时9天 (factor=10-05, daily=10-14)
- worktree_leak: opencode仓库11行未提交+arithmetic.txt缺失
- LHB job暂停: jobs.json enabled字段被覆盖

### 需跟进
- 老三: 刷新因子数据
- 老四: 提交opencode仓库变更
- 总管: 监控kanban+LHB 17:30 tick
