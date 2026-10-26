# P1-C 验收报告：runbook 路径修复 + P-11 卫生断言

**日期**: 2026-10-19
**执行者**: 总管（Agnes）
**原任务**: t_cd473e06 — 「runbook 路径修正：告警指哪儿文件就得在哪儿」

---

## 一、改动清单

| 文件 | 类型 | 行数 | 说明 |
|------|------|------|------|
| `docs/runbook-人工单点.md` | 新增 | 80 | 当前待办版（Gateway churn/D-6余账/self_audit超时/webhook重建） |
| `scripts/self_heal_check.py` | 修改 | +25 | ALERT_REF_PATHS 常量 + validate_alert_paths() 函数 + main() 集成 |
| `scripts/test_p1c_runbook_path.py` | 新增 | 60 | P-11 卫生断言测试：4用例 |

## 二、关键决策

1. **runbook 内容**：不复刻 10-15 旧版（四项全清已归档），新建当前待办版
   - 参考 `docs/archive/runbook-人工单点.md`（旧版）+ `docs/channel-changelog.md`（现状）
   - 四项当前待办：①Gateway重启风暴根治 ②D-6余账修复 ③self_audit超时 ④webhook重建（可选）

2. **P-11 卫生断言**：显式列表（ALERT_REF_PATHS）替代正则扫描
   - 原因：正则对引号转义敏感，易误匹配注释/字符串边界
   - 精确、可审计、零假阳性

3. **path 引用**：
   - `docs/runbook-人工单点.md` ✅ 真实存在（新创建）
   - `docs/规范-静默运行-20261017.md` ✅ 真实存在（原有）

## 三、先红后绿证据

### 红：注入断裂路径
```bash
$ PYTHONPATH= ./.venv/Scripts/python.exe -m pytest \
    scripts/test_p1c_runbook_path.py::test_validate_alert_paths_broken_triggers_p1 -v
# 注入 docs/非存在路径-{id}.md → 预期 P1 alert
```
✅ 实际：`assert "P-11" in p1_alerts[0][0]` PASS + `assert "非存在路径" in ...` PASS

### 绿：全路径真实存在
```bash
$ ls docs/runbook-人工单点.md docs/规范-静默运行-20261017.md
docs/runbook-人工单点.md     docs/规范-静默运行-20261017.md
```
✅ `validate_alert_paths()` → log "告警路径卫生检查通过（2 条路径全部存在）"

## 四、测试覆盖

| 用例 | 场景 | 断言 | 结果 |
|------|------|------|------|
| test_runbook_path_exists | runbook 文件存在 | os.path.exists = True | ✅ |
| test_validate_alert_paths_all_good | 所有路径存在 | 无 alert，有 log | ✅ |
| test_validate_alert_paths_broken_triggers_p1 | 注入不存在路径 | P1 alert 含 P-11 | ✅ |
| test_runbook_content_current_not_archived | runbook 非旧版 | 含 Gateway 关键词 | ✅ |

全量 pytest（20项）：EXIT=0

## 五、真实路径验证

```bash
$ ls docs/runbook-人工单点.md
docs/runbook-人工单点.md
$ ls docs/规范-静默运行-20261017.md
docs/规范-静默运行-20261017.md
```
两条路径均真实存在。

## 六、边界声明

- 不修改 `docs/archive/` 下任何历史文件
- 不改动 `risk_rules.py` 任何参数
- 不写 `data/holdings.json` / `data/trade_log*` / `config.json`
- P-11 断言只检查路径存在性，不检查内容正确性

## 七、回滚点

```bash
git revert HEAD   # 回滚 self_heal_check.py + test_p1c_runbook_path.py
rm docs/runbook-人工单点.md  # 删除新增 runbook
```

## 八、未验证项

- `self_heal_check.py` 完整端到端运行（exit 124 超时问题未解决，本项只测 seam）

---
**验收结论**: ✅ 通过。P1-C 完成：runbook 重建 + P-11 断言接入 + 4测试全绿。
