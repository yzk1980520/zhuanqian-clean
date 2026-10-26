# R1-2 任务单口径快照机制 · 单纪

**录入时间**: 2026-10-16 04:00
**录入人**: 老三

---

## 一、交付物清单

### A段（仓内模板）

| # | 文件 | 状态 | 证据 |
|---|------|------|------|
| 1 | `docs/R1-2_task_single_ruling_snapshot_v1.0.md` | ✅ 已落档 | 7909 bytes, 设计文档 |
| 2 | `docs/tasks/t_dd_gate_rearbitration_20261016.md` | ✅ 已落档 | 3109 bytes, 示例任务单 |
| 3 | `.agent/TASK-TEMPLATE-v2.0.json` | ✅ 已落档 | 1865 bytes, 模板 schema |
| 4 | `utils/ruling_hash.py` | ✅ 已实现 | 7160 bytes, hash 计算工具 |

### B段（Hermes 侧可行性评估）

| # | 文件 | 状态 | 证据 |
|---|------|------|------|
| 1 | `docs/R1-2_B_section_feasibility_20261016.md` | ✅ 已落档 | 4833 bytes, 评估报告 |

---

## 二、RULING 快照 hash 验证

```bash
$ python utils/ruling_hash.py
计算 RULING hash: docs/DD门禁口径裁定-20261015-新基线重裁.md
  → b3c17cb2a1ee

验证对齐:
  → {'aligned': True, 'embedded_hash': 'b3c17cb2a1ee', ...}

Judge 验收测试:
  verdict: ACCEPT
  reason: DD=56.66% ≤ 60%
```

**结论**：hash 计算正确，judge 对齐逻辑可用。

---

## 三、任务单示例验证

`t_dd_gate_rearbitration_20261016.md` body 内嵌：
- RULING: RULING-DD-20261015
- 快照 hash: `b3c17cb2a1ee`
- 裁定期望值: DD ≤ 60%

**可复算性**：✅ 手动计算 `sha1(DD门禁口径裁定-20261015-新基线重裁.md)[:12]` = `b3c17cb2a1ee`

---

## 四、工具函数 API

### compute_ruling_hash(ruling_doc_path)
```python
from utils.ruling_hash import compute_ruling_hash

hash_value = compute_ruling_hash("docs/DD门禁口径裁定-20261015-新基线重裁.md")
# → "b3c17cb2a1ee"
```

### judge_accept_with_ruling_check(task_body, ruling_registry, threshold=0.60)
```python
from utils.ruling_hash import judge_accept_with_ruling_check

result = judge_accept_with_ruling_check(
    task_body="""
    ## RULING 快照对齐
    | 快照 hash | b3c17cb2a1ee |
    ---
    DD = 56.66%
    """,
    ruling_registry={"RULING-DD": "docs/DD门禁口径裁定-20261015-新基线重裁.md"}
)
# → {"verdict": "ACCEPT", "reason": "DD=56.66% <= 60%", ...}
```

---

## 五、测试验证（2026-10-16 老三补全）

### 5.1 新增测试文件
`tests/test_ruling_snapshot_alignment.py`（9533 bytes，20用例）

### 5.2 测试覆盖场景

| 类 | 场景 | 断言 | 结果 |
|----|------|------|------|
| `TestExtractHash` | 表格/空格/无字段/畸形hash | 5用例 | ✅ 5 passed |
| `TestS1_HashConsistent` | hash一致→ACCEPT/REJECT/真源匹配 | 3用例 | ✅ 3 passed |
| `TestS2_HashDrift` | 旧hash→BLOCKED+口径过期/非静默拒/35→60漂移 | 3用例 | ✅ 3 passed |
| `TestS3_NoHashField` | 无hash字段→降级旧逻辑 | 1用例 | ✅ 1 passed |
| `TestComputeRulingHash` | 12位hex/稳定/缺失文件抛错 | 3用例 | ✅ 3 passed |
| `TestValidateAlignment` | 对齐/不对齐/文档不存在 | 3用例 | ✅ 3 passed |
| `TestEndToEnd_DriftScenario` | 35%任务单面对60%RULING→BLOCKED/60%任务→ACCEPT | 2用例 | ✅ 2 passed |

### 5.3 运行证据

```bash
$ .venv/Scripts/python.exe -m pytest tests/test_ruling_snapshot_alignment.py -v
============================= 20 passed in 5.08s ==============================

$ .venv/Scripts/python.exe -m py_compile utils/ruling_hash.py tests/test_ruling_snapshot_alignment.py
SYNTAX OK
```

### 5.4 回归验证

```bash
$ .venv/Scripts/python.exe -m pytest tests/test_ruling_snapshot_alignment.py tests/test_aoci_config.py -q
======================= 26 passed, 7 warnings in 12.83s =======================
```

**结论**：新增测试零回归，漂移场景红→报"口径过期"实证成立。

---

## 六、下一步

### A段 ✅ 闭环
- 模板可实跑 ✅
- hash 可复算 ✅（`b3c17cb2a1ee`）
- 示例任务单已落档 ✅
- 测试全覆盖（20用例）✅
- 漂移场景实证（S2）✅
- 等价性对照（S1）✅
- 容错降级（S3）✅

### B段待老五 R0 评审
- 需确认 Hermes kanban 插件 goal-loop 代码可访问路径
- 需审核等价性对照报告（已随 `R1-2_B_section_feasibility_20261016.md` 提交）
- 需确认回归测试用例覆盖 ✅（已覆盖）

---

**老三签字**: 2026-10-16  
**单纪状态**: A段闭环（含测试），B段待老五R0评审
