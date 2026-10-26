# 全量 pytest 超时排查报告（2026-10-25 任务 T054-T056 附加-1）

**执行人**: 老三（opencode）· **签批**: 总管 · **任务**: t_64cf288b
**现象**: 全量 `pytest tests/ -q` 在 180s 超时退出（exit 124，外部 harness SIGALRM 型超时）
**历史基线**: 1784 passed（见 t_112197e1 等任务记录）

## 1. 实测数据（本机 venv 运行，`.venv/Scripts/python.exe -m pytest`，`unset PYTHONPATH`）

- 测试总数：**1873**（1710 passed + 14 failed + 149 skipped；较 1784 基线 +89，+5%）
- 收集耗时：**~45s**（`--collect-only -q` 实测 45.14s）
- 全量运行：**667.81s（11min07s），exit=1**（因 14 项既有失败；非超时退出）

## 2. 全量运行结果

| 指标 | 值 |
|---|---|
| 命令 | `.venv/Scripts/python.exe -m pytest tests/ -q --tb=no --durations=60` |
| 总耗时 | **667.81s**（0:11:07） |
| 退出码 | 1（14 failed；独立运行无 180s 预算时不会 timeout） |
| passed / failed / skipped | 1710 / 14 / 149 |
| 180s 预算内完成? | **否：670s ≈ 预算的 3.7 倍，必然 exit 124** |

**耗时 Top 10（--durations=60 摘录，合计 484s ≈ 全量 72%）**:

| 耗时 | 测试 | 类型 |
|---|---|---|
| 130.94s | test_evolution_loop_p1v2.py::test_assert1_known_passing_factor | IC 重算 |
| 78.74s | test_layers_contract.py::TestL2FactorsContract::test_no_unknown_factor_fields | L2 因子全量校验 |
| 67.54s | test_gate_fn_integration.py::test_g3_equiv_skip_when_no_path | 门禁 OOS |
| 61.46s | test_gate_fn_integration.py::test_gate_fn_blocks_oos_leakage | 门禁 OOS |
| 54.11s | test_evolution_loop_p3v2.py::test_assert1_lesson_persistence | 演化件 |
| 46.12s | test_s3_strategy_consistency.py::test_chase_ban_disabled_does_not_interfere | 策略一致性 |
| 35.67s | test_scan_performance.py::test_single_scan_speed（setup） | scan fixture |
| 19.20s | test_p2a_retry_on_removal.py::test_p2a_consume_side_zero | P2a |
| 18.06s | test_board_server.py::test_html_contains_expected_sections | 板服 |
| 15.07s | test_factor_decay_monitor.py::test_queue_write_failure_loud | 衰减监控 |

**14 项失败归类（均为既有/环境件，与本次 diff 零交叉）**:
DL/torch×2（test_dl_import_degradation）、model_config 环境键×2、L1 财务缓存契约×4
（test_layers_contract L1，数据文件陈旧/缺失）、trade_log 新鲜度×1（test_system，数据陈旧）、
factor_ic/registry/feishu/weekly_report/bare_core_imports 各×1。

## 3. 超时根因

1. **预算与规模不匹配（主因）**: 180s 是外部 harness 的 SIGALRM 型预算（exit 124 = 被杀）。
   全量实测 **670s = 预算 3.7 倍** → 任何时刻跑全量都必然超时。
2. **少数重测试吃掉大头**: Top 10 重测试 = 484s（72%），其中 Top 4 = 334s（50%）。
   其余 1863 项合计仅 ~184s——长尾很短，**排除 ~15 项最重件即可把门禁档压进 180s**。
3. **测试数量增长**: 1784 → 1873（+5%），且 `slow`/`integration`/`backtest` 等 marker
   **已定义但 0 项使用**（`pytest -m slow` 收集数 0），无排除重测试的通道。
4. **系统负载**: 排查时段（00:5x 夜间静默段）负载低，排除环境抖动；超时是规模型，非负载型。

## 4. 测试数量增长来源（近 10 笔涉及 tests/ 的提交）

- 60197462 test(M1/M7): 数据供给脚本功能回归测试
- 46c28e85 fix(003): M1-M3 测试 + 类型注解（19P）
- 6434c330 test(risk_rules): C-fix 合成数据护栏 3 项
- 8bd943a0 test(C2+C4): 42 项测试红全消解
- cafda15e fix(P2#5-a): closedloop 日报消费键对齐 + fixture
- 本次任务新增：tests/test_precommit_hook.py（3 项）+ test_system_health.py（1 项）+ test_data_flow_audit.py（3 项）= +7

## 5. 建议（按收益排序）

1. **给 180s 门禁换快档（立即可消除 exit 124）**: 外部 180s 调用改跑
   `pytest tests/ -q -m "not slow and not backtest"`，把最重 ~15 项（≈560s，见 §2 Top10）
   排除出门禁档 → 门禁档 ≈ 110s（含 45s 收集），稳进 180s 预算；
   全量件（含重件）改走夜间 cron（大预算/无预算）。
2. **落实 marker**: 给 §2 Top15 逐项补 `@pytest.mark.slow` / `@pytest.mark.backtest`
   （marker 已在 pytest.ini 定义但 0 使用——门禁通道是断的，这是 §5.1 的前置件）。
3. **重件缓存/独立化**: IC 重算（131s）、门禁 OOS（68s+61s）、L2 全量校验（79s）
   类测试落盘缓存结果（数据指纹未变则读缓存）或拆独立 runner（与 OOS runner 同款），
   降低夜间全量成本。
4. **并行化（可选，中期）**: 引入 pytest-xdist `-n 4`（venv 当前仅装 pytest 9.1.1 +
   pytest-cov，无 xdist）；Windows 4 worker 可把纯计算件压到 ~1/4，
   但重 fixture 并行下各自重建，需先做 §5.3 缓存再并行。
5. **收集成本监控**: 45s 收集偏重（模块 import 成本），测试文件继续增长时保持 import 轻量。

## 6. 结论

180s 超时 = **规模型超时**（全量 670s vs 预算 180s，3.7 倍；Top10 重件占 72%；
1784→1873 测试增长且 slow 类 marker 0 使用无排除通道），**非挂起、非负载**
（夜间静默段实测；14 项既有失败均为环境/数据陈旧类，与超时无关）。
按 §5.2（补 marker）+ §5.1（门禁快档）双件即可消除 exit 124；
§5.3/§5.4 为中期优化件，建议单独立卡，不在本任务范围扩张。

## 7. 落地记录（2026-10-26, P3 执行件 t_81fad29b, 总管 default）

**落地件（commit 见下，本地 main；push 受 t_2297a28c 凭据修复门控）**

1. **marker（§5.2，13 个测试文件，纯测试面，断言零改动）**
   - `pytestmark` 整族挂出（重件文件族）:
     - `@pytest.mark.backtest`: test_evolution_loop_p1v2.py（IC 重算族）,
       test_gate_fn_integration.py（门禁 OOS 族）, test_s3_strategy_consistency.py（DataLoader 族）
     - `@pytest.mark.slow`: test_scan_performance.py（Numba fixture 族）,
       test_laya_agent.py / test_laya_integration.py / test_laya_quant_adapter.py（laya 本地模型族）
   - 函数级: test_evolution_loop_p3v2.py::test_assert1_lesson_persistence（backtest,
     同文件其余桩门禁件留快档）, test_layers_contract.py::test_no_unknown_factor_fields（slow）,
     test_factor_decay_monitor.py::test_queue_write_failure_loud（slow）,
     test_board_server.py::TestBoardHtmlGeneration 类（slow）+ TestReviewStatusFallback 一项（slow）,
     test_market_state_engine.py::test_basic_structure（slow）,
     test_no_bare_core_imports.py::test_no_bare_core_imports_in_repo（slow, 本身属 14 项基线）,
     test_p2a_retry_on_removal.py::test_p2a_consume_side_zero（slow）
   - 断言 **`pytest tests/ --collect-only -q -m "slow or backtest"` → 97/1876 collected**
     （与全量档实测 top_slowest 15 件逐一比对: 全部 ∈ 97 项, 无漏挂）

2. **门禁快档（§5.1）**: `scripts/daily_monitor.py run_tests()` 调用面改
   `pytest tests/ -q --tb=line -m "not slow and not backtest"`（timeout=180 不变）。
   实测（2026-10-26 夜间静默段, 干净单跑）:
   **wall=134s（pytest 内 130.91s）< 180s 预算**（余量 46s）;
   结果 11F/1738P/32S/97 deselected, 11 项失败全部 ∈ 14 项既有基线（零新增）。
   并行双跑污染样本 167s/213s（不作断言依据, 仅证负载敏感）。

3. **夜间全量档**: 新增 `scripts/pytest_full_nightly.py`（薄驱动, 退出码契约
   0=跑完/2=运维失败; watchdog: 失败集==基线静默, 漂移→一行摘要）
   + hermes-home 层 `scripts/pytest_full_nightly.py` zq_shim 转发器
   + hermes cron 活 job `QSP_PytestFullNightly`（02:30 每日, no_agent, deliver=local）。
   首跑实测: **rc=0, wall=853.2s（< 2400s 预算）, 1878 项跑通 = 1833P + 12F + 33S**,
   12F 全 ∈ 既有基线（2 项复绿: test_health_status_exists / test_message_id_tracking
   → KNOWN_FAILS 基线已同步 14→12; 14 项立件收口时以该件为准重标定）。
   测试总数 1873（10-25）→ 1878（10-26）: 02603c32 +2（test_data_flow_audit）
   + 收集级数据驱动漂移 ±1-2（非本件改动面, 不追因, 夜间档 durations 监控承接）。

4. **未动（本件边界外）**: 14 项既有失败立件（环境/数据陈旧类, 单独立件处理中）;
   §5.3 重件落盘缓存 / §5.4 pytest-xdist 并行化（中期, 建议单独立卡）。
