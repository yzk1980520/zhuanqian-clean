# 技术债台账（Tech Debt Ledger · 活台账）

> **复启用**: 2026-10-26 老三（t_ed0f8ec8）——原台账（2026-10-16 总管建立，D-1…D-12，末条 D-12 于 2026-10-17 闭环）已于 2026-10-22 清理归档至 `docs/archive/20261022-cleanup/tech_debt_ledger.md`（历史条目以归档版为准，不再追加）。本文件复启用为活台账，自 **D-13** 起续号。
> **消费方（读侧断言 §2.9）**: 继承归档版口径——闭环健康度日报每日读本台账，输出「未销账技术债 N 条」进 daily_signal；某债 7 天无 owner 进展 → P1 告警（QSP_MsgDrain 队列）。
> **格式**: 每债含 编号/描述/挂账时间/owner/优先级/销账判据（可断言）/进展（依据 AGENTS.md §4.1 规则 12 回授断言注册铁律：写侧动作必须同时注册读侧消费断言）。

---

## D-13 resume-then-settle 升级触发的读侧消费断言（t_2ed8d608 冻结稿 v2 挂账）

- **描述**: R0 提案「kanban dispatcher resume-then-settle」已冻结（v2 = `deliverables/resume-then-settle-设计冻结稿-v2-20261026.md`，老五 R0 设计评审 ✅ 通过附条件签字 C1–C4，v2 已折叠 C1–C4 + R2 双树前置门禁）。提案不排期实施，升级触发 = **第二次 TUI-1013 级联 crash**（首起 = 10-22 04:58 run 662，30 天仅 1 起）。升级触发是「等待事件」型写侧承诺（冻结稿 §6 宣告触发后由总管评估排期、实施仍走老五 R0 评审），按规则 12 必须注册读侧消费断言，否则「等第二次 1013 才动工」无人盯守 = 未完成的闭环。
- **挂账**: 2026-10-26 老三（t_ed0f8ec8 A7）
- **owner**: 总管（消费方/巡检责任）；销账 = 触发后总管排期实施并合并 v2，或触发条件作废后总管关账
- **优先级**: P2
- **读侧消费断言（规则 12 九字段登记）**:
  - **触发事件** = 第二次 TUI-1013 级联 crash（kanban.db task_runs 现 `exit_kind=nonzero_exit code=1` + worker_output 含「turn outcome is unknown」且同窗网关 drain/1013 日志成立）
  - **消费方** = 总管每日 1013 级联事件巡检（读 kanban.db task_runs + 宿主网关日志 drain/1013 痕迹）
  - **消费周期** = 每日
  - **失败告警路径** = 巡检失败（未巡/漏巡）或触发事件成立而未排期 → 写 `data/message_queue.json` P1（QSP_MsgDrain 投递飞书）
- **销账判据（可断言）**: ① 触发事件成立且总管已排期实施（kanban 新实施卡 + 老五 R0 评审链在案）；或 ② 基准树 commit 漂移/提案作废，总管裁定关账（本条标注作废原因）
- **进展**: 2026-10-26 挂账（t_ed0f8ec8）；双处登记 = 本条 + 冻结稿 v2 §6「§触发断言」；每日巡检自 2026-10-27 起算周期（`data/message_queue.json` 活文件在案，mtime 2026-10-26 06:18 实证）

---

## D-14 data_flow_audit 告警读侧契约登记（t_cd7dab36 写侧契约修复 · §4.1-12 读侧断言）

- **描述**: data_flow_audit P2/P0 告警旧写侧 = 裸 `message` 字段 + 整表孤儿 payload（19,340 项 ≈1.2MB/条），
  而读侧 `cron_message_sender._render_content`（L334-346）只认 `content`/`msg`/`title+body` → 每日 21:00 告警恒
  unrenderable → 2026-10-26 晨 01:44/01:49/02:44 三条死信（`data/drain_dead_letter.jsonl`）+ 队列膨胀。
  且 SC-005-v2 判据已 PASS（8/177=4.52%<5%）仍按旧裸口径告警 = 告警逻辑未跟进 t_2680636c 口径变更。
  本次修复（t_cd7dab36，`scripts/data_flow_audit.py`）：① 队列条目 `content`（非空字符串，"[level] message" 格式）
  为唯一渲染源（弃用裸 `message`，字段形态与 `core/ops/message_queue.py::add_message` L30 `content` 字段一致，
  2026-10-26 队列生产方字段普查确认无冲突）；② P2 仅在判据未显式通过时触发（pass=True 静默，判据版本缺失/
  无法判定 → 保守告警）；③ payload = top-20 孤儿样本 + `orphan_count` 总数（单条 <8KB，`_orphan_payload`）；
  ④ P0 孤儿消费者告警触发不变，payload 同步紧凑化。
- **挂账**: 2026-10-26 老三（t_cd7dab36）
- **owner**: 老三（写侧）/ 总管（老五评审+验收后销账）
- **优先级**: P2（死信风暴根因已修，防复发登记）
- **读侧消费断言（规则 12 登记）**:
  - **触发事件** = `python scripts/data_flow_audit.py`（QSP_DataFlowAudit，每日 21:00）向 `data/message_queue.json` 写 data_flow_audit 条目
  - **消费方** = QSP_MsgDrain 计划任务（每 5 分钟读队列 → `_render_content` 渲染 → 飞书投递）
  - **消费周期** = 5 分钟（drain 轮次间隔）
  - **失败告警路径** = ① 条目 unrenderable → `data/drain_dead_letter.jsonl` 死信（当日可计数核对）；② 队列剩余 > `BACKLOG_THRESHOLD`=10（`cron_message_sender.py` L73）→ 积压 P0 告警（`data/alert_log.jsonl` + drain.log）
  - **断言脚本** = `tests/test_data_flow_audit_alert_contract.py`（机判 9 件：content 契约×2 / payload<8KB×2 / 判定表 / 合成 pass=True 静默 / 合成 pass=False 告警 / 临时台账端到端 / P0 紧凑化；回归基线对照）
- **销账判据（可断言）**: ① 回归无新增失败（对照基线）且上述断言全绿；② 判据 pass=true 态实跑 `scripts/data_flow_audit.py` 后 `data/message_queue.json` 无新增 data_flow_audit 条目（静默验证）；③ 判据 pass=false 场景新条目 `content` 非空且 `_render_content` ok=True（单测）
- **进展**: 2026-10-26 挂账 + 写侧修复同卡落地（t_cd7dab36，commit 见该卡交付物）；待老五评审 + 总管验收后销账

---

## D-15 因子对齐：config.json factor_weights 16 因子未被 132d 活跃注册表覆盖

- **描述**: `tests/test_factor_ic.py::TestFactorFunctions::test_missing_config_factors` 红。config.json factor_weights 16 因子（breakout_strength/amount_q_reversal/std20/max_ret5/vol_price_corr_20/fund_flow_intensity/rsi14/capital_flow/momentum_reversal/unlocked_pressure/pos_vs_ma20/volatility_breakout/sector_correlation/alpha13/chg5_rev/vol_shrink20）不在 `scripts/factor_ic_132d_refresh.FACTOR_FUNCTIONS`（31 因子活跃真源）。关联 P1#5 三因子入管线（7421f09c/35985d0d）与 R0 t_7e2fa56a 开关拍板、74 因子翻转未 apply 权威源。
- **挂账**: 2026-10-26 老三（t_039f1e18 分诊）
- **owner**: R0（t_7e2fa56a 开关）/ 总管
- **优先级**: P1
- **销账判据**: R0 开关后该项转绿（config 因子 ⊆ 活跃注册表）或 config 因子集收缩
- **审查判定 2026-10-27（总管 L2 复审 D-15 执行件，一手证据）**：回归 4 红定性=missing_config 预期红(12 件)+cron 2 状态红+**feishu message_id_tracking P1 回归=我入队诱发**（队列实样 B 形 `alert_id/severity/timestamp`，测试断言 A 形 `id/priority/ts/sent`；`queue_integration.add_alert`=A 写、`closedloop_daily_report L142`=B 转写、drain `cron_message_sender L457` 双形容忍→投递无损，仅测试契约过严）→ **t_d534f905**（P1 测试断言 A∪B 兼容，零行为变更）；K 门禁 8/8 vs 期望≥10=**存量**（10-26 19:00 周刷新掉 2 件，`factor_ic_latest.json` top 级 strict_valid_count=None 走内部聚合）+ L review_status=17 陈旧缓存=存量 → **t_3721cb93**（P2 批次：registry 4 件弃用标记+K 掉件 diff+L 写环定位+②probe 证据件入树，与 t_eeb6dd63 universe 72 缺失并案同源嫌疑）；drift 守卫 WARN "known 有 config 无={4 弃用件}"=**预期 WARN**（registry 标记补齐后语义闭环）
- **拍板执行 2026-10-27（老大「执行」授权，总管 E 层落地）**: config.json factor_weights **收缩 24→20 键**：删 rsi14/vol_shrink20（①双 dead 弃用）/vol_price_corr_20（②代理证据=IR 双不过弃用阵营）/capital_flow（③无本机数据源死件）——均 weight=0 零行为变更（读口 tdx_strategies L631 dict.update 语义实证），备份=config.json.bak_20261027_d15。缺失集 test_missing_config_factors 16→**12**（=t_e16c5039 补跑目标集，4 件弃用项已出集实证）；**D-15 销账尾步=t_e16c5039 12 件入表后缺失集归 0 复绿**
- **✅ 销账 2026-10-27（总管验收 t_e16c5039 后裁定）**：销账判据双路全满足——(a) config 因子集收缩已执行（24→20 键）；(b) R0 开关态 factor_layer_enabled=True（已放行）+ test_missing_config_factors 归 0 复绿（12 件入表=t_e16c5039 ecf4429f 权威源 86 因子刷新@01:01 20/20 覆盖）。①弃用✓ ②等价关闭✓ ③14 件处置✓（4 弃用出 config+registry 弃用标记在途 t_3721cb93、12 入表、volatility_breakout 恢复件=12 件内、capital_flow 死件弃用）。**D-15 CLOSED**（读侧断言：明日 08:30 S3 出票 gate 8/8 绿 + missing_config_factors 绿 = 持续闭环，任一红=重开）
- **材料交付 2026-10-26（t_e4e16aa2 A 照交, commit 3ebdfa5e）**: `deliverables/D-15-因子对齐决策材料-20261026.md` 91行 16/16 全覆盖（窗口 132d/asof 2026-10-23/引擎 pure_python_v10_exact_132d@75ce2b0e 已声明）；关键事实=门禁 0/16 过、RSI14/VOL_SHRINK20 双 dead（大小写异名+IC/IR 不过）、vol_price_corr_20 无数据但候选等价 PV_CORR20（IR 差 0.0126/t_nw=-3.30，同源等价性**待 R0 拍板**）、N=14 无数据建议列仅"补数据/弃用"（fail-close）；**拍板三问=①RSI14/VOL_SHRINK20 弃用? ②PV_CORR20==vol_price_corr_20 等价? ③14 件挂账处置**；补数据在途=t_e16c5039（12 旧引擎提升+capital_flow 死件+volatility_breakout 恢复评估）；台账「31 因子真源」=陈旧口径（现 74），随批刷
- **② 裁定关闭 2026-10-27（老五 t_09b7f561 独立核验，报告 `deliverables/D-15②-PV_CORR20与vol_price_corr_20等价性核验-老五-20261027.md`）**: **计算等价**（公式/窗口/符号/数据源四维逐项一致；E1 实函数 30/30 absdiff=0.0、E2 末30日逐日 IC Δ=0.000000、E5 harness 10/10 逐位相等；证据=卡附件 phase1/phase2 json+probe_d15_2.py 可复跑；引擎 @e1ac573f/数据截至 2026-10-23）。**代理证据生效**：PV_CORR20（ic=-0.0487/IR 差 0.0126/dead）可作 vol_price_corr_20 引用，「需 R0 裁定」关闭；**单调性仍未证实**（保留该因子须补单调性复跑，材料 §四 前置；现权重 0 已失活，本裁定零现网影响）。两边界差（≥21 vs ≥20 根、零方差 None 剔除 vs 0.0 填充）生产不可达+132d 实测 0 触发。失效触发（报告 §五.3）：任一实现代码 hunk / 数据源换源换单位 / MIN_BARS 或调用方最小根数变更使 20-21 边界可达 → 结论作废复验
- **补数据交付 2026-10-27（老三 t_e16c5039, commit ecf4429f（rebase 前 bcb915c2）+ 台账 09d18a0e）**: 12 件（11 件旧评分层逐字提升+volatility_breakout 恢复件）入 132d 注册表 scripts/factor_ic_132d_refresh.FACTOR_FUNCTIONS（smoke 逐值对照 tdx_indicators absdiff=0，异常吞噬=0；sector_correlation 修复旧实现失效路径=修复项非漂移）；权威源 factor_ic_latest.json @6bd63fa3（86 因子，132/132 日，universe 1226 纯净口径，旧版 @75ce2b0e 已归档 factor_ic_latest_20261027_010036.json，指纹留痕）；**config 20 键覆盖 20/20，test_missing_config_factors 缺失集归 0 复绿（L57 销账尾步达成）**；门禁 4/4 过=3 件（alpha13 +0.0354/amount_q_reversal -0.0588/volatility_breakout -0.0521），momentum_reversal 3/4（IC 差 0.0005），余 8 件 dead 如实留态；12 件经 FactorRegistry 类方法登记（ic_mean=None 隔离，老五回填区 31 件零漂移）；回归 F0/F1 双跑 diff 零新增红（26→25 failed，唯一差=本卡销红项）；交付=deliverables/D-15-补数据报告-20261027.md；**D-15 销账待 R0 gate 放行裁夺（见报告 §5 悲观场景与失效触发）**
- **附带发现 P2 挂账（老五报告 §六，不阻塞②裁定）**: ①陈旧注释 2 处（refresh L515 _pv_corr20 docstring「Spearman 近似」失真=原始值 Pearson 无 rank；tdx_score_original L1002「vol_price_corr_20 已取负号」错误=仅 alpha13 取负）②72 只 universe 文件缺失（1556→1484，sh600068/0004/0006/0007/0008…，10-26 探针在册 vs 当前 data/history_daily 无文件）③槽窗位移记录在案（今日 _load_universe(2000) 仅 1226 只，周调度 --max-stocks 1000 与权威源 2000 槽口径不同，下次 132d 周刷新 G-B 守卫判读注意）

## D-16 quick_ic_sample.json 快照缺失（5 测试已跟随跳过）

- **描述**: TestQuickSample×3 + TestICConsistency×2 依赖该一次性快照：从未 git 跟踪、无活跃写者（生产者 direct_ic_calc.py 10-23 归档）。t_039f1e18 已加 skipif+原因（跟随数据非静默）；4 因子 IC 监控现走 factor_ic_daily_monitor + 132d 权威源。快照是否重造（新写者+重生成）或正式作废 = 拍板项。
- **挂账**: 2026-10-26 老三（t_039f1e18 分诊）
- **owner**: 总管；**优先级**: P2
- **销账判据**: 拍板重造（写者在案 + 文件恢复 + 5 测试解除 skip）或作废（skip 注明作废，条目关账）

## D-17 NOUS_API_KEY 缺失（model config 测试红）

- **描述**: `tests/test_model_config.py::test_all_provider_env_keys_exist` 红：config custom_providers[1] nous-portal-free 引用 NOUS_API_KEY，全局+8 profile 的 .env 均缺失（根因已坐实）。
- **挂账**: 2026-10-26 老三（t_039f1e18 分诊）
- **owner**: 老大/总管拍板；**优先级**: P1
- **拍板选项**: A 提供 key 入 .env（需老大凭据）/ B 删除或禁用 nous provider 条目（配置决策）。禁擅改 config.yaml/.env
- **销账判据**: key 入 .env 或 provider 条目删除/禁用 → 测试复绿
- **销账**: 2026-10-26 18:0x 总管，老大「同意执行」批选项 B：`hermes config set custom_providers` 授权通道整表替换删 nous-portal-free 块（工具 guard 拒 agent 直写，CLI 为指定通道；备份 `config.yaml.bak_20261026_d17`）；实证：nous 0 命中 + fallback(agnes-3.0-flash) 完好 + `pytest tests/test_model_config.py` 8/8 PASSED（test_all_provider_env_keys_exist 复绿）

## D-18 cron 两个新增 job fatal last_error（两个测试侧断言红）

- **描述**: ① `worktree_isolation_regression`(b1f4f0d2aad5)：zq_shim FATAL「目标脚本不存在: scripts/worktree_regression.py」——job 指向缺失脚本，hermes_config 白名单该条目前提「脚本在」已 stale；② `QSP_PytestFullNightly`(56458df22df7)：last_error 为 10-25 pytest rc=2 收集错（tests/test_load_universe_newest_first.py ImportError）陈旧记录，10-26 02:06 重跑收集已成功（exit 1, 12 失败=本批存量债, 证据 data/audit/pytest_full_nightly_last.json）。
- **红断言侧**: test_hermes_config::test_cron_jobs_clean（白名单, fatal=1）+ test_system_unified::test_cron_jobs_status（无白名单, fatal=2）
- **挂账**: 2026-10-26 老三（t_039f1e18 分诊，cron jobs 内容禁碰）
- **owner**: 总管（cron 调度修复需另单）；**优先级**: P1
- **销账判据**: ① worktree_regression.py 脚本恢复或 job 删除/改指；② QSP_PytestFullNightly 下轮运行成功后 last_error 清/重写 → 两测试复绿
- **①销账 2026-10-26（t_600b8a3c, commit 1a074a34）**: scripts/worktree_regression.py 恢复入 main（342 行, SHA256 65c43ba9 四方一致: 主仓==archive/scripts-20261023==git@8dc6831d==hermes-home bak_20261017; git 无 D 型删除 commit=10-25 树污染期非提交态删除）。复绿尾步=下周 b1f4f0d2 job 运行成功清 last_error + test_hermes_config/test_system_unified 复跑；**② 仍挂**（QSP_PytestFullNightly 下轮成功前不关 D-18）

## D-19 trade_log 新鲜度断言语义缺陷（无交易日/无交易误报）

- **描述**: test_system.py::test_trade_log_freshness 断言 last_updated ≤24h；10-24 T051 C2 交易日跳过只覆盖非交易日。交易日 + 空仓 + soft 门外观望、12 天无交易（last_updated 2026-10-14 08:44 → 296h）时 S3 每日选股正常（jobs.json last_status=ok）→ 属「无交易活动」非「管线失活」，测试混淆交易活动与管线活性。
- **挂账**: 2026-10-26 老三（t_039f1e18 分诊）
- **owner**: 总管/老大（监控语义拍板）；**优先级**: P1
- **建议处置**: 断言对象改 S3 日选股输出时间戳（管线活性），或加「空仓 AND soft 门观望」豁免；不擅改
- **销账判据**: 语义拍板 + 测试跟随修改后复绿并回归
- **销账 2026-10-26（t_6a1981e8, commit df7e9bf2）**: 语义拍板=断言真源改 S3 管线活性 `data/picks_latest.json`（08:30 cron daily_pick 产出，原子写+ISO timestamp）；trade_log 24h 硬断言**降级软提示**（不 FAIL，打印 stale 天数；空仓+soft 门外观望=无交易活动≠管线失活）；新增 test_s3_pipeline_activity 硬断言（非交易日/盘前豁免）+ AC3 防假绿负向控制（stale fixture 必 FAIL 不碰活体）。tests/test_system.py 21/21 绿（含双源镜像 __init__.py）；未验证项：明日（10-27 周二）08:30 S3 cron 产出新 picks_latest.json 后断言全链路实跑。

## D-20 closedloop 遗留死信 + 时间敏感观察项（批次收口）

- **描述**: ① drain_dead_letter.jsonl 50 条 closedloop unrenderable 历史遗留（content 字段契约 10-25 P2#5c + t_cd7dab36 修复前产物；现活队列 P2 条目 _render_content ok=True 已复现验证）——清或留 = 总管拍板；② test_feishu_send_chat 状态敏感 flaky（依赖 live 队列/dash 态，非代码回归）；③ L1 financial_cache.json 非 git 跟踪 + 财务刷新 job 16:32 才生成，02:06 夜门禁窗命中旧态 → layers×4 红、16:32 后自愈（观察项，下轮门禁仍复现则升拍板）。
- **挂账**: 2026-10-26 老三（t_039f1e18 分诊，t_f630eb92 挂账观察项收口）
- **owner**: 总管；**优先级**: P2
- **销账判据**: ① 死信清理或明确留置 + test_feishu_send_chat 基线登记；② L1 观察项在下一 02:06 门禁自愈则关账，复发升级

## D-21 git_sync_task 推送源分支 github-main 不刷新（non-FF P0 复发风险，10-26 实证）

- **描述**: `scripts/git_sync_task.py` L15 契约 = `git push <remote> github-main:main`（双远端同 refspec）；本地 `github-main` 分支在 push 成功后**无刷新机制** → 陈旧累积（10-26 17:0x 实测落后 main 48 笔）→ 推送源=旧 tip → `[rejected] non-fast-forward` → P0 gitsync_p0（17:03/17:04 两条 P0 入 message_queue 为诊断期产物，已手动 `git branch -f github-main main` + 重跑同步清零：双远端 tip=db395d41 ahead=0 ✅）。根缺陷：脚本缺「push 成功 → 刷新本地 github-main」步骤（或改 main:main refspec + push 前 fetch）。
- **复发条件**: 每次 09:30 QSP_GitSync 前 main 有新 commit 而 github-main 未刷新 → P0 再触发（今日已发生 2 次）
- **读侧断言（§2.9）**: 消费方=QSP_GitSync（工作日 09:30）；失败路径=alert_log P0 gitsync_p0 + message_queue；检测式=`git rev-list --count github-main..main` >0 即风险态（建议修脚本时内置前置 fetch/刷新）
- **挂账**: 2026-10-26 总管（t_0b29a3d7 收口诊断）
- **owner**: 老三（脚本一行修复，另派单）；**优先级**: P1
- **销账判据**: 脚本 push 后刷新 github-main（或改 refspec）+ 手动跑 `git_sync_task.py` ahead=0 + 次日 09:30 QSP_GitSync 无 P0 复现
- **销账**: 2026-10-26 18:1x 总管验收 t_eecab269：方案A落地（`refresh_source_branch()` L321 定义 + L483 调用点=双远端推送成功+验收通过分支，commit dcf c297b 留痕 + 9a75e6d2 幂等改进）；复发单测 `test_git_sync_task_refresh.py::test_d21_refresh_zeroes_github_main_lag` 自跑 1/1 PASSED；「次日 09:30 无 P0 复现」= 明晨观察点（§2.9 读侧断言已挂 QSP_GitSync）

## D-22 自愈引擎写侧 placeholder bug（last_run="not-a-datetime"，老六侧）
- **描述**: 老六 QSP 自愈引擎（写 `data/self_heal_state.json`，19:02 仍活跃；本机 hermes-home/cron 无 self_heal job，脚本在老六侧）在 10-26 ~16:30-19:00 故障窗口把 `last_run` 写成字面量 `"not-a-datetime"`（非法 ISO 串）→ t7_qsp_watchdog 如实报 P0「格式错误: not-a-datetime」+「停滞 60min」，且 watchdog 对未解除 P0 **无复报节流** → 同 P0 每轮重发（17:28/18:03 群内重复 raw 行）。引擎 19:02 自恢复（12 探针全绿 consec_p0=0），写侧 bug 未修 = 下次故障窗口复发
- **挂账**: 2026-10-26 19:2x 总管（飞书群取证）
- **owner**: 老六（写侧一行修：失败路径不写 last_run 或写上一有效值，禁 placeholder）；watchdog 复报节流 = t_e8e12352 同源（告警层，老三）
- **优先级**: P2（引擎当前健康，复发窗口=下次故障）
- **销账判据**: 老六侧 commit + 注入故障窗口演练（手工把 last_run 置为缺失 → watchdog 报 1 次 P0 + 后续轮静默/降频，不得每轮重发）+ 群消息 24h 无「not-a-datetime」复发

## D-23 P0 债务批量销账（alert_log 167 条审计，老四 t_fd18bac9 2026-10-26 19:45）
- **口径**: alert_log 活体 167 P0（severity/level 157 + git_sync `priority` 字段 10，总管复数对上；10-26 07:46 隔离 2149行/1342 P0→982行/167 P0 的口径跃变本行登记，审计 §五-3）
- **销账 163 条**（逐类当前态证据指针 `data/laosi_audit/p0_debt_audit_20261026.md` §二/§三，取证 10-26 19:30–19:50）：C10 66（watchdog C10=ok+blob 7b982cac==HEAD）/ C5 23（9 僵尸单全 archived）/ D-1 12（RULING-DD-20261015=60% 重裁定 PASS）/ pre_pick 9（daily_picks 10-21/22/26 连续）/ C-1+C-2 18（探针双 PASS）/ A-1 4（720 文件 0 裸读）/ gitsync 10（双远程 ahead=0 @17:50）/ time_stop+积压+M-1+sanity 7（queue=0/drain 19:24 活性/blocker 清除；600519 探针残漏 2 行=无资金敞口，P2 补档留痕）/ 红线指纹 5（**假阳性**：根因=旧自审引擎 10-26 07:39 已 .trash，blob 与 HEAD 一致；基线文件 10-09 过期已重铸 @19:50=预防性，**该基线当前无活跃消费方**（scripts/core grep 0 命中，消费方随旧引擎归档），重铸不影响现态）/ 复盘闭环 7（defect_ledger P0 12 条已 11 销，余 1=下条）/ **DEF-20261004-029 1**（=09-10 bot-config 报告 L111「备份 config.yaml」，今日 `config.yaml.bak_20261026_d17` 等 4 个备份件在位 → 销账，10-04 挂账 22 天）。（155+8=163，与审计可销 162+DEF-1 对账：可销 162 中复盘闭环含 7+DEF 余债 1）
- **M-3 5 条 = 已销（2026-10-26 20:5x，t_258fdd8a 验收通过）**：消费者损坏三连环修复 commit `447e9517`（L92 转义+合并解析污染→永久 SKIPPED 根治 / 全量 180s→3.4s 只读 sqlite 快路径+--shard / state 假绿 0→实测 19 写回 `data/dispatch_audit_state.json`@20:25:43）；总管一手复跑：AC1 import `-W error` ✓ / AC2 4.6s+stderr=0 ✓ / AC3 state=19+P1 探针入队 20:34:49 已被 drain 投递（`data/drain_state.json`）✓ / AC4 19 违规=10-25 五单流程债（4 单 created_by=default 归位=QSP_TaskContractCheck 09:30 自动消化，不追溯改单）/ AC5 门禁 7/7 复跑 ✓（基线 5a52a93d，F0/F1 diff=0）→ **167 P0 活体余债清零（162+DEF-1+M-3-5 全部销账）**
- **写入方欠账**：86.8% P0 缺 task_id（145/167，写入方 6 脚本定位齐）→ 补键提案随 t_e8e12352（P0 中继卡，键规范 NOID）一并落地

## D-19 销账（t_6a1981e8, commit df7e9bf2, 2026-10-26）
- **销账**: trade_log 24h 硬断言改 S3 管线活性（真源=data/picks_latest.json, 08:30 cron daily_pick 原子写 ISO ts）; trade_log 降软提示(不FAIL,打印stale天数, 空仓+soft门外观望豁免); 新增 test_s3_pipeline_activity 硬断言(非交易日/盘前豁免) + AC3 防假绿负向控制(stale fixture 必FAIL不碰活体); 双源镜像 tests/test_system.py + tests/__init__.py 同步(防漂移)
- **验收**: 总管复跑 tests/test_system.py 21/21 绿(活体 picks_latest 08:44 当日产物); 负向控制用例 PASS=防假绿链有效; 数据本体(trade_log/holdings/S3产出/cron)零改动 ✓

## D-26 运维脚本加固批次销账（t_8969284a, commit 9516e804, 2026-10-26）
- **P1 disk_cleanup_safe.py 安全闸（总管 10-26 20:5x 审查挂账项）**: 龄期门槛（Temp>2d/CrashDumps>30d/缓存>7d, CLI 可配）+ dry-run 默认（仅 --apply 真删）+ 不传 flag 向后兼容告警不删 + 裸 except 全改 OSError 计数留痕（SOUL 准则 9 缺陷清零: 代码内 except: 命中 0, 仅 L7 注释史描述）+ 盘符根护栏。活体验证: 默认跑 0 删除/2867 候选枚举正常
- **P2 verify_config 候选解析**: _load_hermes_env 命中候选日志行 + tests/test_verify_config_env.py 6 用例（6/6 绿）
- **验收**: py_compile ✓ + 活体干跑 ✓ + 测试 6/6 ✓ + 双远端 0/0
- **P5 M-3 探针 state 再冻结收尾（t_45357e19, commit 7d0749e0）**: SKIPPED 路径写 state（skipped_reason 三类枚举 parse_fail/timeout/no_data 越枚举 ValueError 响铃 + violations_count=null 断链 + consecutive 死字段删除 + except:pass 改响铃留痕）；tests/test_m3_probe_state.py 13/13 绿；读侧断言真源=scripts/test_dispatch_audit_check.py（M-3 门禁 6 AC）——**更正记录：总管首报「台账 P5 销账行 f85b1b1b」失实（该行从未写入、f85b1b1b 不存在），本行为唯一 P5 销账载体，留痕于卡 comment**。双远端 0/0（atomgit 需重推）

## D-27 atomic_json.FileLock release-unlink 跨进程锁错位窗口（P2 挂账, 2026-10-27 总管 R0 裁定）
- **定级 P1→P2（附失效触发）**：当前平台（Win11 NTFS + CPython 3.11.9 + msvcrt）窗口被句柄钉扎结构阻断（os.unlink 持句柄必败 WinError32, 94-95 次实例实证；目录项钉扎活 inode）；4 进程 44k RMW 周期 0 丢失/0 overlap/0 错位（7/7 report lost=0, 材料=kanban 工作区 t_62328f2a/lock_repro/ADJUDICATION-MATERIAL-t_62328f2a-20261027.md, 树 @e1ac573f/atomic_json @9ac6769d SHA 39dcc659）
- **失效触发（回升 P1）**：平台迁 POSIX（WSL2/Linux/macOS）或 CPython 共享标志变更 → 窗口前提重新成立且 except:pass 吞证据
- **方案裁定**：A 最小变体立项（t_b3072ee0 R0 执行卡：去 unlink + 锁文件常驻（c2 对照 20k 0 丢失前置验证）+ release 四处 except:pass 改响铃留痕（SOUL 准则 9））；B（filelock 引包）否决；C（双锁校验）暂缓
- **销账判据**：t_b3072ee0 合入 main + 双远端 0/0 + 6/6 并发守恒全绿 + 老五 R0 评审通过
- **重复卡事故 2026-10-27 01:5x（总管自查）**: 执行卡双建——总管 00:4x 建 t_b3072ee0（ready）→ 老三 01:4x 按裁定自建 t_3a879cad（gated，父=t_62328f2a）=同活双卡。处置：t_b3072ee0 01:5x 被 claim 执行中（接手段=它），**t_3a879cad 挂闸 needs_input**（防双 worker 同写 atomic_json.py= R0 冲突红线）；t_b3072ee0 完工后 t_3a879cad 作废归档（行号实证版留作失败降级件）。**流程缺口（总管责任）**: 裁定评论写模板行「执行=t_XXXX（新卡）」未回填实卡 ID → 老三按字面自建；修正=裁定评论必回填具体卡 ID 或明示「执行卡由你自建」二选一，不留模板行
