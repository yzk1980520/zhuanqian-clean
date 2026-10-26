# 【评审报告】t_c5e890f8 双源收尾 L2 签批执行 — 老五追溯复审

- 评审人：老五（laowu，R0 独立评审）
- 复审卡：t_9487d0ae（规则15 §四.5 独立成卡；存量清 t_b07a0064 补录）
- 时间：2026-10-23 02:35（CST）
- 引擎/树版本：当前树 HEAD = `bce1474f`（= L2 落地面；L2 两 commit = `3e6389b2` + `bce1474f`，均已并入 github-main）
- 复审性质：**追溯复审**（原单 comment 线程仅有 L2 催签批 + 总管侧执行报告，无 L2 实质复审件；按挂账口径由老五补做）

## 结论：✅ 通过（A/B/C/D 四项 + R0 红线 + P0 止血完整性 + 回归基线 + sanity gate，全绿，L2 无新增 FAIL）

## 一、变更面核验（AC1：未签批项不得带入）

命令：`git diff --name-only 3e6389b2^ bce1474f`
输出（全量 10 文件，逐项归属）：
| 文件 | 归属签批项 |
|---|---|
| .gitignore | C |
| scripts/daily_auto.bat | D |
| archive/scripts-data-20261023/*（8 文件，bce1474f） | B |

- 不含 daily_pick / trade_tracker / cron_message_sender / factor_* / orchestrator / risk_rules → **A 项为纯校验结论（根侧 shim 已覆盖，零合入），B/C/D 变更面精确，未签批项 0 带入** ✅
- 提交链：`...→ba23058d(S5)→42fce041/111e8749(S6 docs)→3e6389b2(L2)→bce1474f(L2-B)=HEAD`；`git merge-base --is-ancestor` 两 commit 均为 HEAD 祖先 ✅

## 二、A 项：WIP 补入根侧 — 逐组核验（根侧 7 行 vs 执行报告）

实测（@bce1474f）：
- `cron_message_sender.py` 含 `SUPPRESS_WINDOW_P0_MIN` ×3（P0 告警分层在根侧）✅ 不覆盖结论成立
- `evolution_loop.py`=S5 shim→core.ops；`factor_gate_v2/factor_registry/tdx_score_original`=S3 shim→core.scoring；`orchestrator.py`=S4 shim→core.pipeline（archive/root-py-batch3 为 10-17~10-19 旧版全量，根侧经基地化后更新）✅ 不合并结论成立
- `_p0_2_refresh_sh_index.py` 根侧不存在 → 跳过 ✅
- 止血内容存留核验：`core/pipeline/daily_pick.py` W1 退出码语义文档在（L7）、`return 3` 在（L181，门禁拦截≠成功）、132d 精确口径在（L109/L129）✅

## 三、B 项：scripts/data/ 双份判定

- `ls scripts/data/` = 不存在（已删除）✅
- `bce1474f` stat = 8 文件入 `archive/scripts-data-20261023/`（alert_log/final_health_check/health_check_report/laowu_review_20261006/market_state_cache/message_queue/risk_report_latest/s3_monitor_log），351 insertions ✅
- 判据可溯：根侧 data/ mtime 10-22~10-23 > scripts 侧 04:42-04:45 批次（10-20）→ 根侧为准 ✅

## 四、C 项：.gitignore `scripts/*` 去除

- `grep -n "^scripts/" .gitignore` → 仅 L220 `scripts/.trash/`（特定目录白名单），全量 `scripts/*` 行已删 ✅
- `grep -c "^!" .gitignore` = 174（白名单全保留，与执行报告一致）✅
- `git check-ignore -q scripts/auto_live_pipeline.py` → not ignored（`visible-to-git`）；`git ls-files scripts/` = 64（git index 内）✅（"456 被忽略"为 L2 前历史口径，不作复验目标）

## 五、D 项：老六遗留 3 签批点 + D-巡检

`git show 3e6389b2 -- scripts/daily_auto.bat`：
- 路径B门禁 fail-safe：`data/review_status.json` 现值 `gate_passed=False` + `freeze_unlocked=True` + `final_verdict=PASS` → 门禁未过即阻断出票，因子层关闭时仍保守 ✅
- bat①退出码：新增 `set "RC=%ERRORLEVEL%"` + 日志行带 `(RC=%RC%)` + `exit /b %RC%`（python 退出码透传，防 echo 吞 0）✅
- bat②解释器：`C:\Users\WIN10\...\Python311\python.exe` → `D:\open code\zhuanqian\.venv\Scripts\python.exe` ✅
- D-巡检可复算：`data/review_status.json` mtime=10-23 01:37:29（与记录 01:37 一致）；sha256 前 12 位实测 `4b59edbfe0ca` = 记录哈希 ✅

## 六、R0 红线 + P0 止血完整性

- `risk_rules.py` blob：`git rev-parse 12b791e8:risk_rules.py bce1474f:risk_rules.py` 均 = `bcca8cd198f109873c925e57e94f8e84dfb3e7af`（与 10-22 t_92c5a111 评审记录 bcca8cd1 数字守恒一致）✅ 未动
- `trade_tracker.py`：12b791e8 根侧（止血版）vs bce1474f core/ops 版，diff 排除 import/PROJECT_ROOT/atomic_json 改写后 = **空** → S5 纯机械改写、止血语义忠实迁移 ✅
- L2 两 commit 变更面不含上述任一文件 ✅

## 七、回归基线复算（引擎版本=当前树 bce1474f，2026-10-23 02:33）

- 4FAIL 定向复跑：`pytest tests/test_b3_gate_consumers.py tests/test_pipeline_equivalence.py tests/test_integrated_picker.py`
  → **4 failed, 23 passed in 3.97s**：test_b3_gate_consumers×2（dead_nested_read + gate_consumers_converge）+ test_pipeline_equivalence×1（test_import_pipeline）+ test_integrated_picker×1（test_l2_gap_filter）
  = 执行报告声明的 4FAIL 集合**逐件一致**，L2 无新增 FAIL（FAIL 根因归 S2 基地化引入，github-main 基线一致）✅
- sanity gate：`run_sanity_gate_cron.py --force`（PYTHONPATH 清空，.venv 解释器）→ **exit 0，19 项全 PASS**（变体=12、单股占比 2.9%、退市覆盖自证 0 缺口；日志 logs/sanity_gate_cron_20261023_022701.log）✅

## 八、观察项（非阻断，移交总管/S6 处置）

1. [R2] 其余 cron .bat 解释器未随 D② 统一：`scripts/Zhuanqian_SanityGate.bat` 仍指系统 Python（`C:\Users\WIN10\...\Python311`）；D 签批点仅覆盖 daily_auto.bat。建议 S6 统一切 .venv。
2. [R2] `archive/scripts-data-20261023/factor_registry`（目录）为 S5 恢复测试依赖（ba23058d）所入，非 L2-B 8 文件口径，引用时勿混。
3. [R1 提示] `core/ops/trade_tracker.py` 现含 R4(P0-3 Option B) Supabase 增量推送（`_push_to_supabase` L228/238/247，失败静默降级）——经比对为 12b791e8 止血版本既含语义、非 S5/L2 引入，**不构成红线违规**；但"Supabase 通道是否应彻底关闭"属止血语义解释权，建议总管在 S6 裁定时一并落口。
4. [R2] `data/review_status.json` 受 git 跟踪（blob@bce1474f=2922e313）而工作树 01:37 内容未随 L2 commit 入库（sha256 前缀 4b59edbfe0ca）——数据目录版本化与运行时漂移为既有口径，S6 双源收敛时建议统一裁定 data/ 跟踪策略。

## 九、适用边界

本评审证据截至 2026-10-23 02:35（HEAD=bce1474f）。其后任何新 commit（含 S6 risk_rules 迁移）将使第七节回归基线失效，需以新引擎版本重跑。
