# P0-1 验收报告：A11 交叉校验矛盾修复
**日期**: 2026-10-19  
**任务**: A6 感知 P0 台账，闭环健康度不再假绿  
**提交**: `1fdab15e`

---

## 根因诊断

| 维度 | 发现 |
|------|------|
| `defect_ledger.json` | 43 条条目，10 条 open P0，41 条 open 全量 |
| A11 原始行为 | 检测到台账有 10 条 P0 但本报告无 FAIL → 判 FAIL（正确） |
| 实际输出 | A11=FAIL，但 A0–A10 全部 PASS → 系统自检"机制健康"与"治理失效"并存 |
| 根本矛盾 | A6（自审机制运行）只验产物新鲜度，不验治理结果 → 假绿 |

## 修复内容

**`scripts/closedloop_health.py`**:
1. 新增 `DEFECT_LEDGER` 路径常量
2. 新增 `_count_open_p0()` 辅助函数（读 `data/audit/defect_ledger.json`）
3. `check_a6_self_audit()` 在产物新鲜后追加 P0 治理检查：
   - `open_p0 > 0` → 返回 `FAIL: "自审机制运行但治理失效: N 条 open P0 未销账"`
   - `open_p0 == 0` → 保持原 PASS

**`tests/test_closedloop_health.py`**:
1. `TestA6SelfAudit.test_pass`: 补充空 defect_ledger + 新鲜产物 setup
2. 新增 `test_fail_open_p0`: 构造含 P0 的台账 → 断言 A6=FAIL

## 修复前后对比

| 断言 | 修复前 | 修复后 |
|------|--------|--------|
| A6_自审机制运行 | PASS（假绿） | **FAIL**（真实反映治理失效） |
| A11_跨体检器交叉校验 | FAIL（矛盾信号） | **PARTIAL**（已被 A6 捕获，不重复计） |
| 整体 score | 11.5/13 (88.5%) | **10.5/13 (80.8%)** |

## 验收断言

```bash
# 1. 单元测试全绿
PYTHONPATH=scripts pytest tests/test_closedloop_health.py -q
# 期望: 43 passed

# 2. A6 现实态检查
PYTHONPATH=scripts python -c "
import sys; sys.path.insert(0,'scripts')
import closedloop_health as m
r = m.run_all_checks()
assert r['A6_自审机制运行']['status'] == 'FAIL'
assert 'P0' in r['A6_自审机制运行']['detail']
print('A6 FAIL confirmed:', r['A6_自审机制运行']['detail'])
"
# 期望: A6 FAIL 10 条 open P0

# 3. A11 降级为 PARTIAL
# 期望: A11 status=PARTIAL, detail 含"已被本报告 FAIL 项捕获"
```

**实测输出**:
- `pytest tests/test_closedloop_health.py`: **43 passed ✅**
- A6: `FAIL 自审机制运行但治理失效: 10 条 open P0 未销账`
- A11: `PARTIAL 台账 10 条 open P0 已被本报告 FAIL 项捕获`

## 证据链
- [x] 根因分析（defect_ledger.json 读取 + A11 逻辑审查）
- [x] 代码变更（+22行 helper，+8行 A6 判断）
- [x] 测试覆盖（3个 A6 用例全绿）
- [x] 回归验证（43/43 test_closedloop_health 全绿）
- [x] git commit: `1fdab15e`

## 遗留
- A6 FAIL 是预期行为——反映真实治理问题（10 条 P0 未消）
- 需老三方讨论：哪些 P0 可立即销账？哪些需等外部依赖？
- 销账后 A6 自动恢复 PASS，闭环完整
