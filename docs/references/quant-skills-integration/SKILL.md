---
name: quant-skills-integration
description: QuantSkills资源接入——504个已验证因子库+B10评估系统接入流程。Phase 1经验：先接20-50代表因子，不做全量500+；B10是截面视角，本项目是单票轮动视角，不可直接迁移IC结果。
version: 1.0.0
author: 总管Hermes
license: GPL-3.0
category: zhuanqian
priority: P1
metadata:
  hermes:
    tags: [QuantSkills, 因子库, B10, 扩展]
    source: "https://www.quantskills.ai/u/abgyjaguo"
---

# QuantSkills资源接入

## ⚡ 触发词

- "接入QuantSkills" / "安装因子库"
- "引入新因子" / "因子库扩展"
- "部署B10评估系统"

## 📦 可用资源

| 资源 | 数量 | 验证状态 | 用途 |
|------|------|----------|------|
| skill-quant-factor-volume-stat-alpha | 216 | ✅ 全部通过 | 量价/流动性/时序排名 |
| skill-quant-factor-risk-pattern-alpha | 288 | ✅ 全部通过 | 波动率/K线形态/RSI/回撤 |
| skill-quant-factor-directional-alpha | ? | ✅ 已验证 | 趋势/动量/反转/突破 |
| B10评估系统 | 1 | ✅ 可用 | IC/ICIR/分层回测 |

## 📋 接入流程

### Phase 1: 快速验证（1-2天）
```bash
# 1. 安装因子库
git clone https://github.com/quantskills/skill-quant-factor-volume-stat-alpha
pip install -e .

# 2. 部署B10评估系统
git clone https://github.com/quantskills/skill-b10-evaluator
python scripts/deploy_b10.py

# 3. 验证Top-10量能因子IC
python scripts/validate_top_factors.py --top 10
```

### Phase 2: 因子替换（3-5天）
```bash
# 1. 对比新旧因子IC
python scripts/compare_factors.py --baseline chg5 --new volume_001

# 2. 替换失效因子
python scripts/replace_factor.py --old chg5 --new volume_001 --weight 0.15

# 3. 运行回测验证
python backtest_rotation.py --strategy new_weights
```

### Phase 3: 系统升级（1-2周）
```bash
# 集成因子技能工厂
python scripts/integrate_factory.py

# 建立因子门禁流程
python scripts/setup_gate.py --threshold ic>0.03,ir>0.3
```

## ⚠️ 注意事项

- 因子验证口径：A股98标的 + 美股50标的，2021-2026真实行情
- 验证指标：覆盖率、5日Rank IC、ICIR、Q5-Q1收益差、换手率、未来函数检查
- 新因子必须通过门禁（IC>0.03, IR>0.3, 单调性, 无未来函数）

## 🔗 关联技能

- `stock-screening` — 选股筛选
- `backtest-engine` — 回测验证
- `factor-maintenance` — 因子监控

## 📎 参考文档

- `references/phase1-lessons-learned.md` — Phase 1经验教训（因子接入策略/视角对齐/IC方向记录）

---

**建立时间**: 2026-09-20
**来源**: QuantSkills技能集成Phase 1项目
**维护者**: 总管/老五
