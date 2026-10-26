# 老四自审P0结论审查报告

**审查人**: 总管  
**审查时间**: 2026-10-20 10:45  
**审查依据**: AGENTS.md 准则5（验收用断言不用打勾）

---

## 一、结论速览

| 编号 | 老四结论 | 审查裁定 | 证据等级 |
|------|----------|----------|----------|
| P0-1 | defect_ledger 10条P0未闭环 | ❌ **假阳性** | 文件实际0条 |
| P0-2 | risk_rules.py红线漂移 | ⚠️ **部分成立** | 双版本已回滚 |
| P0-3 | trade_log双源不一致 | ✅ **成立** | 买入记录缺失 |
| P0-4 | QSP镜像8天未同步 | ⚠️ **部分成立** | 数字不准，架构待确认 |

**裁定汇总**: 4项P0中 **1项假阳性 + 1项成立 + 2项部分成立**

---

## 二、逐项证据链

### P0-1: defect_ledger P0未闭环 ❌ 假阳性

**老四结论**: "defect_ledger 有 10 条未闭环P0缺陷（资金安全类，复盘未应用到选股）"

**审查证据**:
```bash
$ cat data/audit/defect_ledger.json
{"defects": []}  # 空数组
```
```python
$ .venv/Scripts/python.exe -c "import json; d=json.load(open('data/audit/defect_ledger.json')); print(f'总缺陷: {len(d.get(\"defects\",[]))} 条')"
总缺陷: 0 条
```

**根因推断**: 老四可能读取了 `.bak_20261018` 或 `.bak_20261019_073935` 备份文件，而非当前活跃文件。

**裁定**: **不成立**。当前defect_ledger为空，无P0缺陷。建议老四修正读取路径或清理过期备份。

---

### P0-2: risk_rules.py红线漂移 ⚠️ 部分成立

**老四结论**: "risk_rules.py 自基线后被修改（红线漂移，资金安全风险）"

**审查证据**:
```bash
$ git log --oneline -5 risk_rules.py
6adbea0a 总管回滚: P2-1b 根层扫荡还原真源布局(102根py+risk_rules/atomic_json回根)
0a312528 P2-1b 批次3: 102个根目录.py归位scripts/
e779ea27 fix(D-10): risk_rules补alert_log台账
2e3ff47c fix(C10): risk_rules止损10%+TP_SELL_LADDER三档入树
```

**文件现状**:
- `risk_rules.py`（根目录）: mtime=2026-10-20 05:14，内容=总管回滚版本
- `scripts/risk_rules.py`: mtime=2026-10-20 04:25，内容=老六改动版本（含sys.path注入）

**差异分析**:
- 根目录版本 = git HEAD 6adbea0a（已回滚到基线）
- scripts/版本 = 老六P2-1b批次2改动（含架构重构）

**裁定**: **部分成立**。
- ✅ 确有两版本存在
- ✅ 总管已通过commit 6adbea0a回滚根目录版本到基线
- ⚠️ scripts/版本未清理，需后续处理（非紧急P0，降为P1/P2）
- ❌ "资金安全风险"指控过度：回滚后根目录版本已是安全基线

---

### P0-3: trade_log双源不一致 ✅ 成立

**老四结论**: "五件证据②持仓未录trade_log: active=['sh603727'] 但 trade_log.buys=0条"

**审查证据**:
```json
// holdings.json
{
  "code": "sh603727",
  "buy_time": "2026-10-12T09:34:48+08:00",
  "avg_cost": 20.348
}

// trade_log.jsonl（唯一记录）
{"stock_code": "sh603980", "action": "sell", "exec_time": "2026-09-28 09:33:20", ...}
```

**问题定位**:
- holdings记录sh603727于2026-10-12买入
- trade_log.jsonl无sh603727买入记录
- trade_log仅有sh603980卖出记录（2026-09-28，手动执行）

**根因推断**: 
- 买入操作可能由auto_trading_pipeline执行，但未调用atomic_json追加trade_log
- 或买入操作走的是独立写口，未遵循"交易双写"协议

**裁定**: **成立**。这是真实P0问题（交易台账缺失→无法追溯资金流向）。

**修复建议**:
1. 追查auto_trading_pipeline买入路径，确认是否遗漏trade_log写入
2. 补充sh603727买入记录到trade_log.jsonl（事后补录需标注"补录"）
3. 加监控：每日自审检查holdings.buys == trade_log.buys

---

### P0-4: QSP镜像8天未同步 ⚠️ 部分成立

**老四结论**: "QSP镜像双源漂移: 主源=['sh603727'] QSP=[]（镜像8天未同步）"

**审查证据**:
```bash
$ ls -la data/real_holdings.json
ls: cannot access data/real_holdings.json: No such file or directory

$ stat data/holdings.json
Modify: 2026-10-17 08:02:xx
```

**问题定位**:
- real_holdings.json不存在（非"空数组"，是文件缺失）
- holdings.json最后修改: 2026-10-17（3天前，非8天）
- 数字"8天"可能老四看的是其他文件（如alert_history或旧日志）

**架构核查**:
```bash
$ grep -r "real_holdings" scripts/*.py | head -5
# 搜索不到引用
```

**裁定**: **部分成立**。
- ✅ 镜像确实缺失（real_holdings.json不存在）
- ❌ "8天"数字不准（实际3天或文件从未生成）
- ⚠️ 需确认：real_holdings是架构必需还是废弃设计？
  - 如果必需：P0（看板数据缺失）
  - 如果废弃：删除相关代码，降为P2文档清理

---

## 三、行动项

### 立即处置（P0成立项）

1. **P0-3 trade_log缺失买入记录**
   - 责任人: 老三
   - 动作: 追查auto_trading_pipeline买入路径，补录sh603727买入记录
   - 验收: trade_log.jsonl包含sh603727买入记录（标注"补录"）
   - 截止: 今日18:00前

2. **P0-2 scripts/risk_rules.py清理**
   - 责任人: 总管
   - 动作: 删除scripts/risk_rules.py（根目录已是真源）
   - 验收: git status无risk_rules.py变更
   - 截止: 今日20:00前

### 验证项（需老四复核）

3. **P0-1 defect_ledger路径修正**
   - 责任人: 老四
   - 动作: 确认读取路径是否为data/audit/defect_ledger.json（非备份文件）
   - 验收: 自审报告引用正确路径

4. **P0-4 real_holdings架构确认**
   - 责任人: 总管+老五
   - 动作: 确认real_holdings.json是否为架构必需
   - 验收: 文档更新或文件补建

---

## 四、老四自审系统健康度

**优点**:
- 检出了真实P0（trade_log双源不一致）
- 触发机制有效（每日20:00巡检）

**问题**:
- 路径引用可能不准确（defect_ledger读错文件）
- 数字精度不足（"8天"应为3天）
- 需区分"架构缺失"与"运行时故障"（real_holdings可能是设计如此）

**建议**:
- 自审脚本增加路径验证（file.exists()检查）
- 数字断言需附数据来源（mtime vs hardcoded）
- 对"不存在"的文件区分"设计缺失"vs"运行时故障"

---

**签字**: 总管（Hermes）  
**日期**: 2026-10-20 10:45
