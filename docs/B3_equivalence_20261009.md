# B3 等价性对照报告 — review_status.json 消费方统一走 review_gate（K44 遗留，/tdd 执行）

**日期**: 2026-10-09　**作者**: 总管（Hermes）　**定级**: R0 高危（SOUL 准则6：gate 实盘写口，合入前须等价性对照 + sanity gate + 老五评审）

## 一、B3 实质（坐实后精分，非机械 26+ 全改）

全库 23 个 `.py` 读 `review_status.json`，按**读法性质**分类（我逐文件读代码坐实）：

| 类 | 文件 | 读法 | B3 处置 |
|---|---|---|---|
| **① 已走 review_gate**（R0b） | auto_trading / auto_live / cron_daily / automation_scheduler / auto_backtest(生成侧) | 已委托 | ✅ 已统一（残留仅是本地变量名） |
| **② gate 裁定类**（决定能否交易/选股）| `integrated_picker` / `positioner` / `s3_auto_pipeline` | 内联裸读 `laowu_approved` 决定放行/冻结 | **改走 review_gate.evaluate**（B3 核心）|
| **③ 诊断/展示/报告类**（读值不裁定）| `ai_analysis` / `health_audit` / dashboard×4 / `daily_progress_report` / `monitor_diversity` / `quick_status_check` / `generate_exemption_application` | 读 `laowu_approved` 值做矛盾检测/健康卡/报告 | **保留直读值**（改 review_gate 布尔会丢字段级信息，破坏诊断）|
| **④ 真 bug** | `system_audit_checker:192` | 嵌套读 `review_data.get('laowu',{}).get('approved')` — 真字段是**顶层 `laowu_approved`**，嵌套 `laowu` 非 dict → 永远 None → 矛盾检测形同虚设（假绿）| **修嵌套读**（读真字段，保留矛盾检测逻辑）|
| **⑤ fixture（非消费方）** | `jev_bmode_runner:101` | 硬编码 `{"laowu_approved": False,...}` 假数据，不读真文件 | **不动** |

**关键坐实**（等价性脚本 `_b3_equiv_tmp.py` 跑 4 场景 + 真数据，跑完即删）：

| 场景 | review_gate | integ.改前 | positioner改前 | s3改前 | 判定 |
|---|---|---|---|---|---|
| S1 当前真数据 | frozen/final_verdict | exit1 | frozen | frozen | **一致**（B3 不改现行实盘）|
| S2 缺文件 | **frozen/fail_safe** | exit1 | **approved(fail-open)** | **release(fail-open)** | 方向漂移→安全升级 |
| S3 损坏JSON | frozen/fail_safe | exit1 | approved(fail-open) | release(fail-open) | 方向漂移→安全升级 |
| S4 fv=PASS但laowu=False | release/final_verdict | **exit1(误冻)** | **frozen(误冻)** | frozen(误冻) | 统一后正确放行 |
| S5 **fv=FAIL但laowu=True** | **frozen/final_verdict** | **release(假绿)** | **approved(假绿)** | release(假绿) | **B3 核心价值：消除假绿放行** |
| S6 无硬失败+laowu=True+无fv | release | release | approved | release | 一致 |

**结论**：B3 价值 = ① S5 消除"final_verdict=FAIL 被 laowu_approved=True 绕过"的假绿放行（K44 假绿主题）② S2/S3 fail-open→fail-safe（安全方向，缺文件/损坏不再放行）③ S4 final_verdict 优先级正确放行。当前真数据 S1 全 frozen 一致 → **B3 不改现行实盘行为，是防未来假绿 + 安全加固**。

## 二、落码范围（一次一项，R0 高危）

**改（本轮落码）**：
1. `integrated_picker.py` gate 段 → `review_gate.evaluate()`（fail-safe + final_verdict 否决 + B1 否决）
2. `positioner.py` gate2 段 → `review_gate.evaluate()`（缺文件从 fail-open 跳过 → fail-safe 冻结）
3. `s3_auto_pipeline.py` gate 段 → `review_gate.evaluate()`（同上）
4. `system_audit_checker.py:192` 嵌套读 `laowu.approved` → 读真字段 `laowu_approved`（保留矛盾检测，修死读）

**保留直读（不本轮改，设计决策，老五确认）**：
- ③ 类 8 个诊断/展示/报告文件：读 `laowu_approved` 值做矛盾检测/健康卡/报告，**不是 gate 裁定**。强行改 review_gate 布尔会丢失字段级信息（如 `freeze_unlocked`/`approval_timeline`/矛盾检测需顶层 vs 嵌套对比）→ 保留直读，**但纳入老五后续统一评估**（是否某些该改）。

**不动**：⑤ `jev_bmode_runner`（fixture 非消费方）。

## 三、行为漂移声明（SOUL 准则7，不洗成"等价"）

**本轮改 3 个 gate 裁定类后，实盘行为在以下场景变化**（非等价，是 review_gate 有意升级，K47 §二 已拍板）：
- **S2/S3（缺文件/损坏JSON）**：`positioner`/`s3` 从 fail-open **跳过/放行** → fail-safe **冻结**。这是安全方向加固（缺 review 数据时不放行），**改变了缺数据时的放行行为**——若某实盘场景依赖"缺文件=放行"，会被 B3 冻结。**老五评审须确认此方向变更可接受**。
- **S5（fv=FAIL 但 laowu_approved=True）**：3 方从**假绿放行** → 冻结。这是 K44 假绿主题核心修复。
- **S4（fv=PASS 但 laowu_approved=False）**：3 方从误冻 → 放行（final_verdict 优先级）。

## 四、TDD + 回归 + 回滚点

- **TDD**：`tests/test_b3_gate_consumers.py`（seam=各消费方 gate 委托 review_gate，静态 + 4 漂移场景行为）
- **回归**：`pytest tests/test_review_gate.py tests/test_b3_gate_consumers.py -q` + 全量
- **回滚点**：`integrated_picker.py.bak_B3_202610090600` / `positioner.py.bak_B3_202610090600` / `scripts/s3_auto_pipeline.py.bak_B3_202610090600` / `scripts/system_audit_checker.py.bak_B3_20261009`
- **未验证项**：3 个 gate 裁定类改后未实盘跑（S1 真数据下判定一致，缺文件场景需 S2 手动注入验证，留维护窗口）

## 五、老五评审请求（SOUL 准则6，合入前）

> 请独立评审 B3 三处 gate 裁定类改 review_gate + system_audit_checker 嵌套读修复：
> ① S2/S3 fail-open→fail-safe 方向变更是否可接受（缺 review 数据时是否该冻结而非放行）
> ② 8 个诊断/展示类保留直读的分类是否正确（哪些其实该改）
> ③ 等价性对照 S5 假绿消除是否完整覆盖所有 gate 裁定消费方
> 评审回复「✅ 通过」或「❌ 打回：XXX」。

## 六、实际落地（TDD 红→绿）+ 附带 P0 修复

**已落码 4 文件**（回滚点 `*.bak_B3_20261009*`）：
| 文件 | 改动 | TDD |
|---|---|---|
| `integrated_picker.py` gate 段 | 内联裸读 laowu_approved 裁定（含 v5_final_ruling 读法）→ `review_gate.evaluate` fail-safe | `test_b3_gate_consumers.py` |
| `positioner.py` gate2 | 缺文件 fail-open 跳过 → `review_gate.evaluate` fail-safe（S2/S3 方向升级落地）| 同上 |
| `scripts/s3_auto_pipeline.py` gate | 缺文件 fail-open 未设 → `review_gate.evaluate` | 同上 |
| `scripts/system_audit_checker.py:192` | 嵌套死读 `laowu.approved` → 读真字段 `final_verdict` 做矛盾检测 | `test_b3_gate_consumers.py` |

**附带修复预存 P0**（做 B3 时发现，非 B3 引入）：
- `system_audit_checker.py` L37 孤儿 `except (AttributeError)` 无配对 try + `cmd` 未定义 → 整个审计脚本不可 py_compile（git 无历史 untracked 新文件）。重建"扫全库裸 except: 静默吞没"段为纯函数 `_find_bare_except_lines`（可测, 绕开 shell 转义陷阱）。TDD `test_b3_bare_except_fix.py` 3 passed。

**测试全绿**：`test_b3_gate_consumers`(5) + `test_b3_bare_except_fix`(3) + `test_review_gate`(13) = **21 passed**；4 文件 py_compile OK；影响面定向回归 **40 passed**。

**未验证项（如实标注, 非打勾）**：3 gate 裁定类改后未实盘跑——S1 真数据判定一致（frozen），缺文件场景 S2 需手动注入 `review_status.json` 缺失验证 fail-safe 冻结，留维护窗口补跑。

## 七、老五独立评审结果（SOUL 准则6 R0 闸口，2026-10-09）

**评审单**：`t_5a7c75a8`（老五 atomcode），**结论：✅ 通过**。

| 三问 | 老五验证结果 |
|---|---|
| ① S2/S3 fail-open→fail-safe 方向变更 | **无实盘行为变化**——改前缺文件/损坏时 `positioner`/`s3` 虽走 fail-open 分支，但 `gates["laowu_approved"]` 缺省 `False` 默认即冻结，实盘下游读 `gates` 时已隐式冻结；review_gate 只是把这个隐式冻结**显式化 + 加了 source/reason 可追溯**，不是行为翻转 |
| ② 8 诊断/展示类保留直读归类 | **正确**——`ai_analysis`/`health_audit`/dashboard×4/`daily_progress_report`/`monitor_diversity`/`quick_status_check`/`generate_exemption_application` 读字段值做矛盾检测/报告，非 gate 裁定；唯一轻微分支 `generate_dashboard.py` 读 `approval_timeline` 仅渲染时间线，**不影响交易决策**，保留直读合法 |
| ③ S5 假绿消除是否覆盖全部 gate 裁定消费方 | **完整**——全库 grep 确认 gate 裁定路径（决定买卖/选股）仅 3 处（`integrated_picker`/`positioner`/`s3`），已全部改 review_gate；`system_audit_checker` 死读已修；无遗漏裁定路径 |

**老五独立复现**：`pytest tests/test_b3_gate_consumers.py tests/test_b3_bare_except_fix.py tests/test_review_gate.py` = **21 passed**；`system_audit_checker.py` py_compile OK。

**R0 闸口状态**：**闭合**（老五独立评审 PASS + 等价性对照 S1/S5 验证 + 全库 grep 无遗漏）。B3 合入放行。

**遗留未验证（如实标注，非 R0 打回，维护窗口补）**：S2 缺文件手动注入验证 fail-safe 冻结——老五确认改前已隐式冻结（①），此为**防御性补验**，不阻塞合入。
