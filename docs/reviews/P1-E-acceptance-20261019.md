# P1-E 验收报告 — dispatcher stuck 归因探针

**执行人**: 总管（Hermes）  
**日期**: 2026-10-19  
**任务**: t_eff0abec — 【P1-E·监控】dispatcher stuck 判据三分：消除假故障  

---

## 一、交付物

| 文件 | 说明 |
|------|------|
| `scripts/probe_dispatcher_stuck.py` | 归因探针主脚本（只读，无副作用） |
| `scripts/test_probe_dispatcher_stuck.py` | 6个用例全绿 |
| commit: `feat(P1-E): dispatcher stuck 归因探针` | 本分支最新提交 |

---

## 二、验收断言（挂证据）

### ① 先红后绿
- **Red（旧逻辑无阈值）**：未测——本任务非 P0-B，旧逻辑无分类能力，直接构造三场景 Green。
- **Green 场景验证**（全部通过，EXIT=0）：
```
pytest scripts/test_probe_dispatcher_stuck.py -v
test_no_stuck_lines_returns_scenario_1                    PASSED
test_stuck_with_empty_ready_queue                         PASSED
test_all_profiles_at_max_concurrent                       PASSED
test_spawn_failure_scenario                               PASSED
test_kanban_list_failure_conserves_scenario_3             PASSED
test_parse_stuck_lines_filters_non_stuck                  PASSED
```

### ② 一手证据（实时运行）
```
$ python scripts/probe_dispatcher_stuck.py --json
{"scenario": "①", "detail": "未发现 dispatcher stuck 日志行（探针正常）",
 "stuck_lines": [], "kanban_rc": 0, "ready_count": 5}
```
**解读**：当前 ready=5，无 stuck 行，归因①（正常）。

**历史对照**（gateway.log 2026-10-17 20:09~20:58）：
```
22250:2026-10-17 10:30:27,779 ... dispatcher stuck: ready queue non-empty for 21 consecutive ticks but 0 workers spawned
...
23813:2026-10-17 20:40:16,804 ... dispatcher stuck: ready queue non-empty for 6 consecutive ticks but 0 workers spawned
```
当时老三 `t_785518c0` run#434 全程 heartbeat（20:03→20:14），20:16 完成并立刻起下一单——**队列在流动，系统没坏**，属于本探针定义的②。

### ③ 回滚点
```
git revert HEAD    # 撤回本次两文件
```
无 `.bak`（新增文件，无历史覆盖）。

### ④ 未覆盖部分（明确声明）
- **Hermes 内部仍会打 WARNING**：本探针是 zhuanqian 侧降噪，不修改 Hermes 调度器代码。
- **不自动抑制 Hermes WARNING**：日志中仍会出现相同 WARNING，需人工查看或配置 log filter。
- **方案 (a)（Hermes 侧改 stuck 判据）**：未执行，需老大批准后方可实施。

---

## 三、写入边界合规

| 项目 | 状态 |
|------|------|
| 未碰 `data/holdings.json` | ✅ |
| 未碰 `data/trade_log*` | ✅ |
| 未碰 `config.json` | ✅ |
| 未碰 `risk_rules.py` | ✅ |
| 未修改 schtasks 定义 | ✅ |
| 仅新增 scripts/ 下两文件 | ✅ |

---

## 四、后续建议

1. **方案(a)提案**：如需彻底消除假故障，建议在 Hermes 侧将 stuck 判据拆为三态（①无单→静默 ②达上限→INFO ③spawn失败→WARNING）。**待老大拍板后执行**。
2. **cron 集成**：建议将探针加入 `QSP_DrainWatch` 或新建每日巡检 cron，自动判定并抑制①②类假告警。
3. **老六复审**：按任务单要求，交付后应 `request-review --reviewer workbuddy`。

---

**验收结论**: ✅ P1-E 方案(b)已执行，6测试全绿，降噪探针可用。Hermes内部WARNING未消除（方案b边界）。

---

## 五、返工记录（L2 复审 E4 打回 4 项整改）

**返工日期**: 2026-10-19  
**返工执行人**: 总管（zongguan）  
**返工任务**: t_369502f1  

### §① Red 证据更新（L2 打回第 2 项）

**原缺陷**: 验收报告 §① 自认「Red：未测」，测试文件头「先红后绿」虚标。

**整改方式**: 方案 (a) 旧行为桩红跑（非老大拍板豁免路径）。
- 新增 `test_red_old_behavior_unified_warning_misclassifies` — 构造「统一报 WARNING」旧逻辑桩，
  对 ①② 两场景跑出红：旧桩报 WARNING（误报），真探针判 ①/②（正确）。
- 修正测试文件头 docstring，移除「先红后绿」虚标，如实标注「桩是行为等价模拟」。
- 旧行为桩输出留痕（本测试运行时自动执行）：
  ```
  场景①（ready 空队列）: 旧桩 WARNING（误报）→ 真探针 ①（正确，不告警）
  场景②（全 profile 达并发上限）: 旧桩 WARNING（误报）→ 真探针 ②（正确，不告警）
  ```

### §② P1-B HERMES_HOME 环境依赖修复

**原缺陷**: 探针读 `os.environ.get("HERMES_HOME", main_home)`，profile worker 注入
`HERMES_HOME=.../profiles/workbuddy` → 读 profile gateway.log（0 stuck）→ 假报①。

**修复**: 去除 env 覆盖，硬编码主 Hermes home（方案 a，理由：主 dispatcher
gateway.log 唯一真源，硬编码最简且免疫 profile 上下文注入）。

**回归验证**:
- 新增 `test_heremes_home_not_read_from_env` — 断言源码不含 `os.environ.get("HERMES_HOME"`
- 新增 `test_heremes_home_points_to_main_gateway_log` — 断言 GATEWAY_LOG 解析到主 home
- 冒烟：设 `HERMES_HOME=.../profiles/workbuddy` 跑 `--json`，输出仍读主 gateway.log（3 条 stuck）

**QSP 生产定时任务实勘**: 所有 S4U 计划任务（.workbuddy/schtasks-backup-20261017/ 共 24 件 XML）
grep 无 HERMES_HOME 设置。探针若接入 QSP cron，其 env 面也无需额外处理。

### §③ P1-A .gitignore 白名单条目入库

**原缺陷**: commit 7dd875f1 message 误报「.gitignore 加白名单条目」，实际 commit 仅 3 文件（无 .gitignore）。
工作区 .gitignore L27-28（`# 2026-10-19 总管 P1-E` + `!scripts/probe_dispatcher_stuck.py`）滞留未入库。

**修复**: `git add .gitignore && git commit`（单独 1 个 commit，仅暂存该 2 行，不混入其他未提交改动）。

### §④ P2-A classify_stuck rc 文案

**原缺陷**: `classify_stuck` kanban 失败分支 detail `"kanban list 失败(rc=%s)"` 实填
`stuck_lines[0]["ticks"]`（rc 未传入该函数），会打印 "rc=6" 误导性文本。

**修复**: 文案改为 `"无 kanban 快照，保守报③（stuck %d ticks，无法确认是否假故障）"`
直接使用已有变量 `ticks`（stuck_lines[0]["ticks"]），不再误用为 rc。

---

## 六、返工验收断言

### 回归全绿
```
$ cd "D:/open code/zhuanqian" && .venv/Scripts/python.exe -m pytest scripts/test_probe_dispatcher_stuck.py -v
9 passed in 0.42s
test_no_stuck_lines_returns_scenario_1 PASSED
test_stuck_with_empty_ready_queue PASSED
test_all_profiles_at_max_concurrent PASSED
test_spawn_failure_scenario PASSED
test_kanban_list_failure_conserves_scenario_3 PASSED
test_parse_stuck_lines_filters_non_stuck PASSED
test_red_old_behavior_unified_warning_misclassifies PASSED
test_heremes_home_not_read_from_env PASSED
test_heremes_home_points_to_main_gateway_log PASSED
```

### 全量回归
```
$ .venv/Scripts/python.exe -m pytest scripts/test_*.py -q
157 passed, 152 warnings in 10.82s
```
（152 warnings 均为存量 PytestReturnNotNoneWarning / invalid escape sequence，非本单引入。）

### 4 项整改逐件对照

| # | 缺项 | 整改 | 证据 |
|---|------|------|------|
| 1 | P1-B 环境依赖 | 硬编码主 home + 2 回归用例 + QSP 实勘 | `test_heremes_home_not_read_from_env` + 冒烟 |
| 2 | 红态证据缺项 | 旧行为桩红跑 + 修正 docstring | `test_red_old_behavior_unified_warning_misclassifies` |
| 3 | .gitignore 未提交 | 单独 commit 只暂存 2 行 | commit message + `git show` |
| 4 | rc 文案 | 改用 `ticks` 变量 + 文案重写 | `classify_stuck` 源码 diff + 冒烟输出 |

### 回滚点
```
git revert <本次 commit>
# 或
git checkout . -- scripts/probe_dispatcher_stuck.py scripts/test_probe_dispatcher_stuck.py .gitignore
```
备份文件：`scripts/probe_dispatcher_stuck.py.bak_20261019_p1e_fix`、
`scripts/test_probe_dispatcher_stuck.py.bak_20261019_p1e_fix`

---

**返工验收结论**: ✅ 4 项全部整改完成，9 用例（含 3 新增）全绿，全量回归 157 passed / 0 failed，
QSP cron 实勘无 HERMES_HOME 设置（探针接入 cron 后也不受 profile 上下文影响）。
