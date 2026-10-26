# resume-then-settle 设计冻结稿 v2（R0 提案 · 折叠老五 R0 评审 C1–C4 + R2 双树前置 + 升级触发读侧断言登记）

**卡片**: t_2ed8d608（本稿为挂卡 attachment）
**版本**: v2（supersede v1 冻结稿 = t_2ed8d608 卡 body；v1 原文保留在卡 body 留痕）
**修订人/时间**: 老三（laosan）· 2026-10-26 · 任务 t_ed0f8ec8
**输入**:
- v1 冻结稿 = kanban 卡 t_2ed8d608 body（处置层四步 + 边界 + 验收 + 触发）
- 老五 R0 设计评审（权威措辞源）= `report-2ed8d608-resume-then-settle-R0-review-20261026.md`（§二 裁定 / §三 C1–C4 / §四 R2 / §五 失效触发）
- 根因取证 = `report-1013-cascade-root-cause-20261023.md` §六（t_196292bd Q3 派生）
**签字状态**: 老五 R0 设计评审 ✅ 通过（附条件签字 C1–C4）；本 v2 将 C1–C4 全数折叠后，签字转无条件生效（收尾 = 老五对 v2 快速复签，非重新 R0 全评）。
**排期声明**: **不排期实施**。升级触发前保持冻结；触发后由总管评估排期，实施仍走老五 R0 评审（合并门三者齐备才动工，见 §4）。

---

## 0. 实施前置门禁（R2 双树前置，老五 §四-1 裁定，实施前必核）

> **核 运行中网关加载树 == 基准树 e60bdf1f（`data/hermes-home/hermes-agent` @ e60bdf1f6e）；根树 d923a5eb/0.22.2（桌面宿主 `D:\Hermes agent\Hermes Agent CN Desktop`）缺 `acp_adapter/gateway_server.py` 与 `gateway/session_managed_worker.py`，非目标（NOT the target）。若加载树 ≠ 基准树，则等价性对照口径失效，须重新取证后重开评审。**

数据时效（2026-10-26 实测）：团队树 HEAD 已复核 = e60bdf1f6e（与基准一致，`git rev-parse --short HEAD` 实证）；根树版本 0.22.2/d923a5eb 引老五报告 §四。

## 1. 背景与根因（v1 §背景 + 1013 取证 §六 折叠）

10-22 04:58:39 操作员经桌面 dashboard 重启宿主网关（解锁 session 独占维护 409）→ drain 门对 laowu 长连 TUI ws 注入 1013（设计内干净关闭，非故障码）→ shutdown hard-interrupt「explicit stop requested」→ 在途 managed worker EOF（`session_managed_worker.py` L538）→ owner 结算 unknown（L554-562，`ManagedExecutionUnknown`「stops the FIFO without forging failed settlement」）→ **dispatcher 盲重排整 run**：run 662 `exit_kind=nonzero_exit code=1` crash → run 663 全量重跑 11.5min → PASS，交付零损失。

盲重排直接根因（老五报告 §1.2 实证）：`worker_result.exit_code=1`（`turn_exit.py` L29）对 unknown/真失败不可分 → 事件流不可作判定源。优化点在**处置层**（dispatcher 策略），**结算层保持原样**。

## 2. 提案内容 v2（处置层四步，C1/C3 已折叠）

managed run 因网关丢失结算为 unknown 时，dispatcher 在重排新 run 前：

1. **判定源（C1）= owner state.db `session_admissions(status, outcome, payload_digest)` RO 读**：若网关已恢复，经 `hermes_cli/kanban_owner_recovery.py` 既有 RO fence 模式（L9-31 `owner_reclaim_paused`：`sqlite3.connect(db?mode=ro)` + `SELECT status,outcome FROM session_admissions WHERE target_session_id=? AND request_id=?`，异常 → 安全兜底；该 fence 10-22 当天生产运行正常）结构化读恢复 session 的 admission 行 + claim/epoch 一致性校验。
   - **已排除通道（非判定源，C1 裁定）**：v1 step 1「经 session.resume/session.info 读取」被排除——`session.resume` 是 adopt 动词（返回 subscription_id 需 detach，附带 editor MCP rebind / workspace move 订阅副作用 = 幻影 run 风险，对应验收③），`session.info` 不载 admission 结局；事件流 `worker_result.exit_code=1` 对 unknown/真失败不可分（turn_exit L29 + run662 实证）。dispatcher 应直读网关恢复快照所基于的**同一持久行**（`session_admissions` 唯一写者 = 结算层 epoch/generation fence，非第二处真相源）。
2. **结算映射（C3，钉死 outcome 语义）**：结果已持久且 **`terminal+outcome=completed`** ⇒ 从恢复记录结算 run，**不重放**（消除非幂等副作用双放风险）：
   - run 已有持久生命周期事件（kanban_complete / request_review / block）→ 随其状态转换；
   - 无生命周期事件 → task 落 **`review`**（人工复核兜底，**禁止 auto-done**）；
   - **C3b**: `terminal+outcome=interrupted` 不得借「已终态」提前结算（与 unknown 同路，落回现行为）。
3. 结果确属 unknown（`unknown` / 行缺失 / 读异常 / `started`）⇒ 维持现行为（requeue 新 run），与 A(现行为) 逐字段一致（验收④）。
4. 网关未恢复 ⇒ 维持现行为（run 保持 crash + retry_status=ready）。

## 3. 竞态语义（C2 钉死）

同 tick 有界 RO 读；**started/unknown/missing/读异常一律落回现行为**；**禁止 tick 挂起/轮询/新增暂停态**。

| 窗口 | 读到的行态 | B 行为 | 依据 |
|---|---|---|---|
| 网关已恢复且已结算 | terminal + outcome=completed | 从恢复记录结算 run（§2-C3 映射），不重排 | C3 |
| 网关已恢复、drain 时已 fence（10-22 型） | unknown | 现行为（crash+requeue），逐字段同 A（验收④） | `lose_admission_worker` L116 已落盘 |
| 网关刚起、恢复尚未 stamp | started（旧 epoch） | 现行为（requeue）；旧行稍后被网关 fence 为 unknown、孤儿化、永不重提 ⇒ 无副作用双放，代价 = 与 A 相同的一次重跑 | `hermes_state_runtime` L267 / 恢复时序 |
| 网关未恢复 | db 缺失/读异常 | 现行为（run 保持 crash + retry_status=ready） | 既有 fence 异常 → 安全兜底模式（`owner_reclaim_paused` L28-31 先例） |

- 读实现 = `sqlite3.connect(uri, mode=ro)` 有界同步查询；WAL 并发写者不阻塞读，锁竞争 → 立即 OperationalError → 落回现行为（构造上无 hang）；
- 竞态唯一残差 = 「**started 窗口多跑一次**」，与 A 行为等价，**记为可接受边界**（不修 = 与 10-22 现状同损失面，零劣化）。

## 4. 变更面与边界

- **变更面**: `hermes_cli/kanban_db_dispatch.py`（处置策略）+ `hermes_cli/kanban_owner_recovery.py`（fence 旁新增结构化读取：admission 行 status/outcome/payload_digest + claim/epoch 一致性校验）；**不含 ACP 侧、不触碰 risk_rules.py 核心参数** ✓
- **结算层不变**: `ManagedExecutionUnknown` 的 unknown 结算（`gateway/session_managed_worker.py` L32-33「stops the FIFO without forging failed settlement」）保持原样——伪造 failed/succeeded 均 = P0 账务缺陷，不在提案范围。
- **合并门**（三者齐备才动工）: 老五 R0 评审通过 + 等价性对照全绿 + 升级触发发生。本稿 = 设计冻结，不排期实施。

## 5. 验收（等价性对照，同窗口同口径）

合成 drain 场景 A/B：A = 现行为（盲重排）/ B = resume-then-settle。断言：
① 无副作用双放（同一 write 仅落一次）② 无结果丢失（持久结果必被结算）③ 无幻影 run ④ 真 unknown 时 B 行为与 A 逐字段一致（run 事件流对照：事件 kind/payload、task UPDATE、retry_status、_end_run 全量 diff）。

**pytest 口径 =「QSP 门禁全绿 + 本提案新增行为契约全绿（红转绿反例须独立复现）」**；无件数硬编码（用例数快照漂移中，禁引历史件数为验收基准，见老五报告 §1.4 数字守恒台账）。
**等价性对照基准标注**: 基准树 = `hermes-agent` @ **e60bdf1f6e**（dev 树 main + 团队 commits，运行基准）；根树 d923a5eb/0.22.2（release，非目标）。每轮对照须标注当轮跑的树 commit + 引擎版本；旧数字不得作为新引擎验证（准则 7）。

### 最小样本设计（先窄后宽，老五评审要点 #3 裁定）

**L1 单 run 合成 drain × 4 态（A/B 同 fixture 同窗口同口径）**
- fixture：临时 kanban.db + 临时 owner state.db（owner_admitted 绑定 session_id/request_id/db 路径）+ 哨兵写（非幂等副作用探针）；
- 4 态：`terminal+completed` / `terminal+interrupted` / `unknown` / 行缺失（db dangling）；
- 断言映射：completed ⇒ B 结算且**无新 run 生成**、哨兵恰好 1 次（A 态下重放 = 哨兵 2 次 ⇒ 先红后绿证明测试真测到变更）；其余 3 态 ⇒ B 与 A run 事件流逐字段一致（验收④）；全态断言 ③ 无幻影 run（run 计数 + 事件流 diff）。

**L2 双 run FIFO（集成）**：T1 running（admission completed）+ T2 queued（同 authority 不同 task）→ drain + 恢复 → B 结算 T1、重排 T2；断言 `session_admissions.seq` FIFO 顺序不被打乱、T1 结算不阻塞 T2。

**L3 全量门禁**：QSP 门禁全绿（引用「门禁绿」，不引用件数）+ 新增行为契约测试（双态模式：有 hermes 实体 → 全跑，无实体 → skip，先例 t_c5608cfc 16P/0skip、14P/2skip）+ 红转绿反例（B 打补丁前 L1-completed 必 FAIL）独立复现。

## 6. 升级触发与 §触发断言登记（AGENTS.md §4.1 规则 12 回授断言铁律 / TEAM-COMMS v2.3 §2.9）

**升级触发（卡片自带条件）**: TUI-1013 级联**再次**导致 run crash（当前 30 天仅 10-22 一起）。触发前本卡保持冻结；触发后由总管评估排期，实施仍走老五 R0 评审。

**升级触发读侧消费断言（已登记，规则 12：写侧动作必须同时注册读侧消费断言，未注册 = 未完成的闭环）**：
- **触发事件** = 第二次 TUI-1013 级联 crash（首起 = 10-22 run 662）
- **消费方** = 总管每日 1013 级联事件巡检（读 kanban.db task_runs + 网关日志 1013 级联/unknown 结算痕迹）
- **消费周期** = 每日
- **失败告警路径** = 写 `data/message_queue.json` P1（QSP_MsgDrain 投递飞书）
- **台账位置** = `docs/tech_debt_ledger.md` **D-13**（原台账 2026-10-22 归档于 `docs/archive/20261022-cleanup/tech_debt_ledger.md`，本活台账 2026-10-26 复启用）

## 7. 失效触发（反例自检，原样保留自老五报告 §五）

以下任一证据出现 ⇒ 本「通过（附条件）」结论作废、卡片重开（条目中「§」= 老五报告 `report-2ed8d608-resume-then-settle-R0-review-20261026.md` 节号，4 条原样保留自其 §五）：
1. 发现 `session_admissions` 存在结算层之外的写者（grep `INSERT/UPDATE session_admissions` 全树复核 = §1.3 命令）；
2. B 结算路径在「无生命周期事件」时产生 task `done`（违反 C3 review 兜底）或哨兵双写（违反 ①）；
3. RO 读在 Windows 文件锁下出现 >tick 预算的阻塞（违反 #2 不挂起契约）；
4. 触发实施时基准树 commit 已漂移（e60bdf1f6e ≠ 运行树）而未重新取证。

## 8. v1 → v2 修正对照（C1–C4 逐条落地）

| # | v1 措辞 | v2 措辞（老五 C 条） | 源 |
|---|---|---|---|
| C1 | step 1「经 session.resume/session.info 读取」恢复 session 的持久执行行（acp_adapter/gateway_server.py L234/342/371/413 已有原语）——**已排除通道** | 判定源 = owner state.db `session_admissions(status,outcome,payload_digest)` **RO 读**（复用 `hermes_cli/kanban_owner_recovery.py` L9-31 既有 fence 模式）+ claim/epoch 一致性校验；变更面补列 `hermes_cli/kanban_owner_recovery.py`；排除事件流与 ACP RPC（理由见 §2 step 1） | 老五 §三 C1 |
| C2 | （v1 未钉死竞态语义，仅留评审要点 #2） | 同 tick 有界 RO 读；started/unknown/missing/读异常一律落回现行为；禁止 tick 挂起/轮询/新增暂停态；「started 窗口多跑一次」记为可接受边界 | 老五 §三 C2 |
| C3 | 「结果已持久（turn 实已完成）⇒ 从恢复记录结算，不重放」（outcome 语义未区分） | 仅 `terminal+outcome=completed` 结算不重放；run 已有生命周期事件 → 随其转换；无 → task 落 review（禁 auto-done）；interrupted/unknown/missing 与 A(现行为) 逐字段一致；**C3b**: terminal+interrupted 不得借已终态提前结算 | 老五 §三 C3 |
| C4 | 验收 =「QSP 门禁 scripts/test_*.py（件数快照，随树漂移）」 | 验收措辞 =「QSP 门禁全绿 + 本提案新增行为契约全绿（红转绿反例须独立复现）」；无件数硬编码；等价性对照标注基准树 e60bdf1f6e + 引擎版本 | 老五 §三 C4 |

## 9. 数据时效与风险声明

- 代码行号证据截至 2026-10-26 基准树 e60bdf1f6e（老五报告 §1.1 逐处核验：结算层 L32-33/538-562 精确；resume 原语 L234/342/413 精确、371±2；处置层引用偏移 17 行，实施时按 `kanban_owner_recovery.py` L9-31 fence 现读复核，不阻塞本文档化）；
- 本任务零代码改动（纯文档 + 台账）；未触碰 hermes-agent 任何 .py / kanban_db_dispatch.py / risk_rules.py；
- 风险：无行为变化——v2 保持冻结，升级触发前零交付影响。

---
*老三 · t_ed0f8ec8 · 2026-10-26*
