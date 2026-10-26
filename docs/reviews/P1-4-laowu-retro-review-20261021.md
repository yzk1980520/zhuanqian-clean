# P1-4 存量 except:pass 批量修复 · 老五追溯复审（L2）

**评审人**: 老五（laowu，独立数据/回测评审）
**时间**: 2026-10-21 19:55
**对象**: t_272bf8d2【P1-4】存量 except:pass 批量修复（D-6余面，共33处），执行人 laosan，commit 18ceda88
**挂接卡**: t_c5c003e9（本复审件）
**口径**: 主树 `D:/open code/zhuanqian` @ HEAD 18067b57 之上工作区，2026-10-21 实测

---

## 裁定

**❌ 打回（工单级）；7处修复本身 ✅ 通过（带 R1×2 / R2×3 注记）**

原单 2026-10-19 20:21 以"7处 bare except → 具体异常类型"关闭，但其工单范围是 **33 处全量**（工单正文路线图 Week1–Week3），关闭时实际完成 **7/33（21%）**，验收断言不成立，余面 25 处无后续工单。本复审补录实质结论。

## 一、实测证据（命令 + 输出）

### 1.1 commit 18ceda88 实际内容 vs commit message 声称

```
$ git show 18ceda88 --stat
 scripts/dispatch_audit_check.py |   9 ++--
 scripts/risk_manager.py         |   9 ++--
 self_audit_checkers.py          | 115 +++...(P1-3 部分)
 tests/test_hermes_config.py     |  68 +...(P1-3 部分)
```

- commit message 声称 7 个文件（dispatch_audit_check / risk_manager / cron_daily_select / auto_trading_pipeline / factor_health_check×2 / check_protocol_mount / data_flow_checker），**实际入库仅 2 个**。
- 4 个文件为 **gitignored 本地脚本**（`git check-ignore` → `.gitignore:15: scripts/*`），修复只落盘、无法入库：
  `git check-ignore -v scripts/cron_daily_select.py scripts/auto_trading_pipeline.py scripts/factor_health_check.py scripts/data_flow_checker.py`
  全部命中 `.gitignore:15:scripts/*`。
- check_protocol_mount.py 的 `except AttributeError:` 修复实际随 ceb5944e（bulk79 归位）入库，非 18ceda88。
- **注记 [R2]**：commit message 过称（over-claim）：7 处中 4 处本地脚本不在 commit 内，handoff/comment 未标注"入2处+本地5处"。

### 1.2 7 处修复的技术质量（逐一核实）

| 位置 | 现状 | 判定 |
|---|---|---|
| dispatch_audit_check.py:91 `_read_all` | `except OSError:` + stderr print | 类型合理；**print 缺文件名上下文**（变量 `p` 未用）[R2] |
| risk_manager.py:180 `check_position_compliance` | `except (ValueError, TypeError):` + print "CR-01: except:" | 类型合理；**风险合规检查器吞掉日期解析失败 → 合规项静默漏报**，print 未记异常值 [R1] |
| cron_daily_select.py:44 / auto_trading_pipeline.py:48 | `except OSError:` + print（日志旁路） | 合理（日志写入失败不杀主链路）；message 写 "except Exception" 与实际捕获不符 [R2] |
| factor_health_check.py:53,172 | `except (ValueError, json.JSONDecodeError):` + print | 合理；message 同上不符 [R2] |
| **factor_health_check.py:208** | `except Exception: t_stat, p_val = None, None` **静默** | **宣称修复的同一文件，此处在 7 处清单之外漏修**：t 检验静默失败 → p_val=None 灌入因子健康报告，IC/统计监控假绿 [R1] |
| check_protocol_mount.py:25 / data_flow_checker.py:15 | `except AttributeError:` + print（reconfigure 守卫） | 合理 |
| data_flow_checker.py:32,42 `load_json/save_json` | `except Exception as e: log(...); return default` | 带日志但**损坏文件仍返回默认值 = D-6 P0-3 同族假绿语义**（诊断器自身说"无数据"）[R2，降为低优先] |

### 1.3 验收断言不成立（工单正文自带命令）

```
$ grep -rn "^ *except:" scripts/ self_audit*.py | grep -v "except.*as\|except.*Exception\|except.*Error" | wc -l
114        # 工单期望 0
```

对 113 处裸 `except:` 行做体分类（scripts/ 全量 + self_audit*.py）：
- **103 处已响铃化**（体为 print/log —— 10-21 bulk79 等批次批量转换）
- **10 处仍静默**（其中 t2b_gate_v2.py:38 已被 CR-01 lint 命中，余 9 处为 lint 体判定盲区：赋值/tuple 体）

### 1.4 CR-01 门禁当前存量（`python scripts/code_review_lint.py --rule CR-01`）

```
扫描 694 个文件 | 🔴 Blocker 61 | 🟡 Suggestion 0   [FAIL]
```
- 基线 10-16 首扫 = 33 处（603 文件）；现 61 处（694 文件，2026-10-21）→ **新增代码引入的静默吞噬未走 `--files` 门禁**（"只卡新增"未落实）。
- 静默吞噬合计 = 61（lint 命中）+ 9（裸 except 赋值/tuple 体盲区）= **70 处**。

### 1.5 高危点（R1 排序）

1. `scripts/t2b_gate_v2.py:38` `except: pass` —— **门禁脚本**静默吞异常 = 门禁假绿，直接违背"门禁五查"。
2. `scripts/factor_ic_monitor_unified_v2.py:103` `except: return None, None` —— IC 监控假绿（老五域）。
3. `scripts/fix_ic_data.py:109` `ic = 0` 静默 —— IC 数据修复工具把失败写成 0 值。
4. `scripts/factor_health_check.py:208`（见 1.2）。
5. `scripts/emotion_monitor/northbound.py:47` `net_inflow = 0`、`scripts/feishu_event_server.py:118` `text = content`、`scripts/task_*.py` `wait_hours = 0`×3、`scripts/_migrate_root_py_batch3.py:37` `return set()`（一次性工具，可标白）。

### 1.6 回归与红线核查

- `./.venv/Scripts/python.exe -m pytest tests/test_exception_swallowing_fix.py -q` → **11 passed in 0.48s** ✅（工单要求的回归全绿）
- P0-1 红线 `stop_loss_strategy.py` `calc_time_stop`：现为 loud fail（`raise ValueError ... from e`，代码内注明 2026-10-17 修复，"调用方仅测试、无生产调用方"）✅ 红线无假阴性残留。
- `risk_rules.py` 未被 18ceda88 触碰 ✅。

### 1.7 台账与留档

- `docs/派单台账-20261021.md`（tracked，10-21 当日未提交变更）第 12/49 行已挂接本卡：C2=已审、C4=豁免。**该"✅(19:41)"为结构性挂接存在性标记，非实质复审**；实质结论即本报告（C2 在案补正）。
- 原单 comment 线程仅 laosan 完成通告，无 L2 判决留档 → 本件为**首次实质复审**。
- D-11（单语句 `except: pass` AST 盲区）已由 t_f1383ec2 修复并全树复扫，本报告 61 处计数基于 D-11 修复后工具口径。

## 二、裁定理由（对称陈述）

**支持维持"7处已完成"的论点（看多）**：
- 7 处替换本身质量合格：具体异常类型 + 响铃 print，回归 11/11 绿，P0-1 红线 loud fail 确认，risk_rules 未触碰。
- 103 处裸 except 已被后续批次响铃化，静默面比 10-19 关闭时进一步收窄。

**打回的论点（看空，权重更高）**：
- 范围缺口：工单 33 处（工单标题+路线图 Week2/Week3），完成 7 处即关单，余 25 处无工单承接；工单关闭时刻（10-19）早于路线图 Week1 起点（10-20）3 天——**提前关单**。
- 验收断言实测 114 命中 ≠ 0（工单自带 grep）；静默吞噬存量 70 处 > 工单范围 33 处（新增回流）。
- 证据链瑕疵：commit message 把 4 处 gitignored 本地脚本算入 18ceda88（不可入库，D-6 遗留③"本地脚本不入库"未解）；"self_audit 可正常跑通无异常吞噬"无留档输出。
- 高危残留：t2b_gate_v2.py:38（门禁假绿）+ factor_ic_monitor_unified_v2.py:103 / fix_ic_data.py:109（IC 监控假绿，老五域）未修。

**反例自检（什么证据能推翻本报告）**：若 10-19 之后存在（a）P1-4 余面 25 处的后续工单且已关闭、或（b）70 处静默清单中 P1 组 8 处已被其他单修复且留有 L2 留档，则"范围缺口"论点失效。已查 kanban 全库（P1-4/D-6/except 关键词）：t_3c469237 仅为 runbook §2 引用纠错（文档面），t_2da48f19 为 trading_hours 单点补 loud——**均非余面批量工单**。论点成立。

## 三、建议（给总管）

1. **P1-4 重新挂账为 P1-4b**：余面清零工单，基准 = 本报告 §1.4/§1.5 的 70 处静默清单（2026-10-21 口径）+ 103 处裸 except 语法件（改具名 except 或注释白名单）；验收断言沿用工单 grep（0 命中）+ `code_review_lint.py --rule CR-01` 全树 0 Blocker（D-11 后工具已可全量判定，无需再等 7 日分周）。
2. **R1×5 先行**：t2b_gate_v2:38、factor_ic_monitor_unified_v2:103、fix_ic_data:109、factor_health_check:208、northbound:47 —— 其中前 4 处属门禁/回测/IC 监控关键路径，建议 48h 内完成并跑等价性对照。
3. **本地脚本入库决策**：cron_daily_select / auto_trading_pipeline / factor_health_check / data_flow_checker 走 `.gitignore` 白名单或迁 `local/` 后入库（D-6 遗留③），否则每次 clone 丢失修复。
4. **台账提交**：docs/派单台账-20261021.md 的当日变更未 commit，建议随 P1-4b 工单一并入库留痕。
5. **技术债台账更新**：`docs/tech_debt_ledger.md` D-6 条目补 2026-10-21 口径（33 → 70 静默，含新增回流原因：门禁 `--files` 只卡改动面、新文件未走门禁）。

## 四、风险边界（适用条件）

- 本复审基于 2026-10-21 19:30–19:55 主树工作区快照；此后若 P1-4b 或 bulk 批次再改 scripts/，70 处清单需重跑 `code_review_lint.py --rule CR-01` 复算（引擎=code_review_lint D-11 修复后版）。
- 9 处"赋值/tuple 体"盲区判定基于人工体分类脚本（scratch/bare_scan.py），与 lint 工具口径不同，清单以 §1.5 逐项列出为准。
- 老五不风控：t2b_gate_v2 假绿的**处置**（是否冻结门禁）归总管，本件仅提供数据。
