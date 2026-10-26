# 层间契约固化 (layers-contract)

## 目的
定义各系统层之间的接口契约，确保层间接口稳定性，防止跨层重构导致隐性耦合断裂。

## 层间契约

### 数据层 → 因子层
- 真源: TDX日线二进制文件
- 格式: `.day` / `.json`，schema_version=2
- 变更需走 `scripts/data_migrate.py`

### 因子层 → 评分层
- 真源: `data/factor_registry/registry.json`
- 判据: IC_mean, IC_IR, coverage_pct
- 门禁: DD门禁=35%（规则7），DD超限→gate_status=frozen

### 评分层 → 选股层
- 入口: `scripts/integrated_picker.py`
- 出口: `data/signal.json` → top_pick, score, assertions
- 必须走 `should_include()` 过滤（2026-10-20 P0修复）

### 选股层 → 风控层
- 入口: `data/risk_rules.py`
- 规则: 全仓1只 / 止损10% / 移动止盈阶梯6-8-10-12% / 时间止损120日 / 追高关闭4%
- 变更需总管审批

### 风控层 → 持仓层
- 真源: `data/holdings.json`
- 同步: trade_log.json + holdings.json 双写（规则3）
- 任何持仓变动必须写入 trade_log.json

## 契约变更流程
1. 修改合同 → commit 到 main
2. 跑 `scripts/closedloop_health.py` 验证契约完整性
3. 老五R0评审确认无违宪条款
4. 入 `data/review_status.json` 标记 approved

## 判据真源
- `scripts/closedloop_health.py::check_a1_contract`
- 此文件本身即为契约真源，不得在spec中复述数值（宪法I）
