# 【老五 R0·D-2】goal-loop judge RULING 对齐改动放行评审

评审人：老五（laowu）
时间：2026-10-18 08:00（CST）
被评审对象：hermes-agent 工作树（`data/hermes-home/hermes-agent`）D-2 改动
- `hermes_cli/goals.py` L962-1043：新增 `judge_accept_with_ruling_check`（+84 行，纯新增）
- `hermes_cli/kanban.py` L851 + L878-895：import + "done" 判定处挂 RULING 对齐检查（+19/-1 行）

## 结论

## ❌ 打回：RULING 检查存在 1 处无防护崩溃面（T11）+ 1 处 reason 归属错误（T10）+ 仓内零测试资产 + 工作树夹带 out-of-scope 文件

核心判定语义（pass-through / must_contain / min / value / regex / 口径）经 12 场景红绿实证全部正确，但 R0 0 容忍线不放过 4 项，全部为低成本修复（合计 <20 行 + 1 个测试文件）。

## 逐判据核验

### 判据 1 安全面 —— ⚠️ 部分立
- ✅ 无 RULING 零影响成立：T1（verdict≠"done"→(True,"")）/ T2（无 rulings 目录）/ T3（workdir 空串）/ T4（task_id 不匹配）全 PASS。
- ✅ json parse 失败不 crash（T8：坏 JSON 文件被 `except Exception: continue` 跳过，同目录合法 RULING 仍生效）。
- ✅ regex 无效不 crash（T9：`_re.error` 被捕获后 skip）。
- ❌ **T11 无防护崩溃面（P0 候选）**：`metadata_assertions` 含非 dict 元素（如字符串 `"oops"`）时，L1015 `assertion.get("key")` 抛 `AttributeError: 'str' object has no attribute 'get'`。调用点 kanban.py L883 **不在 try/except 内**（try 块 L854-870 只包 `judge_goal`）→ 异常穿透 `_goal_mode_handoff_rejection` → `_cmd_complete`/request-review 命令带 traceback 硬崩 → goal-mode 任务永久卡死在 done 手递，且无重试路径。触发条件：工作区 `data/rulings/*.json` 结构失范（手改/损坏/写入方 schema 漂移）。与函数自身"异常安全"的 docstring 意图（json/regex 双防护）自相矛盾——防护只做到 2/3。
- ⚠️ 附带边界（记 P2）：judge client 不可用（L848）/ transport_failed（L871-877）两条 fail-open 路径**提前 return ("done", None)，RULING 检查整体被跳过**。若 RULING 是 D-2 的唯一硬门禁，该门禁可被 judge 通道故障静默绕过——是否接受此边界请总管裁定。
- ⚠️ 静默吞噬记录（P1，不阻塞）：L994 坏 JSON `continue` 无 log；L1039 坏 regex `pass` 无 log。建议 `logger.warning` 输出文件名，否则审计时无法区分"无 RULING"与"RULING 读挂了"。

### 判据 2 口径面 —— ✅ 立
RULING 块位于 `if verdict == "done":`（L878）之内；"continue"/"blocked"/"wait" 走 L895 原路径 `return (verdict, None if verdict=="done" else reason)`，diff 未触碰。函数内部 L979-980 对 `verdict != "done"` 二次早退（防御性双保险）。mismatch 时 override 为 `("continue", "RULING mismatch: ...")`，原因经 `logger.info` 落日志（L890-893）。

### 判据 3 消费面 —— ✅ 立
`Task` dataclass（kanban_db.py L614 起）：`workspace_path: Optional[str]`（L624）、`metadata: Optional[dict]`（L718，DB 列 L951 `metadata TEXT` + L732 `_json_or` 解析）。调用侧 L881-882 用 `getattr(task, "workspace_path", None) or ""` / `getattr(task, "metadata", None) or {}`，字段名对齐、缺省值安全。全库 grep `judge_accept_with_ruling_check` 仅 3 处命中（goals.py 定义 + kanban.py L851 import + L883 调用），无其他消费方。

### 判据 4 先红后绿 —— ✅ 可测（已实证）
12 场景独立测试（scratch `d2_ruling_test.py`，函数源码切片 exec，避免重依赖导入）：
- 绿：T5 must_contain 缺 key → reject（reason 点名 'ir'）；T6 ic=0.01<min 0.03 → reject；T7 min+value+regex 全过 → accept；T1-T4 pass-through。
- 红：T10/T11（见下）。mismatch 场景构造无阻碍，可直接进仓内 pytest。

### 判据 5 改动面 0 容忍 —— ❌ 工作树不洁
D-2 diff 本体严格 2 文件（git diff：goals.py +84、kanban.py +19/-1，零交叉）。**但** `git status --short hermes_cli/ gateway/` 显示 `M gateway/status.py`（+33 行，OPS-1 2026-10-16 WMI 回退，注释自带日期，早于 D-2）+ 未跟踪 `gateway/pid_identity.py`、`gateway/status.py.bak_20261016_192630`。这些非 D-2 产物，但夹在同一工作树——若后续按"整树提交"纪律操作会把 OPS-1 混入 D-2 变更集。要求：D-2 与 OPS-1 分单/分提交，或明确 OPS-1 已另行销账。

## 发现的缺陷清单

1. **[P0] T11 崩溃面**（goals.py L1014-1015）：`metadata_assertions` 非 dict 元素 → `AttributeError`，调用点无 try 包裹。修复：`if not isinstance(assertion, dict): continue`；同时给 `must_contain`/`task_ids` 加 `isinstance(list)` 守卫（`task_ids` 为字符串时 L999 `task_id in ids` 退化成子串匹配——T12 实证 `t_00f` 可命中 `t_00f3f017` 的 RULING，P2）。
2. **[P1] T10 reason 归属错误**（goals.py L1012/1019）：reason 串引用外层 glob 循环变量 `path`（保留最后一个文件名），多 RULING 命中时归属错位（实证：a.json 的 missing key 被记到 b.json 名下）。不影响判定结果，但审计线索失真。修复：glob 循环改存 `(path, doc)` 元组，reason 用本文件的 basename；顺手删 L1008 死代码 `fname = ... # placeholder`。
3. **[P1] 零测试资产**：仓内 grep `judge_accept_with_ruling_check` tests/ 零命中。R0 新判定函数无回归测试 = 下次改动无护栏。要求新增 `tests/hermes_cli/test_goals_ruling.py`（本评审 12 场景可直接移植，T11/T12 修复后翻绿）。
4. **[P1] 静默吞噬**（L994/L1039）：坏 JSON/坏 regex 静默 skip，无 log。加 `logger.warning`（带文件路径）。
5. **[P2] out-of-scope 夹带**：gateway/status.py（OPS-1）+ pid_identity.py + .bak 与 D-2 同树，需分单。
6. **[P2] 边界裁定**：judge 不可用 fail-open 路径跳过 RULING 检查（kanban.py L848/L871-877），适用边界需总管书面确认。

## 复验条件（修复后老五重跑）

```
cd "D:/Hermes agent/Hermes Agent CN Desktop/data/hermes-home/hermes-agent"
python -m py_compile hermes_cli/goals.py hermes_cli/kanban.py
python -m pytest tests/hermes_cli/test_goals_ruling.py -v        # 12 场景全绿
git diff --stat hermes_cli/  # 仍须仅 goals.py + kanban.py（测试文件除外）
git status --short gateway/  # OPS-1 已分单/销账
python <scratch>/d2_ruling_test.py  # 老五独立红绿复现，期望 0 FAIL
```

## 验证证据

- 命令：`git diff hermes_cli/goals.py / hermes_cli/kanban.py`（完整 diff 已逐行审阅，本报告行号以此为准）
- 命令：`python d2_ruling_test.py` → `12 场景, 2 FAIL`（T10 FAIL reason 归属；T11 FAIL `AttributeError: 'str' object has no attribute 'get'`）；其余 10 项 PASS
- 命令：`python -m py_compile` 双文件 → OK
- 命令：全库 `grep -rn judge_accept_with_ruling_check` → 3 处（定义 1 + 消费 2）
- 时间戳：2026-10-18 07:52-08:00（CST），引擎：hermes-agent 工作树 @ 未提交态（goals.py mtime 10-17 20:22 / kanban.py 10-17 20:24）
