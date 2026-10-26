# 任务单：DD门禁口径重裁后一致性修复

**任务编号**: t_dd_gate_rearbitration_20261016  
**指派给**: 老三  
**优先级**: P0  
**创建时间**: 2026-10-16 04:00

---

## RULING 快照对齐

| 字段 | 值 |
|------|-----|
| 适用 RULING | RULING-DD-20261015 |
| RULING 文档路径 | `docs/DD门禁口径裁定-20261015-新基线重裁.md` |
| **快照 hash** | `b3c17cb2a1ee` |
| 裁定期望值 | DD ≤ 60%（过渡值），回退触发 S3 全量132日 DD<53% |
| 快照时间 | 2026-10-16 04:00 |

> ⚠️ **judge 验收前必读**：若当前 RULING 文档 hash ≠ `b3c17cb2a1ee`，报"口径过期"而非静默按旧值 35% 拒。

---

## 一、任务背景

RULING-DD-20261015 已裁定 DD 门禁 = 60%（基于新基线 S3 DD=56.66%）。但以下文件仍用旧口径或占位值：

| 文件 | 当前值 | 位置 | 问题 |
|------|--------|------|------|
| `evaluate.py` | max_drawdown: 0.70 | L21 | 注释"固定不可修改"，无拍板背书 |
| `phase2_optimization_run.py` | max_dd <= 35 | L90/L107/L181 | 旧口径残留 |
| `dashboards/dashboard_v2.py` | "37.3% > 35%" | L112/L473 | 看板展示用旧值 |

**问题链**：
1. judge 验收 t_a93747fe 时 body 写 35%
2. RULING 已裁 60%（10-15）
3. judge 按原文 35% 拒单 ×2
4. block-loop → auto-decomposer 白拆 5 子任务

---

## 二、任务内容

### 2.1 修正 evaluate.py
- L21 `"max_drawdown": 0.70` → `"max_drawdown": 0.60`
- 更新文件头注释，注明"依 RULING-DD-20261015"

### 2.2 修正 phase2_optimization_run.py
- L90/L107/L181 `max_dd <= 35` → `max_dd <= 60`

### 2.3 修正 dashboards/ 下 4 个文件
- `dashboards/board_server.py` L589
- `dashboards/dashboard_v2.py` L116/L478
- `dashboards/dynamic_dashboard.py` L298
- `dashboards/generate_dashboard.py` L442/L480
- 静态"❌超限"改为按新门禁动态判定

---

## 三、验收标准

1. **语法检查**：
   ```bash
   python -m py_compile evaluate.py phase2_optimization_run.py
   ```
   输出：无报错

2. **门禁测试**：
   ```bash
   python evaluate.py
   ```
   断言：DD 56.66% ≤ 60% → dd_ok=True

3. **快照一致性**：judge 读 body 时 hash = `b3c17cb2a1ee` → 按 60% 评

4. **回归验证**：
   ```bash
   pytest tests/ -q
   ```
   断言：全绿

---

## 四、交付物

| 交付物 | 路径 | 状态 |
|--------|------|------|
| evaluate.py 修正 | `evaluate.py` | 待实现 |
| phase2_optimization_run.py 修正 | `phase2_optimization_run.py` | 待实现 |
| 看板动态判定 | `dashboards/*.py` | 待实现 |
| 验收报告 | `docs/t_dd_gate_rearbitration_acceptance_20261016.md` | 待生成 |

---

## 五、注意事项

1. **备份先行**：
   ```powershell
   Copy-Item evaluate.py evaluate.py.bak_20261016
   Copy-Item phase2_optimization_run.py phase2_optimization_run.py.bak_20261016
   ```

2. **清环境**：跑 python 前 `Remove-Item Env:PYTHONPATH`

3. **不写交易数据**：holdings/trade_log 只读

4. **通知总管**：完成后飞书回复「✅ DD门禁修复完成」+ 交付物链接

---

**创建人**: 总管  
**状态**: 待执行
