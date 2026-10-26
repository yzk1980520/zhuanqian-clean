# 步级审批检查点约定（借鉴 LazyMind State Brain 设计）

**版本**: v1.0 · 2026-10-26  
**授权**: 老大拍板  
**来源**: LazyMind 设计借鉴（不引入代码）

---

## 设计原理

当前系统只有 `laowu_approved` 一个固定审批门。  
借鉴 LazyMind "审批检查点" 设计：**任务在任意步骤前可暂停，等待人工审批后再继续**。

---

## 约定

### 任务体格式

任务 body 中用如下标记指定检查点：

```
CHECKPOINT <checkpoint_id>: <暂停原因描述>
  触发条件: <什么情况下触发>
  审批方: <总管/老五/老大>
  超时: <N 小时>（可选）
```

**示例**：
```
CHECKPOINT cp_001: 修改 risk_rules.py 前
  触发条件: 执行到 patch risk_rules.py 之前
  审批方: 老五
  超时: 4h

CHECKPOINT cp_002: 修改 trade_log 写入路径前
  触发条件: 执行到写入 data/trade_log.json 之前
  审批方: 总管
  超时: 2h
```

### 执行机制

Worker（老三/老五）在到达 CHECKPOINT 时：

1. 调用 `kanban_block(kind=needs_input, reason="CHECKPOINT <id>: <描述>")`
2. 任务进入 `blocked` 状态，dispatcher 暂停调度
3. 审批方通过飞书或 kanban UI 审批
4. 审批方调用 `kanban_unblock`（或 `kanban_complete` 跳过）
5. Worker 从断点继续（**不重启全任务**，用 `kanban_comment` 记录"已审批，继续"）

### 与现有流程的关系

| 现有门 | 新增门 |
|--------|--------|
| `laowu_approved`（laowu 评审前） | 任意步骤前插入（含代码修改前、写入前、回测前） |
| `review_status.json`（review 状态） | 步骤内部分支（通过/驳回/继续） |

**CHECKPOINT 是 `laowu_approved` 的超集**：
- 若任务无 CHECKPOINT → 现有 `laowu_approved` 流程不变
- 若任务有 CHECKPOINT → 该步骤前暂停，`laowu_approved` 在 CHECKPOINT 之后仍生效

---

## 实施清单

| 项 | 工作量 | 负责人 |
|----|--------|--------|
| 在任务模板中加入 CHECKPOINT 字段说明 | 10 min | 总管 |
| 在 AGENTS.md §4.1 加 CHECKPOINT 规则 | 5 min | 总管 |
| 在 worker skill 中加 CHECKPOINT 检测逻辑 | 30 min | 老三 |
| 首次使用 CHECKPOINT 的任务（验证） | 随任务 | 三方 |

---

## 风险与边界

- ❌ CHECKPOINT **不替代** `laowu_approved`（R0 任务仍需老五评审）
- ❌ CHECKPOINT 超时（默认 4h）自动放行 = **fail-open**，须在任务 body 中显式写"超时策略：继续 / 打回"
- ✅ CHECKPOINT 记录写入 kanban comment（审计日志）
