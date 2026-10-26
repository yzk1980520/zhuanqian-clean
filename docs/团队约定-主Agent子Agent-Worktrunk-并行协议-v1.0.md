# 团队约定：主Agent + 子Agent + Worktrunk 并行执行协议

**版本**: v1.0  
**日期**: 2026-10-11  
**状态**: ✅ 已拍板（2026-10-15 老大"执行"授权；参见 AGENTS.md §10.4）  
**真源**: AGENTS.md §二/三/四、worktrunk skill、delegation-execution.md

---

## 一、架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        老大（御龙决）                           │
│                     最终决策 / 资金 / 方向                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    总管（Hermes/agnes）                         │
│           调度 / 验收 / cron / 实盘合入 / 系统健康               │
│         ✅ 权限：派单、验收、归档  ❌ 不写交易数据               │
└─────────────────────────────────────────────────────────────────┘
            ↓              ↓              ↓
    ┌───────────┐    ┌───────────┐    ┌───────────┐
    │   老三    │    │   老五    │    │   牛马    │
    │ opencode  │    │ atomcode  │    │ niuma     │
    │ 编码/回测 │    │ 评审/合规 │    │ 后备/研究 │
    │ ✅ 代码修改│    │ ❌ 只读   │    │ ⚠️ 按需启用│
    └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
          │                │                │
    ┌─────▼─────┐    ┌─────▼─────┐    ┌─────▼─────┐
    │ worktree  │    │ worktree  │    │ worktree  │
    │ agent-ops │    │ agent-atm │    │ agent-nm  │
    └───────────┘    └───────────┘    └───────────┘
```

**核心原则**：每个子Agent在独立worktree中运行，互不污染主仓。

---

## 二、子Agent角色定义

### 2.1 老三（opencode）— 编码执行层

| 属性 | 值 |
|------|-----|
| **代号** | opencode / laosan |
| **CLI** | `opencode run --dir <worktree> "<task>"` |
| **Working-dir** | **自有默认目录**（非进程cwd），必须显式传 `--dir` |
| **权限** | ✅ 代码修改 / ❌ 不改交易数据 / ❌ 不commit/push |
| **红线** | risk_rules.py、holdings.json、trade_log.json、review_status.json |
| **隔离断言** | 产出文件仅在自身worktree；主仓无answers_*.txt泄漏 |

**任务模板**：
```yaml
【任务单】老三执行
assignee: opencode
priority: P1
worktree: testrepo.agent-opencode
branch: feat/<task-id>
deadline: <时间>

任务内容：
- 背景：...
- 需求：...
- 交付物清单：
  1. <文件路径>：功能说明
  2. <测试文件>：覆盖用例

红线：
- 禁止修改：risk_rules.py、holdings.json、trade_log.json
- 禁止commit/push到主分支
- 禁止访问 Wind Alice 敏感接口

验收标准：
- 单元测试通过（pytest -v）
- 回归全绿（python .agent/regression/__init__.py .）
- 产出文件位于worktree（非主仓）
- 挂一手证据：命令+输出+时间戳
```

### 2.2 老五（atomcode）— 独立评审层

| 属性 | 值 |
|------|-----|
| **代号** | atomcode / laowu |
| **CLI** | `atomcode -p "<task>"`（ cwd=worktree 即可） |
| **Working-dir** | process.cwd()（尊重cwd设置） |
| **权限** | ❌ 不写代码 / ✅ 评审报告 / ✅ 打回权 |
| **红线** | 不得修改任何生产文件 |
| **隔离断言** | 仅产出评审报告；不触碰主仓业务文件 |

**任务模板**：
```yaml
【评审请求】老五独立评审
assignee: atomcode
priority: P0
worktree: testrepo.agent-atomcode
branch: review/<task-id>
deadline: <时间>

评审对象：
- 代码变更：git diff <base>..<head>
- 测试覆盖：test_*.py
- 证据链字段：决策ID/时间戳/数据窗口/前后指标

评审要点：
1. 红线检查：risk_rules.py / holdings / trade_log 是否被触碰
2. 门禁检查：IC>0.03 / IR>0.3 / 单调性 / 132日确认
3. 异常吞噬：except: 默认值 = P0打回
4. 测试真绿：fixture有正前置，回填数值精确落盘

输出格式：
- ✅ 通过：附签字+建议合入分支
- ❌ 打回：附P0/P1缺陷列表+修复建议
```

### 2.3 牛马（niuma）— 后备研究层

| 属性 | 值 |
|------|-----|
| **代号** | prime-agent / niuma |
| **CLI** | hermes -p niuma chat -q "..." --oneshot |
| **权限** | ⚠️ 按需启用 / ❌ 不阻塞主流程 |
| **场景** | 批量数据拉取 / 研究支持 / 非紧急任务 |

**任务模板**：
```yaml
【后备任务】牛马执行
assignee: niuma
priority: P2
worktree: testrepo.agent-niuma
branch: research/<topic>

任务类型：
- 数据拉取（akshare/tushare公开接口）
- 行业研究 / 宏观分析
- 批量因子IC计算（非实时）

注意：
- 资源紧张时降级为只读查询
- 产出仅限scratch目录，不污染主仓
```

---

## 三、Worktrunk隔离协议

### 3.1 Worktree创建规范

```bash
# 老三：编码任务
git worktree add -b feat/<task-id> ../testrepo.agent-opencode

# 老五：评审任务（只读clone即可）
git worktree add -b review/<task-id> ../testrepo.agent-atomcode

# 牛马：研究任务
git worktree add -b research/<topic> ../testrepo.agent-niuma
```

**隔离断言**（每个worktree必须满足）：
1. ✅ 各自worktree目录下产出文件仅属于该agent
2. ✅ 主仓无`answers_*.txt`泄漏
3. ✅ seed文件（arithmetic.txt等）在各自worktree未被修改
4. ✅ git status porcelain显示的状态码正确解析（`??`前缀=untracked）

### 3.2 子Agent CLI调用规范

| Agent | 调用方式 | 关键参数 |
|-------|----------|----------|
| opencode | `opencode run --dir <wt> "<task>"` | `--dir` 必须显式传 |
| atomcode | `atomcode -p "<task>"` | `cwd=<wt>` 即可 |
| hermes子profile | `hermes -p <profile> -z --in <wt> "..."` | `--in` 必须显式传 |

**警告**：spawn-with-cwd不够！opencode和hermes都解析自己的working-dir，不信任进程cwd。

### 3.3 Worktree清理规范

```bash
# 任务完成后
git worktree remove testrepo.agent-opencode  # 仅删除worktree
git worktree remove --with-branch testrepo.agent-opencode  # 删除+分支

# W2自动化（待实现）：kanban done → 自动清理
```

---

## 四、执行协议（七步闭环强化）

### 4.1 派发前检查

```python
# 总管派发前必须验证：
def pre_dispatch_check(agent: str, worktree: str) -> bool:
    checks = [
        ("worktree存在", os.path.isdir(worktree)),
        ("分支未污染", git_is_clean(worktree)),
        ("seed文件完整", os.path.exists(f"{worktree}/arithmetic.txt")),
        ("无旧答案泄漏", not glob.glob(f"{worktree}/answers_*.txt")),
    ]
    return all(c[1] for c in checks)
```

### 4.2 运行中监控

```bash
# 监控worktree状态
git -C <worktree> status --porcelain
# 输出示例：
# ?? answers_opencode.txt    ← 正常产出
# ?? run.log                 ← 正常日志
# M  arithmetic.txt          ← 异常！seed被改

# 监控进程存活（MSYS陷阱）
wmic process where "name like '%python%' or name like '%hermes%'" get ProcessId,CommandLine
```

### 4.3 完成后验收（总管独立断言）

**验收三件套**（缺一不可）：
1. **真源重读**：`cat <产出文件>` 验证内容，不靠日志回显
2. **泄漏扫描**：`ls <主仓>/answers_*.txt` 应为空
3. **回归验证**：`python -m pytest <test_file>` 全绿

**高危项独立复现**：
- IC/corr/metrics：单股单函数重算
- 门禁真值：`python gate_check.py`; echo $? （管道会掩盖fail）
- 测试真绿：三查（测试未碰生产文件、fixture正前置、回填数值精确）

---

## 五、审查机制

### 5.1 老五独立评审清单

| 检查项 | 通过标准 | 打回条件 |
|--------|----------|----------|
| 红线文件 | holdings/trade_log/risk_rules 未变 | 任何触碰 |
| 门禁阈值 | IC>0.03, IR>0.3, 单调性成立 | 任一不达标 |
| 数据窗口 | 含退市股，point-in-time校验 | 幸存者偏差 |
| 异常吞噬 | 无`except: 默认值` | 发现即P0 |
| 证据链 | 决策ID/时间戳/前后指标/失效条件 | 字段缺失 |

### 5.2 审查输出模板

```markdown
【老五评审报告】<任务ID>

✅ 通过 / ❌ 打回：xxx

检查项：
- [x] 红线文件未触碰
- [x] IC门禁：mean=0.05, IR=0.35 ✓
- [ ] 数据窗口：缺失退市股标记 ✗
- [x] 无异常吞噬
- [x] 证据链完整

打回原因（如有）：
P1: 数据窗口不完整，需补充退市股覆盖

建议修复：
1. ...
2. ...

签字：老五(atomcode)
时间：2026-10-11T10:00:00
```

---

## 六、验收标准

### 6.1 验收 checklist

```
□ 代码变更符合预期（git diff --stat）
□ 单元测试通过（pytest -v，挂证据）
□ 回归测试全绿（.agent/regression/__init__.py .）
□ 无生产文件污染（holdings/trade_log/risk_rules mtime未变）
□ 无worktree泄漏（主仓无answers_*.txt）
□ 老五评审报告已归档
□ 证据链字段完整（决策ID/时间戳/数据窗口/前后指标）
□ 失败路径已记录（即使不采用也要诚实报告）
```

### 6.2 验收不通过处理

- **P0**：红线触碰 / 异常吞噬 → 立即打回，总管代做机械合入（标注"总管代收尾"）
- **P1**：数据窗口不完整 / 测试假绿 → 打回补测，定性指向写盘契约
- **P2**：文档缺失 / 风格问题 → 记录待办，不阻塞合入

---

## 七、防炸原则（不可违反）

### 7.1 数据安全红线

```
❌ 禁止：子Agent写入 holdings.json / trade_log.json / config.json
❌ 禁止：子Agent修改 risk_rules.py 止损止盈参数
❌ 禁止：子Agent直接commit/push到主分支
❌ 禁止：子Agent访问 Wind Alice 敏感接口（持仓/策略参数）
❌ 禁止：用shell & 后台化子Agent进程（孤儿化陷阱）
❌ 禁止：管道里用 $? 判断命令退出码（会掩盖真实fail）
```

### 7.2 执行安全红线

```
✅ 必须：每个子Agent有独立worktree
✅ 必须：显式传 --dir/--in 参数（不信任进程cwd）
✅ 必须：总管独立验收（不采信worker口头结论）
✅ 必须：验收挂一手证据（命令+输出+时间戳）
✅ 必须：异常吞噬检测（except: 默认值 = P0打回）
✅ 必须：旧数字不作验证（声明来自哪个commit）
```

### 7.3 沟通安全红线

```
✅ 必须：任务单附写入边界（谁写哪个文件）
✅ 必须：完成即反馈（三件套+证据链）
✅ 必须：失败如实报告（不隐瞒不美化）
✅ 必须：飞书消息分级（P0实时/P1每日/P2按需/P3归档）
❌ 禁止："已修复/已解决"用于未复核项
❌ 禁止："IC反向"未附数值+文件+时间戳
❌ 禁止：数字作验证未声明引擎commit
```

---

## 八、命令速查表

### 8.1 总管常用命令

```bash
# 创建worktree
git worktree add -b feat/<id> ../testrepo.agent-opencode

# 查看worktree状态
git worktree list

# 清理worktree
git worktree remove testrepo.agent-opencode
git worktree remove --with-branch testrepo.agent-opencode

# 派发任务（老三）
hermes -p opencode chat -q "$(cat task.txt)" --oneshot --run-budget 1200

# 派发任务（老五）
hermes -p atomcode chat -q "$(cat review.txt)" --oneshot

# 验收扫描
python scripts/worktree_leak_detector.py  # W3 daily check
python scripts/worktree_regression.py      # W4 weekly regression
```

### 8.2 子Agent调用格式

```bash
# 老三（opencode）- 必须显式传 --dir
opencode run --dir D:/path/to/testrepo.agent-opencode "执行任务X"

# 老五（atomcode）- 尊重cwd
cd D:/path/to/testrepo.agent-atomcode
atomcode -p "评审任务Y"

# 牛马（niuma）- hermes子profile
hermes -p niuma chat -q "研究任务Z" --oneshot
```

---

## 九、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-10-11 | 初稿：基于worktrunk技能+delegation-execution规范 |
| v1.0 | 2026-10-11 | 定稿：主Agent+3子Agent+Worktrunk并行协议 |

---

**签字**: 总管（Hermes）· 待老大拍板  
**状态**: ⏳ 待拍板  
**参考**: AGENTS.md §二/三/四、worktrunk SKILL.md、delegation-execution.md
