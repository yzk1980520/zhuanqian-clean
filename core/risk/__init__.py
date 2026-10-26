# -*- coding: utf-8 -*-
"""core.risk — 风控红线模块（S6基地化迁入）

原risk_rules.py(905L) + 子模块(config/adapter/engine)已迁入本包。
根级risk_rules.py为向后兼容shim(re-export)。

S6修复(2026-10-23, 卡t_303fc7e3): 移除包级急加载import。
原4行 `from core.risk import risk_rules_*` 使 `import core.risk` (含
`import core.risk.risk_rules_config` 的子包解析) 即拖起 根级shim↔impl↔engine 循环:
根级shim→core.risk包init→impl→engine→根级risk_rules_config(部分初始化)→ImportError。
本包对齐core/scoring先例: 包init仅留docstring, 子模块按需import。
"""

