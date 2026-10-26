# 契约变更台账（CONTRACT-CHANGELOG）

> 建立：2026-10-17 · W5 治理（B3）　·　维护责任人：改契约的人（谁改谁登记）
> 文件名带日期后缀的原因：本目录（`docs/`）存在大量历史文档，W4 正在并行归档，
> 带 `20261017` 后缀避免与归档批次撞名。
>
> **TSS:c1d29f831efa** ← 真源戳（`risk_rules.py` SHA256 前 12 位，`.agent/true-source-stamp.json`，2026-10-26 老五同步刷新 c1d29f83）。
> 真源变了而此戳未刷新 → `tests/test_doc_freshness.py` 判 FAIL，
> 意思是"文档没跟上真源"。刷新命令：`python scripts/sync_true_source_stamp.py`。

---

## 〇、为什么有这份文件（不读会返工）

本系统是「文档驱动」而非「契约驱动」——契约的代码真源只有 `risk_rules.py` 一处，
描述它的文档曾有 12 处，且**改完没有广播机制**。结果：

- 2026-09-30 三方会签把止损 **8% → 10%** 之后，仍有 **6 处文档继续写 8%**；
- 其中 `.agent/P0-EXEC-ORDER-20260930.md` 还挂着「P0 / 禁止修改」标签 ——
  **错误值戴着最高权威标签被供奉 17 天**，持续误导后续 agent。

「谁改的谁知道」是结构性的必然。**这份台账 + 广播脚本就是把这条裂缝钉死。**

---

## 一、铁律

1. **改契约 = 改 `risk_rules.py`**。文档一律不复述数值，只写指针
   （`止损 = risk_rules.STRATEGY_STOP_LOSS_PCT`）。复述即造第二个真源。
2. **改完必须登记本台账**，一条变更一行，字段不全 = 未完成。
3. **登记完必须广播**：`python scripts/broadcast_contract_change.py`
   （CHANGELOG + 每日记忆 + 飞书 + 看板卡）。**只改代码不广播 = 未完成的变更**。
4. **132 日全量回测复核**未过的变更**不得合入生产**（回测结论写进 `回测复核` 字段）。
5. 机器守卫：`tests/test_contract_docs_consistency.py`（活跃层 md vs 真源，漂移即 FAIL）。

### 登记格式（缺字段即打回）

```
### <YYYY-MM-DD> <契约项> <旧值> → <新值>
- 变更人：<谁>
- 依据：<老大拍板 / 三方会签 / 事故修复 —— 附决策台账编号>
- 真源位置：`risk_rules.py:<行号>`
- 回测复核：<已过 132 日全量 / 未过（说明）/ 不适用（说明）>
- 广播：<已跑 broadcast_contract_change.py，时间戳> / <未广播，原因>
- 影响面：<需要同步的文档/技能/记忆清单>
```

---

## 二、变更记录

### 2026-09-30 硬止损 8% → 10%（**历史补录**，2026-10-17 补）

- 变更人：三方会签（总管 + 老三 + 老五）
- 依据：09-30 三方会签，全策略统一
- 真源位置：`risk_rules.py` `STRATEGY_STOP_LOSS_PCT`
- 回测复核：已过（会签时结论，一手证据未见留档 —— **这正是本台账要根治的问题**）
- 广播：❌ **未广播** → 直接后果：6 处文档残留 8%，供奉 17 天（见 §〇）
- 影响面：AGENTS.md / CONTEXT.md / .agent/P0-EXEC-ORDER / .agent/OPTIMIZATION-PLAN /
  SOUL.md / RULES.md / 技能文档等 12 处
- **教训**：变更未登记 + 未广播 = 文档层 17 天口径漂移。2026-10-17 已由
  `tests/test_contract_docs_consistency.py` 钉死，残留 8% 无法再悄悄回来。

### 2026-10-17 止盈语义澄清：回撤容忍 vs 卖出比例（**事故驱动**）

- 变更人：老六（WorkBuddy）执行，老大 2026-10-17 拍板「三档 + 留仓过半」
- 依据：踩坑——`TREND_TP_LADDER` 的第二个值被误读为卖出比例，实为**回撤容忍**；
  分批减仓比例另由 `TP_SELL_LADDER` 表达。**两者禁止混用。**
- 真源位置：`risk_rules.py` `TREND_TP_LADDER` / `TP_SELL_LADDER`
- 回测复核：老大拍板口径 = 三档，总卖 **48%**、留仓 **52%**（决策台账 D-001）
- 广播：已建 `scripts/broadcast_contract_change.py`（2026-10-17 起强制）
- 影响面：`.workbuddy/RULES.md` §3.1（已降级为指针）、`SOUL.md` §3.1、
  `.hermes/memory/MEMORY.md`、`deliverables/决策台账-20261017.md`
- **F4 提示**：本条属「契约级语义」，已强制进长期记忆。

### 2026-10-17 `risk_rules.py` 0.08 静默兜底修复

- 变更人：老六（WorkBuddy）
- 依据：代码里 `STRATEGY_STOP_LOSS_PCT.get(strategy, 0.08)` 是**最后一个活着的 8%**，
  会签改的是 dict 值，兜底没跟着改 → 未登记策略静默吃 8%
- 真源位置：`risk_rules.py`（原 L352 附近）
- 回测复核：不适用（纯 bug 修复，语义回到会签值 10%）
- 广播：已随本次治理一并广播
- 守卫：`tests/test_contract_docs_consistency.py::test_zero_point_zero_eight_gone_from_code`

---

## 三、待办（本台账建立时已识别，未清）

- [ ] 老大拍板：老五模型三说打架（glm-4.7-flash / atomcode(hy3) / hy3(agnes-2.0轮动)）
      → `deliverables/待老大拍板清单-20261017.md`
- [ ] 老大拍板：飞书群 ID 三值 → 同上
- [ ] 环境门建议仓位 30% vs 50% 打架 → 同上

---
### 2026-10-23 C-fix 时间止损 P0 合成数据护栏（**非契约变更**）

- 变更人：总管（Hermes）｜飞书管事群 meta-P0 根因修复（时间止损日期解析失败假 P0）触发
- 性质：**契约常量一个都没动**（止损10% / 移动止盈阶梯 / 追高4% / 时间止损120 全部不变）。
  本次仅在 `core/risk/risk_rules_impl.py::_emit_time_stop_unknown_alert` 加一道
  defense-in-depth 护栏：生产默认路径（未显式传 queue_path）+ stock_code 无 6 位 A股代码
  （合成/测试哨兵 unknown/TEST001/TESTDEDUP/TEST_VERIFY/INVALID/MISSING）→ 跳过生产 P0
  写入（不写 message_queue / 不写 alert_log P0），仅记 `data/synthetic_alert_audit.jsonl`。
  堵住测试/监控喂合成数据导致的假 P0。测试显式传 tmp queue_path 时护栏不触发（隔离不变）。
- 真源戳：`7c35cf9a638f`（C-fix 前）→ **`ee01c83fe89f`**（当前内容）
- 附带修复：`tests/test_except_narrowing.py::test_valueerror_is_caught` 过期 3-tuple 解包
  （`evaluate_exit` 实返 4 值 `(should_exit, reason, exit_type, extra)`）。
- 回测复核：不适用（无契约数值变更）；`tests/test_risk_rules.py` +
  `tests/test_except_narrowing.py` 全绿（33 passed, 2 skipped）。
- 广播：⚠️ **未执行** —— 本次非契约数值变更（护栏只改告警发射行为），无下游文档数值漂移，
  不广播打扰全员；TSS 刷新仅登记源哈希变更。是否补发广播列待老大确认。
- 守卫：`tests/test_doc_freshness.py::test_true_source_stamp_registered`

---

### 2026-10-19 真源戳同步 + 守卫口径修正（**非契约变更**）

- 变更人：老六（WorkBuddy）｜架构审查触发
- 性质：**契约常量一个都没动**（`git diff 2e3ff47c e779ea27 -- risk_rules.py` 只含
  `_emit_time_stop_unknown_alert` 补 `alert_log.jsonl` 台账留痕，D-10 项）。
  本次只是把被非契约改动打成过期的真源戳同步回当前内容。
- 真源戳：`f39cdae2961c`（2026-10-17 18:37 那版）→ **`7c35cf9a638f`**（该版内容）
- 附带修正（口径缺陷，非数值）：原 `sha256_of` 按**原始字节**哈希，而本机 working tree
  是 CRLF（`risk_rules.py` 含 905 个 `\r\n`）、git 库内是 LF（`.gitattributes:7`）
  ⇒ 同一份内容在不同 checkout 机器上算出两个不同的戳，守卫变成**环境相关**
  （可假红也可假绿）。已改为 CRLF→LF 归一化后哈希，戳只反映内容。
  改动点：`scripts/sync_true_source_stamp.py::sha256_of` +
  `tests/test_doc_freshness.py::sha256_of`（**两处必须同口径**）
- 回测复核：不适用（无契约数值变更）
- 广播：⚠️ **未执行** —— 本次非契约变更，广播会打扰全员；已列入
  `deliverables/待老大拍板清单-20261019-架构审查.md`，待老大确认是否补发。
- 守卫：`tests/test_doc_freshness.py::test_true_source_stamp_registered`

---

> 2026-10-23 02:45 · 契约变更广播：S6 risk_rules迁移缺陷修复 7c35cf9a638f → 7c35cf9a638f ｜ 真源戳 `TSS:7c35cf9a638f` ｜ 广播人 workbuddy ｜ 回测 done

> 2026-10-23 07:05 · 契约变更广播：时间止损P0合成数据护栏(非契约参数,仅真源戳刷新) TSS:7c35cf9a638f → TSS:ee01c83fe89f ｜ 真源戳 `TSS:ee01c83fe89f` ｜ 广播人 总管(Hermes) ｜ 回测 done

> 2026-10-26 09:05 · 契约变更广播：alert_log D-10段合成码护栏(非契约参数,仅真源戳刷新) TSS:ee01c83fe89f → TSS:c1d29f831efa ｜ 真源戳 `TSS:c1d29f831efa` ｜ 广播人 老五 ｜ 回测 done
