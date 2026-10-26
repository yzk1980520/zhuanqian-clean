# AGENTS.md — A股单票轮动选股系统（v2.0）

**版本**: 2.4（2026-10-25 S6基地化落地+tests/contract 子目录建立，总管更新）  
**更新日期**: 2026-10-25  
**状态**: ✅ v2.3 已拍板（Kimi 终审 2026-10-20）；v2.4 工程变更（S6基地化：risk_rules.py 迁 core/risk/，根级透明 shim 代理）

---

## 一、项目概览

A股单票轮动系统：每日选股 → 全仓1只 → 移动止盈吃大波段 → 本金安全。

### 1.1 最终目标

**A股市场赚钱，获得财富自由，团队紧密合作**。

### 1.2 核心策略

- **持仓**: 全仓1只股票
- **止盈**: 移动止盈阶梯 S3吃大肉五档（激活 10/15/25/∞，锁 5/7/9/12%；首档 6% 激活容 15% 让利润奔跑），代码真源 `risk_rules.py` L227
- **止损**: 硬止损 risk_rules.STRATEGY_STOP_LOSS_PCT(10%，全策略统一，09-30 三方会签 8%→10%) + 时间止损 risk_rules.TIME_STOP_TRADING_DAYS(120交易日)
- **追高关闭**: 信号日涨幅> risk_rules.CHASE_BAN_PCT(4%)不买（已验证+14pp）
- **环境门**: 软提示，门关→建议仓位≤50%（2026-10-17 老大拍板统一，取代 D3 的 ≤30%），不阻塞出票

---

## 二、角色架构（7角色分层）

### 2.1 决策层（3角色）

| 角色 | 代号 | 职责 | 签字权 | 限制 |
|------|------|------|--------|------|
| **老大** | 御龙决 | 最终决策/资金/方向 | ✅ | 不介入执行细节 |
| **总管** | Hermes/agnes | 调度/验收/cron/实盘合入/系统健康 | ✅ | 不直接写代码 |
| **老五** | atomcode/hy3 | 独立评审/合规把关/风控守门 | ✅ | 不写交易数据 |

### 2.2 执行层（3角色）

| 角色 | 代号 | 职责 | 权限 | 边界 |
|------|------|------|------|------|
| **老三** | opencode | 代码/回测/数据工程/因子开发 | ✅ 代码修改 | ❌ 不改交易数据 |
| **牛马** | prime-agent | 后备执行/研究支持/批量任务 | ⚠️ 按需启用 | ❌ 资源紧张时降级 |
| **老六** | WorkBuddy | 研究域主理人+云端仓合规评审 | ✅ 云端仓独占写 | ❌ 不入4方核心签字 |

### 2.3 独立层（1角色，自审哨兵）

| 角色 | 代号 | 职责 | 权限 | 边界 |
|------|------|------|------|------|
| **老四** | laosi | 自审巡检（契约漂移/双源/假绿/口径冲突）+独立审查+编码后备 | ✅ 只读检查/审查报告 | ❌ 不写交易数据/不碰cron/不改risk_rules.py/不直接推送 |

- **部署**：profile=`laosi`，cron `d92eb2ba2c2e` 每日20:00自检，审计日志 `data/laosi_audit/laosi_*.json`
- **定位**：与老五"静态快照评审"互补，老四是"动态哨兵"（周期巡检，保证未来持续干净）
- **不参与三方讨论**：三方=总管+老三+老五；有审查需求时总管单独派单，完成后三方照常裁定

### 2.4 技术实现层（2角色，不对外暴露）

| 角色 | 代号 | 职责 | 映射到 |
|------|------|------|--------|
| 编码代理 | opencode CLI | 实际代码编写 | → 老三 |
| 评审代理 | atomcode CLI | 独立评审执行 | → 老五 |

> 系统认知地图 = specs/002-system-overview/spec.md（系统真源规格，宪法判据 .specify/memory/constitution.md）

---

## 三、协作流程（七步闭环）

```
┌─────────────────────────────────────────────────────────────────┐
│  ①需求提出 → ②三方讨论 → ③任务单生成 → ④执行 → ⑤评审 → ⑥验收 → ⑦总结归档  │
└─────────────────────────────────────────────────────────────────┘
         ↓              ↓              ↓           ↓         ↓          ↓
       老大         总管+老三+老五    总管        老三      老五       总管
```

### 3.1 流程说明

| 步骤 | 执行人 | 交付物 | 验收标准 |
|------|--------|--------|----------|
| ① 需求提出 | 老大/总管 | 需求描述 | 清晰、可执行 |
| ② 三方讨论 | 总管发起 | 讨论纪要 | 形成一致建议 |
| ③ 任务单生成 | 总管 | Kanban任务单 | 包含证据链字段 |
| ④ 执行 | 老三 | 代码+测试 | 回归全绿 |
| ⑤ 评审 | 老五 | 评审报告 | 可放行/打回 |
| ⑥ 验收 | 总管 | 验收报告 | 断言证据 |
| ⑦ 总结归档 | 总管 | 归档文档 | 进入知识库 |

---

## 四、关键规则（可执行约束）

### 4.0 契约真源铁律（2026-10-17 W5 治理确立，最高位阶）

> **病根**：本系统是「文档驱动」而非「契约驱动」。契约的代码真源只有 `risk_rules.py` 一处，
> 但描述它的文档曾有 12 处，没有机器强制一致，且改完**没有广播机制**。
> 结果 09-30 三方会签把止损**旧口径** 8%→10% 后，仍有 6 处文档继续写 8%（其中 `.agent/P0-EXEC-ORDER`
> 还挂着「P0/禁止修改」标签），错误值戴着最高权威标签被供奉 17 天。

**三条铁律**：

1. **代码是真源** —— 一切策略契约数值（止损/止盈阶梯/追高/时间止损）的**唯一真源是 `risk_rules.py`**。
   文档**不得复述数值**，只写**指针**：`止损 = risk_rules.STRATEGY_STOP_LOSS_PCT`（当前 10%）。
   复述即造第二个真源，是本次要根治的病。
2. **机器校验** —— `tests/test_contract_docs_consistency.py` 扫描活跃层 md 与真源比对，
   出现已废弃口径直接 **FAIL**（pytest 红）。白名单必须写理由，不允许裸放行。
3. **改契约必留痕 + 广播** —— 任何契约变更走两步：
   ① 在 `docs/CONTRACT-CHANGELOG-20261017.md` 登记（谁/何时/从什么改到什么/是否回测复核）；
   ② 跑 `python scripts/broadcast_contract_change.py` 广播（CHANGELOG + 每日记忆 + 飞书 + 看板卡）。
   **只改代码不广播 = 未完成的变更**，同「回授断言注册铁律」§4.1-12 一并执法。

- 真源指针速查：`止损 risk_rules.STRATEGY_STOP_LOSS_PCT` / `追高 risk_rules.CHASE_BAN_PCT` /
  `时间止损 risk_rules.TIME_STOP_TRADING_DAYS` / `止盈 risk_rules.TREND_TP_LADDER` +
  `risk_rules.TP_SELL_LADDER`（两者语义不同，禁止混用，见 `.workbuddy/RULES.md` §3.1）。
- 变更台账：`docs/CONTRACT-CHANGELOG-20261017.md`　决策依据台账：`deliverables/决策台账-20261017.md`
- **TSS:c1d29f831efa** ← 真源戳（`core/risk/risk_rules_impl.py` SHA256 前 12 位，S6基地化后真源迁至此；
  戳按 CRLF→LF 归一化后的内容计算，与 checkout 换行符无关）。根级 `risk_rules.py` 现为透明 shim，
  所有 import 转发至 impl。**真源变更未刷新此戳 → `tests/test_doc_freshness.py` 判 FAIL**。
  刷新：`python scripts/sync_true_source_stamp.py`（**刷新前必须先完成 CONTRACT-CHANGELOG 登记 + 广播**）

### 4.1 投资纪律

0. **选股看板入口**：本地面板 http://127.0.0.1:8666/board
1. 全仓1只，移动止盈吃大波段，本金安全第一
2. 追高关闭：信号日涨幅> risk_rules.CHASE_BAN_PCT(4%)不买（已验证+14pp）
3. 环境门：软提示，门关→建议仓位≤50%（2026-10-17 老大拍板统一，取代 D3 的 ≤30%），不阻塞出票
4. 快速版20日改善必须全量132日确认才合入（铁律）
5. 回测必须含退市股（幸存者偏差已修复）
6. 成交模型统一：涨停买不进/跌停卖不出/停牌顺延
7. 数据不出本机，Wind Alice仅调用公开数据Skill
8. 写JSON用atomic_json（防并发覆盖）
9. 不采用也要诚实记录，失败如实报告
10. 输出全中文，标数据时效
11. **告警唯一出口（T2立规 2026-10-15，Hermes治理方案v1）**：所有告警（position_alerts / health_monitor / freshness / self_audit）一律写 `data/message_queue.json`，由计划任务 `QSP_MsgDrain`（5min）作为**唯一投递器**发飞书；`alert_log.jsonl` 是本地台账，**不代表触达**（"每个告警只对发出去负责、无人对到达人负责"即16天停机根因，不得再犯）。告警环自身活性由 `QSP_DrainWatch`（5min, `scripts/drain_meta_check.py`）盯 `data/drain_state.json` last_run 新鲜度 <15min，连续 2 轮 stale → P0 **绕过队列**经 default 应用 bot API 直发；`self_audit.py --audit` 的 M-1 项每日 15:35 复检。同步环 = `QSP_GitSync`（工作日 09:30，`scripts/git_sync_task.py`）：pytest 门禁不绿不推 → 双远程 push → 推后验收远程 main tip==HEAD(ahead=0)。
12. **回授断言注册铁律（老大拍板 2026-10-16，TEAM-COMMS-PROTOCOL v2.3 §2.9）**：一切写侧动作（cron 事件/台账/消息/文档条目/任务单结论）必须同时注册读侧消费断言（消费方+消费周期+失败告警路径），未注册=未完成的闭环，不得上线、不得宣称"已闭环/已生效/已送达"；既有无断言写侧一次性审计补断言或挂技术债台账（闭环健康度日报跟踪销账）。豁免：P0 实时告警类可先行直发，24h 内补断言。执法：老五评审 checklist + 老四 laosi 自审 + 四方审查环（老六复审）三道。
13. **四方审查环（老六全局审查 2026-10-16 §五，TEAM-COMMS-PROTOCOL v2.4 §2.10）**：老大派单→老六机制审查出方案→总管调度子Agent（worktree隔离）→执行反馈老六→老六复审（每结论挂一手证据+先红后绿判据）→❌打回（附P0/P1/P2分级+复验方式）总管重派 / ✅老五独立评审（红线/门禁/数据窗口）→总管合入归档。打回判据四件套（缺一即打回）：✅未挂一手证据 / 称"已解决"但回归未跑 / 数字验证未声明引擎commit / 读侧断言缺失。集成判据：老六复审+老五独立评审+回归全绿+回滚点(.bak/commit)四者齐才合入。P0豁免：实时止损类P0可直报总管不绕环，24h内补断言补审。
14. **任务契约块与自愈规则（老大拍板 2026-10-20，元宝四件套对照，v2.3）**：R0/R1 任务单派单必附【契约块】（五字段：input_contract / acceptance_criteria 机判项 / output_contract / retry_budget / degradation_path，全文见 `docs/多Agent任务契约与自愈规则-元宝对照-20261020.md` §二）；验收=逐条跑 acceptance_criteria 机判项，任一 FAIL → `kanban_request_changes` 打回，不得跨闸；重试预算创建时显式声明（kanban `max_retries`：R0=2 / 数据类=3 / 评审类=1）；R0 单失败 block 前先走 §3.2 降级路径表（截短窗口复现 → sanity gate → 20日快速版标"未全量确认" → 仍败才 block）；执法 = `scripts/check_task_contract.py`（cron `QSP_TaskContractCheck` 工作日 09:30：窗口内违规经 `data/message_queue.json` 发 P1/P2 飞书，绿则静默）+ 总管验收门；读侧断言按 §2.9 铁律注册于该文档 §3.4。
15. **R0.5 出票链分级（老大拍板 2026-10-25，协议 v1.1）**：出票链路**非写**操作（`daily_pick.py` 执行与逻辑修改、`picks_latest.json` 生成、信号→出票判定逻辑）独立为 **R0.5**，门槛：先备份 → `python check_backtest_sanity.py` PASS → 总管签字（无需老五评审）。**若涉及 trade_log/holdings 写操作，自动升级为 R0**（需老五评审 + 老大确认）。P0 实时止损类：总管即时执行，30 min 内通知老大。详见 `WORKFLOW_PROTOCOL_20260926.md` v1.1。
16. **步级审批检查点（借鉴 LazyMind State Brain，2026-10-26 拍板）**：任务 body 可声明 `CHECKPOINT <id>: <描述>` 标记；worker 到达该步骤前调用 `kanban_block(kind=needs_input, reason="CHECKPOINT <id>: <描述>")` 暂停，审批方通过 `kanban_unblock` 放行后从断点继续（**不重启全任务**，用 `kanban_comment` 记录"已审批，继续"）。全文见 `docs/step-checkpoint-convention.md`。CHECKPOINT 不替代 `laowu_approved`；须显式声明超时策略（fail-open 或 fail-close），未声明默认 fail-close（超时自动 block，须人工解锁）。

### 4.2 风控红线（不可修改）

- ❌ `risk_rules.py` 全部止损止盈参数
- ❌ `TIME_STOP_TRADING_DAYS=120`
- ❌ `CHASE_BAN_PCT=4%`
- ❌ 全仓超过1只
- ❌ 数据出本机（Wind Alice除外）
- ⚠️ `factor_layer_enabled=True` 前置（D-9 2026-10-25 挂账）：`strict_valid_count ≥ 8` **或** 老大大量裁定豁免；在此之前擅自开启将导致出票静默停摆（FAIL 1/8），属红线事故

---

## 五、决策表（常见场景）

| 场景 | 选择 |
|------|------|
| 新因子/新策略想上线 | 过门禁：IC>0.03 / IR>0.3 / 单调性 / 全量132日确认 |
| 快速版(20日)vs全量(132日)结论冲突 | 以全量为准 |
| 外部数据(akshare)拉不到 | 非交易时段不可达 → 开盘后重试 |
| 老三/老五意见冲突 | 双方方案都进回测，用数据裁决 |
| 实盘交易数据(holdings/trade_log) | 只读，只有总管能写 |
| 因子选择 | 反转因子短期无效但中期有效；动量因子短期有效 |
| 因子层想开启 | 前置：`strict_valid_count≥8` **或** 老大大量豁免；不满足 → 维持关闭，不影响出票 |
| Wind Alice调用 | 仅公开数据Skill，禁止上传敏感数据 |

---

## 六、运行时合规检查

### 6.1 自动化审批闸

- **老五审批**：`automation_system.py` 选股执行前必须检查 `data/review_status.json` 中的 `laowu_approved` 字段
- **总管独占**：交易数据（trade_log.json/holdings.json）写入权限归总管
- **门禁阈值**：止损/止盈阈值代码只读

### 6.2 证据链字段

每个进化变更必须包含：
- 决策ID/时间戳/提案来源/数据窗口
- 含退市股标记/前后指标对照
- 悲观场景损失/论点对称性
- 失效触发条件/评审人/验收结论

---

## 七、开发流程

### 7.1 日常开发

1. **备份**：改任何核心脚本前 `Copy-Item x.py x.py.bak_<日期>`
2. **清环境**：跑python前 `Remove-Item Env:PYTHONPATH`
3. **语法**：`python -m py_compile x.py` 通过
4. **回测**：`python backtest_rotation.py` 全量132扫描日
5. **回归**：`python .agent\regression\__init__.py .` 全绿
6. **验证脚本**：`hermes-verify-*.py` 前置
7. **报告**：三件套（结果/产出文件/验收对照）

### 7.2 测试命令（S6基地化后路径变化）

- **全量测试**：`C:/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe -m pytest tests/ -x`
- **单测**：`C:/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe -m pytest tests/test_contract_docs_consistency.py -v`
- **门禁测试**：`C:/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe -m pytest tests/test_doc_freshness.py tests/test_contract_docs_consistency.py tests/test_walk_forward_backtest.py -v`
- **跳过慢测**：`-m "not slow"`
- **tests/contract/**：契约架构 schema 测试，随任务单流转自动执行

### 7.3 进化流程

- **日度**：收盘后cron巡检（只读）
- **周度**：周日21:00 Kimi盲区审查
- **月度**：月末首交易日权重/阈值回归重估
- **季度**：季末全量132日walk-forward

---

## 八、Wind Alice使用规范

### 8.1 允许调用

- ✅ 公开市场数据查询（股价、财务、研报）
- ✅ 公司一页纸投资备忘
- ✅ 调研问题清单
- ✅ 财报点评
- ✅ 事实核验（公开数据）

### 8.2 禁止上传

- ❌ 持仓数据（holdings.json）
- ❌ 交易记录（trade_log.json）
- ❌ 内部因子权重
- ❌ 策略参数
- ❌ 回测结果明细

### 8.3 调用模板

```bash
# 公司一页纸
wind-alice --prompt "贵州茅台600519公司一页纸投资备忘" --skill "Company One-Page Investment Memo"

# 调研问题清单
wind-alice --prompt "300498温氏股份调研问题清单" --skill "Stock DD List"

# 财报点评
wind-alice --prompt "宁德时代300750 2026Q2财报点评" --skill "Global Share Quarterly Earnings Review"
```

---

## 九、文档结构

### 9.1 真源文档（根目录）

- `CONTEXT.md` - 统一术语表
- `AGENTS.md` - 核心协议
- `SOUL.md` - 总管人格定义
- `CHANGELOG.md` - 版本变更记录

### 9.2 ADR文档

- `mainline/docs/adr/` - 架构决策记录

### 9.3 归档文档

- `docs/archive/` - 历史报告、诊断文档

---

## 十、团队沟通

### 10.1 飞书群聊消息分级

| 级别 | 场景 | 发送人 | 频率 |
|------|------|--------|------|
| P0 紧急 | 止损触发/系统故障 | 总管 | 实时 |
| P1 关键 | 选股信号/持仓变动 | 总管 | 每日1次 |
| P2 常规 | 进度更新/评审结果 | 老三/老五 | 按需 |
| P3 归档 | 报告/文档链接 | 总管 | 每周1次 |

### 10.2 任务分派话术

**总管→老三**：
```
@laosan 【任务单】XXX功能开发
需求：XXX
验收标准：XXX
截止时间：XXX
执行完毕后回复「✅ 已完成」+ 交付物链接
```

**总管→老五**：
```
@laowu 【评审请求】XXX功能开发
交付物：XXX
验收标准：XXX
请独立评审并回复「✅ 通过」或「❌ 打回：XXX原因」
```

### 10.3 成员写入/输出标准（K45 R4 落档，2026-10-08）

> 全文见 `docs/成员写入输出标准-20261008.md`。以下为分派话术强制层，与各角色 SOUL 同等效力。

**每个任务单必附写入边界**（谁写哪个文件、走哪个合法写口、read-back 断言）：
- 实盘数据（`holdings.json`/`trade_log.json`/`config.json`）= 总管独占写，走 `atomic_json.update_json`；
- 因子登记/评审回填（`data/factor_registry/registry.json`）= 老三登记 + 老五回填，走 `FactorRegistry` 类方法（passthrough 不洗扩展字段）；
- 成员输出（回执/报告）最低字段：**改动+一手证据(命令/输出/时间戳)+回归+回滚点+未验证项**；写不出证据的项**如实标"未验证"**，禁止打勾放行（SOUL 准则 5）。

**禁止表述**（出现即打回）：
- "已修复/已归一/已解决" 用于未复核项；
- "IC 反向" 未附 IC 数值+文件+时间戳（记忆/引用不算证据）；
- 数字作"结果验证"但未声明引擎 commit（SOUL 准则 7）。

**口径红线（K45 #3 修正）**：chg5=反向、chg10=弱-死（不得写"反向"）；`ic_mean=None` 为 Q1 合法隔离值，禁洗 0.0 / 禁当死数据删。

### 10.4 并行执行协议（主Agent+子Agent+Worktrunk，2026-10-15 拍板）

> 全文见 `docs/团队约定-主Agent子Agent-Worktrunk-并行协议-v1.0.md`（v1.0, 2026-10-11）。核心：总管调度 3 个子Agent（老三/老五/牛马），各自在独立 worktree 运行互不污染主仓；派发前三检查→运行中监控→完成后三件套验收；老五独立评审清单（红线/门禁/数据窗口/异常吞噬/证据链）；防炸三红线（数据安全/执行安全/沟通安全）。老三/老五 profile 挂载本约定引用线，读单必过本清单。

### 10.5 飞书消息规范（2026-10-20 总管立规）

**原则**：关键结论不刷屏，单条<400字符，P0预警先核查再发送。

#### 10.5.1 等级与场景

| 级别 | 场景 | 发送人 | 字符限制 |
|------|------|--------|----------|
| P0 紧急 | 止损触发/系统故障 | 总管 | 200 |
| P1 关键 | 持仓变动/审查裁定/任务验收 | 总管 | 400 |
| P2 常规 | 进度更新/评审结果 | 老三/老五 | 400 |
| P3 归档 | 报告/文档链接 | 总管 | 无限制 |

#### 10.5.2 强制字段

**裁定类消息**必须附：
- ✅/❌/⚠️ 等级前缀
- 命令+输出证据（$ command → output）
- 原行动项状态（作废/继续/更新）

**修正类消息**必须附：
- 原消息时间戳
- 原行动项状态变化表

#### 10.5.3 禁止表述

- 「可能/大概/似乎」→ 改为「待验证/初裁」
- 「已修复/已解决」未附证据 → 打回
- P0预警未核查 → 禁止发送

#### 10.5.4 模板脚本

使用 `scripts/feishu_message_template.py` 生成符合规范的message body，自动校验字符数+字段完整性。

---

**签字**: 总管（Hermes）· K45 裁定 D1–D6 已拍板（2026-10-09）  
**日期**: 2026-10-09  
**状态**: ✅ 已拍板（Kimi 终审 2026-10-09，裁定见 `docs/裁定落档-D1D6-20261009.md`）
