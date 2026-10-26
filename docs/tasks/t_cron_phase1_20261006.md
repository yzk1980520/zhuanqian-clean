# 任务单：实现Phase 1 Cron任务

**任务编号**: t_cron_phase1_20261006  
**指派给**: 老三  
**优先级**: P1  
**截止时间**: 2026-10-08  

---

## 一、任务背景

老大已拍板重新设计cron任务（基于新架构）。Phase 1为核心任务，需今日完成。

**决策依据**：
- `docs/cron-redesign-20261006.md` - 设计方案
- `docs/拍板决策记录-20261006.md` - 老大拍板

---

## 二、任务内容

### 2.1 Hermes_DataRefresh（09:15）

**目的**：盘前数据刷新，确保数据新鲜度

**实现要求**：
- 脚本路径：`scripts/cron_data_refresh.py`
- 检查项：
  - TDX日线数据新鲜度（<24小时）
  - 因子缓存新鲜度（<24小时）
  - 市场状态文件存在性
- 输出：`data/data_freshness.json`
- 失败处理：飞书P1告警

**执行命令**：
```bash
cd "D:/open code/zhuanqian"
.venv/Scripts/python.exe scripts/cron_data_refresh.py
```

---

### 2.2 Hermes_DailyPick（09:25）

**目的**：盘前选股，生成候选池

**实现要求**：
- 脚本路径：`scripts/cron_daily_pick.py`
- 前置条件检查：
  - `laowu_approved=true`（读取data/review_status.json）
  - 数据新鲜度检查通过
- 执行选股：调用`integrated_picker.py --date 今日`
- 输出：`data/pool_today.json`
- 飞书P1消息：候选TOP10

**执行命令**：
```bash
cd "D:/open code/zhuanqian"
.venv/Scripts/python.exe scripts/cron_daily_pick.py
```

---

## 三、验收标准

1. **语法检查**：`python -m py_compile scripts/cron_*.py` 通过
2. **功能验证**：手动执行脚本，确认无报错
3. **日志输出**：日志写入`logs/cron/`目录
4. **飞书告警**：失败时能发送飞书消息

---

## 四、交付物

| 交付物 | 路径 | 状态 |
|--------|------|------|
| DataRefresh脚本 | `scripts/cron_data_refresh.py` | 待实现 |
| DailyPick脚本 | `scripts/cron_daily_pick.py` | 待实现 |
| 日志目录 | `logs/cron/` | 待创建 |
| 测试报告 | `docs/cron-phase1-test-report-20261006.md` | 待生成 |

---

## 五、注意事项

1. **备份**：改任何核心脚本前 `Copy-Item x.py x.py.bak_<日期>`
2. **清环境**：跑python前 `Remove-Item Env:PYTHONPATH`
3. **不写交易数据**：holdings/trade_log只读
4. **通知总管**：完成后飞书回复「✅ Phase 1完成」+ 交付物链接

---

**创建人**: 总管  
**创建时间**: 2026-10-06 08:25  
**状态**: 待执行
